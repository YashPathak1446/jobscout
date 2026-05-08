"""
Location Matcher

Parses messy job location strings into structured location data.
This module handles the "how" of location parsing — the profile
handles the "what" of user preferences.

Location: jobscout_v3/tools/jobs/location_matcher.py
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class LocationResult:
    """Structured result from parsing a raw location string."""
    raw: str
    is_remote: bool = False
    country: Optional[str] = None       # e.g., "United States", "Canada"
    state: Optional[str] = None         # e.g., "California", "British Columbia"
    city: Optional[str] = None          # e.g., "San Francisco"
    confidence: str = "low"             # "high", "medium", "low"

    def __str__(self) -> str:
        parts = []
        if self.is_remote:
            parts.append("Remote")
        if self.city:
            parts.append(self.city)
        if self.state:
            parts.append(self.state)
        if self.country and self.country != "United States":
            parts.append(self.country)
        return ", ".join(parts) if parts else self.raw or "Unknown"


# ---------------------------------------------------------------------------
# Country detection map
# Each entry: display_name -> list of indicators (lowercase)
# Ordered from most-specific to least-specific within each country
# ---------------------------------------------------------------------------
COUNTRY_INDICATORS = {
    "Canada": [
        # Provinces / territories
        "british columbia", "ontario", "alberta", "quebec", "manitoba",
        "saskatchewan", "nova scotia", "new brunswick",
        # Common abbreviations used in job postings
        ", bc", ", on", ", ab", ", qc", ", mb", ", sk",
        # Cities
        "toronto", "vancouver", "montreal", "ottawa", "calgary",
        "edmonton", "winnipeg", "halifax", "waterloo", "kitchener",
        # Country names
        "canada", "canadian",
    ],
    "United Kingdom": [
        "england", "scotland", "wales", "northern ireland",
        "london", "manchester", "birmingham", "edinburgh",
        "bristol", "leeds", "glasgow", "liverpool",
        "united kingdom", " uk ", ", uk", "(uk)",
    ],
    "India": [
        "karnataka", "maharashtra", "telangana", "tamil nadu",
        "bangalore", "bengaluru", "hyderabad", "mumbai", "pune",
        "delhi", "new delhi", "chennai", "kolkata", "noida",
        "india", "indian",
    ],
    "Germany": [
        "berlin", "munich", "hamburg", "frankfurt", "cologne",
        "düsseldorf", "stuttgart", "bavaria",
        "germany", "deutschland",
    ],
    "Ireland": [
        "dublin", "cork", "galway", "limerick",
        "ireland", "republic of ireland",
    ],
    "Australia": [
        "new south wales", "victoria", "queensland",
        "sydney", "melbourne", "brisbane", "perth", "adelaide",
        "australia", "australian",
    ],
    "Singapore": ["singapore"],
    "Netherlands": ["amsterdam", "rotterdam", "the hague", "netherlands"],
    "Sweden": ["stockholm", "gothenburg", "malmö", "sweden"],
    "Israel": ["tel aviv", "jerusalem", "haifa", "israel"],
    "Japan": ["tokyo", "osaka", "kyoto", "japan"],
    "France": ["paris", "lyon", "marseille", "france"],
    "Switzerland": ["zurich", "geneva", "switzerland"],
    "Poland": ["warsaw", "krakow", "wroclaw", "poland"],
    "Brazil": ["sao paulo", "rio de janeiro", "brazil", "brasil"],
    "Mexico": ["mexico city", "guadalajara", "monterrey", "mexico"],
    "China": ["beijing", "shanghai", "shenzhen", "guangzhou", "china"],
    "Taiwan": ["taipei", "taiwan"],
    "South Korea": ["seoul", "busan", "south korea", "korea"],
}

# US state full names and abbreviations
US_STATES = {
    "Alabama": "al", "Alaska": "ak", "Arizona": "az", "Arkansas": "ar",
    "California": "ca", "Colorado": "co", "Connecticut": "ct",
    "Delaware": "de", "Florida": "fl", "Georgia": "ga", "Hawaii": "hi",
    "Idaho": "id", "Illinois": "il", "Indiana": "in", "Iowa": "ia",
    "Kansas": "ks", "Kentucky": "ky", "Louisiana": "la", "Maine": "me",
    "Maryland": "md", "Massachusetts": "ma", "Michigan": "mi",
    "Minnesota": "mn", "Mississippi": "ms", "Missouri": "mo",
    "Montana": "mt", "Nebraska": "ne", "Nevada": "nv",
    "New Hampshire": "nh", "New Jersey": "nj", "New Mexico": "nm",
    "New York": "ny", "North Carolina": "nc", "North Dakota": "nd",
    "Ohio": "oh", "Oklahoma": "ok", "Oregon": "or", "Pennsylvania": "pa",
    "Rhode Island": "ri", "South Carolina": "sc", "South Dakota": "sd",
    "Tennessee": "tn", "Texas": "tx", "Utah": "ut", "Vermont": "vt",
    "Virginia": "va", "Washington": "wa", "West Virginia": "wv",
    "Wisconsin": "wi", "Wyoming": "wy",
    "District of Columbia": "dc",
}

# Reverse map: abbreviation -> full name
US_STATE_BY_ABBREV = {v: k for k, v in US_STATES.items()}

# Remote indicators
REMOTE_INDICATORS = [
    "remote", "work from home", "wfh", "fully remote",
    "remote-first", "remote first", "distributed", "anywhere",
    "virtual", "telecommute",
]


def parse_location(raw_location: str) -> LocationResult:
    """
    Parse a raw job location string into structured data.

    Examples:
        "San Francisco, CA"       → country=US, state=California, city=San Francisco
        "Vancouver, BC"           → country=Canada, state=British Columbia, city=Vancouver
        "Remote"                  → is_remote=True
        "Remote - US Only"        → is_remote=True, country=United States
        "London, UK"              → country=United Kingdom, city=London
        "US"                      → country=United States
        "Multiple Locations"      → country=None, confidence=low

    Args:
        raw_location: Raw location string from job posting

    Returns:
        LocationResult with parsed fields
    """
    if not raw_location or not raw_location.strip():
        return LocationResult(raw="", confidence="low")

    raw = raw_location.strip()
    loc_lower = raw.lower()

    result = LocationResult(raw=raw)

    # -----------------------------------------------------------------------
    # Step 1: Check for remote
    # -----------------------------------------------------------------------
    is_remote = any(indicator in loc_lower for indicator in REMOTE_INDICATORS)
    result.is_remote = is_remote

    # If remote with US qualifier, note country
    if is_remote:
        if any(x in loc_lower for x in ["us only", "usa only", "us-only",
                                          "united states", "us based", ", us"]):
            result.country = "United States"
            result.confidence = "high"
        elif any(x in loc_lower for x in ["canada", "uk", "india"]):
            pass  # Fall through to country detection
        else:
            result.country = None  # Truly location-agnostic remote
            result.confidence = "medium"
            return result

    # -----------------------------------------------------------------------
    # Step 2: Detect non-US country
    # -----------------------------------------------------------------------
    for country_name, indicators in COUNTRY_INDICATORS.items():
        if any(ind in loc_lower for ind in indicators):
            result.country = country_name
            result.confidence = "high"
            # Try to extract city/state
            _enrich_non_us(result, loc_lower, country_name)
            return result

    # -----------------------------------------------------------------------
    # Step 3: Detect United States
    # -----------------------------------------------------------------------
    # Explicit US indicators
    us_indicators = [
        "united states", "usa", ", usa", "u.s.a", "u.s.",
        "america", "north america",
    ]
    if any(ind in loc_lower for ind in us_indicators):
        result.country = "United States"
        result.confidence = "high"
        _enrich_us(result, loc_lower)
        return result

    # Detect US by state abbreviation: ", CA" or ", NY" at end of string
    abbrev_match = re.search(r',\s*([a-z]{2})\s*$', loc_lower)
    if abbrev_match:
        abbrev = abbrev_match.group(1)
        if abbrev in US_STATE_BY_ABBREV:
            result.country = "United States"
            result.state = US_STATE_BY_ABBREV[abbrev]
            result.confidence = "high"
            # City is everything before the state
            city_part = loc_lower[:abbrev_match.start()].strip().strip(',').strip()
            if city_part:
                result.city = city_part.title()
            return result

    # Detect US by full state name
    for state_name, abbrev in US_STATES.items():
        if state_name.lower() in loc_lower:
            result.country = "United States"
            result.state = state_name
            result.confidence = "high"
            _enrich_us(result, loc_lower)
            return result

    # -----------------------------------------------------------------------
    # Step 4: Ambiguous / unknown
    # -----------------------------------------------------------------------
    # Common vague values from job boards
    vague_indicators = [
        "multiple", "various", "nationwide", "national",
        "flexible", "hybrid", "on-site", "onsite", "in-office",
    ]
    if any(v in loc_lower for v in vague_indicators):
        result.confidence = "low"
        return result

    # No match — keep raw, low confidence
    result.confidence = "low"
    return result


def _enrich_us(result: LocationResult, loc_lower: str) -> None:
    """Try to extract US city and state from location string."""
    # State from abbreviation
    abbrev_match = re.search(r',\s*([a-z]{2})\s*$', loc_lower)
    if abbrev_match:
        abbrev = abbrev_match.group(1)
        if abbrev in US_STATE_BY_ABBREV:
            result.state = US_STATE_BY_ABBREV[abbrev]
            city_part = loc_lower[:abbrev_match.start()].strip().strip(',').strip()
            if city_part and city_part not in ("us", "usa", "united states"):
                result.city = city_part.title()
            return

    # State from full name
    for state_name in US_STATES:
        if state_name.lower() in loc_lower:
            result.state = state_name
            break


def _enrich_non_us(result: LocationResult, loc_lower: str, country: str) -> None:
    """Try to extract city from non-US location string."""
    # Simple heuristic: first comma-separated token is often the city
    parts = [p.strip() for p in loc_lower.split(',')]
    if parts:
        city_candidate = parts[0].strip()
        # Don't use the country name itself as the city
        if city_candidate and city_candidate != country.lower():
            result.city = city_candidate.title()
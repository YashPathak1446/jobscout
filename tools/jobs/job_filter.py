"""
Job Filter

Evaluates whether a job should be included or excluded based on
user profile preferences. Handles all filtering and scoring decisions.

This module is the "how" of filtering — the profile is the "what."

Location: jobscout_v3/tools/jobs/job_filter.py
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional, List

from .location_matcher import parse_location, LocationResult

logger = logging.getLogger(__name__)


@dataclass
class FilterDecision:
    """Result of evaluating a job against a profile."""
    exclude: bool
    reason: Optional[str] = None

    # Scores (higher = better match)
    location_score: int = 0      # 3=priority, 2=acceptable, 1=remote, 0=other, -1=unknown
    role_score: int = 0          # 0-3 based on title match
    seniority_score: int = 0     # 2=explicit entry-level, 1=acceptable, 0=unknown, -1=senior

    # Parsed location for downstream use
    location_result: Optional[LocationResult] = None

    # Human-readable reasoning for UI/logging
    reasons: List[str] = field(default_factory=list)

    @property
    def overall_score(self) -> int:
        """
        Composite discovery score.
        Used for ranking jobs after filtering.
        Higher is better.
        """
        if self.exclude:
            return -1
        return (
            self.location_score * 10
            + self.role_score * 8
            + self.seniority_score * 5
        )


# Wording that marks a posting as pitched above entry level. Used only to
# decide whether a posting *needs* to match the profile's accepted range —
# a title with none of these is never excluded on seniority.
SENIOR_INDICATORS = [
    'senior', 'sr.', 'sr ', 'staff', 'principal',
    'lead', 'director', 'manager', 'head of',
]

# How each level a profile can ask for actually appears in job ads. The
# profile stores levels ("new grad"); postings phrase them a dozen ways
# ("recent graduate", "0-2 years", "University Graduate"), so the profile
# field alone would match far less than it should.
SENIORITY_SYNONYMS = {
    "new grad": ["new grad", "new graduate", "recent graduate",
                 "university graduate", "early career", "campus"],
    "entry level": ["entry level", "entry-level", "associate",
                    "0-2 years", "0-1 years", "1-2 years"],
    "junior": ["junior", "jr.", "jr "],
    "mid": ["mid-level", "mid level", "2-4 years", "3-5 years",
            "engineer ii", "engineer iii"],
    "senior": ["senior", "sr.", "sr ", "5+ years", "engineer iv"],
    "staff": ["staff", "principal", "8+ years", "10+ years"],
    "lead": ["lead", "manager", "director", "head of"],
}


def accepted_seniority_terms(levels) -> list:
    """
    Expand a profile's seniority levels into the phrasings ads actually use.

    This replaces a hardcoded entry-level list. `job_preferences.seniority`
    has existed on every profile since the schema was written and was read by
    nothing but a print statement — the same dead-field shape as
    `rarely_include` (R31). Reading it is what lets a mid-level or senior user
    see jobs at all, rather than having their whole range excluded by a
    constant written for one new grad.

    An unknown level falls back to matching itself, so a profile can name a
    level this map has never heard of and still work.
    """
    terms = []
    for level in levels or []:
        key = (level or "").strip().lower()
        if not key:
            continue
        # The level's own name always counts. An ad that literally says
        # "mid" should match the "mid" level, and only the paraphrases are
        # listed in the map.
        terms.append(key)
        terms.extend(SENIORITY_SYNONYMS.get(key, []))
    return sorted(set(terms))


# ---------------------------------------------------------------------------
# The body gate (R54)
#
# `evaluate()` above reads the *title*, and that is deliberate: it runs before
# enrichment, so it must not need a JD, which protects the scraping budget.
# The cost is that it cannot see a clean title over a disqualifying body, and
# three of eight resumes in one run went to jobs that ruled the candidate out
# in their second paragraph:
#
#   Samsara     "Finance & Strategy AI Engineer"        8+ years experience
#   Scale AI    "Forward Deployed Software Engineer"    5+ years experience
#   Databricks  "AI Engineer - FDE (ALL LEVELS)"        "not intended for
#                                                        new graduate ...
#                                                        applicants"
#
# Databricks is the sharpest: the title advertises all levels and the body
# excludes new graduates by name.
#
# So this is a second pass, after enrichment and before generation. It reads
# the JD and costs nothing — no model, no network, just regex — which is what
# lets it sit downstream of the cheap gate without undoing that gate's point.
# ---------------------------------------------------------------------------

# How many years of experience a candidate at each level can credibly claim.
# The gate compares a JD's *floor* against the top of the profile's range, so
# a profile of [new grad, entry level, junior] tolerates a floor of 3 and is
# ruled out by 5.
YEARS_BY_LEVEL = {
    "new grad": 0, "entry level": 2, "junior": 3,
    "mid": 5, "senior": 8, "staff": 10, "lead": 10,
}

# A requirement, not an anecdote. "5+ years" and "3-5 years" are floors; the
# nearby word "experience" is what separates them from "grew 40% in 3 years".
_YEARS_PATTERNS = (
    re.compile(r"(\d{1,2})\s*\+\s*years?", re.I),
    # The `\+?` on the upper bound matters more than it looks. A real posting
    # read "3-5+ years of QA automation experience": without it only the "5+"
    # matched, the floor was read as 5 rather than 3, and a job the candidate
    # qualifies for was dropped. A gate's false positives are invisible —
    # nobody sees the job that was never shown — so the range form has to win.
    re.compile(r"(\d{1,2})\s*(?:-|–|to)\s*\d{1,2}\s*\+?\s*years?", re.I),
    re.compile(r"(?:at least|minimum(?:\s+of)?|min\.?)\s*(\d{1,2})\s*years?", re.I),
)

_EXPERIENCE_NEARBY = re.compile(
    r"experience|building|engineering|professional|industry|working", re.I)

# Terms that describe the candidate this profile is.
_ENTRY_TERMS = re.compile(
    r"new\s+grad(?:uate)?s?|entry[-\s]?level|recent\s+graduates?|"
    r"university\s+graduates?|early\s+career", re.I)

# Phrases that turn a mention of those terms into an exclusion. Without this
# the gate would reject the very jobs it exists to keep: Elastic's JD reads
# "an entry-level position perfect for new graduates", which contains every
# term above and means the opposite.
_EXCLUSION_CUES = re.compile(
    r"not\s+intended\s+for|not\s+(?:open|available|suitable)\s+(?:to|for)|"
    r"is\s+not\s+an?\s|does\s+not\s+(?:accept|consider)|"
    r"no\s+(?:new\s+grad|entry[-\s]?level)|unfortunately[^.]{0,40}not|"
    r"cannot\s+(?:accept|consider)|ineligible", re.I)


def _tolerated_years(profile) -> int:
    """The highest experience floor this profile's seniority range can meet."""
    levels = getattr(profile.job_preferences, "seniority", None) or []
    known = [YEARS_BY_LEVEL[level.strip().lower()]
             for level in levels if level.strip().lower() in YEARS_BY_LEVEL]
    # An unrecognised range should not silently reject everything, so an empty
    # result means "no opinion" rather than "zero years tolerated".
    return max(known) if known else max(YEARS_BY_LEVEL.values())


def required_years(text: str):
    """
    The lowest experience floor the JD states, or None if it states none.

    The *lowest* because a posting often lists several — "5+ years backend,
    2+ years with Go" — and the smallest is the one a candidate has to clear
    to be considered at all. Taking the largest would reject jobs over a
    nice-to-have.
    """
    floors = []
    for pattern in _YEARS_PATTERNS:
        for match in pattern.finditer(text or ""):
            window = text[max(0, match.start() - 60):match.end() + 60]
            if _EXPERIENCE_NEARBY.search(window):
                floors.append(int(match.group(1)))
    return min(floors) if floors else None


def excludes_entry_level(text: str) -> bool:
    """
    Does the body rule out early-career applicants *by name*?

    Presence of "new graduate" proves nothing on its own — the jobs worth
    keeping say it too. What matters is an exclusion cue shortly before it,
    which is how "not intended for internship, new graduate, or entry-level
    applicants" is told apart from "perfect for new graduates".
    """
    for term in _ENTRY_TERMS.finditer(text or ""):
        before = text[max(0, term.start() - 120):term.start()]
        if _EXCLUSION_CUES.search(before):
            return True
    return False


def body_disqualifiers(text: str, profile) -> list:
    """
    Reasons this JD's body rules the profile out. Empty means keep.

    Deterministic and offline by design: it runs on every enriched job, and a
    gate that cost an API call per posting would be a gate nobody could afford
    to leave on.
    """
    if not text:
        return []

    reasons = []

    floor = required_years(text)
    tolerated = _tolerated_years(profile)
    if floor is not None and floor > tolerated:
        reasons.append(
            f"asks for {floor}+ years of experience; this profile's range "
            f"tops out around {tolerated}")

    if excludes_entry_level(text):
        reasons.append("states that early-career applicants are not eligible")

    return reasons


def evaluate(job, profile) -> FilterDecision:
    """
    Evaluate a job against a user profile.

    Args:
        job: JobListing object with title, description, location fields
        profile: UserProfile object with job_preferences

    Returns:
        FilterDecision with exclude flag, reason, and scores
    """
    decision = FilterDecision(exclude=False)

    # -----------------------------------------------------------------------
    # 1. Seniority / keyword filtering
    # -----------------------------------------------------------------------
    text = f"{job.title} {job.description}".lower()
    prefs = profile.job_preferences

    for keyword in prefs.exclude_keywords:
        if keyword.lower() in text:
            decision.exclude = True
            decision.reason = f"Excluded keyword: {keyword}"
            return decision

    has_senior = any(ind in text for ind in SENIOR_INDICATORS)
    accepted = accepted_seniority_terms(prefs.seniority)
    has_accepted = any(term in text for term in accepted)

    if has_senior and not has_accepted:
        decision.exclude = True
        decision.reason = (
            "Seniority above this profile's range "
            f"({', '.join(prefs.seniority) or 'unset'})"
        )
        return decision

    if has_accepted:
        decision.seniority_score = 2
    elif not has_senior:
        decision.seniority_score = 1  # Unknown seniority — acceptable
    else:
        decision.seniority_score = 0  # Senior wording, but within range

    # -----------------------------------------------------------------------
    # 2. Role relevance scoring
    # -----------------------------------------------------------------------
    title_lower = job.title.lower()
    role_score = 0
    for target_role in prefs.target_roles:
        role_lower = target_role.lower()
        if role_lower in title_lower:
            # Exact match in title
            role_score = 3
            decision.reasons.append(f"Matches target role: {target_role}")
            break
        # Partial word match
        role_words = set(role_lower.split())
        title_words = set(title_lower.split())
        overlap = role_words & title_words
        if overlap and len(overlap) >= 1:
            role_score = max(role_score, 2)

    decision.role_score = role_score

    # -----------------------------------------------------------------------
    # 3. Location filtering and scoring
    # -----------------------------------------------------------------------
    loc_result = parse_location(job.location)
    decision.location_result = loc_result

    # Remote check
    if loc_result.is_remote:
        if prefs.locations.remote_ok:
            decision.location_score = 3
            decision.reasons.append("Remote (accepted)")
        else:
            decision.location_score = 0
            decision.reasons.append("Remote (not preferred)")
        return decision

    # Unknown / vague location — keep but rank low
    if loc_result.confidence == "low" or loc_result.country is None:
        decision.location_score = -1
        decision.reasons.append(f"Location unclear: {job.location or '(empty)'}")
        return decision

    # Whitelist check: is the detected country in user's preferred countries?
    preferred_countries = prefs.locations.countries
    if preferred_countries and loc_result.country not in preferred_countries:
        decision.exclude = True
        decision.reason = (
            f"Location country '{loc_result.country}' "
            f"not in preferred countries {preferred_countries}"
        )
        return decision

    # Country matches — score by state preference
    location_score = _score_us_location(loc_result, prefs.locations)
    decision.location_score = location_score

    if location_score >= 3:
        decision.reasons.append(
            f"Priority location: {loc_result.state or loc_result.country}"
        )
    elif location_score >= 2:
        decision.reasons.append(
            f"Acceptable location: {loc_result.state or loc_result.country}"
        )
    else:
        decision.reasons.append(
            f"Other US location: {loc_result.state or loc_result.city or job.location}"
        )

    return decision


def _score_us_location(loc_result: LocationResult, location_prefs) -> int:
    """
    Score a US job location based on state preferences.

    Returns:
        3 = priority state
        2 = acceptable state
        0 = US but not in priority/acceptable
    """
    if not loc_result.state:
        return 0

    state_lower = loc_result.state.lower()

    for priority_state in location_prefs.states_priority:
        if priority_state.lower() == state_lower:
            return 3

    for acceptable_state in location_prefs.states_acceptable:
        if acceptable_state.lower() == state_lower:
            return 2

    return 0
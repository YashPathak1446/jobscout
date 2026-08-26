"""
What a posting demands, as facts about the posting (R64).

The public board has no visitor. Every gate this project has built — R54's
experience floor, R55's country check, R56's eligibility — answers "does this
rule *you* out", and that question needs a profile. R60's plan said the board
would apply the R56 gate; it cannot, because there is nobody to apply it to.

So the board states what each posting *asks for* and lets the reader filter.
`required_years`, `excludes_entry_level` and `parse_location` were already
profile-free; `posting_demands` (R64) is the detection half of R56's gate with
the judgement removed. Nothing here reads a profile, and nothing here decides
who should apply.

**Every facet carries its basis.** `required_years` returns None for two
different things — the posting states no floor, and the text could not be read
— and under a gate that collapse was harmless, because it only meant a job
slipped through. Under a *filter* it is not: a five-years role whose floor
failed to parse lands in the early-career view looking like it belongs there.
So "none stated" and "unknown" are different values, and the frontend must show
`unknown` under a filter rather than hide it. That is R62's lesson — a filter
that removes things without saying so — applied to the visitor's side.

Pure functions, no I/O: everything here takes rows and returns data.

Location: jobscout_v3/tools/jobs/board_export.py
"""

import re
from collections import Counter

from .job_filter import (
    SENIOR_INDICATORS,
    excludes_entry_level,
    posting_demands,
    required_years,
)
from .location_matcher import parse_location

# Bumped whenever a field changes meaning or disappears, so a frontend built
# against an older shape fails loudly instead of rendering nonsense.
SCHEMA_VERSION = 1

# Below this, the text is discovery's one-line summary rather than a job
# description, and no facet read from it means anything.
#
# Calibrated, not guessed. In the store as it stands, real scraped bodies run
# from 818 characters upward (p10 = 2,987; median = 5,663). The short
# descriptions a failed scrape falls back to since R61 run 25-300 characters
# (median 80). Nothing at all lands between 300 and 818, so the threshold sits
# in an empty gap with margin on both sides rather than on a judgement call.
READABLE_MIN_CHARS = 500

# Language that asks for experience without ever naming a number: "several
# years of experience", "experience required". When this appears and no floor
# parsed, the honest answer is "unknown" rather than "none stated" — the
# posting has an opinion and this code failed to read it.
_YEARS_LANGUAGE = re.compile(
    r"years?\s+of\s+[^.]{0,40}?experience|experience\s+(?:is\s+)?required|"
    r"minimum\s+experience|proven\s+(?:track\s+record|experience)",
    re.I)

# The default view. It lives in the data rather than in the frontend because
# early-career is a *default*, not a filter — that is the whole reason facets
# were chosen over gates — and a default anyone might want to change should not
# need a deploy to change it.
DEFAULT_PRESET = {
    "name": "Early career",
    "description": "Roles that do not ask for experience you would not have "
                   "yet. Postings whose requirements could not be read are "
                   "shown, not hidden.",
    "max_years_required": 3,
    "include_unknown_years": True,
    "exclude_entry_level_exclusions": True,
    "exclude_clearance_required": True,
}


def years_facet(text: str) -> tuple:
    """
    (floor, basis) — how much experience this posting asks for.

    basis is "stated" when a number was read, "none_stated" when a real body
    asks for none, and "unknown" when there was no body worth reading or the
    body asks for experience in words this code cannot turn into a number.
    """
    text = text or ""
    if len(text) < READABLE_MIN_CHARS:
        return None, "unknown"

    floor = required_years(text)
    if floor is not None:
        return floor, "stated"
    if _YEARS_LANGUAGE.search(text):
        return None, "unknown"
    return None, "none_stated"


def demands_facet(text: str) -> tuple:
    """(demands, basis) — clearance, citizenship and sponsorship."""
    text = text or ""
    if len(text) < READABLE_MIN_CHARS:
        return posting_demands(""), "unknown"
    return posting_demands(text), "read"


def classify_level(title: str, years, years_basis: str, excludes_entry: bool) -> str:
    """
    "entry", "mid", "senior" or "unspecified".

    Deliberately admits it does not know. A posting with no stated floor and an
    unremarkable title genuinely has not said, and inventing "entry" for it
    would put senior roles in the view most visitors start on.
    """
    title_lower = (title or "").lower()
    if any(indicator in title_lower for indicator in SENIOR_INDICATORS):
        return "senior"

    if years_basis == "stated":
        if years >= 5:
            return "senior"
        if years >= 2:
            return "mid"
        return "entry"

    # The body ruled out early-career applicants by name (R54), which says
    # nothing about how senior it is but does say it is not entry level.
    if excludes_entry:
        return "mid"

    return "unspecified"


def build_row(row: dict) -> dict:
    """
    One store row as a board row.

    Reads `full_jd` and emits facts derived from it; never emits the text
    itself. The employer owns that prose, and R60's whole redistribution answer
    is that the board links out rather than mirroring.
    """
    body = row.get("full_jd") or ""
    years, basis = years_facet(body)
    demands, demands_of = demands_facet(body)
    excludes = excludes_entry_level(body) if len(body) >= READABLE_MIN_CHARS else False
    location = parse_location(row.get("location") or "")

    return {
        "url": row.get("url"),
        "title": row.get("title"),
        "company": row.get("company"),
        "location": row.get("location"),
        "source": row.get("source"),
        # Named for what it is. The employer's own posting date is not
        # available — `JobListing.created` is set to the crawl time by
        # `ats_search`, so it says when we looked, not when they posted.
        "first_seen": row.get("first_seen"),
        "years_required": years,
        "years_basis": basis,
        "excludes_entry_level": excludes,
        "demands": demands,
        "demands_basis": demands_of,
        "country": location.country,
        "state": location.state,
        "remote": bool(location.is_remote),
        "level": classify_level(row.get("title"), years, basis, excludes),
    }


def build_rows(rows) -> list:
    return [build_row(row) for row in rows or []]


def summarise_facets(rows) -> dict:
    """
    How much each facet actually knows, so the frontend builds controls that
    earn their place.

    A country filter over postings that mostly state no country is a control
    that looks useful and does nothing; a years slider is decoration if most
    rows are `unknown`. These counts are free here and awkward to get later.
    """
    rows = list(rows or [])
    total = len(rows)

    years_values = Counter(
        r["years_required"] for r in rows if r["years_basis"] == "stated")

    return {
        "total": total,
        "years_basis": dict(Counter(r["years_basis"] for r in rows)),
        "years_distribution": dict(sorted(years_values.items())),
        "demands_basis": dict(Counter(r["demands_basis"] for r in rows)),
        "demands": {
            key: sum(1 for r in rows if r["demands"][key])
            for key in ("clearance_held", "us_person", "no_sponsorship")
        },
        "excludes_entry_level": sum(1 for r in rows if r["excludes_entry_level"]),
        "level": dict(Counter(r["level"] for r in rows)),
        "with_country": sum(1 for r in rows if r["country"]),
        "remote": sum(1 for r in rows if r["remote"]),
        "with_state": sum(1 for r in rows if r["state"]),
    }

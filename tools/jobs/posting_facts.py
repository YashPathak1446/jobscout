"""
What a posting demands, as facts about the posting rather than a verdict.

Every gate this project built answers "does this rule *you* out", which needs a
profile. That is the right question for one user and the wrong shape for many:
**one posting is evaluated against many people**, so what the posting asks for
should be read once and compared per-user, not re-derived for each.

`required_years`, `excludes_entry_level` and `parse_location` were already
profile-free. `posting_demands` is the detection half of R56's eligibility gate
with the judgement removed. Nothing here reads a profile and nothing here
decides who should apply.

**Every fact carries its basis.** `required_years` returns None for two
different things — the posting states no floor, and the text could not be read
— and collapsing those is harmless in a gate and not in a filter: a five-years
role whose floor failed to parse looks like a role that asks for nothing.

Written for the public board (R64) and kept when the board was dropped (R66),
because the shape turned out to be what a multi-user product needs anyway.

Location: jobscout_v3/tools/jobs/posting_facts.py
"""

import re

from .job_filter import (
    SENIOR_INDICATORS,
    excludes_entry_level,
    posting_demands,
    required_years,
)
from .location_matcher import parse_location

# Below this, the text is discovery's one-line summary rather than a job
# description, and no fact read from it means anything.
#
# Calibrated, not guessed. Real scraped bodies in the store run from 818
# characters upward (p10 = 2,987; median = 5,663). The short descriptions a
# failed scrape falls back to since R61 run 25-300 characters (median 80).
# Nothing lands between 300 and 818, so this sits in an empty gap with margin
# on both sides rather than on a judgement call.
READABLE_MIN_CHARS = 500

# Language that asks for experience without naming a number: "several years of
# experience", "experience required". When this appears and no floor parsed,
# the honest answer is "unknown" rather than "none stated" — the posting has an
# opinion and this code failed to read it.
_YEARS_LANGUAGE = re.compile(
    r"years?\s+of\s+[^.]{0,40}?experience|experience\s+(?:is\s+)?required|"
    r"minimum\s+experience|proven\s+(?:track\s+record|experience)",
    re.I)


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
    would file senior roles as junior. Measured on 107 real postings:
    unspecified 46, mid 32, senior 25, entry 4 — most early-career roles state
    no floor at all, which is why this is a weak signal and `years_facet` is
    the strong one.
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


def posting_facts(row: dict) -> dict:
    """
    Everything a posting says about its own requirements.

    Takes a store row or an enriched job — anything with `full_jd`, `title` and
    `location`. Reads the description and emits facts derived from it; never
    emits the text itself.
    """
    body = row.get("full_jd") or ""
    years, basis = years_facet(body)
    demands, demands_of = demands_facet(body)
    excludes = excludes_entry_level(body) if len(body) >= READABLE_MIN_CHARS else False
    location = parse_location(row.get("location") or "")

    return {
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

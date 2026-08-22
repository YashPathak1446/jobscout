"""
Profile field derivation — defaults computed from the master resume.

`migration_plan.md` splits every profile field into DERIVED, USER-INPUT or
INTERNAL. This module holds the DERIVED half: values a new user should never
have to write, because the resume already implies them.

The contract everywhere here is **derived values are defaults**. Anything the
profile states explicitly wins. That keeps hand-tuned profiles working
untouched while giving a profile-less user something sensible, which is the
whole point of Step 7.

Location: jobscout_v3/tools/profile/derivation.py
"""

import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# Resume order as an importance signal: people lead with their strongest
# work. Measured against this project's hand-tuned profile, importance is
# monotonically decreasing with position, with one exception out of 18.
#
# These boundaries were chosen by measurement, not taste. Against the frozen
# 20-JD baseline, top-2/next-4 agreed with the hand-tuned tiers 14/18 and
# perturbed selection least (4/20). Alternatives scored worse on both:
# top2/next2 13/18 and 15/20, top1/next3 11/18 and 13/20, top3/next3 13/18
# and 16/20. Agreement and low disruption moving together is the reason to
# trust the rule rather than the numbers individually.
DEFAULT_HIGH_COUNT = 2
DEFAULT_MEDIUM_COUNT = 4


def derive_component_importance(
    ordered_ids: List[str],
    high_count: int = DEFAULT_HIGH_COUNT,
    medium_count: int = DEFAULT_MEDIUM_COUNT,
) -> Dict[str, str]:
    """
    Assign importance tiers from the order components appear in the resume.

    Args:
        ordered_ids: Component IDs in resume order, strongest first.
        high_count: How many leading components are 'high'.
        medium_count: How many after those are 'medium'.

    Returns:
        {component_id: 'high' | 'medium' | 'low'}
    """
    tiers = {}

    for index, comp_id in enumerate(ordered_ids):
        if index < high_count:
            tiers[comp_id] = "high"
        elif index < high_count + medium_count:
            tiers[comp_id] = "medium"
        else:
            tiers[comp_id] = "low"

    return tiers


# Which academic term a graduation month belongs to. June has to land in
# Spring, not Summer: commencement is June at plenty of schools and the term
# is still Spring. Checked against this project's hand-written profile, which
# pairs "June 2025" with "Spring 2025".
_TERM_BY_MONTH = {
    1: "Spring", 2: "Spring", 3: "Spring", 4: "Spring", 5: "Spring", 6: "Spring",
    7: "Summer", 8: "Summer",
    9: "Fall", 10: "Fall", 11: "Fall", 12: "Fall",
}

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _graduation_from_dates(education_dates: str) -> tuple:
    """
    Pull ("June 2025", "Spring 2025") out of "Sep. 2021 – June 2025".

    Returns ("", "") when the range can't be read, rather than guessing —
    a wrong graduation date silently changes which jobs a user is eligible
    for, so a blank the user must fill is the safer failure.
    """
    if not education_dates:
        return "", ""

    # The end of the range is what matters; separators vary (en dash, hyphen,
    # "to"). Only the LAST chunk is considered: falling back to an earlier one
    # turns "Sept 2022 – Present" into a graduation date of Sept 2022, which
    # reports a current student as already graduated. No year in the tail
    # means we genuinely do not know.
    parts = [p.strip() for p in re.split(r"[–—\-]|\bto\b", education_dates) if p.strip()]
    tail = parts[-1] if parts else ""

    if not tail or not re.search(r"\b(19|20)\d{2}\b", tail):
        return "", ""

    year = re.search(r"\b((?:19|20)\d{2})\b", tail).group(1)

    # Look for a month by name, not for any three letters — "Expected May
    # 2026" would otherwise match "Exp" and lose the month entirely.
    month_match = re.search(
        r"\b(" + "|".join(_MONTHS) + r")[a-z]*", tail, re.IGNORECASE
    )
    if not month_match:
        return year, ""

    month_word = month_match.group(0)
    month_num = _MONTHS[month_word[:3].lower()]

    # Normalise to "Month YYYY", dropping qualifiers like "Expected".
    return f"{month_word} {year}", f"{_TERM_BY_MONTH[month_num]} {year}"


def derive_personal_info(parsed_resume) -> Dict[str, str]:
    """
    Personal-info fields the resume header already states.

    Covers the DERIVED rows of `migration_plan.md`'s personal_info table.
    Deliberately absent: `location`, `visa_status`, `us_citizen` and
    `permanent_resident`. Those carry legal and eligibility meaning that a
    resume does not reliably state — an address line is where you live now,
    not where you can work — so they stay USER-INPUT.

    Note this changes no generated output: the .tex header is copied from the
    master resume, and the profile's personal_info is used only for logging,
    output filenames and the run summary. The value here is onboarding —
    eight fewer fields for a new user to hand-write.
    """
    graduation_date, graduation_term = _graduation_from_dates(
        getattr(parsed_resume, "education_dates", "") or ""
    )

    derived = {
        "name": getattr(parsed_resume, "name", "") or "",
        "email": getattr(parsed_resume, "email", "") or "",
        "phone": getattr(parsed_resume, "phone", "") or "",
        "github_url": getattr(parsed_resume, "github_url", "") or "",
        "linkedin_url": getattr(parsed_resume, "linkedin_url", "") or "",
        "school": getattr(parsed_resume, "education_school", "") or "",
        "degree": getattr(parsed_resume, "education_degree", "") or "",
        "graduation_date": graduation_date,
        "graduation_term": graduation_term,
    }

    return {k: v for k, v in derived.items() if v}


def merge_importance(
    profile_map: Optional[Dict[str, str]],
    derived_map: Dict[str, str],
) -> Dict[str, str]:
    """
    Overlay explicit profile tiers on the derived defaults.

    A component the profile does not mention takes its derived tier; one it
    does mention keeps the profile's. Hand-tuned profiles are therefore
    unaffected, and the gaps a partial profile leaves stop defaulting to a
    silent 'medium'.
    """
    merged = dict(derived_map)

    for comp_id, tier in (profile_map or {}).items():
        merged[comp_id] = tier

    return merged

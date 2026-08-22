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



# =============================================================================
# CONDITIONAL TRIGGERS
# =============================================================================

# A trigger's job is to discriminate *within* its pool — to say "this JD wants
# this project rather than the other twelve". So genericness here is
# corpus-relative, not a fixed list, and `_GENERIC_TERMS` alone is the wrong
# instrument: it holds words that are generic in the abstract ("backend",
# "api") and cannot know that on *this* resume `python` sits in 7 of 13
# project tech stacks. A term carried by half the pool moves every component
# together and separates none of them.
#
# 0.4 keeps that judgement proportional: on 13 projects it drops terms carried
# by 6 or more, on 5 experiences terms carried by 3 or more.
#
# Be precise about how much measurement backs this number, because it is less
# than it looks. Against the frozen 20-JD baseline, 0.3, 0.4 and 0.5 produce
# *byte-identical* selections — on this resume only `python` (7 of 13) is
# common enough for any of them to drop, so the whole band collapses to one
# behaviour. 0.4 is the middle of the indistinguishable range, not a measured
# optimum. What is genuinely justified is the filter existing at all, and that
# argument is principled rather than empirical: a term carried by half the
# pool cannot separate the pool. See R21.
TRIGGER_DOCUMENT_RATIO = 0.4

# Two characters is the floor `split_skill_list` already applies. Anything
# shorter is an initial, not a technology.
MIN_TRIGGER_LENGTH = 2


DERIVED_RULE_DESCRIPTION = "Auto-derived from tech stack and bullet keywords"


def _trigger_candidates(component) -> set:
    """
    The terms a component could contribute, before any filtering.

    Two sources, both vocabulary-controlled: the LaTeX emph{...} tech stack
    projects carry, and the keywords the parser already extracted from
    bullets. Experiences have no tech stack, so they rely on keywords alone.

    **The component's name is deliberately not a source**, though
    `migration_plan.md` proposes it. Names do yield the occasional good
    trigger — "spotify", "minecraft" — but they are free text, and splitting
    them also yields `resume`, `computer`, `object`, `search` and `engine`.
    Those are rare across the resume, so the document-frequency filter below
    sees nothing wrong with them; they are common in *job descriptions*, which
    is the corpus that actually matters and the one not available at
    derivation time. Every JD says "resume" and "Computer Science".

    Dropping the name buys a property worth more than the terms it costs:
    every derived trigger is a term from `TECH_KEYWORDS` or the user's own
    skills section, so no free-text word can reach the trigger list at all.
    """
    from tools.resume.latex_parser import split_skill_list
    from tools.resume.resume_parser import _GENERIC_TERMS

    candidates = set()

    tech = getattr(component, "tech", "") or ""
    if tech:
        candidates |= set(split_skill_list(tech))

    candidates |= {kw.lower() for kw in (component.keywords or [])}

    return {
        term for term in candidates
        if term not in _GENERIC_TERMS and len(term) >= MIN_TRIGGER_LENGTH
    }


def _prune_redundant(terms: set) -> set:
    """
    Drop a term when a shorter one in the same set already matches inside it.

    `split_skill_list` deliberately emits both a compound and its parts, so
    "OAuth 2.0" arrives as `oauth 2.0` *and* `oauth`, and "WSL/Linux" as
    `wsl/linux`, `wsl` and `linux`. Keeping both sides double-counts: R14 made
    the trigger term score per-hit, so a JD saying "OAuth 2.0" would earn two
    hits for what the resume lists once.

    The shorter term is the one kept. It fires wherever the longer one would —
    "oauth" is inside "oauth 2.0" — so nothing stops matching.
    """
    from tools.resume.latex_parser import term_matches

    kept = set(terms)

    for term in sorted(terms, key=len, reverse=True):
        for other in terms:
            if other != term and len(other) < len(term) and term_matches(other, term):
                kept.discard(term)
                break

    return kept


def derive_conditional_triggers(
    components: List,
    document_ratio: float = TRIGGER_DOCUMENT_RATIO,
) -> Dict[str, List[str]]:
    """
    Auto-generate `include_if_jd_contains` lists from what each component uses.

    This is `migration_plan.md`'s last DERIVED field. Hand-authored triggers
    are the reason a tuned profile selects better than a bootstrapped one, and
    a new user was never going to write them.

    Args:
        components: Parsed experiences or projects — one pool at a time.
            Document frequency is counted within the pool because that is
            where the components compete.
        document_ratio: Drop a term carried by more than this share of the
            pool. See TRIGGER_DOCUMENT_RATIO.

    Returns:
        {component_id: [trigger, ...]}, omitting components with nothing
        distinctive left. An empty rule would be indistinguishable from a
        rule that never matched, which is exactly the silence R17 set out to
        remove.
    """
    if not components:
        return {}

    candidates = {comp.id: _trigger_candidates(comp) for comp in components}

    document_count = {}
    for terms in candidates.values():
        for term in terms:
            document_count[term] = document_count.get(term, 0) + 1

    # At least 1, so a two-component pool still derives something.
    cutoff = max(1, int(len(components) * document_ratio))

    derived = {}
    for comp_id, terms in candidates.items():
        distinctive = {t for t in terms if document_count[t] <= cutoff}
        kept = _prune_redundant(distinctive)
        if kept:
            derived[comp_id] = sorted(kept)

    dropped = sorted(t for t, n in document_count.items() if n > cutoff)
    if dropped:
        logger.debug(
            f"Triggers: dropped {len(dropped)} term(s) carried by more than "
            f"{cutoff}/{len(components)} components: {', '.join(dropped)}"
        )

    return derived


def merge_conditional_triggers(
    profile_rules: Optional[Dict],
    derived: Dict[str, List[str]],
) -> Dict[str, Dict[str, List[str]]]:
    """
    Overlay hand-authored rules on the derived ones, per component.

    Same contract as `merge_importance`: a component the profile writes a rule
    for keeps it untouched, and one it says nothing about takes the derived
    list. Whole-map replacement would be wrong in both directions — it would
    either discard tuning or bury it.

    Returns rules in `ConditionalInclusion` shape, ready to hand to the schema.
    """
    merged = {
        comp_id: {
            "include_if_jd_contains": list(triggers),
            # `description` is required by ConditionalInclusion, and a derived
            # rule saying so is worth more than a blank: it tells anyone
            # reading the profile which rules they wrote and which the resume
            # produced, so hand-tuning knows what it is overriding.
            "description": DERIVED_RULE_DESCRIPTION,
        }
        for comp_id, triggers in derived.items()
    }

    for comp_id, rule in (profile_rules or {}).items():
        merged[comp_id] = rule

    return merged


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

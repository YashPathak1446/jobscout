"""
Profile validation against a parsed resume.

Several profile fields are keyed by component ID — `always_include`,
`never_include`, `high_priority`, and the `conditional_inclusion` maps. An ID that does not match a parsed component is not an
error anywhere: the lookup simply misses, the rule never applies, and nothing
says so.

That failure has now happened three separate ways. `user_profiles/template.json`
shipped five example IDs (`exp_company1`, `exp_healthcare_company`,
`proj_best_project`, ...) which every bootstrapped profile inherited. The live
profile referenced components that had been renamed (R4). And a rule keyed to a
stale ID looks identical to a rule that simply never matched a JD.

So this is a check, not another one-time correction. A rule that cannot fire
should never be silent.

Resolution deliberately goes through the parser's own `get_experience_by_id` /
`get_project_by_id`, which do prefix and substring matching. Anything the
scorer would resolve, this resolves — otherwise the check would report
false problems for aliases that actually work (`exp_outlier` really does
resolve to `exp_outlier_ai`).

Location: jobscout_v3/tools/profile/validation.py
"""

import logging
from typing import List

logger = logging.getLogger(__name__)


# (section, field, is_mapping). Mappings are keyed by component ID; lists
# hold them directly.
_ID_FIELDS = [
    ("experiences", "always_include", False),
    ("experiences", "never_include", False),
    ("experiences", "conditional_inclusion", True),
    ("projects", "always_include", False),
    ("projects", "never_include", False),
    ("projects", "high_priority", False),
    ("projects", "conditional_inclusion", True),
]


def _declared_ids(profile):
    """
    Every (section, field, id) a profile names. One walk, two checkers.

    Copied into the ambiguity check below it would be the shape this file
    exists to catch: two readers of one list, and only one of them updated
    when a field is added to `_ID_FIELDS`.
    """
    rp = profile.resume_preferences

    for section_name, field, is_mapping in _ID_FIELDS:
        section = getattr(rp, section_name, None)
        if section is None:
            continue

        value = getattr(section, field, None) or ({} if is_mapping else [])
        for comp_id in (list(value.keys()) if is_mapping else list(value)):
            yield section_name, field, comp_id


def find_ambiguous_ids(profile, resume_parser) -> List[str]:
    """
    Return a problem per profile ID that could mean more than one component.

    The other half of the check above, and the half that the fuzzy resolver
    hides. Two roles at one employer used to share one ID; Q34 gave each of
    them a title suffix, which means a rule written against the old bare
    spelling now **prefix-matches both** -- and `get_experience_by_id` returns
    the first, so the rule silently attaches to whichever role the parser
    reached first. `find_unresolvable_ids` cannot see it, deliberately: it
    resolves through the same fuzzy path, so an ambiguous key looks resolved.

    That is the order-dependence Q34's ID scheme removed, reappearing in
    resolution rather than in assignment. It is worth its own message because
    the remedy is different: an unresolvable ID means *delete or correct this
    rule*, an ambiguous one means *say which of these you meant*.

    Narrow on purpose. It checks one tier -- a key that exactly matches nothing
    and is a prefix of two or more component IDs -- rather than reimplementing
    the resolver's three tiers, because a second copy of that logic is how the
    two would drift apart.
    """
    problems = []

    pools = {
        "experiences": resume_parser.get_experiences(),
        "projects": resume_parser.get_projects(),
    }

    for section_name, field, comp_id in _declared_ids(profile):
        ids = [c.id for c in pools[section_name]]
        if comp_id in ids:
            continue

        matches = [cid for cid in ids if cid.startswith(comp_id)]
        if len(matches) > 1:
            problems.append(
                f"{section_name}.{field}: '{comp_id}' matches "
                f"{len(matches)} components ({', '.join(sorted(matches))}) "
                f"— the rule applies to whichever is parsed first"
            )

    return problems


def find_unresolvable_ids(profile, resume_parser) -> List[str]:
    """
    Return a human-readable problem per profile ID that matches no component.

    Empty list means every rule in the profile can actually fire.
    """
    problems = []

    resolvers = {
        "experiences": resume_parser.get_experience_by_id,
        "projects": resume_parser.get_project_by_id,
    }

    rp = profile.resume_preferences

    for section_name, field, comp_id in _declared_ids(profile):
        if resolvers[section_name](comp_id) is None:
            problems.append(
                f"{section_name}.{field}: '{comp_id}' matches no component "
                f"in the resume — this rule can never fire"
            )

    # component_importance is keyed the same way and equally silent when wrong.
    importance = getattr(rp, "component_importance", None)
    if importance is not None:
        for section_name in ("experiences", "projects"):
            for comp_id in (getattr(importance, section_name, None) or {}):
                if resolvers[section_name](comp_id) is None:
                    problems.append(
                        f"component_importance.{section_name}: '{comp_id}' "
                        f"matches no component in the resume — tier ignored"
                    )

    return problems


def find_id_problems(profile, resume_parser) -> List[str]:
    """
    Every way a profile's component IDs can fail to mean what they say.

    Both halves together, because a caller wanting one of them wants the
    other: a rule that fires on the wrong component is not better off than a
    rule that never fires, and a caller that asked only the first question
    would report "every profile rule resolves" over an ambiguous key.
    """
    return (find_unresolvable_ids(profile, resume_parser)
            + find_ambiguous_ids(profile, resume_parser))


def warn_id_problems(profile, resume_parser, context: str = "") -> List[str]:
    """
    Run both checks and log anything found at WARNING.

    Returns the problems so a caller can also surface them in a UI. Logging
    is the point: the whole failure mode is silence.
    """
    problems = find_id_problems(profile, resume_parser)

    if problems:
        where = f" ({context})" if context else ""
        logger.warning(
            f"⚠️  {len(problems)} profile rule(s) do not name one real "
            f"component{where}:"
        )
        for problem in problems:
            logger.warning(f"      {problem}")
        logger.warning(
            "      These are applied silently at scoring time — to nothing, or "
            "to the wrong component. Fix the IDs or remove the rules."
        )

    return problems

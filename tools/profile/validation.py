"""
Profile validation against a parsed resume.

Several profile fields are keyed by component ID — `always_include`,
`never_include`, `high_priority`, and the `conditional_inclusion` /
`rarely_include` maps. An ID that does not match a parsed component is not an
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
    ("experiences", "rarely_include", True),
    ("projects", "always_include", False),
    ("projects", "never_include", False),
    ("projects", "high_priority", False),
    ("projects", "conditional_inclusion", True),
]


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

    for section_name, field, is_mapping in _ID_FIELDS:
        section = getattr(rp, section_name, None)
        if section is None:
            continue

        value = getattr(section, field, None) or ({} if is_mapping else [])
        ids = list(value.keys()) if is_mapping else list(value)

        for comp_id in ids:
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


def warn_unresolvable_ids(profile, resume_parser, context: str = "") -> List[str]:
    """
    Run the check and log anything found at WARNING.

    Returns the problems so a caller can also surface them in a UI. Logging
    is the point: the whole failure mode is silence.
    """
    problems = find_unresolvable_ids(profile, resume_parser)

    if problems:
        where = f" ({context})" if context else ""
        logger.warning(
            f"⚠️  {len(problems)} profile rule(s) reference components that do "
            f"not exist{where}:"
        )
        for problem in problems:
            logger.warning(f"      {problem}")
        logger.warning(
            "      These are ignored silently at scoring time. Fix the IDs or "
            "remove the rules."
        )

    return problems

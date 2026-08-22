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

"""
Job Filter

Evaluates whether a job should be included or excluded based on
user profile preferences. Handles all filtering and scoring decisions.

This module is the "how" of filtering — the profile is the "what."

Location: jobscout_v3/tools/jobs/job_filter.py
"""

import logging
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

    senior_indicators = [
        'senior', 'sr.', 'sr ', 'staff', 'principal',
        'lead', 'director', 'manager', 'head of',
    ]
    entry_indicators = [
        'new grad', 'entry level', 'junior', 'early career',
        'associate', '0-2 years', '0-1 years', 'recent graduate',
        'new graduate',
    ]

    has_senior = any(ind in text for ind in senior_indicators)
    has_entry = any(ind in text for ind in entry_indicators)

    if has_senior and not has_entry:
        decision.exclude = True
        decision.reason = "Seniority too high (senior/staff/principal without entry-level indicator)"
        return decision

    if has_entry:
        decision.seniority_score = 2
    elif not has_senior:
        decision.seniority_score = 1  # Unknown seniority — acceptable
    else:
        decision.seniority_score = 0  # Has senior indicator but also entry — borderline

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
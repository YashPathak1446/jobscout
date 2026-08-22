"""
Profile Management Module

Provides user profile loading and validation.
"""

from .profile_schema import (
    UserProfile,
    PersonalInfo,
    JobPreferences,
    ResumePreferences,
    AgentPreferences,
    TechnicalSkills,
    ConditionalInclusion,
)
from .profile_loader import (
    load_profile,
    list_available_profiles,
    validate_profile_file,
    print_profile_summary,
    ProfileLoadError,
)
from .derivation import (
    derive_component_importance,
    derive_conditional_triggers,
    derive_personal_info,
    merge_conditional_triggers,
    merge_importance,
)
from .validation import (
    find_unresolvable_ids,
    warn_unresolvable_ids,
)

__all__ = [
    # Schema
    'UserProfile',
    'PersonalInfo',
    'JobPreferences',
    'ResumePreferences',
    'AgentPreferences',
    'TechnicalSkills',
    'ConditionalInclusion',
    # Loader
    'load_profile',
    'list_available_profiles',
    'validate_profile_file',
    'print_profile_summary',
    'ProfileLoadError',
    # Derivation
    'derive_component_importance',
    'derive_conditional_triggers',
    'derive_personal_info',
    'merge_conditional_triggers',
    'merge_importance',
    # Validation
    'find_unresolvable_ids',
    'warn_unresolvable_ids',
]

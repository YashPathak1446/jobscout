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
]

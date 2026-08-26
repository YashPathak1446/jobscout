"""
Profile Loader - Load and validate user profiles from JSON

Reads user_profiles/*.json and validates against Pydantic schema.
Provides convenient access to profile data throughout the application.

Location: jobscout_v3/tools/profile/profile_loader.py
"""

import json
import os
from pathlib import Path
from typing import Optional
import logging

from .profile_schema import UserProfile

logger = logging.getLogger(__name__)


class ProfileLoadError(Exception):
    """Raised when profile cannot be loaded or is invalid."""
    pass


def load_profile(profile_name: str, profiles_dir: Optional[str] = None) -> UserProfile:
    """
    Load and validate a user profile from JSON.
    
    Args:
        profile_name: Profile filename without extension (e.g., 'yash_pathak')
        profiles_dir: Directory containing profiles (default: 'user_profiles/')
        
    Returns:
        Validated UserProfile object
        
    Raises:
        ProfileLoadError: If profile file not found or validation fails
        
    Example:
        >>> profile = load_profile('yash_pathak')
        >>> print(profile.personal_info.name)
        'Yash Pathak'
    """
    # Determine profiles directory
    if profiles_dir is None:
        # Try to find user_profiles/ relative to current location
        current_dir = Path.cwd()
        if (current_dir / 'user_profiles').exists():
            profiles_dir = current_dir / 'user_profiles'
        elif (current_dir.parent / 'user_profiles').exists():
            profiles_dir = current_dir.parent / 'user_profiles'
        else:
            raise ProfileLoadError(
                f"Could not find user_profiles/ directory. "
                f"Searched: {current_dir} and {current_dir.parent}"
            )
    else:
        profiles_dir = Path(profiles_dir)
    
    # Build profile path
    profile_path = profiles_dir / f"{profile_name}.json"
    
    if not profile_path.exists():
        raise ProfileLoadError(
            f"Profile not found: {profile_path}\n"
            f"Available profiles: {list_available_profiles(profiles_dir)}"
        )
    
    # Load JSON
    try:
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_data = json.load(f)
    except json.JSONDecodeError as e:
        raise ProfileLoadError(f"Invalid JSON in {profile_path}: {e}")
    except Exception as e:
        raise ProfileLoadError(f"Error reading {profile_path}: {e}")
    
    # Validate with Pydantic
    try:
        profile = UserProfile(**profile_data)
        logger.info(f"✅ Loaded profile: {profile.user_id} ({profile.personal_info.name})")
        return profile
    except Exception as e:
        raise ProfileLoadError(f"Profile validation failed for {profile_name}: {e}")


def list_available_profiles(profiles_dir: Optional[str] = None) -> list[str]:
    """
    List all available profile names (without .json extension).
    
    Args:
        profiles_dir: Directory to search (default: 'user_profiles/')
        
    Returns:
        List of profile names
    """
    if profiles_dir is None:
        current_dir = Path.cwd()
        if (current_dir / 'user_profiles').exists():
            profiles_dir = current_dir / 'user_profiles'
        elif (current_dir.parent / 'user_profiles').exists():
            profiles_dir = current_dir.parent / 'user_profiles'
        else:
            return []
    else:
        profiles_dir = Path(profiles_dir)
    
    if not profiles_dir.exists():
        return []
    
    profiles = []
    for file in profiles_dir.glob('*.json'):
        if file.name == 'template.json':          # not a person
            continue
        # Rebuilding a profile keeps a timestamped backup beside it (R30), and
        # this listed those as if they were profiles you could pick — so the
        # app's "use an existing profile" dropdown offered yesterday's copy of
        # your own profile as a separate choice. A backup is a safety net, not
        # an option. Spotted by `scripts/doctor.py` reporting three profiles
        # where there is one.
        if '.bak' in file.suffixes or file.stem.endswith('.bak'):
            continue
        profiles.append(file.stem)

    return sorted(profiles)


def validate_profile_file(profile_path: str) -> tuple[bool, str]:
    """
    Validate a profile JSON file without loading it fully.
    
    Args:
        profile_path: Path to profile JSON file
        
    Returns:
        (is_valid: bool, message: str)
    """
    try:
        with open(profile_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Try to create UserProfile
        profile = UserProfile(**data)
        return (True, f"✅ Profile is valid: {profile.user_id}")
    
    except json.JSONDecodeError as e:
        return (False, f"❌ Invalid JSON: {e}")
    except Exception as e:
        return (False, f"❌ Validation error: {e}")


def print_profile_summary(profile: UserProfile) -> None:
    """
    Print a human-readable summary of a profile.
    
    Args:
        profile: Loaded UserProfile object
    """
    print(f"\n{'='*60}")
    print(f"📋 Profile: {profile.user_id}")
    print(f"{'='*60}")
    
    print(f"\n👤 Personal Info:")
    print(f"  Name: {profile.personal_info.name}")
    print(f"  Email: {profile.personal_info.email}")
    print(f"  School: {profile.personal_info.school}")
    print(f"  Graduation: {profile.personal_info.graduation_date}")
    print(f"  Visa: {profile.personal_info.visa_status}")
    
    print(f"\n💼 Job Preferences:")
    print(f"  Target Roles: {len(profile.job_preferences.target_roles)} roles")
    print(f"    → {', '.join(profile.job_preferences.target_roles[:3])}...")
    from tools.jobs.job_filter import effective_seniority
    years = profile.job_preferences.years_experience
    if years is not None:
        print(f"  Experience: {years} year(s)")
    print(f"  Seniority: {', '.join(effective_seniority(profile)) or 'unset'}"
          f"{'' if profile.job_preferences.seniority else '  (derived)'}")
    print(f"  Priority Locations: {', '.join(profile.job_preferences.locations.states_priority)}")
    
    print(f"\n📝 Resume Preferences:")
    print(f"  Master Resume: {profile.resume_preferences.master_resume_path}")
    print(f"  Experiences: {profile.resume_preferences.experiences.typical_count} typical, {profile.resume_preferences.experiences.max_count} max")
    print(f"    Always Include: {', '.join(profile.resume_preferences.experiences.always_include)}")
    if profile.resume_preferences.experiences.conditional_inclusion:
        print(f"    Conditional: {len(profile.resume_preferences.experiences.conditional_inclusion)} rules")
    print(f"  Projects: {profile.resume_preferences.projects.typical_count} typical, {profile.resume_preferences.projects.max_count} max")
    if profile.resume_preferences.projects.high_priority:
        print(f"    High Priority: {', '.join(profile.resume_preferences.projects.high_priority[:3])}")
    
    print(f"\n🤖 Agent Preferences:")
    print(f"  Discovery Sources: {', '.join(profile.agent_preferences.discovery_sources)}")
    print(f"  Scoring Threshold: {profile.agent_preferences.scoring_threshold}%")
    print(f"  Max Jobs: {profile.agent_preferences.max_jobs_to_discover} discover → {profile.agent_preferences.max_jobs_to_generate} generate")
    print(f"  Checkpoints: ", end="")
    checkpoints = []
    if profile.agent_preferences.checkpoint_after_discovery:
        checkpoints.append("Discovery")
    if profile.agent_preferences.checkpoint_after_scoring:
        checkpoints.append("Scoring")
    if profile.agent_preferences.checkpoint_after_generation:
        checkpoints.append("Generation")
    print(', '.join(checkpoints) if checkpoints else "None")
    
    if profile.technical_skills:
        print(f"\n🛠️  Technical Skills:")
        print(f"  Languages: {len(profile.technical_skills.languages)} ({', '.join(profile.technical_skills.languages[:5])}...)")
        print(f"  Cloud: {len(profile.technical_skills.cloud_infrastructure)} tools")
        print(f"  AI/ML: {len(profile.technical_skills.ai_ml)} frameworks")
    
    print(f"\n{'='*60}\n")


# CLI for testing
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python profile_loader.py <profile_name>")
        print(f"\nAvailable profiles: {', '.join(list_available_profiles())}")
        sys.exit(1)
    
    profile_name = sys.argv[1]
    
    try:
        profile = load_profile(profile_name)
        print_profile_summary(profile)
        
        # Test conditional logic
        print("\n🧪 Testing Conditional Logic:")
        
        test_jd_healthcare = "We're looking for a software engineer with healthcare AI experience"
        rules = profile.get_experience_selection_rules(test_jd_healthcare)
        print(f"\nHealthcare JD → Experiences to include:")
        print(f"  Always: {rules['always']}")
        print(f"  Conditional: {rules['conditional']}")
        
        test_jd_backend = "Backend engineer position requiring Python and AWS experience"
        rules = profile.get_experience_selection_rules(test_jd_backend)
        print(f"\nBackend JD → Experiences to include:")
        print(f"  Always: {rules['always']}")
        print(f"  Conditional: {rules['conditional']}")
        
    except ProfileLoadError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

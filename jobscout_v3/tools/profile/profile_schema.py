"""
Pydantic Schema for User Profiles

Validates profile JSON structure and provides type safety.
All profile fields are defined here with validation rules.

Location: jobscout_v3/tools/profile/profile_schema.py
"""

from typing import Optional, Dict, List
from pydantic import BaseModel, Field, field_validator


class PersonalInfo(BaseModel):
    """Personal information section."""
    name: str
    email: str
    phone: str
    github_url: str
    linkedin_url: str
    graduation_date: str
    graduation_term: str
    school: str
    location: str
    degree: str
    visa_status: str
    us_citizen: bool
    permanent_resident: bool


class LocationPreferences(BaseModel):
    """Location preferences."""
    countries: List[str]
    exclude_countries: List[str] = Field(default_factory=list)
    states_priority: List[str] = Field(default_factory=list)
    states_acceptable: List[str] = Field(default_factory=list)
    cities: List[str] = Field(default_factory=list)
    remote_ok: bool = True
    willing_to_relocate: bool = True


class CitizenshipRestrictions(BaseModel):
    """Citizenship requirements."""
    us_citizenship_required: bool = False
    green_card_acceptable: bool = True
    h1b_sponsorship_ok: bool = True


class JobPreferences(BaseModel):
    """Job search preferences."""
    target_roles: List[str]
    experience_level: str
    seniority: List[str]
    graduation_eligibility: List[str]
    employment_types: List[str]
    exclude_keywords: List[str]
    locations: LocationPreferences
    citizenship_restrictions: CitizenshipRestrictions
    job_recency_hours: int = 168
    comments: Optional[str] = None


class ConditionalInclusion(BaseModel):
    """Conditional inclusion rule for experiences/projects."""
    include_if_jd_contains: List[str]
    max_bullets: Optional[int] = None
    description: str


class ExperiencePreferences(BaseModel):
    """Experience selection preferences."""
    max_count: int = 3
    typical_count: int = 2
    min_count: int = 2
    selection_strategy: str = "jd_dependent"
    always_include: List[str] = Field(default_factory=list)
    priority_order: str = "auto"
    conditional_inclusion: Dict[str, ConditionalInclusion] = Field(default_factory=dict)
    rarely_include: Dict[str, ConditionalInclusion] = Field(default_factory=dict)
    never_include: List[str] = Field(default_factory=list)
    bullets_per_experience: Dict[str, int] = Field(default_factory=dict)
    comments: Optional[str] = None


class ProjectPreferences(BaseModel):
    """Project selection preferences."""
    max_count: int = 4
    typical_count: int = 3
    min_count: int = 2
    selection_strategy: str = "jd_dependent"
    always_include: List[str] = Field(default_factory=list)
    high_priority: List[str] = Field(default_factory=list)
    conditional_inclusion: Dict[str, ConditionalInclusion] = Field(default_factory=dict)
    bullets_per_project: Dict[str, int] = Field(default_factory=dict)
    comments: Optional[str] = None


class FormattingPreferences(BaseModel):
    """Resume formatting preferences."""
    max_bullet_chars_experiences: int = 280
    min_bullet_chars_experiences: int = 140
    max_bullet_chars_projects: int = 140
    min_bullet_chars_projects: int = 120
    target_page_count: int = 1
    max_skill_categories: int = 6
    languages_category_first: bool = True
    template: str = "jakes_resume"
    style_guide: Optional[str] = None
    required_elements: List[str] = Field(default_factory=list)


class ResumePreferences(BaseModel):
    """Resume generation preferences."""
    master_resume_path: str
    experiences: ExperiencePreferences
    projects: ProjectPreferences
    formatting: FormattingPreferences


class AgentPreferences(BaseModel):
    """Agent behavior preferences."""
    discovery_sources: List[str]
    discovery_source_priority: Optional[Dict[str, int]] = None
    scoring_threshold: int = 70
    max_jobs_to_discover: int = 30
    max_jobs_to_enrich: int = 25
    max_jobs_to_generate: int = 10
    checkpoint_after_discovery: bool = False
    checkpoint_after_enrichment: bool = False
    checkpoint_after_scoring: bool = True
    checkpoint_after_generation: bool = False
    use_mock_embeddings: bool = False
    retry_on_validation_fail: bool = True
    max_retries: int = 2
    fallback_to_snippet: bool = True
    comments: Optional[str] = None


class TechnicalSkills(BaseModel):
    """Technical skills inventory."""
    languages: List[str] = Field(default_factory=list)
    cloud_infrastructure: List[str] = Field(default_factory=list)
    databases: List[str] = Field(default_factory=list)
    frameworks_libraries: List[str] = Field(default_factory=list)
    ai_ml: List[str] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    specializations: List[str] = Field(default_factory=list)


class ProfileNotes(BaseModel):
    """Optional notes about profile design."""
    profile_design: Optional[str] = None
    generalization: Optional[str] = None
    jd_dependent: Optional[str] = None
    always_vs_conditional: Optional[str] = None
    future_extensions: Optional[str] = None


class UserProfile(BaseModel):
    """Complete user profile schema."""
    user_id: str
    version: str = "1.0.0"
    created: str
    description: str
    personal_info: PersonalInfo
    job_preferences: JobPreferences
    resume_preferences: ResumePreferences
    agent_preferences: AgentPreferences
    technical_skills: Optional[TechnicalSkills] = None
    notes: Optional[ProfileNotes] = None

    @field_validator('user_id')
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        """Ensure user_id is lowercase with underscores."""
        if not v.replace('_', '').isalnum():
            raise ValueError('user_id must contain only alphanumeric characters and underscores')
        return v.lower()

    @field_validator('version')
    @classmethod
    def validate_version(cls, v: str) -> str:
        """Ensure version follows semantic versioning."""
        parts = v.split('.')
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError('version must follow semantic versioning (e.g., 1.0.0)')
        return v

    def get_experience_selection_rules(self, jd_text: str) -> Dict[str, List[str]]:
        """
        Get which experiences to include based on JD content.
        
        Args:
            jd_text: Job description text (lowercase for matching)
            
        Returns:
            Dict with 'always', 'conditional', 'rarely' lists
        """
        jd_lower = jd_text.lower()
        
        result = {
            'always': self.resume_preferences.experiences.always_include.copy(),
            'conditional': [],
            'rarely': []
        }
        
        # Check conditional inclusion rules
        for exp_id, rule in self.resume_preferences.experiences.conditional_inclusion.items():
            if any(keyword in jd_lower for keyword in rule.include_if_jd_contains):
                result['conditional'].append(exp_id)
        
        # Check rarely include rules
        for exp_id, rule in self.resume_preferences.experiences.rarely_include.items():
            if any(keyword in jd_lower for keyword in rule.include_if_jd_contains):
                result['rarely'].append(exp_id)
        
        return result

    def get_project_selection_rules(self, jd_text: str) -> Dict[str, List[str]]:
        """
        Get which projects to include based on JD content.
        
        Args:
            jd_text: Job description text (lowercase for matching)
            
        Returns:
            Dict with 'always', 'high_priority', 'conditional' lists
        """
        jd_lower = jd_text.lower()
        
        result = {
            'always': self.resume_preferences.projects.always_include.copy(),
            'high_priority': self.resume_preferences.projects.high_priority.copy(),
            'conditional': []
        }
        
        # Check conditional inclusion rules
        for proj_id, rule in self.resume_preferences.projects.conditional_inclusion.items():
            if any(keyword in jd_lower for keyword in rule.include_if_jd_contains):
                result['conditional'].append(proj_id)
        
        return result

    def should_exclude_job(self, job_title: str, job_description: str) -> tuple[bool, str]:
        """
        Determine if a job should be excluded based on profile rules.
        
        Args:
            job_title: Job title
            job_description: Job description text
            
        Returns:
            (should_exclude: bool, reason: str)
        """
        text = f"{job_title} {job_description}".lower()
        
        # Check exclude keywords (e.g., "PhD required", "10+ years")
        for keyword in self.job_preferences.exclude_keywords:
            if keyword.lower() in text:
                return (True, f"Contains excluded keyword: {keyword}")
        
        # Check for explicitly senior roles (more aggressive filtering)
        senior_indicators = ['senior', 'sr.', 'sr ', 'staff', 'principal', 'lead', 'director', 'manager', 'head of']
        if any(indicator in text for indicator in senior_indicators):
            # But allow if it also mentions entry-level keywords
            entry_indicators = ['new grad', 'entry level', 'junior', 'early career', 'associate', '0-2 years', '0-1 years', 'recent graduate']
            if not any(entry in text for entry in entry_indicators):
                return (True, "Seniority level too high (senior/staff/principal)")
        
        # REMOVED: Don't require seniority keywords to be present
        # GitHub jobs have short descriptions without these keywords
        # We'll catch senior roles with the check above instead
        
        return (False, "")


# Export for convenience
__all__ = [
    'UserProfile',
    'PersonalInfo',
    'JobPreferences',
    'ResumePreferences',
    'AgentPreferences',
    'TechnicalSkills',
    'ConditionalInclusion',
]
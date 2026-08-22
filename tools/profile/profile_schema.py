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
    never_include: List[str] = Field(default_factory=list)
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


class ComponentImportance(BaseModel):
    """
    User-defined importance tiers for resume components.

    Controls bullet allocation — how much space a component gets
    when it is selected for a resume.

    Importance is separate from selection (which is JD-relevance driven).
    A component can be:
      - conditionally selected (appears only for relevant JDs)
      - but always low importance (only gets 1 bullet when it appears)

    Tiers:
      high   — component is one of the user's strongest; gets priority bullets
      medium — standard allocation; default if unspecified
      low    — weak or supporting component; gets minimum bullets (1)

    Supports both canonical IDs and short aliases (resolved via ResumeParser).
    Maps cleanly to a future UI: "Rate your experiences: Strongest / Normal / Supporting"
    """
    experiences: Dict[str, str] = Field(
        default_factory=dict,
        description="Map of experience_id -> 'high' | 'medium' | 'low'"
    )
    projects: Dict[str, str] = Field(
        default_factory=dict,
        description="Map of project_id -> 'high' | 'medium' | 'low'"
    )


class ResumePreferences(BaseModel):
    """Resume generation preferences."""
    master_resume_path: str
    experiences: ExperiencePreferences
    projects: ProjectPreferences
    formatting: FormattingPreferences
    component_importance: ComponentImportance = Field(
        default_factory=ComponentImportance,
        description="User importance tiers for bullet budget allocation"
    )


class AgentPreferences(BaseModel):
    """Agent behavior preferences."""
    discovery_sources: List[str]
    discovery_source_priority: Optional[Dict[str, int]] = None
    scoring_threshold: int = 50
    max_jobs_to_discover: int = 10
    max_jobs_to_enrich: int = 10
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

    def _normalize_jd_for_matching(self, jd_text: str) -> str:
        """
        Strip non-role sections from JD text to reduce false-positive trigger matches.

        Many JDs contain "healthcare benefits", "mental health support", or perks/values
        sections that contain medical/domain words unrelated to the actual role. We
        truncate the JD at the first occurrence of any benefits/perks/about-us marker
        so triggers only fire on language describing the *role*, not the company perks.
        """
        import re

        jd_lower = jd_text.lower()

        # Markers that typically begin non-role sections.
        # Order matters less than coverage — we cut at the earliest match.
        section_markers = [
            # Benefits section variants
            "benefits\n",
            "benefits:",
            "benefits include",
            "perks and benefits",
            "perks & benefits",
            "compensation and benefits",
            "our benefits",
            "company benefits",
            "what we offer",
            "what you'll get",
            "what you will get",
            "what we provide",
            "what you can expect",
            "we offer",
            # Compensation
            "salary range",
            "pay range",
            "compensation range",
            "compensation:",
            "compensation\n",
            # Equal opportunity / values / about
            "equal opportunity",
            "equal employment",
            "we are an equal",
            "diversity, equity",
            "diversity and inclusion",
            "we are committed to",
            "about our company",
            "about us",
            "about the company",
            "our values",
            "our mission",
            "our culture",
            "why join",
            "why work",
            # Insurance / time off (often appear as standalone benefits)
            "medical, dental",
            "dental, and vision",
            "dental and vision",
            "401(k)",
            "401k",
            "paid time off",
            "pto policy",
            "parental leave",
        ]

        # Find the earliest section marker and truncate there
        cut_at = len(jd_lower)
        for marker in section_markers:
            idx = jd_lower.find(marker)
            if idx >= 0 and idx < cut_at:
                cut_at = idx

        return jd_lower[:cut_at]

    def _trigger_matches(self, trigger: str, jd_normalized: str) -> bool:
        """
        Check if a trigger word/phrase appears in the JD as a whole word.

        Uses word boundaries so 'ai' doesn't match 'available', 'training', etc.
        Multi-word triggers ('reinforcement learning') match as exact phrases.
        """
        import re

        trigger_lower = trigger.lower().strip()
        if not trigger_lower:
            return False

        # Multi-word phrases — match as substring (already specific enough)
        if " " in trigger_lower or "-" in trigger_lower:
            return trigger_lower in jd_normalized

        # Single words — require word boundaries
        # \b doesn't work for things like "c++" or "c#" so handle those specially
        if any(c in trigger_lower for c in "+#"):
            return trigger_lower in jd_normalized

        pattern = r'\b' + re.escape(trigger_lower) + r'\b'
        return bool(re.search(pattern, jd_normalized))

    def get_experience_selection_rules(self, jd_text: str) -> Dict[str, List[str]]:
        """
        Get which experiences to include based on JD content.

        Triggers match against the *role-relevant* portion of the JD only
        (benefits/perks/about-us sections are stripped). Single-word triggers
        require word boundaries so 'ai' doesn't match 'available'.

        Args:
            jd_text: Job description text

        Returns:
            Dict with 'always', 'conditional', 'rarely' lists
        """
        jd_normalized = self._normalize_jd_for_matching(jd_text)

        result = {
            'always': self.resume_preferences.experiences.always_include.copy(),
            'conditional': [],
            'conditional_hits': {},
            'rarely': []
        }

        # Check conditional inclusion rules. The number of distinct triggers
        # that match is recorded, not just whether any did: one incidental
        # word is weak evidence and several is strong, and the scorer needs
        # to tell them apart (see R14).
        for exp_id, rule in self.resume_preferences.experiences.conditional_inclusion.items():
            hits = sum(
                1 for kw in rule.include_if_jd_contains
                if self._trigger_matches(kw, jd_normalized)
            )
            if hits:
                result['conditional'].append(exp_id)
                result['conditional_hits'][exp_id] = hits

        # Check rarely include rules
        for exp_id, rule in self.resume_preferences.experiences.rarely_include.items():
            if any(self._trigger_matches(kw, jd_normalized) for kw in rule.include_if_jd_contains):
                result['rarely'].append(exp_id)

        return result

    def get_project_selection_rules(self, jd_text: str) -> Dict[str, List[str]]:
        """
        Get which projects to include based on JD content.

        Triggers match against the *role-relevant* portion of the JD only
        (benefits/perks/about-us sections are stripped). Single-word triggers
        require word boundaries so 'ai' doesn't match 'training'.

        Args:
            jd_text: Job description text

        Returns:
            Dict with 'always', 'high_priority', 'conditional' lists
        """
        jd_normalized = self._normalize_jd_for_matching(jd_text)

        result = {
            'always': self.resume_preferences.projects.always_include.copy(),
            'high_priority': self.resume_preferences.projects.high_priority.copy(),
            'conditional': [],
            'conditional_hits': {}
        }

        # Check conditional inclusion rules (hit counts as above).
        for proj_id, rule in self.resume_preferences.projects.conditional_inclusion.items():
            hits = sum(
                1 for kw in rule.include_if_jd_contains
                if self._trigger_matches(kw, jd_normalized)
            )
            if hits:
                result['conditional'].append(proj_id)
                result['conditional_hits'][proj_id] = hits

        return result

    def should_exclude_job(self, job_title: str, job_description: str, job_location: str = "") -> tuple[bool, str]:
        """
        Thin wrapper — delegates to JobFilter service.

        Kept for backward compatibility. New code should call
        tools.jobs.job_filter.evaluate(job, profile) directly.
        """
        from tools.jobs.job_filter import evaluate
        from tools.search.job_listing import JobListing
        from datetime import datetime, timezone

        # Build a minimal JobListing for the filter
        job = JobListing(
            id="temp",
            title=job_title,
            company="",
            location=job_location,
            description=job_description,
            apply_url="",
            salary_min=None,
            salary_max=None,
            created=datetime.now(timezone.utc).isoformat(),
            source="temp",
        )

        decision = evaluate(job, self)
        return (decision.exclude, decision.reason or "")


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
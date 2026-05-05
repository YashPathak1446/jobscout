"""
Resume Parser - Unified interface for resume analysis

Combines LaTeX parsing and embedding scoring into a single class.

Location: jobscout_v3/tools/resume/resume_parser.py
"""

import os
import logging
from pathlib import Path
from typing import Dict, List, Tuple

from .latex_parser import (
    parse_latex_resume,
    LatexResume,
    LatexExperience,
    LatexProject,
)
from .embedding_scorer import (
    embed_resume_components,
    score_job_with_embeddings,
    EmbeddingScore,
)

logger = logging.getLogger(__name__)


class ResumeParser:
    """
    Unified resume parser and analyzer.
    
    Handles:
    - LaTeX resume parsing
    - Component embedding
    - Job-resume similarity scoring
    - Component selection for each job
    
    Example:
        >>> parser = ResumeParser("data/master_resumes/yash_pathak.tex")
        >>> experiences = parser.get_experiences()
        >>> score = parser.score_job("Software engineer with Python experience...")
        >>> selected = parser.select_components(jd_text, profile)
    """
    
    def __init__(self, resume_path: str, skip_embeddings: bool = False, mock_embeddings: bool = False):
        """
        Initialize parser with a LaTeX resume.
        
        Args:
            resume_path: Path to .tex file
            skip_embeddings: If True, skip embedding computation (saves API calls).
                           Use when you only need parsed resume data, not scoring.
            mock_embeddings: If True, use deterministic local mock embeddings for testing
                             analysis/scoring without calling the Gemini Embeddings API.
        """
        self.resume_path = Path(resume_path)
        
        if not self.resume_path.exists():
            raise FileNotFoundError(f"Resume not found: {resume_path}")
        
        logger.info(f"📄 Parsing resume: {self.resume_path.name}")
        
        # Parse the LaTeX resume
        self.parsed_resume: LatexResume = parse_latex_resume(str(self.resume_path))
        
        logger.info(f"✅ Parsed: {len(self.parsed_resume.experiences)} experiences, "
                   f"{len(self.parsed_resume.projects)} projects")
        
        if skip_embeddings:
            logger.info("⏭️  Skipping embeddings (--input mode, saves API calls)")
            self.component_embeddings = {}
            self.using_mock_embeddings = False
            return

        from .embedding_scorer import embed_resume_components, embed_resume_components_mock

        if mock_embeddings:
            logger.info("🧪 Using mock embeddings for analysis (zero API calls)")
            self.component_embeddings = embed_resume_components_mock(self.parsed_resume)
            self.using_mock_embeddings = True
            logger.info(f"✅ Embedded {len(self.component_embeddings)} components (mock)")
            return
        
        # ---------------------------------------------------------------
        # Real embeddings with cache
        # ---------------------------------------------------------------
        # Check cache first — if the master resume hasn't changed,
        # reuse the cached embeddings instead of making 25 API calls.
        from ..cache.embedding_cache import EmbeddingCache

        cache = EmbeddingCache()
        cached = cache.get(self.resume_path)

        if cached and cached.get('embeddings'):
            cached_embeddings = cached['embeddings']
            # Verify cache has embeddings for all current components
            current_ids = (
                {exp.id for exp in self.parsed_resume.experiences}
                | {proj.id for proj in self.parsed_resume.projects}
                | {'__skills__'}
            )
            cached_ids = set(cached_embeddings.keys())

            if current_ids <= cached_ids:
                logger.info(f"📦 Cache hit — reusing {len(cached_embeddings)} embeddings (0 API calls)")
                self.component_embeddings = cached_embeddings
                self.using_mock_embeddings = False
                return
            else:
                missing = current_ids - cached_ids
                logger.info(f"📦 Cache partial — missing {len(missing)} components, recomputing")

        # Cache miss or partial — compute real embeddings
        logger.info("🔢 Computing embeddings for resume components...")
        
        self.component_embeddings: Dict[str, List[float]] = embed_resume_components(
            self.parsed_resume
        )
        
        # Fall back to mock if real embeddings failed
        if len(self.component_embeddings) == 0:
            logger.warning("⚠️  Real embeddings failed, falling back to mock")
            self.component_embeddings = embed_resume_components_mock(
                self.parsed_resume
            )
            self.using_mock_embeddings = True
        else:
            self.using_mock_embeddings = False
            # Save to cache for next run
            cache.set(
                resume_path=self.resume_path,
                parsed_data={},  # We don't cache parsed data, just embeddings
                embeddings=self.component_embeddings,
            )
        
        logger.info(f"✅ Embedded {len(self.component_embeddings)} components" +
                   (" (mock)" if self.using_mock_embeddings else ""))
    
    def get_experiences(self) -> List[LatexExperience]:
        """Get all work experiences from resume."""
        return self.parsed_resume.experiences
    
    def get_projects(self) -> List[LatexProject]:
        """Get all projects from resume."""
        return self.parsed_resume.projects
    
    def get_experience_by_id(self, exp_id: str) -> LatexExperience | None:
        """Get a specific experience by ID. Supports fuzzy matching for backwards compatibility."""
        # Exact match first
        for exp in self.parsed_resume.experiences:
            if exp.id == exp_id:
                return exp
        # Prefix match (e.g., 'exp_sorenson' matches 'exp_sorenson_communications')
        for exp in self.parsed_resume.experiences:
            if exp.id.startswith(exp_id) or exp_id.startswith(exp.id):
                return exp
        # Substring match (e.g., 'exp_minecraft_agent' matches 'exp_autonomous_minecraft_agent')
        for exp in self.parsed_resume.experiences:
            # Strip prefix for comparison
            search_key = exp_id.replace('exp_', '')
            full_key = exp.id.replace('exp_', '')
            if search_key in full_key or full_key in search_key:
                return exp
        return None
    
    def get_project_by_id(self, proj_id: str) -> LatexProject | None:
        """Get a specific project by ID. Supports fuzzy matching for backwards compatibility."""
        # Exact match first
        for proj in self.parsed_resume.projects:
            if proj.id == proj_id:
                return proj
        # Prefix match (e.g., 'proj_jobscout' matches 'proj_jobscout_ai_job_automation')
        for proj in self.parsed_resume.projects:
            if proj.id.startswith(proj_id) or proj_id.startswith(proj.id):
                return proj
        # Substring match (e.g., 'proj_minecraft_agent' matches 'proj_autonomous_minecraft_agent')
        for proj in self.parsed_resume.projects:
            search_key = proj_id.replace('proj_', '')
            full_key = proj.id.replace('proj_', '')
            if search_key in full_key or full_key in search_key:
                return proj
        return None
    
    def score_job(self, jd_text: str, job_id: str = "unknown", 
                  title: str = "Unknown", company: str = "Unknown") -> EmbeddingScore:
        """
        Score how well the resume matches a job description.
        
        Args:
            jd_text: Full job description text
            job_id: Job identifier
            title: Job title
            company: Company name
            
        Returns:
            EmbeddingScore with overall score and component rankings
        """
        # Use appropriate scoring function based on embeddings type
        if self.using_mock_embeddings:
            from .embedding_scorer import score_job_mock
            score = score_job_mock(
                jd_text=jd_text,
                resume_embeddings=self.component_embeddings,
                parsed_resume=self.parsed_resume,
                max_experiences=5,
                max_projects=5,
            )
        else:
            from .embedding_scorer import score_job_with_embeddings
            score = score_job_with_embeddings(
                jd_text=jd_text,
                resume_embeddings=self.component_embeddings,
                parsed_resume=self.parsed_resume,
                max_experiences=5,
                max_projects=5,
            )
        
        # Update the job metadata
        if score:
            score.job_id = job_id
            score.title = title
            score.company = company
        
        return score
    
    def select_components(
        self,
        jd_text: str,
        profile,
        embedding_score: EmbeddingScore = None
    ) -> Dict[str, List[str]]:
        """
        Select which experiences and projects to include based on:
        1. Profile rules (always_include, conditional_inclusion)
        2. Embedding similarity scores
        3. Max counts from profile
        
        Args:
            jd_text: Full job description text
            profile: UserProfile with selection rules
            embedding_score: Pre-computed score (optional, will compute if not provided)
            
        Returns:
            Dict with:
                'experiences': List of experience IDs to include
                'projects': List of project IDs to include
                'skills': List of skills to emphasize
        """
        # Get or compute embedding score
        if embedding_score is None:
            embedding_score = self.score_job(jd_text)
        
        # Get selection rules from profile
        exp_rules = profile.get_experience_selection_rules(jd_text)
        proj_rules = profile.get_project_selection_rules(jd_text)
        
        # === SELECT EXPERIENCES ===
        selected_experiences = []
        
        # 1. Always include (from profile)
        selected_experiences.extend(exp_rules['always'])
        
        # 2. Conditional inclusion (triggered by JD keywords)
        selected_experiences.extend(exp_rules['conditional'])
        
        # 3. Fill remaining slots with top-scored experiences
        max_exp = profile.resume_preferences.experiences.max_count
        remaining_slots = max_exp - len(selected_experiences)
        
        if remaining_slots > 0:
            # Get top scored experiences not already selected
            for exp_id in embedding_score.best_experience_ids:
                if exp_id not in selected_experiences:
                    selected_experiences.append(exp_id)
                    remaining_slots -= 1
                    if remaining_slots == 0:
                        break
        
        # Trim to max count
        selected_experiences = selected_experiences[:max_exp]
        
        # === SELECT PROJECTS ===
        selected_projects = []
        
        # 1. Always include
        selected_projects.extend(proj_rules['always'])
        
        # 2. High priority
        selected_projects.extend(proj_rules['high_priority'])
        
        # 3. Conditional inclusion
        selected_projects.extend(proj_rules['conditional'])
        
        # 4. Fill remaining with top-scored
        max_proj = profile.resume_preferences.projects.max_count
        remaining_slots = max_proj - len(selected_projects)
        
        if remaining_slots > 0:
            for proj_id in embedding_score.best_project_ids:
                if proj_id not in selected_projects:
                    selected_projects.append(proj_id)
                    remaining_slots -= 1
                    if remaining_slots == 0:
                        break
        
        # Trim to max count
        selected_projects = selected_projects[:max_proj]
        
        # === SELECT SKILLS ===
        # Extract keywords from selected components
        selected_skills = set()
        
        for exp_id in selected_experiences:
            exp = self.get_experience_by_id(exp_id)
            if exp:
                selected_skills.update(exp.keywords)
        
        for proj_id in selected_projects:
            proj = self.get_project_by_id(proj_id)
            if proj:
                selected_skills.update(proj.keywords)
        
        return {
            'experiences': selected_experiences,
            'projects': selected_projects,
            'skills': sorted(list(selected_skills)),
        }
    
    def get_component_text(self, component_id: str) -> str:
        """Get the full text of a component (for debugging/logging)."""
        # Check experiences
        exp = self.get_experience_by_id(component_id)
        if exp:
            bullets = "\n".join(f"• {b}" for b in exp.bullets)
            return f"{exp.title} @ {exp.company}\n{bullets}"
        
        # Check projects
        proj = self.get_project_by_id(component_id)
        if proj:
            bullets = "\n".join(f"• {b}" for b in proj.bullets)
            return f"{proj.name}\n{bullets}"
        
        return ""


# CLI for testing
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python -m tools.resume.resume_parser <path_to_resume.tex>")
        sys.exit(1)
    
    resume_path = sys.argv[1]
    
    print(f"Testing ResumeParser with: {resume_path}\n")
    
    # Parse resume
    parser = ResumeParser(resume_path)
    
    print(f"{'='*80}")
    print(f"Resume: {parser.parsed_resume.name}")
    print(f"Email: {parser.parsed_resume.email}")
    print(f"{'='*80}\n")
    
    # Show experiences
    print("Experiences:")
    for exp in parser.get_experiences():
        print(f"  {exp.id}: {exp.title} @ {exp.company}")
    print()
    
    # Show projects
    print("Projects:")
    for proj in parser.get_projects():
        print(f"  {proj.id}: {proj.name}")
    print()
    
    # Test scoring with sample JD
    sample_jd = """
    We're looking for a Software Engineer with strong Python and AWS experience.
    You'll build scalable backend systems and work with distributed architectures.
    Experience with Docker, Kubernetes, and CI/CD is a plus.
    """
    
    print("Testing with sample JD...")
    score = parser.score_job(sample_jd, "test_job", "Software Engineer", "Test Company")
    
    print(f"\nOverall Score: {score.overall_score:.2f}")
    print(f"Top Experiences: {score.best_experience_ids[:3]}")
    print(f"Top Projects: {score.best_project_ids[:3]}")
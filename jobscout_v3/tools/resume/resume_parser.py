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
    
    def __init__(self, resume_path: str):
        """
        Initialize parser with a LaTeX resume.
        
        Args:
            resume_path: Path to .tex file
        """
        self.resume_path = Path(resume_path)
        
        if not self.resume_path.exists():
            raise FileNotFoundError(f"Resume not found: {resume_path}")
        
        logger.info(f"📄 Parsing resume: {self.resume_path.name}")
        
        # Parse the LaTeX resume
        self.parsed_resume: LatexResume = parse_latex_resume(str(self.resume_path))
        
        logger.info(f"✅ Parsed: {len(self.parsed_resume.experiences)} experiences, "
                   f"{len(self.parsed_resume.projects)} projects")
        
        # Pre-compute embeddings for all components
        logger.info("🔢 Computing embeddings for resume components...")
        
        # Try real embeddings first
        from .embedding_scorer import embed_resume_components, embed_resume_components_mock
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
        
        logger.info(f"✅ Embedded {len(self.component_embeddings)} components" +
                   (" (mock)" if self.using_mock_embeddings else ""))
    
    def get_experiences(self) -> List[LatexExperience]:
        """Get all work experiences from resume."""
        return self.parsed_resume.experiences
    
    def get_projects(self) -> List[LatexProject]:
        """Get all projects from resume."""
        return self.parsed_resume.projects
    
    def get_experience_by_id(self, exp_id: str) -> LatexExperience | None:
        """Get a specific experience by ID."""
        for exp in self.parsed_resume.experiences:
            if exp.id == exp_id:
                return exp
        return None
    
    def get_project_by_id(self, proj_id: str) -> LatexProject | None:
        """Get a specific project by ID."""
        for proj in self.parsed_resume.projects:
            if proj.id == proj_id:
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
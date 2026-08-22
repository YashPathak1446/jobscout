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
    
    def __init__(self, resume_path: str, skip_embeddings: bool = False,
                 mock_embeddings: bool = False, api_key: str = None):
        """
        Initialize parser with a LaTeX resume.
        
        Args:
            resume_path: Path to .tex file
            skip_embeddings: If True, skip embedding computation (saves API calls).
                           Use when you only need parsed resume data, not scoring.
            mock_embeddings: If True, use deterministic local mock embeddings for testing
                             analysis/scoring without calling the Gemini Embeddings API.
            api_key: Explicit Gemini key. None falls back to the environment,
                     which is what the CLI wants; a UI passes the user's own.
        """
        self.resume_path = Path(resume_path)
        self.api_key = api_key
        
        if not self.resume_path.exists():
            raise FileNotFoundError(f"Resume not found: {resume_path}")
        
        logger.info(f"📄 Parsing resume: {self.resume_path.name}")
        
        # Parse the LaTeX resume
        self.parsed_resume: LatexResume = parse_latex_resume(str(self.resume_path))

        # Keyword vocabulary is per-user: the curated TECH_KEYWORDS base plus
        # every tool in this resume's own skills section. Without this, a JD
        # naming a tool you actually list produces no keyword match at all
        # (Q7 — 45 of this resume's 74 skills were invisible).
        from tools.resume.latex_parser import (
            build_tech_vocabulary, keyword_source_text, _extract_keywords,
        )

        self.tech_vocabulary = build_tech_vocabulary(
            self.parsed_resume.skills.categories
        )

        # Component keywords are computed during parsing, against the base
        # list. Recompute them against the augmented vocabulary so both sides
        # of the keyword comparison use the same words. keyword_source_text
        # is shared with the parser so the two cannot drift — an earlier
        # version built the text here as tech+bullets and silently dropped
        # keywords that appear only in a title or employer name.
        for comp in list(self.parsed_resume.experiences) + list(self.parsed_resume.projects):
            comp.keywords = _extract_keywords(
                keyword_source_text(comp), vocabulary=self.tech_vocabulary
            )

        # Importance defaults from resume order — people lead with their
        # strongest work. These are defaults only; anything the profile
        # states explicitly wins (see tools/profile/derivation.py).
        from tools.profile.derivation import derive_component_importance

        self.derived_importance = {
            "experiences": derive_component_importance(
                [e.id for e in self.parsed_resume.experiences]
            ),
            "projects": derive_component_importance(
                [p.id for p in self.parsed_resume.projects]
            ),
        }

        logger.info(f"✅ Parsed: {len(self.parsed_resume.experiences)} experiences, "
                   f"{len(self.parsed_resume.projects)} projects, "
                   f"{len(self.tech_vocabulary)} keyword vocabulary")
        
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
        from config import EMBEDDING_MODEL

        # Model is passed in so a switch invalidates the cache instead of
        # silently mixing two vector spaces (R11).
        cache = EmbeddingCache(model=EMBEDDING_MODEL)
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
            self.parsed_resume, api_key=self.api_key
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
                api_key=self.api_key,
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
        Select which experiences and projects to include using composite scoring.

        Score per component:
            final_score =
                embedding_score          (semantic similarity)
              + keyword_match_bonus      (exact tech/skill matches in JD)
              + conditional_bonus        (profile conditional rules triggered)
              + importance_boost         (user-defined component importance)
              + always_include_boost     (profile always_include)
              never_include → excluded entirely

        This replaces the old waterfall (always → high_priority → conditional
        → score-based) which blocked JD-specific matches when high-priority
        slots were full.

        Returns:
            Dict with 'experiences', 'projects', 'skills' lists of canonical IDs.
        """
        # Get or compute embedding score
        if embedding_score is None:
            embedding_score = self.score_job(jd_text)

        exp_rules = profile.get_experience_selection_rules(jd_text)
        proj_rules = profile.get_project_selection_rules(jd_text)

        # Profile tiers layered over the resume-order defaults, so a profile
        # that omits a component gets a considered tier instead of an
        # implicit 'medium'.
        from tools.profile.derivation import merge_importance

        importance_cfg = profile.resume_preferences.component_importance
        exp_importance = merge_importance(
            importance_cfg.experiences, self.derived_importance["experiences"]
        )
        proj_importance = merge_importance(
            importance_cfg.projects, self.derived_importance["projects"]
        )

        jd_lower = jd_text.lower()
        jd_keywords = _extract_jd_keywords(jd_lower, self.tech_vocabulary)

        max_exp = profile.resume_preferences.experiences.max_count
        max_proj = profile.resume_preferences.projects.max_count

        # ── Experience selection ──────────────────────────────────────────────
        # Hit counts keyed by canonical id, matching how conditional_ids is
        # resolved below — a profile may reference a component by alias.
        exp_hits = {
            self._resolve_exp_canonical(eid): n
            for eid, n in (exp_rules.get('conditional_hits') or {}).items()
        }

        never_exp = set(
            self._resolve_exp_canonical(eid)
            for eid in (profile.resume_preferences.experiences.never_include or [])
        )

        exp_scores = {}
        for exp in self.parsed_resume.experiences:
            if exp.id in never_exp:
                continue

            score = _composite_score(
                comp_id=exp.id,
                embedding_scores=embedding_score.experience_scores,
                jd_keywords=jd_keywords,
                comp_text=f"{exp.title} {exp.company} {' '.join(exp.bullets)}",
                comp_tech="",
                comp_keywords=exp.keywords,
                always_ids=set(
                    self._resolve_exp_canonical(eid)
                    for eid in exp_rules['always']
                ),
                conditional_ids=set(
                    self._resolve_exp_canonical(eid)
                    for eid in exp_rules['conditional']
                ),
                importance_map=exp_importance,
                conditional_hits=exp_hits,
            )
            exp_scores[exp.id] = score

        selected_experiences = _pick_top(exp_scores, max_exp)

        # ── Project selection ─────────────────────────────────────────────────
        proj_hits = {
            self._resolve_proj_canonical(pid): n
            for pid, n in (proj_rules.get('conditional_hits') or {}).items()
        }

        never_proj = set(
            self._resolve_proj_canonical(pid)
            for pid in (profile.resume_preferences.projects.never_include or [])
        )
        always_proj = set(
            self._resolve_proj_canonical(pid)
            for pid in proj_rules['always']
        )
        conditional_proj = set(
            self._resolve_proj_canonical(pid)
            for pid in proj_rules['conditional']
        )

        proj_scores = {}
        for proj in self.parsed_resume.projects:
            if proj.id in never_proj:
                continue

            score = _composite_score(
                comp_id=proj.id,
                embedding_scores=embedding_score.project_scores,
                jd_keywords=jd_keywords,
                comp_text=f"{proj.name} {' '.join(proj.bullets)}",
                comp_tech=proj.tech,
                comp_keywords=proj.keywords,
                always_ids=always_proj,
                conditional_ids=conditional_proj,
                importance_map=proj_importance,
                conditional_hits=proj_hits,
            )
            proj_scores[proj.id] = score

        selected_projects = _pick_top(proj_scores, max_proj)

        # Log score breakdown for selected components
        # Build the breakdown structure for return + logging
        score_breakdown = {}
        for cid, sd in {**exp_scores, **proj_scores}.items():
            score_breakdown[cid] = sd

        # Log JD keywords extracted (helps spot scraper noise + missing terms)
        if jd_keywords:
            logger.info(f"   📋 JD keywords ({len(jd_keywords)}): {', '.join(sorted(jd_keywords))}")

        # Log which conditional triggers fired
        fired_exp = sorted(
            self._resolve_exp_canonical(eid)
            for eid in exp_rules['conditional']
        )
        fired_proj = sorted(
            self._resolve_proj_canonical(pid)
            for pid in proj_rules['conditional']
        )
        if fired_exp or fired_proj:
            logger.info(f"   🔔 Conditional triggers fired:")
            for cid in fired_exp:
                logger.info(f"      exp  {cid}")
            for cid in fired_proj:
                logger.info(f"      proj {cid}")

        # Log full score breakdown for selected + top-ranked components (INFO)
        logger.info("   🎯 Component scores (top 10):")
        for cid, sd in sorted(
            score_breakdown.items(),
            key=lambda x: -x[1]['final']
        )[:10]:
            selected = cid in selected_experiences or cid in selected_projects
            marker = "✅" if selected else "  "
            short = cid.replace('proj_', '').replace('exp_', '')[:32]
            logger.info(
                f"   {marker} {short:32} "
                f"emb={sd['embedding']:.2f} kw={sd['keyword']:.2f} "
                f"cond={sd['conditional']:.2f} imp={sd['importance']:.2f} "
                f"alw={sd['always']:.2f} → {sd['final']:.2f}"
            )

        # ── Skills ───────────────────────────────────────────────────────────
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
            'score_breakdown': score_breakdown,
            'jd_keywords': sorted(jd_keywords),
            'conditional_fired': {
                'experiences': fired_exp,
                'projects': fired_proj,
            },
        }

    def _resolve_exp_canonical(self, eid: str) -> str:
        exp = self.get_experience_by_id(eid)
        return exp.id if exp else eid

    def _resolve_proj_canonical(self, pid: str) -> str:
        proj = self.get_project_by_id(pid)
        return proj.id if proj else pid
    
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

# =============================================================================
# COMPOSITE SCORING HELPERS
# =============================================================================

# Generic terms that are too common to count as meaningful JD keyword matches.
# These appear in almost every SWE JD and don't differentiate components.
_GENERIC_TERMS = {
    "api", "backend", "frontend", "software", "application", "system",
    "data", "service", "server", "client", "code", "build", "team",
    "work", "experience", "strong", "knowledge", "skills", "ability",
    "development", "engineering", "developer", "engineer", "project",
    "solution", "support", "management", "process", "performance",
    "design", "architecture", "implement", "deploy", "test", "debug",
}


def _extract_jd_keywords(jd_lower: str, vocabulary=None) -> set:
    """
    Extract meaningful tech keywords from the JD text.

    Uses the caller's vocabulary — the parser's per-user augmented list —
    falling back to the shared TECH_KEYWORDS base so this stays usable
    standalone. Both sides of the keyword comparison must use the same
    words, or a JD term can match nothing simply because the resume side
    never learned it.
    """
    from tools.resume.latex_parser import TECH_KEYWORDS, term_matches
    found = set()
    for kw in (vocabulary if vocabulary is not None else TECH_KEYWORDS):
        kw_lower = kw.lower()
        if kw_lower in _GENERIC_TERMS:
            continue
        # Same matcher as the resume side. This was plain substring matching,
        # with no boundaries at all, so a JD saying "scalable" credited Scala
        # and "antitrust" credited Rust.
        if term_matches(kw_lower, jd_lower):
            found.add(kw_lower)
    return found


def _keyword_match_score(
    jd_keywords: set,
    comp_tech: str,
    comp_keywords: list,
    comp_text: str,
) -> float:
    """
    Score a component based on exact keyword overlap with JD.

    Weights:
    - Tech stack match (pipe-separated list in project heading): +0.08 each
    - Component keywords match: +0.05 each
    - Capped at 0.25 total to avoid dominating embedding score.

    Generic terms are excluded to avoid everything matching everything.
    """
    if not jd_keywords:
        return 0.0

    score = 0.0

    # Tech stack matches (highest weight — explicit technology listing)
    if comp_tech:
        tech_terms = {t.strip().lower() for t in comp_tech.split(",")}
        tech_terms -= _GENERIC_TERMS
        overlap = jd_keywords & tech_terms
        score += len(overlap) * 0.08

    # Component keyword matches
    kw_set = {k.lower() for k in comp_keywords} - _GENERIC_TERMS
    overlap = jd_keywords & kw_set
    score += len(overlap) * 0.05

    return min(score, 0.25)


# Conditional-trigger weighting. Per-hit rather than all-or-nothing: see R14.
CONDITIONAL_PER_HIT = 0.07
CONDITIONAL_MAX = 0.20


def _composite_score(
    comp_id: str,
    embedding_scores: dict,
    jd_keywords: set,
    comp_text: str,
    comp_tech: str,
    comp_keywords: list,
    always_ids: set,
    conditional_ids: set,
    importance_map: dict,
    conditional_hits: dict | None = None,
) -> dict:
    """
    Compute the composite selection score for one component.

    Components:
        embedding    : semantic similarity (0.0–1.0)
        keyword      : exact tech match bonus (0.0–0.25, capped)
        conditional  : +0.07 per distinct trigger matched, capped at +0.20
        importance   : high=+0.15, medium=+0.05, low=+0.00
        always       : +0.30 if in always_include list
        final        : sum of above

    Args:
        comp_id: Canonical component ID
        embedding_scores: Dict of {comp_id: float} from EmbeddingScore
        jd_keywords: Set of meaningful keywords extracted from JD
        comp_text: Combined text of component (title + company + bullets)
        comp_tech: Tech stack string (for projects)
        comp_keywords: Pre-extracted keyword list from parser
        always_ids: Set of canonical IDs in always_include
        conditional_ids: Set of canonical IDs triggered by conditional rules
        conditional_hits: {comp_id: number of distinct triggers matched}.
            Absent or empty falls back to the old all-or-nothing +0.20.
        importance_map: Dict of {comp_id: 'high'|'medium'|'low'}

    Returns:
        Dict with 'embedding', 'keyword', 'conditional', 'importance',
        'always', 'final' keys for logging/debugging.
    """
    emb = embedding_scores.get(comp_id, 0.0)

    kw = _keyword_match_score(jd_keywords, comp_tech, comp_keywords, comp_text)

    # Partial credit by hit count. A single incidental keyword used to earn
    # the same +0.20 as a genuinely on-topic match, and 85% of fires were
    # single-hit: a JD saying "rapid prototyping" gave a UX project the full
    # bonus against a backend role. Scaling removes the cliff without
    # discarding weak evidence outright. See R14.
    if conditional_hits:
        cond = min(CONDITIONAL_PER_HIT * conditional_hits.get(comp_id, 0),
                   CONDITIONAL_MAX)
    else:
        cond = CONDITIONAL_MAX if comp_id in conditional_ids else 0.0

    imp_tier = importance_map.get(comp_id, "medium")
    imp = {"high": 0.15, "medium": 0.05, "low": 0.0}.get(imp_tier, 0.05)

    always = 0.30 if comp_id in always_ids else 0.0

    final = emb + kw + cond + imp + always

    return {
        "embedding": emb,
        "keyword": kw,
        "conditional": cond,
        "importance": imp,
        "always": always,
        "final": final,
    }


def _pick_top(score_details: dict, n: int) -> list:
    """
    Return IDs of top-N components by final score.

    Args:
        score_details: Dict of {comp_id: score_dict_with_'final'_key}
        n: Number of components to select

    Returns:
        List of comp_ids, highest score first.
    """
    ranked = sorted(score_details.items(), key=lambda x: -x[1]["final"])
    return [cid for cid, _ in ranked[:n]]


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
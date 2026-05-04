"""
Embedding Scorer — Semantic similarity scoring using Gemini embeddings.

Uses gemini-embedding-001 (free tier) to convert resume components and
JD text into vectors, then computes cosine similarity for ranking.

Falls back to simple keyword overlap when --mock-embeddings is used.
"""

import os
import logging
import math
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingScore:
    """Score for a single job listing against the resume."""
    job_id: str
    title: str
    company: str
    overall_score: float                # 0.0 to 1.0
    best_experience_ids: list[str]      # Top matching experience IDs
    best_project_ids: list[str]         # Top matching project IDs
    experience_scores: dict[str, float] # component_id → similarity
    project_scores: dict[str, float]    # component_id → similarity


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# =========================================================================
# GEMINI EMBEDDINGS (Real)
# =========================================================================

def _get_embedding(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]:
    """
    Get embedding vector from Gemini API.
    Uses gemini-embedding-001 (free tier, text-only).

    Args:
        text: Text to embed (max 2048 tokens).
        task_type: RETRIEVAL_DOCUMENT for resume/JD content,
                   RETRIEVAL_QUERY for search queries.
    """
    try:
        from google import genai

        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

        result = client.models.embed_content(
            model="gemini-embedding-001",
            contents=text[:8000],  # Safety truncation
            config={
                "task_type": task_type,
                "output_dimensionality": 768,  # Smaller = faster, still high quality
            },
        )

        return result.embeddings[0].values

    except Exception as e:
        logger.error(f"Embedding API error: {e}")
        return []


def embed_resume_components(parsed_resume) -> dict[str, list[float]]:
    """
    Embed all resume components (experiences + projects).
    Returns dict mapping component_id → embedding vector.
    Called once at startup, cached for all JD comparisons.
    """
    embeddings = {}

    # Embed each experience
    for exp in parsed_resume.experiences:
        text = f"{exp.title} {exp.company} {' '.join(exp.bullets)}"
        vec = _get_embedding(text, "RETRIEVAL_DOCUMENT")
        if vec:
            embeddings[exp.id] = vec
            logger.debug(f"Embedded experience: {exp.id}")

    # Embed each project
    for proj in parsed_resume.projects:
        text = f"{proj.name} {proj.tech} {' '.join(proj.bullets)}"
        vec = _get_embedding(text, "RETRIEVAL_DOCUMENT")
        if vec:
            embeddings[proj.id] = vec
            logger.debug(f"Embedded project: {proj.id}")

    # Embed the full skills section
    # Embed skills section
    if parsed_resume.skills and parsed_resume.skills.categories:
        skills_text = " ".join(parsed_resume.skills.categories.values())
        vec = _get_embedding(skills_text, "RETRIEVAL_DOCUMENT")
        if vec:
            embeddings["__skills__"] = vec

    logger.info(f"Embedded {len(embeddings)} resume components")
    return embeddings


def score_job_with_embeddings(
    jd_text: str,
    resume_embeddings: dict[str, list[float]],
    parsed_resume,
    max_experiences: int = 3,
    max_projects: int = 4,
) -> EmbeddingScore | None:
    """
    Score a single JD against pre-computed resume embeddings.

    Args:
        jd_text: The JD text (full or snippet).
        resume_embeddings: Pre-computed embeddings from embed_resume_components().
        parsed_resume: The parsed resume (for ID lookups).
        max_experiences: How many top experiences to select.
        max_projects: How many top projects to select.

    Returns:
        EmbeddingScore with similarity scores, or None on failure.
    """
    # Embed the JD
    jd_vec = _get_embedding(jd_text, "RETRIEVAL_QUERY")
    if not jd_vec:
        return None

    # Score each component
    exp_scores = {}
    proj_scores = {}

    for exp in parsed_resume.experiences:
        if exp.id in resume_embeddings:
            sim = _cosine_similarity(jd_vec, resume_embeddings[exp.id])
            exp_scores[exp.id] = sim

    for proj in parsed_resume.projects:
        if proj.id in resume_embeddings:
            sim = _cosine_similarity(jd_vec, resume_embeddings[proj.id])
            proj_scores[proj.id] = sim

    # Skills section bonus
    skills_sim = 0.0
    if "__skills__" in resume_embeddings:
        skills_sim = _cosine_similarity(jd_vec, resume_embeddings["__skills__"])

    # Select top components
    sorted_exp = sorted(exp_scores.items(), key=lambda x: x[1], reverse=True)
    sorted_proj = sorted(proj_scores.items(), key=lambda x: x[1], reverse=True)

    best_exp = [eid for eid, _ in sorted_exp[:max_experiences]]
    best_proj = [pid for pid, _ in sorted_proj[:max_projects]]

    # Overall score: weighted combination
    top_exp_avg = (
        sum(s for _, s in sorted_exp[:max_experiences]) / max_experiences
        if sorted_exp else 0
    )
    top_proj_avg = (
        sum(s for _, s in sorted_proj[:max_projects]) / max_projects
        if sorted_proj else 0
    )

    # Weight: 40% experiences, 30% projects, 30% skills
    overall = top_exp_avg * 0.4 + top_proj_avg * 0.3 + skills_sim * 0.3

    # Normalize to 0-100 scale
    # Cosine similarity for embeddings typically ranges 0.3-0.9
    # Map 0.3-0.9 → 0-100
    overall_pct = max(0, min(100, (overall - 0.3) / 0.6 * 100))

    return EmbeddingScore(
        job_id="",
        title="",
        company="",
        overall_score=round(overall_pct, 1),
        best_experience_ids=best_exp,
        best_project_ids=best_proj,
        experience_scores=exp_scores,
        project_scores=proj_scores,
    )


# =========================================================================
# MOCK EMBEDDINGS (Testing — zero API calls)
# =========================================================================

def _mock_embedding(text: str) -> list[float]:
    """
    Generate a deterministic pseudo-embedding from text.
    Uses keyword hashing — not semantic, but good enough for testing pipeline flow.
    """
    import hashlib

    # Create a reproducible 768-dim vector from text content
    text_lower = text.lower()
    vec = [0.0] * 768

    # Hash each word and scatter into vector dimensions
    words = text_lower.split()
    for word in words:
        h = hashlib.md5(word.encode()).hexdigest()
        for i in range(0, len(h), 4):
            dim = int(h[i:i+4], 16) % 768
            vec[dim] += 1.0

    # Normalize
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]

    return vec


def embed_resume_components_mock(parsed_resume) -> dict[str, list[float]]:
    """Mock embedding for testing without API calls."""
    embeddings = {}
    for exp in parsed_resume.experiences:
        text = f"{exp.title} {exp.company} {' '.join(exp.keywords)} {' '.join(exp.bullets)}"
        embeddings[exp.id] = _mock_embedding(text)
    for proj in parsed_resume.projects:
        text = f"{proj.name} {proj.tech} {' '.join(proj.keywords)} {' '.join(proj.bullets)}"
        embeddings[proj.id] = _mock_embedding(text)
    # Mock embed skills
    if parsed_resume.skills and parsed_resume.skills.categories:
        skills_text = " ".join(parsed_resume.skills.categories.values())
        embeddings["__skills__"] = _mock_embedding(skills_text)
    logger.info(f"Mock-embedded {len(embeddings)} resume components")
    return embeddings


def score_job_mock(
    jd_text: str,
    resume_embeddings: dict[str, list[float]],
    parsed_resume,
    max_experiences: int = 3,
    max_projects: int = 4,
) -> EmbeddingScore:
    """Score using mock embeddings. Same interface as real scorer."""
    jd_vec = _mock_embedding(jd_text)

    exp_scores = {}
    proj_scores = {}

    for exp in parsed_resume.experiences:
        if exp.id in resume_embeddings:
            exp_scores[exp.id] = _cosine_similarity(jd_vec, resume_embeddings[exp.id])
    for proj in parsed_resume.projects:
        if proj.id in resume_embeddings:
            proj_scores[proj.id] = _cosine_similarity(jd_vec, resume_embeddings[proj.id])

    sorted_exp = sorted(exp_scores.items(), key=lambda x: x[1], reverse=True)
    sorted_proj = sorted(proj_scores.items(), key=lambda x: x[1], reverse=True)

    best_exp = [eid for eid, _ in sorted_exp[:max_experiences]]
    best_proj = [pid for pid, _ in sorted_proj[:max_projects]]

    top_exp_avg = sum(s for _, s in sorted_exp[:max_experiences]) / max(1, min(len(sorted_exp), max_experiences))
    top_proj_avg = sum(s for _, s in sorted_proj[:max_projects]) / max(1, min(len(sorted_proj), max_projects))
    skills_sim = _cosine_similarity(jd_vec, resume_embeddings.get("__skills__", [0.0]*768))

    overall = top_exp_avg * 0.4 + top_proj_avg * 0.3 + skills_sim * 0.3
    overall_pct = max(0, min(100, (overall - 0.1) / 0.5 * 100))

    return EmbeddingScore(
        job_id="", title="", company="",
        overall_score=round(overall_pct, 1),
        best_experience_ids=best_exp,
        best_project_ids=best_proj,
        experience_scores=exp_scores,
        project_scores=proj_scores,
    )


# === CLI for testing ===
if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")

    from jobscout.tools.resume_parser import parse_resume_file

    parsed = parse_resume_file("data/master_resume.txt")
    print(f"Parsed: {len(parsed.experiences)} exp, {len(parsed.projects)} proj\n")

    # Test with mock embeddings
    print("Testing mock embeddings...")
    embeddings = embed_resume_components_mock(parsed)
    print(f"Embedded {len(embeddings)} components\n")

    test_jd = (
        "Software Engineer. Requirements: Python, AWS, Docker, Kubernetes, "
        "CI/CD, REST APIs, distributed systems, microservices."
    )
    result = score_job_mock(test_jd, embeddings, parsed)
    print(f"Score: {result.overall_score}%")
    print(f"Best experiences: {result.best_experience_ids}")
    print(f"Best projects: {result.best_project_ids}")
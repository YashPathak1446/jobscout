"""
Embedding Scorer — Semantic similarity scoring using Gemini embeddings.

Converts resume components and JD text into vectors, then computes cosine
similarity for ranking. The model comes from config.EMBEDDING_MODEL — it
used to be hardcoded here, which quietly made the config constant a lie.

Falls back to simple keyword overlap when --mock-embeddings is used.
"""

import os
import logging
import math
from dataclasses import dataclass, field

from config import EMBEDDING_BACKEND, EMBEDDING_MODEL, LOCAL_EMBEDDING_MODEL
from .latex_parser import _GENERIC_TERMS, term_matches

logger = logging.getLogger(__name__)

# Vectors are requested at a fixed width so cosine similarity is defined
# across everything in one cache. This does NOT make vectors from different
# models comparable — same width, different space. See R11.
EMBEDDING_DIMENSIONS = 768


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
    # What the score is made of (R67). A single number nobody can take apart
    # is what let a job with two shared technologies outrank one with eleven.
    embedding_score: float = 0.0        # the semantic half, 0-100
    keyword_score: float = 0.0          # the evidence half, 0-100
    keyword_hits: list[str] = field(default_factory=list)  # terms both name


# Raw similarity is not comparable between backends, so the map onto 0-100 is
# per backend. Gemini's cosines for this kind of text sit around 0.3-0.9;
# model2vec's static embeddings run an order of magnitude lower, because a
# short component is being compared against a long job description and static
# vectors dilute across length.
#
# Both figures are measured, not assumed. The Gemini pair is the original
# calibration; the local pair comes from scoring the frozen 20-JD baseline,
# where raw overall ran from about 0.00 to 0.08. Getting this wrong is not
# subtle in the way R24's threshold was — the wrong floor sends every job to
# 0.0 and the pipeline finds nothing at all, which is exactly what the first
# version of the local backend did.
CALIBRATION = {
    "gemini": (0.30, 0.60),
    "local": (0.00, 0.10),
}


# How the two halves of a job score are weighted (R67).
#
# The embedding half alone barely discriminates: across 69 real scored jobs it
# ran 41.5-55.8 with a standard deviation of 3.58 — a coefficient of variation
# of 0.071, which is to say every job scored about the same. Half of them sat
# inside a 4-point band. R49 noticed the symptom and answered it with display
# bands; this is the cause.
#
# Concrete overlap — technologies named by both the posting and the resume —
# discriminates roughly eight times better on the same corpus (CoV 0.586), and
# the two rank jobs differently enough to matter: Spearman 0.312. Where they
# disagreed, the embedding was wrong. It put a posting sharing *two*
# technologies with the resume in fourth place and one sharing *eleven* near
# the bottom, because the resume is AI-heavy and the embedding rewards a
# document that reads like AI rather than one that names the same tools.
#
# Blending at 0.3 mirrors `_composite_score`, where the keyword term is capped
# at 0.25 against an embedding around 0.6 — about 30% of the total — and was
# not tuned to flatter this corpus.
KEYWORD_WEIGHT = 0.3

# Shared technologies at which the keyword half is full marks. The 90th
# percentile of the same 69 jobs; past that, more overlap says little, and the
# cap stops a keyword-stuffed posting from topping the board on repetition.
KEYWORD_SATURATION = 8


def resume_terms(parsed_resume) -> set:
    """
    Every technology the resume names, minus the words every posting contains.

    Taken from the components' own keyword lists, which the parser already
    built against the user's own vocabulary (Q7) — so this generalises to a
    resume this code has never seen.
    """
    terms = set()
    for component in list(parsed_resume.experiences) + list(parsed_resume.projects):
        terms |= {k.lower() for k in (component.keywords or [])}
    return terms - _GENERIC_TERMS


def keyword_overlap(jd_text: str, parsed_resume) -> list:
    """The technologies this posting and this resume both name, sorted."""
    jd_lower = (jd_text or "").lower()
    return sorted(t for t in resume_terms(parsed_resume) if term_matches(t, jd_lower))


def _normalise(overall: float) -> float:
    """Map a raw blended similarity onto 0-100 for the active backend."""
    backend = active_backend()[0]
    floor, span = CALIBRATION.get(backend, CALIBRATION["gemini"])
    return round(max(0.0, min(100.0, (overall - floor) / span * 100)), 1)


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

_BACKEND = None


def active_backend() -> tuple:
    """
    Which backend this process embeds with, as (name, model, dimensions).

    Resolved once and reused, so a single run can never mix backends —
    embedding a resume with one model and a job description with another
    would produce a similarity score with no meaning.

    "auto" prefers Gemini when a key is resolvable, because it is the backend
    every measurement in `known_questions.md` was taken against. Without a
    key it falls back to local rather than failing, which is the whole point.
    """
    global _BACKEND

    if _BACKEND is not None:
        return _BACKEND

    from config import resolve_api_key
    from tools.resume import local_embeddings

    choice = (EMBEDDING_BACKEND or "auto").lower()

    if choice == "auto":
        choice = "gemini" if resolve_api_key() else "local"

    if choice == "local":
        if not local_embeddings.is_available():
            logger.error(
                "Local embeddings requested but model2vec is not installed. "
                "Run: pip install model2vec"
            )
            _BACKEND = ("local", LOCAL_EMBEDDING_MODEL, 0)
        else:
            dims = local_embeddings.dimensions(LOCAL_EMBEDDING_MODEL)
            logger.info(f"Embeddings: local, {LOCAL_EMBEDDING_MODEL} ({dims}d), no API key needed")
            _BACKEND = ("local", LOCAL_EMBEDDING_MODEL, dims)
    else:
        _BACKEND = ("gemini", EMBEDDING_MODEL, EMBEDDING_DIMENSIONS)

    return _BACKEND


_EMBEDDING_CACHE = None


def _embedding_cache():
    """
    One cache per process, built on first use.

    Lazy so that importing this module does not create a directory, which
    matters for tests and for anyone importing the scorer to read a
    dataclass.
    """
    global _EMBEDDING_CACHE

    if _EMBEDDING_CACHE is None:
        from config import EMBEDDING_CACHE_DIR, EMBEDDING_CACHE_ENABLED
        from tools.cache.text_embedding_cache import TextEmbeddingCache

        _, _, dims = active_backend()
        _EMBEDDING_CACHE = TextEmbeddingCache(
            cache_dir=EMBEDDING_CACHE_DIR,
            enabled=EMBEDDING_CACHE_ENABLED,
            # Sized to the *active* backend. Gemini is 768 and the local model
            # 256, so a fixed number here would reject every entry from
            # whichever backend it was not written for (R28's guard).
            dimensions=dims or None,
        )

    return _EMBEDDING_CACHE


def _get_embedding(
    text: str,
    task_type: str = "RETRIEVAL_DOCUMENT",
    api_key: str = None,
) -> list[float]:
    """
    Get embedding vector from Gemini API, using config.EMBEDDING_MODEL.

    Args:
        text: Text to embed (max 2048 tokens).
        task_type: RETRIEVAL_DOCUMENT for resume/JD content,
                   RETRIEVAL_QUERY for search queries.
        api_key: Explicit key; falls back to the environment when None.
    """
    # The cache key is the string actually sent to the API, truncation
    # included. Keying on the untruncated text would give two inputs that
    # truncate identically separate entries for one identical API call.
    payload = text[:8000]
    backend, model_name, _ = active_backend()
    cache = _embedding_cache()

    cached = cache.get(payload, model_name, task_type)
    if cached is not None:
        return cached

    if backend == "local":
        from tools.resume import local_embeddings

        vector = local_embeddings.embed(payload, model_name)
        cache.set(payload, model_name, task_type, vector)
        return vector

    try:
        from google import genai

        from config import resolve_api_key

        client = genai.Client(api_key=resolve_api_key(api_key))

        result = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=payload,
            config={
                "task_type": task_type,
                "output_dimensionality": EMBEDDING_DIMENSIONS,
            },
        )

        vector = result.embeddings[0].values
        cache.set(payload, model_name, task_type, vector)
        return vector

    except Exception as e:
        logger.error(f"Embedding API error: {e}")
        return []


def embed_resume_components(parsed_resume, api_key: str = None) -> dict[str, list[float]]:
    """
    Embed all resume components (experiences + projects).
    Returns dict mapping component_id → embedding vector.
    Called once at startup, cached for all JD comparisons.
    """
    embeddings = {}

    # Embed each experience
    for exp in parsed_resume.experiences:
        text = f"{exp.title} {exp.company} {' '.join(exp.bullets)}"
        vec = _get_embedding(text, "RETRIEVAL_DOCUMENT", api_key=api_key)
        if vec:
            embeddings[exp.id] = vec
            logger.debug(f"Embedded experience: {exp.id}")

    # Embed each project
    for proj in parsed_resume.projects:
        text = f"{proj.name} {proj.tech} {' '.join(proj.bullets)}"
        vec = _get_embedding(text, "RETRIEVAL_DOCUMENT", api_key=api_key)
        if vec:
            embeddings[proj.id] = vec
            logger.debug(f"Embedded project: {proj.id}")

    # Embed the full skills section
    # Embed skills section
    if parsed_resume.skills and parsed_resume.skills.categories:
        skills_text = " ".join(parsed_resume.skills.categories.values())
        vec = _get_embedding(skills_text, "RETRIEVAL_DOCUMENT", api_key=api_key)
        if vec:
            embeddings["__skills__"] = vec

    logger.info(f"Embedded {len(embeddings)} resume components")
    return embeddings


def _section_average(sorted_scores, cap: int):
    """
    The mean of the top `cap` components, and whether there were any.

    Divided by **how many were actually considered**, not by the cap. The
    production scorer divided by the cap, so a resume with three jobs scored
    its experience term at three-fifths of what it earned and a resume with no
    projects scored that whole term as zero. The mock scorer next door has had
    the correct divisor all along, which is the third time a fix has existed on
    one of two twin paths (R69, R70) — and this is the one that decided whether
    the product returned anything at all.

    Returns `(average, present)`. `present` is False for a section the resume
    does not have, which is not the same as one that scored badly and must not
    be averaged in as a zero.
    """
    considered = sorted_scores[:cap]
    if not considered:
        return 0.0, False
    return sum(score for _, score in considered) / len(considered), True


def _weighted(terms):
    """
    Blend `(value, weight, present)` triples over the sections that exist.

    A section the resume does not have contributes no evidence, so its weight
    is shared out among the ones that do rather than dragging the total toward
    zero. Priya Raghunathan has three jobs and no projects: under the old
    arithmetic her ceiling was 0.4 x (3/5) x similarity, and five senior
    backend roles she is plainly qualified for scored 1.8%, 1.8%, 1.8%, 4.7%
    and 15.2% against a threshold of 40. The run finished, reported success,
    and produced nothing.

    This is the codebase's own invariant reaching the scorer: absence is not a
    value. A missing section is unknown evidence, not evidence of a bad match.
    """
    live = [(value, weight) for value, weight, present in terms if present]
    if not live:
        return 0.0
    total_weight = sum(weight for _, weight in live)
    return sum(value * weight for value, weight in live) / total_weight


def score_job_with_embeddings(
    jd_text: str,
    resume_embeddings: dict[str, list[float]],
    parsed_resume,
    max_experiences: int = 3,
    max_projects: int = 4,
    api_key: str = None,
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
    jd_vec = _get_embedding(jd_text, "RETRIEVAL_QUERY", api_key=api_key)
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

    # Overall score: weighted combination. 40% experiences, 30% projects,
    # 30% skills — over the sections this resume actually has.
    top_exp_avg, has_exp = _section_average(sorted_exp, max_experiences)
    top_proj_avg, has_proj = _section_average(sorted_proj, max_projects)
    overall = _weighted([
        (top_exp_avg, 0.4, has_exp),
        (top_proj_avg, 0.3, has_proj),
        (skills_sim, 0.3, "__skills__" in resume_embeddings),
    ])

    embedding_pct = _normalise(overall)

    # The half that knows what the job is actually built with (R67).
    #
    # Blended after normalisation rather than before, because `_normalise` is
    # calibrated per backend against raw cosine ranges — folding a keyword
    # count into `overall` would push it outside the window those constants
    # were measured for and silently rescale every score.
    hits = keyword_overlap(jd_text, parsed_resume)
    keyword_pct = min(len(hits) / KEYWORD_SATURATION, 1.0) * 100
    overall_pct = (embedding_pct * (1 - KEYWORD_WEIGHT)
                   + keyword_pct * KEYWORD_WEIGHT)

    return EmbeddingScore(
        job_id="",
        title="",
        company="",
        overall_score=round(overall_pct, 1),
        best_experience_ids=best_exp,
        best_project_ids=best_proj,
        experience_scores=exp_scores,
        project_scores=proj_scores,
        embedding_score=round(embedding_pct, 1),
        keyword_score=round(keyword_pct, 1),
        keyword_hits=hits,
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

    # Same arithmetic as the real scorer, through the same helpers. This one
    # already divided by what it considered; what it shared with production
    # was averaging an absent section in as a zero.
    top_exp_avg, has_exp = _section_average(sorted_exp, max_experiences)
    top_proj_avg, has_proj = _section_average(sorted_proj, max_projects)
    has_skills = "__skills__" in resume_embeddings
    skills_sim = _cosine_similarity(
        jd_vec, resume_embeddings.get("__skills__", [0.0] * 768))

    overall = _weighted([
        (top_exp_avg, 0.4, has_exp),
        (top_proj_avg, 0.3, has_proj),
        (skills_sim, 0.3, has_skills),
    ])
    embedding_pct = max(0, min(100, (overall - 0.1) / 0.5 * 100))

    # Mock embeddings are fake; the keyword overlap is not, because it is read
    # from the real JD text. Blended here too so `--mock` exercises the same
    # shape a real run does — a mock that behaves differently from production
    # is how the pipeline hid an invented job description for a week (R61).
    hits = keyword_overlap(jd_text, parsed_resume)
    keyword_pct = min(len(hits) / KEYWORD_SATURATION, 1.0) * 100
    overall_pct = (embedding_pct * (1 - KEYWORD_WEIGHT)
                   + keyword_pct * KEYWORD_WEIGHT)

    return EmbeddingScore(
        job_id="", title="", company="",
        overall_score=round(overall_pct, 1),
        best_experience_ids=best_exp,
        best_project_ids=best_proj,
        experience_scores=exp_scores,
        project_scores=proj_scores,
        embedding_score=round(embedding_pct, 1),
        keyword_score=round(keyword_pct, 1),
        keyword_hits=hits,
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
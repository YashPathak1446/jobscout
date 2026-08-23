"""
Embeddings without an API key, a network, or a GPU.

Gemini is reached at two call sites and embeddings are the larger of them —
roughly twenty calls per run against three for generation. Moving them here
means discovery, scoring and component selection work with **no API access at
all**, which is what makes the free ladder in Phase 2 item 11 possible: only
bullet rewriting is left needing a model.

**model2vec rather than sentence-transformers.** The obvious choice pulls
PyTorch, which is 2-3GB on Windows and hostile to item 15's packaging goal —
that is not a dependency you ask someone to install to try a job-search tool.
model2vec uses static distilled embeddings: `tokenizers` and numpy, no torch,
no transformers, and a model of about 30MB. Inference is pure numpy and
roughly a thousand times faster than a network round trip.

The trade is real and should be stated: static embeddings have no contextual
attention, so they capture topic well and syntax not at all. For matching a
resume component against a job description — which is a bag-of-concepts
comparison, not a reading-comprehension task — that is a fair trade, but it is
a trade.

Vectors from here are **not comparable to Gemini's**. They differ in
dimension (256 against 768) and in meaning. Both caches key on the model name,
so a switch of backend is a cache miss rather than a wrong answer — which is
R11's lesson, already learned once.

Location: jobscout_v3/tools/resume/local_embeddings.py
"""

import logging

logger = logging.getLogger(__name__)

_MODEL = None
_MODEL_NAME = None


def is_available() -> bool:
    """Can we embed locally? Cheap enough to ask on every run."""
    try:
        import model2vec  # noqa: F401
        return True
    except ImportError:
        return False


def load(model_name: str):
    """
    The model, loaded once per process.

    First call downloads roughly 30MB and takes a few seconds; afterwards it
    is served from the local cache. Kept module-level because the pipeline
    embeds in several places and reloading per call would dominate the cost.
    """
    global _MODEL, _MODEL_NAME

    if _MODEL is not None and _MODEL_NAME == model_name:
        return _MODEL

    from model2vec import StaticModel

    logger.info(f"Loading local embedding model {model_name}...")
    _MODEL = StaticModel.from_pretrained(model_name)
    _MODEL_NAME = model_name
    return _MODEL


def embed(text: str, model_name: str) -> list:
    """
    One vector for one string, as a plain list of floats.

    Returns [] on failure, matching what the Gemini path does, so callers do
    not need to care which backend produced the miss.
    """
    try:
        vector = load(model_name).encode([text])[0]
        return [float(x) for x in vector]
    except Exception as exc:
        logger.error(f"Local embedding failed: {exc}")
        return []


def dimensions(model_name: str) -> int:
    """
    The model's actual vector width, asked rather than assumed.

    A hardcoded number here would be a constant nobody validated, which is
    how R24 happened. The cache's dimension guard (R28) uses this, so getting
    it wrong would quietly reject every entry.
    """
    try:
        return int(load(model_name).dim)
    except Exception as exc:
        logger.warning(f"Could not determine local embedding dimensions: {exc}")
        return 0

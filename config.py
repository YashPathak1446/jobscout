"""
Global configuration for JobScout V3.

Model IDs live here rather than inline in agents because Google's retirement
cadence is fast: gemini-2.0-flash and gemini-2.5-flash-lite were both shut
down between May and July 2026, and gemini-2.5-flash has an announced
shutdown of 2026-10-16. When a model dies, this is the only file to edit.

Verify with `python scripts/check_models.py` before changing the chain.
IMPORTANT: models.list() is not authoritative — gemini-2.5-flash-lite appeared
in the listing with full generateContent support while 404-ing on real calls.
Only the live probe tells the truth.
"""

# Generation fallback chain, tried in order.
# Free-tier quota is per-model, so each entry adds real daily capacity.
#
# Probed live 2026-08-20 (all OK):
#   gemini-3.5-flash        Google's documented successor to gemini-2.5-flash
#   gemini-3.1-flash-lite   GA until 2027-05-07, lite tier = higher RPD
#   gemini-flash-lite-latest  floating alias, last resort before mock
#
# The alias is deliberately last: it silently re-points to new models, which
# means resume output can shift between runs for reasons invisible in a diff.
# Fine as a safety net, not as a primary.
#
# Also live but unproven for this workload: gemini-3.6-flash, gemini-3.7-flash,
# gemini-3-flash-preview. Worth a quality spot-check before promoting.
# Dead as of probing: gemini-2.0-flash, gemini-2.5-flash-lite.
GENERATION_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
]

# Where bullet rewriting happens: "auto", "gemini", "openai", "ollama" or
# "none". See tools/generation/llm_backends.py for the ladder.
#
# "auto" prefers Gemini when a key is resolvable, because every measurement in
# known_questions.md was taken against it, then a hosted OpenAI-compatible key,
# then a local Ollama, then "none" — which needs nothing and still produces a
# correctly targeted resume, just without rewriting.
LLM_BACKEND = "auto"

# OpenAI-compatible endpoint, used for "openai". Point it anywhere that speaks
# /chat/completions: Groq, OpenRouter, Together, DeepSeek, LM Studio.
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_MODEL = "gpt-4o-mini"

# Ollama speaks the same shape on a different port.
OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_API_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.1"

# Analysis embeddings. gemini-embedding-001 is past its listed shutdown date
# (2026-07-14) but still serving — Google treats listed dates as the earliest
# possible retirement, not the actual one. gemini-embedding-2 is now GA and is
# the migration target, but switching means re-embedding everything and
# invalidating the embedding cache. Tracked as an open question, not urgent.
EMBEDDING_MODEL = "gemini-embedding-001"

# Where embeddings come from: "auto", "gemini" or "local".
#
# "auto" prefers Gemini when a key is resolvable and falls back to the local
# model otherwise, so the pipeline runs with no key at all rather than failing.
# Embeddings are the larger of the two API dependencies — ~20 calls a run
# against ~3 for generation — so this is what makes a keyless run possible.
#
# The two are not interchangeable: different dimensions, different meaning.
# Both caches key on the model name, so switching costs a re-embed, never a
# wrong answer.
EMBEDDING_BACKEND = "auto"

# Static distilled embeddings: tokenizers and numpy, no torch. ~30MB, and
# inference is roughly a thousand times faster than a network round trip.
LOCAL_EMBEDDING_MODEL = "minishlab/potion-base-8M"

# Prompt-hash response cache. The real fix for dev-session quota burn:
# re-running the same jobs costs zero API requests.
LLM_CACHE_ENABLED = True
LLM_CACHE_DIR = ".cache/llm"

# Embedding vector cache. embedding_cache.py covers the resume's own
# components; this covers everything else that gets embedded, which in
# practice means job descriptions. Replaying the frozen baseline used to cost
# ~20 embedding calls every time, so the instrument this project measures
# every scoring change with was also the thing exhausting its quota.
EMBEDDING_CACHE_ENABLED = True
EMBEDDING_CACHE_DIR = ".cache/embeddings"


# --- Error classification ---------------------------------------------------

def classify_api_error(exc: Exception) -> str:
    """
    Bucket a Gemini API exception so callers know whether to fall through,
    retry, or give up.

    Returns one of:
        'quota'     - 429 / RESOURCE_EXHAUSTED. Model is alive, cap is hit.
                      Fall through to the next model.
        'retired'   - 404 NOT_FOUND. Model no longer exists. Fall through,
                      but log loudly: config.py is stale.
        'transient' - 503 UNAVAILABLE / 500. Service hiccup. Retry, then
                      fall through if it persists.
        'fatal'     - Anything else (bad API key, malformed request, etc).
                      Raise immediately; falling through would mask a real bug.
    """
    msg = str(exc)
    lower = msg.lower()

    if '404' in msg or 'NOT_FOUND' in msg or 'no longer available' in lower:
        return 'retired'

    if (
        '429' in msg
        or 'RESOURCE_EXHAUSTED' in msg
        or 'quota' in lower
        or 'rate limit' in lower
    ):
        return 'quota'

    if '503' in msg or 'UNAVAILABLE' in msg or '500' in msg or 'high demand' in lower:
        return 'transient'

    return 'fatal'

# --- API key resolution -----------------------------------------------------

# Read at five sites before this existed, always straight from the process
# environment. That is correct for a CLI, where the key comes from `.env`, and
# wrong the moment a UI collects it from a user: the value would have to be
# pushed back into `os.environ` to be seen, which makes a user's credential
# process-global and racy.
#
# So callers pass one down instead, and this is the single place that decides
# what "no key passed" means. Threading the parameter is cheap now and
# invasive after a UI exists — the same argument R11 made for the cache guard.

API_KEY_ENV_VAR = "GOOGLE_API_KEY"


def resolve_api_key(explicit: str = None) -> str:
    """
    The key to use: an explicitly supplied one, else the environment's.

    Args:
        explicit: A key from a caller — a UI form, a test, an orchestrator
            that was handed one. None means "no opinion", not "no key".

    Returns:
        The resolved key, or "" when neither source has one. Empty rather
        than None so callers can test it plainly, and so a missing key
        reaches the API as an obvious absence rather than the string "None".
    """
    import os

    if explicit:
        return explicit

    return os.getenv(API_KEY_ENV_VAR) or ""

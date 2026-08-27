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

# `.env` is loaded here rather than per entry point.
#
# The three agents each called `load_dotenv()` at import, which covered every
# path that goes through an agent and no others. `scripts/init_profile.py`
# does not, so importing a PDF from the command line resolved no key, dropped
# to the heuristic floor, and produced a resume with zero experiences — a
# silent degradation on a machine that had a perfectly good key in `.env`.
#
# This module is already the one that decides what "no key" means
# (`resolve_api_key`), and everything imports it, so loading here fixes every
# entry point at once. `load_dotenv` is idempotent, and it never overrides a
# variable already set in the real environment.
import os as _os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


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
#
# This is the **default**, not the answer. `resolve_backend` below holds the
# precedence chain; a CLI flag, an environment variable and a profile field all
# outrank this literal. It was a bare constant until R80, which meant choosing
# a rung required editing this file — so the free rung was unreachable by the
# people it exists for, and measuring it required a script that monkeypatched
# this module attribute.
LLM_BACKEND = _os.getenv("JOBSCOUT_LLM_BACKEND") or "auto"

# OpenAI-compatible endpoint, used for "openai". Point it anywhere that speaks
# /chat/completions: Groq, OpenRouter, Together, DeepSeek, LM Studio.
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_MODEL = "gpt-4o-mini"

# Ollama speaks the same shape on a different port.
#
# One variable, two forms. They were two literals and nothing tied them
# together, so pointing Ollama somewhere else meant editing both and getting
# it right twice — the shape of every ignore-by-filename bug in this project.
# The `/v1` suffix is derived, so they cannot disagree.
OLLAMA_API_URL = _os.getenv("JOBSCOUT_OLLAMA_URL") or "http://localhost:11434"
OLLAMA_BASE_URL = OLLAMA_API_URL.rstrip("/") + "/v1"
OLLAMA_MODEL = _os.getenv("JOBSCOUT_OLLAMA_MODEL") or "llama3.1"

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


# --- backend resolution -----------------------------------------------------

# Every rung, plus the word that means "decide for me". `auto` is a valid
# *instruction* and not a valid stored answer — see `AgentPreferences`.
BACKEND_CHOICES = ("auto", "gemini", "openai", "ollama", "none")


class UnknownBackend(ValueError):
    """A rung nobody has, named as though somebody did."""


def resolve_backend(explicit: str = None, profile=None) -> str:
    """
    Which rung this run should use, or `"auto"` to let detection decide.

    The precedence chain, highest first:

        CLI --backend  >  JOBSCOUT_LLM_BACKEND  >  profile  >  "auto"

    One function because it is one decision. Four callers used to answer it
    separately — `GenerationAgent._resolve_backend`, `complete_json`,
    `backend_status` and the orchestrator — each reading `LLM_BACKEND`
    straight from this module, which is fine while there is one source and
    guarantees drift the moment there are four. That is the two-paths bug,
    and it is being named here before it happens rather than after.

    Note what this does **not** do: it never calls `detect()`. Resolving to
    `"auto"` means "nobody has stated a preference", and the caller detects.
    Folding detection in here would make a network probe happen wherever this
    is called, including in a UI rendering on every keystroke.

    Args:
        explicit: a flag or a run request. `None` and `""` both mean "no
            opinion" — not "auto", which is an opinion about who decides.
        profile: a `UserProfile`, or anything with the same
            `agent_preferences.llm_backend` shape. `None` means no profile is
            loaded yet, which is the state resume import runs in.

    Raises:
        UnknownBackend: on a name no rung has. A typo'd `--backend olama` must
            not read as `auto` — silently detecting after being told exactly
            what to do is how a measurement ends up describing the wrong rung.
    """
    stored = getattr(
        getattr(profile, "agent_preferences", None), "llm_backend", None)

    # `LLM_BACKEND` is last and is read here rather than anywhere else. It is
    # the module's own default — env-backed, and the attribute tests patch to
    # force a rung. Leaving it out of this chain is how the first draft of
    # this function made it **computed and never read**: five tests that set
    # `config.LLM_BACKEND = "ollama"` fell straight through to detection and
    # made real network calls against a fake URL. The recurring bug of this
    # codebase, committed inside the change that adds a setting.
    #
    # Below the profile, because it is a code default and a person's stated
    # preference outranks one. Above nothing — when it is still "auto",
    # nobody has chosen and the caller detects.
    for candidate, source in ((explicit, "--backend"),
                              (_os.getenv("JOBSCOUT_LLM_BACKEND"),
                               "JOBSCOUT_LLM_BACKEND"),
                              (stored, "the profile"),
                              (LLM_BACKEND, "config.LLM_BACKEND")):
        if not candidate:
            continue
        choice = str(candidate).strip().lower()
        if choice not in BACKEND_CHOICES:
            raise UnknownBackend(
                f"{source} says '{candidate}', which is not a backend. "
                f"Choose one of: {', '.join(BACKEND_CHOICES)}.")
        return choice

    return "auto"

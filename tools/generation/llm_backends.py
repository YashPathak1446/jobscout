"""
Where bullet rewriting gets done, and what to do when nowhere is available.

R36 moved embeddings off the API, so discovery, scoring and component
selection now work with no key at all. Rewriting bullets is the last thing
that needs a model, and this is the ladder for it:

    none    nothing needed          selection only, your own bullets
    ollama  install + ~4GB + RAM    free, local, private
    openai  a key                   any OpenAI-compatible provider
    gemini  a key                   what every measurement here used

They are not ranked, they trade differently. Ollama needs no account, no
quota and sends nothing anywhere, but wants a real machine. A hosted key needs
a signup but runs on a laptop. `none` excludes nobody and rewrites nothing.

**One adapter covers most of the paid and free world.** OpenAI, Groq,
OpenRouter, Together, DeepSeek, LM Studio and Ollama all speak the same
`/chat/completions` shape, so `openai` and `ollama` are the same code with a
different base URL.

R33 decided the policy: detect what is available, pick the best of it, and say
plainly what was chosen. Not silent, because output quality differs materially
between rungs; not a mandatory question at setup, because most people do not
yet know enough to answer it.

Location: jobscout_v3/tools/generation/llm_backends.py
"""

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 120

# Ordered best-effort-first. `none` is last because it always works, so it is
# the floor rather than a preference.
LADDER = ("gemini", "openai", "ollama", "none")

class BackendFailure(RuntimeError):
    """
    A rung that should have answered did not.

    Distinct from *having* no rung, which is `none` and is a legitimate state
    rather than an error. Keeping the two apart is the whole point: for most
    of this project's life both produced a bare `None`, so a machine with a
    perfectly good key in `.env` and a machine deliberately running keyless
    were indistinguishable from the caller's side — and the first of those
    shipped a resume with zero experiences before anyone noticed (R41).

    Callers still fall back. They can now say why in the log, and tell the
    user, which is the difference between a graceful degradation and a silent
    one.
    """


DESCRIPTIONS = {
    "gemini": "Google Gemini — the backend every measurement in this project used",
    "openai": "an OpenAI-compatible API",
    "ollama": "Ollama, running locally — free and private",
    "none": "no model: components are selected for each job, but your bullets "
            "are used exactly as written",
}


def ollama_models(base_url: str) -> list:
    """
    Every model this Ollama has actually pulled.

    Asked rather than assumed, because Ollama being installed and Ollama being
    *up* are different things, and the difference is a run that fails halfway
    rather than one that picks another rung.

    The list itself matters, not just its length — see `choose_model`.
    """
    try:
        request = urllib.request.Request(f"{base_url.rstrip('/')}/api/tags")
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []

    return [entry.get("name", "") for entry in (payload.get("models") or [])
            if entry.get("name")]


def ollama_is_running(base_url: str) -> bool:
    """Is there an Ollama serving at least one model right now?"""
    return bool(ollama_models(base_url))


def choose_model(available, preferred: str = "") -> str:
    """
    Which of the pulled models to actually call.

    Detection and invocation used to disagree about what "available" meant.
    Detection returned true if *any* model was pulled; the call then asked for
    `OLLAMA_MODEL`, hard-coded to one name. Someone running Ollama with
    `mistral` was told bullets would be rewritten locally, and then the call
    404'd on a model that was never there — falling back silently, because a
    failed rung and a chosen `none` look identical from outside.

    So the preference is a preference, not a requirement. Tags are matched
    loosely on purpose: `ollama pull llama3.1` stores `llama3.1:latest`, and a
    config naming the bare model should not miss its own default.

    Kept separate from `ollama_models` so the choosing can be tested without a
    server, which is the only half of this that tests can reach.
    """
    available = [name for name in (available or []) if name]
    if not available:
        return ""

    if preferred:
        if preferred in available:
            return preferred
        stem = preferred.split(":")[0]
        for name in available:
            if name.split(":")[0] == stem:
                return name

    return available[0]


def resolve_ollama_model(base_url: str, preferred: str = "") -> str:
    """The model to call on a live Ollama, or empty if it has none."""
    return choose_model(ollama_models(base_url), preferred)


def detect(gemini_key=None, openai_key=None, ollama_url=None) -> str:
    """
    The best rung actually available, as a name from LADDER.

    Order is deliberate. Gemini first because it is what the measurements
    were taken against, so preferring anything else would silently change
    every recorded result. Then a hosted OpenAI-compatible key, then a local
    Ollama, then nothing — which always works.
    """
    if gemini_key:
        return "gemini"
    if openai_key:
        return "openai"
    if ollama_url and ollama_is_running(ollama_url):
        return "ollama"
    return "none"


def describe(backend: str, model: str = "") -> str:
    """One line a user can act on, for the log and for the UI."""
    detail = DESCRIPTIONS.get(backend, backend)
    if model and backend not in ("none",):
        return f"{detail} ({model})"
    return detail


def call_chat_json(prompt: str, base_url: str, model: str, api_key: str = None) -> dict:
    """
    One OpenAI-compatible chat completion, parsed as JSON.

    Deliberately not the `openai` package: this is one POST, and the shape is
    the same across every provider that matters. Adding a dependency to send
    it would buy nothing and cost everyone who installs this.

    Raises on transport or parse failure so the caller can fall down the
    ladder rather than silently producing an empty resume.
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        # Low but not zero: bullet rewriting under hard length constraints
        # wants consistency, and some providers reject exactly 0.
        "temperature": 0.2,
        "stream": False,
        # Ask the server for JSON rather than asking the model nicely and
        # scraping whatever markup it chose. Measured on llama3.1:8b: without
        # this the reply is `{"n": 5}` in backticks, with it the reply is bare
        # JSON — and it came back three times faster. This is the right fix
        # for R44's parse failures; unwrapping prose after the fact is not.
        "response_format": {"type": "json_object"},
    }

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    def _post(body_dict):
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/chat/completions",
            data=json.dumps(body_dict).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        response_payload = _post(payload)
    except urllib.error.HTTPError:
        # One adapter serves every OpenAI-compatible provider, and not all of
        # them accept `response_format`. A provider that rejects it should
        # cost a retry, not the run.
        payload.pop("response_format")
        response_payload = _post(payload)

    text = response_payload["choices"][0]["message"]["content"].strip()
    return json.loads(_strip_code_fence(text))


def complete_json(prompt: str, gemini_key: str = None,
                  backend: str = None, profile=None) -> dict:
    """
    Ask whichever backend is available for a JSON answer.

    A standalone entry point, unlike the generation agent's tailoring path,
    because resume import needs the same ladder without needing a profile or
    a parsed resume to exist yet — at import time neither does.

    Returns None when there is deliberately no backend — the `none` rung, a
    legitimate state. Raises `BackendFailure` when a rung that should have
    answered did not.

    Those were the same return value until R47, which meant "you chose to run
    without a model" and "your model is misconfigured or down" reached the
    caller identically, and every caller guessed the friendlier of the two.

    **Resolves the rung the same way `GenerationAgent` does, through
    `config.resolve_backend`.** This is the two-paths bug named before it
    happened: import and generation are the project's two model consumers, and
    if one obeyed a `--backend` flag while the other went on detecting, a run
    pinned to Ollama would have imported through Gemini and nothing would have
    said so. Every previous instance of this shape — the escape table (R69),
    the experience field order (R70), the selection breakdown (R57) — was
    found months later by somebody walking the path the author does not.
    `test_backend_selection.py` holds the two together.
    """
    from config import (OLLAMA_API_URL, OLLAMA_BASE_URL,
                        OLLAMA_MODEL, OPENAI_BASE_URL, OPENAI_MODEL,
                        resolve_api_key, resolve_backend)

    choice = resolve_backend(backend, profile)
    key = resolve_api_key(gemini_key)

    if choice == "auto":
        choice = detect(gemini_key=key, openai_key=env_openai_key(),
                        ollama_url=OLLAMA_API_URL)

    if choice == "none":
        # Chosen, not failed. The only path that returns None.
        return None

    if choice == "gemini":
        from google import genai
        from config import GENERATION_MODELS

        client = genai.Client(api_key=key)
        last_error = None
        for model in GENERATION_MODELS:
            try:
                response = client.models.generate_content(model=model, contents=prompt)
                return json.loads(_strip_code_fence(response.text.strip()))
            except Exception as exc:      # quota, retirement, bad JSON
                last_error = exc
        raise BackendFailure(
            f"every Gemini model failed ({last_error})") from last_error

    base_url = OLLAMA_BASE_URL if choice == "ollama" else OPENAI_BASE_URL
    api_key = None if choice == "ollama" else env_openai_key()
    if choice == "ollama":
        # Ask what this Ollama actually has rather than assuming the config's
        # default is pulled. Empty means it has nothing to answer with.
        model = resolve_ollama_model(OLLAMA_API_URL, OLLAMA_MODEL)
        if not model:
            raise BackendFailure(
                "Ollama is running but has no model pulled — "
                "run `ollama pull llama3.1` or any model you prefer")
    else:
        model = OPENAI_MODEL
    try:
        return call_chat_json(prompt, base_url, model, api_key)
    except Exception as exc:
        raise BackendFailure(f"{choice} ({model}) failed: {exc}") from exc


def _strip_code_fence(text: str) -> str:
    """
    Unwrap a model's JSON out of whatever markup it decided to wrap it in.

    Smaller models mark up their output far more often than Gemini does, and
    an unstripped wrapper is the single most common reason a local reply fails
    to parse. This handled triple-backtick fences and only those, which was a
    guess about *which* markup, and the guess was wrong: the first real reply
    from llama3.1:8b came back as `{"n": 1}` — a single-backtick inline span.
    Every call on the Ollama rung would have failed on it.

    Worth recording how that was missed. R43 tested fence-stripping against a
    fake server, and a fake server returns exactly what the test told it to —
    so it proved the stripper handles the wrapper the test already knew about.
    Only a real model volunteers a wrapper nobody predicted.
    """
    text = text.strip()

    if text.startswith("```"):
        body = text.split("\n", 1)[1] if "\n" in text else ""
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
        return body.strip()

    # An inline code span: one or two backticks either side, no newline needed.
    if text.startswith("`") and text.endswith("`") and len(text) > 1:
        return text.strip("`").strip()

    # DELIBERATELY NOT HANDLED: a reply that opens with prose, like
    # "Here is the rewritten JSON output:\n\n```\n{...}". llama3.1:8b does
    # exactly this, and pulling the JSON out of it is four lines.
    #
    # Do not add those four lines without reading R44 first. On that model the
    # JSON inside the prose was *fabricated* — invented metrics, an invented
    # date, technologies absent from the resume — and the parse failure is the
    # only reason none of it reached a resume. Being stricter here is currently
    # load-bearing: it fails to the verbatim floor, which uses the user's real
    # bullets. Loosening it without a content-preservation check first would
    # turn a safe failure into a silent one.
    return text


def env_openai_key() -> str:
    """A hosted OpenAI-compatible key from the environment, if there is one."""
    for name in ("OPENAI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY",
                 "TOGETHER_API_KEY", "DEEPSEEK_API_KEY"):
        value = os.getenv(name)
        if value:
            return value
    return ""

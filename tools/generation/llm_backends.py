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

DESCRIPTIONS = {
    "gemini": "Google Gemini — the backend every measurement in this project used",
    "openai": "an OpenAI-compatible API",
    "ollama": "Ollama, running locally — free and private",
    "none": "no model: components are selected for each job, but your bullets "
            "are used exactly as written",
}


def ollama_is_running(base_url: str) -> bool:
    """
    Is there an Ollama serving models right now?

    Asked rather than assumed, because Ollama being installed and Ollama
    being *up* are different things, and the difference is a run that fails
    halfway rather than one that picks another rung.
    """
    try:
        request = urllib.request.Request(f"{base_url.rstrip('/')}/api/tags")
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return bool(payload.get("models"))
    except Exception:
        return False


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
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        # Low but not zero: bullet rewriting under hard length constraints
        # wants consistency, and some providers reject exactly 0.
        "temperature": 0.2,
        "stream": False,
    }).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions", data=body, headers=headers)

    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))

    text = payload["choices"][0]["message"]["content"].strip()
    return json.loads(_strip_code_fence(text))


def _strip_code_fence(text: str) -> str:
    """
    Unwrap ```json fences.

    Smaller models fence their output far more often than Gemini does, and an
    unwrapped fence is the single most common reason a local model's reply
    fails to parse. Cheap to handle, tedious to debug.
    """
    if not text.startswith("```"):
        return text

    body = text.split("\n", 1)[1] if "\n" in text else ""
    if body.rstrip().endswith("```"):
        body = body.rstrip()[:-3]
    return body.strip()


def env_openai_key() -> str:
    """A hosted OpenAI-compatible key from the environment, if there is one."""
    for name in ("OPENAI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY",
                 "TOGETHER_API_KEY", "DEEPSEEK_API_KEY"):
        value = os.getenv(name)
        if value:
            return value
    return ""

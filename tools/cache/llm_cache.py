"""
Prompt-hash LLM response cache.

Sits alongside embedding_cache.py and job_cache.py and follows the same
pattern. Purpose: during development you re-run the same jobs repeatedly,
and every rerun burns free-tier quota on prompts whose answers haven't
changed. Keyed on the prompt text, an identical rerun costs zero requests.

Keyed on the prompt ONLY, not (prompt, model). If gemini-3.5-flash answered
a prompt yesterday and today the chain falls through to flash-lite, you still
want the cached answer — the point is avoiding the call. The model that
actually produced the response is recorded in the payload so you can tell
later which model's output you're looking at.
"""

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class LLMCache:
    """File-backed cache of parsed LLM JSON responses, keyed by prompt hash."""

    def __init__(self, cache_dir: str = ".cache/llm", enabled: bool = True):
        self.enabled = enabled
        self.cache_dir = Path(cache_dir)
        if self.enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.hits = 0
        self.misses = 0

    def _key(self, prompt: str) -> str:
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:32]

    def _path(self, prompt: str) -> Path:
        return self.cache_dir / f"{self._key(prompt)}.json"

    def get(self, prompt: str) -> Optional[Dict]:
        """Return the cached parsed response, or None on miss."""
        if not self.enabled:
            return None

        path = self._path(prompt)
        if not path.exists():
            self.misses += 1
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            # Corrupt or half-written entry — treat as a miss and move on.
            logger.warning(f"   Cache read failed for {path.name}: {e}")
            self.misses += 1
            return None

        self.hits += 1
        model = payload.get("model", "unknown")
        logger.info(f"   💾 Cache hit (originally from {model}) — 0 API requests")
        return payload.get("response")

    def set(self, prompt: str, response: Dict, model: str) -> None:
        """
        Store a successfully-parsed response.

        Only call this after json.loads() has succeeded. Caching an unparseable
        response would pin a failure in place across every future run.
        """
        if not self.enabled:
            return

        payload = {
            "model": model,
            "cached_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "prompt_chars": len(prompt),
            "response": response,
        }

        # Write to a temp file then rename, so an interrupted run can't leave
        # a truncated JSON file that poisons later reads.
        path = self._path(prompt)
        tmp = path.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            tmp.replace(path)
        except OSError as e:
            logger.warning(f"   ⚠️  Cache write failed: {e}")

    def stats(self) -> str:
        total = self.hits + self.misses
        if total == 0:
            return "cache: unused"
        pct = 100 * self.hits / total
        return f"cache: {self.hits} hits / {total} lookups ({pct:.0f}% saved)"

    def clear(self) -> int:
        """Delete all entries. Returns the count removed."""
        if not self.cache_dir.exists():
            return 0
        removed = 0
        for f in self.cache_dir.glob("*.json"):
            f.unlink()
            removed += 1
        logger.info(f"   🗑️  Cleared {removed} cached responses")
        return removed
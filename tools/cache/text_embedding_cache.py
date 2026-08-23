"""
Content-addressed cache for embedding vectors.

`embedding_cache.py` caches the resume's component vectors, keyed on the
resume file's hash. Nothing cached the *other* side of the comparison, so
every replay of the frozen baseline re-embedded all 20 job descriptions.
That is the instrument this project measures every scoring change with —
R14, R15, R21, R23 and R27 all rest on replaying it — and it cost ~20 API
calls each time. Running five comparisons in an afternoon exhausted a day's
free-tier quota, which is a poor property for the thing you are supposed to
reach for before every change.

Keyed on (model, task_type, text), and all three matter:

- **model**, because vectors from different models are not comparable. This
  is R11's lesson: the resume cache shipped without the model in its key and
  silently served `gemini-embedding-001` vectors to a different model.
- **task_type**, because `RETRIEVAL_QUERY` and `RETRIEVAL_DOCUMENT` produce
  genuinely different vectors for identical text. Omitting it would serve a
  JD-as-query vector where a JD-as-document vector was asked for.
- **text**, exactly. No normalisation, no truncation before hashing. A JD
  that gained a whitespace character is a different JD as far as the API is
  concerned, so it must be a different key here.

Unlike `llm_cache.py`, which deliberately keys on the prompt alone so a
fallback model can still serve a cached answer, there is no equivalent
latitude here. A wrong vector does not look wrong — it quietly shifts every
cosine similarity that touches it.

Location: jobscout_v3/tools/cache/text_embedding_cache.py
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class TextEmbeddingCache:
    """File-backed cache of embedding vectors, one file per (model, task, text)."""

    def __init__(self, cache_dir: str = ".cache/embeddings", enabled: bool = True,
                 dimensions: Optional[int] = None):
        """
        Args:
            cache_dir: Where entries live, one JSON file per key.
            enabled: False makes every get a miss and every set a no-op.
            dimensions: Expected vector length. Entries of any other length
                are refused on write and ignored on read. A wrong-length
                vector is always a bug — a stubbed test vector, a truncated
                write, a model change that slipped the key — and it is
                exactly the kind that produces plausible numbers instead of
                an error. This guard exists because a test double with a
                2-element vector reached a real cache directory once.
        """
        self.enabled = enabled
        self.dimensions = dimensions
        self.cache_dir = Path(cache_dir)
        if self.enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.hits = 0
        self.misses = 0

    def _key(self, text: str, model: str, task_type: str) -> str:
        # NUL separators so ("ab", "c") and ("a", "bc") cannot collide.
        payload = "\0".join((model or "", task_type or "", text))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def _path(self, text: str, model: str, task_type: str) -> Path:
        return self.cache_dir / f"{self._key(text, model, task_type)}.json"

    def get(self, text: str, model: str, task_type: str) -> Optional[List[float]]:
        """Return the cached vector, or None on a miss."""
        if not self.enabled:
            return None

        path = self._path(text, model, task_type)
        if not path.exists():
            self.misses += 1
            return None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            vector = payload.get("vector")
        except (json.JSONDecodeError, OSError) as exc:
            # A truncated or unreadable entry is a miss, never an error. The
            # only cost of being wrong here is one API call.
            logger.debug(f"Embedding cache entry unreadable, treating as miss: {exc}")
            self.misses += 1
            return None

        if not vector:
            self.misses += 1
            return None

        if self.dimensions and len(vector) != self.dimensions:
            logger.warning(
                f"Discarding cached embedding of {len(vector)} dimensions, "
                f"expected {self.dimensions}: {path.name}"
            )
            try:
                path.unlink()
            except OSError:
                pass
            self.misses += 1
            return None

        self.hits += 1
        return vector

    def set(self, text: str, model: str, task_type: str, vector: List[float]) -> None:
        """
        Store a vector. Empty vectors are refused.

        `_get_embedding` returns [] when the API call fails, and caching that
        would turn one transient 429 into a permanently wrong answer that no
        amount of retrying clears.
        """
        if not self.enabled or not vector:
            return

        if self.dimensions and len(vector) != self.dimensions:
            logger.warning(
                f"Refusing to cache an embedding of {len(vector)} dimensions, "
                f"expected {self.dimensions}"
            )
            return

        path = self._path(text, model, task_type)
        try:
            path.write_text(
                json.dumps({
                    "model": model,
                    "task_type": task_type,
                    "dimensions": len(vector),
                    "vector": vector,
                }),
                encoding="utf-8",
            )
        except OSError as exc:
            # A cache that cannot write is slow, not broken.
            logger.debug(f"Could not write embedding cache entry: {exc}")

    def stats(self) -> str:
        total = self.hits + self.misses
        if not total:
            return "embedding cache: unused"
        return (f"embedding cache: {self.hits} hit / {self.misses} miss "
                f"({100 * self.hits / total:.0f}% saved)")

    def clear(self) -> int:
        """Delete every entry. Returns how many were removed."""
        if not self.cache_dir.exists():
            return 0

        removed = 0
        for path in self.cache_dir.glob("*.json"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass

        self.hits = self.misses = 0
        return removed

"""
Content-addressed embedding cache (R28).

Replaying the frozen baseline re-embedded all 20 JDs every time, so the
instrument this project measures every scoring change against was also what
exhausted its daily quota. These tests pin the three parts of the key,
because a wrong vector does not look wrong — it quietly shifts every cosine
similarity that touches it.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.cache.text_embedding_cache import TextEmbeddingCache  # noqa: E402

VECTOR = [0.1, 0.2, 0.3]


class TestTextEmbeddingCache(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cache = TextEmbeddingCache(cache_dir=self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_stores_and_returns_a_vector(self):
        self.cache.set("hello", "model-a", "RETRIEVAL_QUERY", VECTOR)
        self.assertEqual(self.cache.get("hello", "model-a", "RETRIEVAL_QUERY"), VECTOR)

    def test_unknown_text_is_a_miss(self):
        self.assertIsNone(self.cache.get("nothing", "model-a", "RETRIEVAL_QUERY"))

    def test_a_different_model_does_not_share_an_entry(self):
        """R11: the resume cache once served one model's vectors to another."""
        self.cache.set("hello", "model-a", "RETRIEVAL_QUERY", VECTOR)
        self.assertIsNone(self.cache.get("hello", "model-b", "RETRIEVAL_QUERY"))

    def test_a_different_task_type_does_not_share_an_entry(self):
        # RETRIEVAL_QUERY and RETRIEVAL_DOCUMENT genuinely differ for the
        # same text; sharing a key would serve the wrong one.
        self.cache.set("hello", "model-a", "RETRIEVAL_QUERY", VECTOR)
        self.assertIsNone(self.cache.get("hello", "model-a", "RETRIEVAL_DOCUMENT"))

    def test_text_is_matched_exactly(self):
        self.cache.set("hello", "model-a", "RETRIEVAL_QUERY", VECTOR)
        self.assertIsNone(self.cache.get("hello ", "model-a", "RETRIEVAL_QUERY"))

    def test_key_fields_cannot_collide_by_concatenation(self):
        """("ab","c") and ("a","bc") must not hash to the same key."""
        self.cache.set("x", "ab", "c", VECTOR)
        self.assertIsNone(self.cache.get("x", "a", "bc"))

    def test_an_empty_vector_is_never_stored(self):
        # _get_embedding returns [] on API failure. Caching that would turn
        # one transient 429 into a permanently wrong answer.
        self.cache.set("hello", "model-a", "RETRIEVAL_QUERY", [])
        self.assertIsNone(self.cache.get("hello", "model-a", "RETRIEVAL_QUERY"))

    def test_a_corrupt_entry_is_a_miss_not_a_crash(self):
        self.cache.set("hello", "model-a", "RETRIEVAL_QUERY", VECTOR)
        path = next(Path(self.dir).glob("*.json"))
        path.write_text("{not json", encoding="utf-8")
        self.assertIsNone(self.cache.get("hello", "model-a", "RETRIEVAL_QUERY"))

    def test_disabled_cache_stores_nothing_and_returns_nothing(self):
        off = TextEmbeddingCache(cache_dir=self.dir, enabled=False)
        off.set("hello", "model-a", "RETRIEVAL_QUERY", VECTOR)
        self.assertIsNone(off.get("hello", "model-a", "RETRIEVAL_QUERY"))

    def test_hit_and_miss_counts_are_tracked(self):
        self.cache.get("absent", "model-a", "RETRIEVAL_QUERY")
        self.cache.set("hello", "model-a", "RETRIEVAL_QUERY", VECTOR)
        self.cache.get("hello", "model-a", "RETRIEVAL_QUERY")
        self.assertEqual((self.cache.hits, self.cache.misses), (1, 1))
        self.assertIn("1 hit", self.cache.stats())

    def test_clear_removes_entries(self):
        self.cache.set("a", "m", "t", VECTOR)
        self.cache.set("b", "m", "t", VECTOR)
        self.assertEqual(self.cache.clear(), 2)
        self.assertIsNone(self.cache.get("a", "m", "t"))

    def test_the_stored_payload_records_what_produced_it(self):
        self.cache.set("hello", "model-a", "RETRIEVAL_QUERY", VECTOR)
        payload = json.loads(next(Path(self.dir).glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(payload["model"], "model-a")
        self.assertEqual(payload["task_type"], "RETRIEVAL_QUERY")
        self.assertEqual(payload["dimensions"], len(VECTOR))


class TestDimensionGuard(unittest.TestCase):
    """A wrong-length vector is always a bug, and always a silent one."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cache = TextEmbeddingCache(cache_dir=self.dir, dimensions=768)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_refuses_to_store_a_wrong_length_vector(self):
        # This is the real incident: a test double returning [0.1, 0.2]
        # reached the live cache directory under the real model name.
        self.cache.set("hello", "gemini-embedding-001", "RETRIEVAL_QUERY", [0.1, 0.2])
        self.assertEqual(list(Path(self.dir).glob("*.json")), [])

    def test_stores_a_correct_length_vector(self):
        good = [0.0] * 768
        self.cache.set("hello", "m", "t", good)
        self.assertEqual(self.cache.get("hello", "m", "t"), good)

    def test_a_wrong_length_entry_already_on_disk_is_discarded_on_read(self):
        loose = TextEmbeddingCache(cache_dir=self.dir)          # no guard
        loose.set("hello", "m", "t", [0.1, 0.2])
        self.assertIsNone(self.cache.get("hello", "m", "t"))
        self.assertEqual(list(Path(self.dir).glob("*.json")), [],
                         "the bad entry should be removed, not merely ignored")

    def test_no_guard_means_any_length_is_accepted(self):
        loose = TextEmbeddingCache(cache_dir=self.dir)
        loose.set("hello", "m", "t", [0.1, 0.2])
        self.assertEqual(loose.get("hello", "m", "t"), [0.1, 0.2])


if __name__ == "__main__":
    unittest.main()

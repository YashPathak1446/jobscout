"""
API key resolution and injection (R22).

The key was read from `os.environ` at five sites. That is fine for a CLI and
wrong for a UI, which has to push a user's credential into the process
environment to be seen — making one user's secret process-global. These tests
pin the replacement: callers pass a key down, and one function decides what
"nothing passed" means.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import API_KEY_ENV_VAR, resolve_api_key  # noqa: E402


class _EnvKey:
    """Set or clear the key env var for the duration of a block."""

    def __init__(self, value):
        self.value = value

    def __enter__(self):
        self.previous = os.environ.get(API_KEY_ENV_VAR)
        if self.value is None:
            os.environ.pop(API_KEY_ENV_VAR, None)
        else:
            os.environ[API_KEY_ENV_VAR] = self.value

    def __exit__(self, *exc):
        if self.previous is None:
            os.environ.pop(API_KEY_ENV_VAR, None)
        else:
            os.environ[API_KEY_ENV_VAR] = self.previous


class TestResolveApiKey(unittest.TestCase):

    def test_explicit_key_beats_the_environment(self):
        with _EnvKey("from-env"):
            self.assertEqual(resolve_api_key("explicit"), "explicit")

    def test_falls_back_to_the_environment(self):
        with _EnvKey("from-env"):
            self.assertEqual(resolve_api_key(), "from-env")

    def test_returns_empty_string_when_neither_source_has_one(self):
        # Empty rather than None: callers test it plainly, and a missing key
        # never reaches the API as the literal string "None".
        with _EnvKey(None):
            self.assertEqual(resolve_api_key(), "")
            self.assertEqual(resolve_api_key(None), "")

    def test_empty_explicit_falls_through_rather_than_winning(self):
        # A UI with an empty form field means "no opinion", not "use no key".
        with _EnvKey("from-env"):
            self.assertEqual(resolve_api_key(""), "from-env")


class TestKeyIsThreadedNotGlobal(unittest.TestCase):
    """Every agent that talks to Gemini has to accept a key."""

    def test_pipeline_entry_points_accept_an_api_key(self):
        import inspect
        from agents.analysis_agent import AnalysisAgent
        from agents.generation_agent import GenerationAgent
        from agents.orchestrator import JobScoutOrchestrator
        from tools.resume import ResumeParser

        for cls in (JobScoutOrchestrator, AnalysisAgent, GenerationAgent, ResumeParser):
            with self.subTest(cls=cls.__name__):
                params = inspect.signature(cls.__init__).parameters
                self.assertIn("api_key", params)
                self.assertIsNone(params["api_key"].default,
                                  f"{cls.__name__} must default to 'no opinion'")

    def test_explicit_key_reaches_the_embedding_client(self):
        """The point of the exercise: injection must survive the whole path."""
        import google.genai as genai
        import tools.resume.embedding_scorer as scorer

        seen = {}

        class FakeClient:
            def __init__(self, api_key=None):
                seen["key"] = api_key
                self.models = self

            def embed_content(self, **kwargs):
                class R:
                    embeddings = [type("V", (), {"values": [0.1, 0.2]})()]
                return R()

        # The embedding cache short-circuits before the client is built, so
        # without disabling it this test either reads a real vector or writes
        # its 2-element stub into the real cache directory. It did the latter
        # once; hence also the dimension guard in TextEmbeddingCache.
        from tools.cache.text_embedding_cache import TextEmbeddingCache

        original_client, original_cache = genai.Client, scorer._EMBEDDING_CACHE
        genai.Client = FakeClient
        scorer._EMBEDDING_CACHE = TextEmbeddingCache(cache_dir="", enabled=False)
        try:
            with _EnvKey("env-key-must-not-win"):
                vec = scorer._get_embedding("text", api_key="explicit-key")
        finally:
            genai.Client = original_client
            scorer._EMBEDDING_CACHE = original_cache

        self.assertEqual(seen["key"], "explicit-key")
        self.assertEqual(vec, [0.1, 0.2])


if __name__ == "__main__":
    unittest.main()

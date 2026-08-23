"""
The bullet-rewriting ladder (R37).

R36 took embeddings off the API, leaving rewriting as the last thing needing a
model. This is the ladder for it: `none` always works, Ollama if the machine
can, a key if preferred. The rungs are not ranked — they trade differently.

No network here. `call_chat_json` is exercised against its parsing, which is
where smaller models actually fail.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.generation import llm_backends as backends  # noqa: E402


class TestDetection(unittest.TestCase):
    """R33: detect what is available, prefer the best, say so."""

    def test_gemini_wins_when_a_key_is_present(self):
        # Not because it is best in the abstract, but because every
        # measurement in known_questions.md was taken against it.
        self.assertEqual(backends.detect(gemini_key="k", openai_key="k2"), "gemini")

    def test_a_hosted_key_comes_next(self):
        self.assertEqual(backends.detect(gemini_key="", openai_key="k"), "openai")

    def test_falls_through_to_none_when_nothing_is_available(self):
        self.assertEqual(
            backends.detect(gemini_key="", openai_key="", ollama_url=None), "none")

    def test_ollama_is_only_chosen_when_it_is_actually_running(self):
        # Installed and serving are different things, and the difference is a
        # run that dies halfway rather than one that picks another rung.
        original = backends.ollama_is_running
        backends.ollama_is_running = lambda url: False
        try:
            self.assertEqual(
                backends.detect(gemini_key="", openai_key="",
                                ollama_url="http://localhost:11434"), "none")
        finally:
            backends.ollama_is_running = original

    def test_a_running_ollama_beats_nothing(self):
        original = backends.ollama_is_running
        backends.ollama_is_running = lambda url: True
        try:
            self.assertEqual(
                backends.detect(gemini_key="", openai_key="",
                                ollama_url="http://localhost:11434"), "ollama")
        finally:
            backends.ollama_is_running = original

    def test_a_down_ollama_is_reported_as_not_running(self):
        self.assertFalse(backends.ollama_is_running("http://localhost:59999"))


class TestDescriptions(unittest.TestCase):
    """A backend nobody can identify is a backend nobody can change."""

    def test_every_rung_can_describe_itself(self):
        for rung in backends.LADDER:
            self.assertTrue(backends.describe(rung))

    def test_the_model_name_is_included_when_there_is_one(self):
        self.assertIn("llama3.1", backends.describe("ollama", "llama3.1"))

    def test_the_no_model_rung_says_what_it_does_instead(self):
        text = backends.describe("none").lower()
        self.assertIn("bullets", text)


class TestResponseParsing(unittest.TestCase):
    """Where small models actually fail: fencing their JSON."""

    def test_a_plain_json_body_parses(self):
        self.assertEqual(json.loads(backends._strip_code_fence('{"a": 1}')), {"a": 1})

    def test_a_fenced_body_is_unwrapped(self):
        fenced = '```json\n{"a": 1}\n```'
        self.assertEqual(json.loads(backends._strip_code_fence(fenced)), {"a": 1})

    def test_a_fence_without_a_language_is_unwrapped(self):
        self.assertEqual(json.loads(backends._strip_code_fence('```\n{"a": 1}\n```')),
                         {"a": 1})

    def test_text_that_only_looks_fenced_is_left_alone(self):
        self.assertEqual(backends._strip_code_fence('{"a": "```"}'), '{"a": "```"}')


class TestHostedKeyDiscovery(unittest.TestCase):

    def test_any_known_provider_key_counts(self):
        import os

        names = ("OPENAI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY",
                 "TOGETHER_API_KEY", "DEEPSEEK_API_KEY")
        saved = {n: os.environ.pop(n, None) for n in names}
        try:
            self.assertEqual(backends.env_openai_key(), "")
            os.environ["GROQ_API_KEY"] = "abc"
            self.assertEqual(backends.env_openai_key(), "abc")
        finally:
            os.environ.pop("GROQ_API_KEY", None)
            for name, value in saved.items():
                if value is not None:
                    os.environ[name] = value


if __name__ == "__main__":
    unittest.main()

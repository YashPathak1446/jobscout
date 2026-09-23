"""
A Gemini key that cannot be sent says so, and is never blamed on Gemini (R101).

A run's summary read: "Bullets were not rewritten: Gemini could not be reached
('ascii' codec can't encode character '\\u2014' in position 76 ...)". No
request had left the machine. The key travels as an HTTP header, httpx encodes
header values as ASCII, and a key carrying a copied comment with an em dash
fails inside the client. Then `_gemini_tailor`'s catch-all labelled every
exception, ours included, "Gemini could not be reached".

These tests hold:

* the mechanism itself, so it stays a fact rather than an inference;
* one place builds a Gemini client, and it refuses an unsendable key with a
  message that names the character and never repeats the key;
* a degraded resume names whose fault it was: the key, Gemini, or JobScout;
* the key panel reports the problem instead of "add a key".
"""

import ast
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402

# Deliberately format-free: a key is whatever Google issues. Old keys were
# `AIza…`/39 and current ones `AQ…`/53, and the check must pass both and any
# successor (R101's correction). Nothing here encodes a prefix or a length.
GOOD = "AQ." + "Ab3_x-9" * 7 + "Zq"
OLD_STYLE = "AIzaSy" + "A" * 33
BAD = GOOD + "  # free tier key from AI Studio — personal"


class TestTheMechanism(unittest.TestCase):

    def test_httpx_cannot_send_this_key_as_a_header(self):
        """What the run hit, reproduced at its source rather than assumed."""
        import httpx
        with self.assertRaises(UnicodeEncodeError) as caught:
            httpx.Request("POST", "https://example.invalid",
                          headers={"x-goog-api-key": BAD})
        self.assertIn("'ascii' codec", str(caught.exception))


class TestTheKeyCheck(unittest.TestCase):

    def test_any_sendable_key_passes_whatever_its_format(self):
        for key in (GOOD, OLD_STYLE, "x" * 200, "k"):
            with self.subTest(length=len(key)):
                self.assertIsNone(config.gemini_key_problem(key))
        self.assertIsNone(config.gemini_key_problem(""))

    def test_quote_characters_are_named(self):
        for quote in "\"'`":
            with self.subTest(quote=quote):
                self.assertIn("quote character",
                              config.gemini_key_problem(quote + GOOD + quote))

    def test_a_copied_comment_is_named_by_character_and_position(self):
        problem = config.gemini_key_problem(GOOD + "—note")
        self.assertIn("U+2014", problem)
        self.assertIn(f"position {len(GOOD)}", problem)

    def test_whitespace_is_named(self):
        self.assertIn("space", config.gemini_key_problem(GOOD + " x"))

    def test_the_message_never_repeats_the_key(self):
        self.assertNotIn(GOOD, config.gemini_key_problem(BAD))
        self.assertNotIn(GOOD[:8], config.gemini_key_problem(BAD))

    def test_the_client_is_refused_before_it_is_built(self):
        from google import genai
        with mock.patch.object(genai, "Client") as client:
            with self.assertRaises(config.ApiKeyProblem):
                config.gemini_client(BAD)
            client.assert_not_called()

    def test_one_place_builds_a_gemini_client(self):
        """Four sites built one; the fifth is the one this test catches."""
        offenders = []
        for path in [*ROOT.glob("agents/*.py"), *ROOT.glob("tools/**/*.py"),
                     *ROOT.glob("scripts/*.py"), ROOT / "app.py", ROOT / "api/main.py"]:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "Client"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "genai"):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual(offenders, [], "build it through config.gemini_client")


class TestWhoseFaultItWas(unittest.TestCase):

    def reason(self, exc):
        from agents.generation_agent import _degraded_reason
        return _degraded_reason(exc)

    def test_an_unsendable_key_is_the_keys_fault(self):
        text = self.reason(config.ApiKeyProblem(config.gemini_key_problem(BAD)))
        self.assertIn("Your Gemini key was not used", text)
        self.assertNotIn("could not be reached", text)

    def test_quota_and_outages_are_geminis(self):
        from tools.cache.rate_limiter import RateLimitError
        self.assertIn("could not be reached", self.reason(RateLimitError("all models exhausted")))
        self.assertIn("could not be reached", self.reason(Exception("503 UNAVAILABLE")))

    def test_a_network_failure_is_geminis_not_ours(self):
        """A transport error must not read as a JobScout bug."""
        import httpx
        text = self.reason(httpx.ConnectError("connection refused"))
        self.assertIn("could not be reached", text)
        self.assertNotIn("bug in JobScout", text)

    def test_an_encoding_error_in_our_own_code_is_ours(self):
        exc = UnicodeEncodeError("ascii", "—", 0, 1, "ordinal not in range(128)")
        text = self.reason(exc)
        self.assertIn("bug in JobScout", text)
        self.assertNotIn("could not be reached", text)

    def test_any_other_exception_of_ours_is_ours(self):
        self.assertIn("bug in JobScout", self.reason(KeyError("experiences")))

    def _tailor_with(self, exc):
        """`_gemini_tailor` with its call raising `exc`; returns the degraded reason."""
        import agents.generation_agent as gen
        agent = gen.GenerationAgent.__new__(gen.GenerationAgent)
        agent.resume_parser = mock.Mock()
        agent._build_selected_experience_text = lambda selected: ""
        agent._build_selected_project_text = lambda selected: ""

        def boom(prompt):
            raise exc
        agent._call_gemini_json = boom
        agent._verbatim_tailor = lambda job, selected, budgets, reason: {"reason": reason}
        with mock.patch.object(gen, "build_generic_tailoring_prompt", return_value="p"):
            return agent._gemini_tailor({"full_jd": "jd"}, {}, {})["reason"]

    def test_the_tailor_uses_the_classified_reason(self):
        """The call site, not only the classifier: this is where the label lived."""
        key = self._tailor_with(config.ApiKeyProblem("The Gemini key contains ..."))
        self.assertIn("Your Gemini key was not used", key)
        ours = self._tailor_with(UnicodeEncodeError("ascii", "\u2014", 0, 1, "x"))
        self.assertIn("bug in JobScout", ours)
        self.assertNotIn("could not be reached", ours)

    def test_generation_refuses_the_key_before_calling_out(self):
        from agents.generation_agent import GenerationAgent
        agent = GenerationAgent.__new__(GenerationAgent)
        agent.llm_cache = mock.Mock(get=mock.Mock(return_value=None))
        agent.api_key = BAD
        with self.assertRaises(config.ApiKeyProblem):
            agent._call_gemini_json("prompt")


class TestEveryConsumerSaysSo(unittest.TestCase):

    def test_embeddings_report_it_as_fatal_with_the_reason(self):
        import tempfile
        import tools.resume.embedding_scorer as scorer
        from tools import paths
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {paths.HOME_ENV: home}), \
                mock.patch.object(scorer, "active_backend", lambda: ("gemini", "m", 2)), \
                mock.patch.object(scorer, "_EMBEDDING_CACHES", {}), \
                mock.patch.object(scorer, "_sleep", lambda s: None):
            report = []
            self.assertEqual(scorer._get_embedding("jd", api_key=BAD, user_id=None,
                                                   report=report), [])
        self.assertEqual(report[0]["kind"], "fatal")
        # The first unsendable character is the space where the real key ends.
        self.assertIn(f"position {len(GOOD)}", report[0]["error"])

    def test_import_says_the_key_not_the_network(self):
        from tools.resume import resume_import

        def agent(prompt):
            return config.gemini_client(BAD)
        schema = resume_import.to_schema("Jane Doe\njane@example.com\n", agent=agent)
        why = schema["_extraction"]["why"]
        self.assertIn("copied with it", why)
        self.assertNotIn("could not be reached", why)

    def test_the_key_panel_names_the_problem_and_does_not_choose_gemini(self):
        from agents.orchestrator import backend_status
        from tools.generation import llm_backends
        with mock.patch.object(llm_backends, "ollama_is_running", return_value=False), \
                mock.patch.object(llm_backends, "env_openai_key", return_value=""), \
                mock.patch.dict(os.environ, {"JOBSCOUT_LLM_BACKEND": ""}):
            status = backend_status(BAD)
        self.assertIn("copied with it", status["key_problem"])
        self.assertNotEqual(status["backend"], "gemini")
        self.assertFalse(status["available"]["gemini"])

    def test_a_good_key_has_no_problem_field_value(self):
        from agents.orchestrator import backend_status
        from tools.generation import llm_backends
        with mock.patch.object(llm_backends, "ollama_is_running", return_value=False), \
                mock.patch.object(llm_backends, "env_openai_key", return_value=""), \
                mock.patch.dict(os.environ, {"JOBSCOUT_LLM_BACKEND": ""}):
            self.assertIsNone(backend_status(GOOD)["key_problem"])


if __name__ == "__main__":
    unittest.main()

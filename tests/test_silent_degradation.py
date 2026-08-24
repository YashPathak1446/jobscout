"""
Telling "you chose this" apart from "this broke" (R47).

Five bugs in three days had one signature: the pipeline kept working, produced
something worse, and said nothing distinguishable. An unloaded `.env` shipped a
resume with zero experiences (R41). An Ollama with the wrong model pulled
promised local rewriting and 404'd (R42). A cache served one model's answers as
another's (R45). In each case the fallback itself was right — falling back is
the design — and what was missing was any way to tell a chosen floor from a
failed climb.

So the rule these tests hold: **the deliberate floor returns, a broken rung
raises, and anything that lands on the floor by accident says why in a place
the user will see.**
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.generation import llm_backends  # noqa: E402


class TestChosenFloorAndBrokenRungDiffer(unittest.TestCase):

    def setUp(self):
        import config
        self.config = config
        self.saved = (config.LLM_BACKEND, config.OLLAMA_API_URL,
                      config.OLLAMA_BASE_URL, config.resolve_api_key)

    def tearDown(self):
        (self.config.LLM_BACKEND, self.config.OLLAMA_API_URL,
         self.config.OLLAMA_BASE_URL, self.config.resolve_api_key) = self.saved

    def test_the_none_rung_returns_rather_than_raising(self):
        """Running without a model is a choice, not a fault."""
        self.config.LLM_BACKEND = "none"
        self.assertIsNone(llm_backends.complete_json("anything"))

    def test_a_rung_that_cannot_answer_raises(self):
        """
        Pointed at a port with nothing on it. Before R47 this returned None —
        the same value as choosing to run without a model.
        """
        self.config.LLM_BACKEND = "ollama"
        self.config.OLLAMA_API_URL = "http://127.0.0.1:59999"
        self.config.OLLAMA_BASE_URL = "http://127.0.0.1:59999/v1"

        with self.assertRaises(llm_backends.BackendFailure):
            llm_backends.complete_json("anything")

    def test_the_failure_says_what_to_do_about_it(self):
        """An error a user cannot act on is barely better than silence."""
        self.config.LLM_BACKEND = "ollama"
        self.config.OLLAMA_API_URL = "http://127.0.0.1:59999"
        self.config.OLLAMA_BASE_URL = "http://127.0.0.1:59999/v1"

        with self.assertRaises(llm_backends.BackendFailure) as caught:
            llm_backends.complete_json("anything")
        self.assertTrue(str(caught.exception).strip())

    def test_a_backend_failure_is_catchable_as_a_runtime_error(self):
        """Callers that already catch broadly keep working."""
        self.assertTrue(issubclass(llm_backends.BackendFailure, RuntimeError))


class TestExtractionSaysWhichHappened(unittest.TestCase):
    """
    `to_schema` falls back to heuristics either way, and the log line is the
    only thing that tells you whether to go fix something.
    """

    def _log_from(self, agent):
        from tools.resume import resume_import

        with self.assertLogs("tools.resume.resume_import", level="INFO") as logs:
            resume_import.to_schema("Jane Doe\njane@example.com\n", agent=agent)
        return " ".join(logs.output)

    def test_no_model_configured_is_reported_as_a_choice(self):
        text = self._log_from(lambda prompt: None)
        self.assertIn("No model configured", text)
        self.assertNotIn("failed", text.lower())

    def test_a_broken_backend_is_reported_as_a_failure(self):
        def broken(prompt):
            raise llm_backends.BackendFailure("no key resolved")

        text = self._log_from(broken)
        self.assertIn("failed", text.lower())
        self.assertIn("no key resolved", text)


class TestTheFloorRecordsWhyItWasReached(unittest.TestCase):
    """
    `_verbatim_tailor` produces byte-identical output whether it was chosen or
    fallen back to. The reason is the only thing separating them.
    """

    def setUp(self):
        from agents.generation_agent import GenerationAgent
        from tools.profile import load_profile
        from tools.resume import ResumeParser

        if not (ROOT / "user_profiles" / "yash_pathak.json").exists():
            self.skipTest("needs a real profile; skipped on a clean clone")

        profile = load_profile("yash_pathak")
        parser = ResumeParser(profile.resume_preferences.master_resume_path,
                              skip_embeddings=True)
        self.agent = GenerationAgent(profile, parser, generate_pdf=False)
        self.selected = {"experiences": ["exp_sorenson_communications"],
                         "projects": []}

    def test_a_chosen_floor_carries_no_reason(self):
        tailored = self.agent._verbatim_tailor({}, self.selected)
        self.assertNotIn("_verbatim_reason", tailored)

    def test_a_fallen_back_floor_carries_one(self):
        tailored = self.agent._verbatim_tailor(
            {}, self.selected, reason="Gemini could not be reached (quota)")
        self.assertIn("quota", tailored["_verbatim_reason"])

    def test_the_reason_does_not_change_the_resume(self):
        """
        The output is the same either way, which is exactly why the reason has
        to travel separately rather than being inferred from the content.
        """
        chosen = self.agent._verbatim_tailor({}, self.selected)
        fallen = self.agent._verbatim_tailor({}, self.selected, reason="x")
        self.assertEqual(chosen["experiences"], fallen["experiences"])


class TestTheUserIsToldInTheSummary(unittest.TestCase):
    """A log line nobody reads is not much better than silence."""

    def _summary_for(self, results):
        import json
        import tempfile
        from agents.orchestrator import JobScoutOrchestrator
        from tools.profile import load_profile

        if not (ROOT / "user_profiles" / "yash_pathak.json").exists():
            self.skipTest("needs a real profile; skipped on a clean clone")

        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = JobScoutOrchestrator(
                profile_name="yash_pathak", output_dir=tmp, generate_pdf=False)
            orchestrator.state["generation_results"] = results
            orchestrator.state["discovered_jobs"] = []
            orchestrator.state["analysis_results"] = []
            orchestrator._generate_summary()
            return (orchestrator.output_path / "summary.md").read_text(
                encoding="utf-8")

    def _result(self, degraded=None):
        return {"job": {"company": "Acme", "title": "Engineer"},
                "status": "valid", "latex_path": "a.tex", "pdf_path": None,
                "page_count": 1, "degraded": degraded,
                "validation": {"valid": True, "errors": [], "warnings": []}}

    def test_a_degraded_run_says_so(self):
        text = self._summary_for([self._result("Gemini could not be reached")])
        self.assertIn("not rewritten", text)
        self.assertIn("Gemini could not be reached", text)

    def test_a_clean_run_does_not_cry_wolf(self):
        text = self._summary_for([self._result()])
        self.assertNotIn("not rewritten", text)


if __name__ == "__main__":
    unittest.main()

"""
Two silent-failure bugs the board surfaced (A2, A3).

Both share the shape this project keeps re-finding: the system kept working,
produced wrong output, and said nothing. Neither was reachable by reading the
code — one needed a machine with the "wrong" model pulled, the other needed
two postings shown side by side.

No network here. `ollama_models` is the only part that talks to a server, and
it is deliberately split from `choose_model` so the choosing — where the bug
actually was — can be tested without one.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.generation import llm_backends  # noqa: E402


class TestChoosingAnOllamaModel(unittest.TestCase):
    """
    A2: detection and invocation disagreed about "available".

    Detection returned true when *any* model was pulled; the call then asked
    for the one name in config. Someone running Ollama with `mistral` was told
    bullets would be rewritten locally, and the call 404'd on a model that was
    never there.
    """

    def test_the_preferred_model_wins_when_it_is_there(self):
        self.assertEqual(
            llm_backends.choose_model(["mistral:latest", "llama3.1:8b"], "llama3.1:8b"),
            "llama3.1:8b")

    def test_a_bare_name_matches_its_own_tag(self):
        """`ollama pull llama3.1` stores `llama3.1:latest`."""
        self.assertEqual(
            llm_backends.choose_model(["llama3.1:latest"], "llama3.1"),
            "llama3.1:latest")

    def test_a_tagged_preference_matches_a_different_tag(self):
        self.assertEqual(
            llm_backends.choose_model(["llama3.1:70b"], "llama3.1:8b"),
            "llama3.1:70b")

    def test_an_absent_preference_falls_back_to_what_is_there(self):
        """The actual bug: this used to return the missing model and 404."""
        self.assertEqual(
            llm_backends.choose_model(["mistral:latest"], "llama3.1"),
            "mistral:latest")

    def test_no_models_means_no_choice(self):
        self.assertEqual(llm_backends.choose_model([], "llama3.1"), "")

    def test_no_preference_takes_the_first(self):
        self.assertEqual(
            llm_backends.choose_model(["mistral:latest", "qwen:7b"]),
            "mistral:latest")

    def test_blank_entries_are_ignored(self):
        self.assertEqual(llm_backends.choose_model(["", "qwen:7b"]), "qwen:7b")

    def test_running_means_serving_at_least_one_model(self):
        """
        An Ollama that is up with nothing pulled cannot answer, so it is not
        an available rung. Checked through the seam rather than the network.
        """
        real = llm_backends.ollama_models
        try:
            llm_backends.ollama_models = lambda url: []
            self.assertFalse(llm_backends.ollama_is_running("http://x"))
            llm_backends.ollama_models = lambda url: ["qwen:7b"]
            self.assertTrue(llm_backends.ollama_is_running("http://x"))
        finally:
            llm_backends.ollama_models = real

    def test_a_down_server_reports_no_models_rather_than_raising(self):
        """One real call, to a closed port. Falling back beats crashing."""
        self.assertEqual(llm_backends.ollama_models("http://localhost:59999"), [])


class TestResumeFilenamesAreUnique(unittest.TestCase):
    """
    A3: two postings could share one resume file.

    The names below are the real collision, from the job store: Affirm posts
    the same title in several countries, so the last resume written won and
    the others' stored paths pointed at a resume tailored to a different JD.
    """

    def setUp(self):
        from agents.generation_agent import GenerationAgent

        # `_generate_filename` reads `self.profile` and nothing else, so it is
        # called against a stand-in rather than a whole agent — which would
        # want a resume, a key and a model to exist first.
        class _Agent:
            profile = type("_Profile", (), {
                "personal_info": type("_Person", (), {"name": "Yash Pathak"})(),
            })()

            _generate_filename = GenerationAgent._generate_filename

        self.agent = _Agent()

    def name_for(self, company, title, url=""):
        return self.agent._generate_filename(company, title, url)

    def test_two_postings_of_the_same_role_get_different_files(self):
        spain = self.name_for(
            "Affirm", "Software Engineer I, Fullstack (Servicing International)",
            "https://job-boards.greenhouse.io/affirm/jobs/7809763003")
        poland = self.name_for(
            "Affirm", "Software Engineer I, Fullstack (Servicing International)",
            "https://job-boards.greenhouse.io/affirm/jobs/7809761003")

        self.assertNotEqual(spain, poland)

    def test_the_readable_part_survives(self):
        """The old name was readable, and that was a feature worth keeping."""
        filename = self.name_for("Affirm", "Software Engineer I, Fullstack",
                                 "https://example.test/1")
        self.assertTrue(filename.startswith("Yash_Pathak_Affirm_Software_Engineer_I"))

    def test_the_same_posting_always_gets_the_same_name(self):
        """
        Stable, not sequential: re-running overwrites a posting's own resume
        rather than accumulating near-duplicates beside it.
        """
        url = "https://job-boards.greenhouse.io/affirm/jobs/7809763003"
        first = self.name_for("Affirm", "Software Engineer I", url)
        second = self.name_for("Affirm", "Software Engineer I", url)
        self.assertEqual(first, second)

    def test_a_posting_with_no_url_keeps_the_old_shape(self):
        """Nothing to disambiguate with, so nothing is appended."""
        filename = self.name_for("Affirm", "Software Engineer I")
        self.assertEqual(filename, "Yash_Pathak_Affirm_Software_Engineer_I")

    def test_the_name_stays_filesystem_safe(self):
        filename = self.name_for(
            "O'Reilly & Co.", "Engineer/Developer (Remote)",
            "https://example.test/2")
        self.assertTrue(all(c.isalnum() or c == "_" for c in filename), filename)


class TestThePanelDoesNotOverclaim(unittest.TestCase):
    """
    A5: the UI recommended a rung nobody had verified.

    The panel is where a user decides whether to go and install something, so
    it is the one place the untested-ness has to be visible. `backend` is the
    screen's own cache, so injecting it renders any rung without needing that
    backend present.
    """

    def _panel_text(self, backend, key=""):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
        app.session_state["step"] = 1
        app.session_state["profile_name"] = "template"
        app.session_state["api_key"] = key
        app.session_state["backend"] = {
            "backend": backend,
            "forced": False,
            "description": llm_backends.describe(backend, ""),
            "available": {"gemini": False, "openai": False,
                          "ollama": backend == "ollama", "none": True},
            "key_used": key,
        }
        app.run()
        return " ".join(
            [w.value for w in app.warning]
            + [s.value for s in app.success]
            + [c.value for c in app.caption]
        )

    def test_the_ollama_rung_is_described_as_unmeasured(self):
        text = self._panel_text("ollama")
        self.assertIn("not been measured", text.lower().replace("’", "'"))

    def test_the_floor_still_says_how_to_move_up(self):
        text = self._panel_text("none")
        self.assertIn("Ollama", text)
        self.assertIn("Gemini key", text)

    def test_the_floor_no_longer_names_one_specific_model(self):
        """
        A2 made any pulled model work, so telling people to pull `llama3.1`
        is now both unnecessary and slightly wrong.
        """
        self.assertNotIn("llama3.1", self._panel_text("none"))


if __name__ == "__main__":
    unittest.main()

r"""
Which rung runs is a decision with four inputs and one place that makes it.

R79 gave a run the ability to *say* which rung wrote it. It still could not be
*told* which rung to use: `LLM_BACKEND` was a module constant, so choosing one
meant editing `config.py`. Three things followed from that single gap — Ollama
could not be measured, users could not choose it, and per-user-per-run
selection could not be expressed at all, which is the one subsystem the
accounts audit found that does not take a parameter.

The chain, highest first:

    --backend  >  JOBSCOUT_LLM_BACKEND  >  profile.agent_preferences.llm_backend  >  detect()

**Detection is the default, never the answer** — the same shape as
years-then-derive-levels (R68): ask what the person can answer, derive the
rest, and let a stated choice outlive later edits to anything else.

Two things this file is careful about, both of them the invariant again:

* `None` is not `"auto"`. Absent means nobody has stated a preference;
  `"auto"` means somebody stated that detection should decide. Storing
  `"auto"` in a profile is refused, because two spellings of "not chosen" —
  one of them absent and one of them a value — is exactly how
  `location_score == 0` and `years_required: None` began.
* An unknown name raises. A typo'd `--backend olama` must not fall through to
  detection, because a measurement that silently describes a different rung
  than the one it names is worse than one that fails.

And the two-paths check, written **before** the paths could diverge:
`complete_json` (import) and `GenerationAgent` (generation) are the project's
two model consumers, and they resolve through the same function. Every
previous instance of this shape — the escape table (R69), the experience field
order (R70), the selection breakdown (R57) — was found months later by
somebody walking the path the author does not.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config import BACKEND_CHOICES, UnknownBackend, resolve_backend  # noqa: E402
from tools.profile.profile_schema import AgentPreferences  # noqa: E402


def profile_saying(backend):
    """Anything with the shape `resolve_backend` reads."""
    return type("P", (), {"agent_preferences": AgentPreferences(llm_backend=backend)})()


def no_env():
    """The environment with no opinion, so a test measures its own inputs."""
    return mock.patch.dict(os.environ, {"JOBSCOUT_LLM_BACKEND": ""}, clear=False)


class TestThePrecedenceChain(unittest.TestCase):

    def test_nothing_stated_defers_to_detection(self):
        with no_env():
            self.assertEqual(resolve_backend(None, None), "auto")

    def test_the_profile_is_used_when_nothing_outranks_it(self):
        with no_env():
            self.assertEqual(resolve_backend(None, profile_saying("ollama")),
                             "ollama")

    def test_the_environment_beats_the_profile(self):
        with mock.patch.dict(os.environ, {"JOBSCOUT_LLM_BACKEND": "none"}):
            self.assertEqual(resolve_backend(None, profile_saying("ollama")),
                             "none")

    def test_the_flag_beats_the_environment(self):
        with mock.patch.dict(os.environ, {"JOBSCOUT_LLM_BACKEND": "none"}):
            self.assertEqual(resolve_backend("gemini", profile_saying("ollama")),
                             "gemini")

    def test_the_flag_beats_a_profile_with_no_environment(self):
        with no_env():
            self.assertEqual(resolve_backend("none", profile_saying("gemini")),
                             "none")

    def test_every_layer_is_reachable(self):
        """
        Each rung in turn, so a chain that happened to return the right answer
        for one input cannot pass by accident.
        """
        for rung in ("gemini", "openai", "ollama", "none"):
            with self.subTest(rung=rung), no_env():
                self.assertEqual(resolve_backend(rung, None), rung)


class TestAbsentIsNotAValue(unittest.TestCase):

    def test_none_and_auto_are_different_answers(self):
        with no_env():
            self.assertEqual(resolve_backend(None, None), "auto")
            self.assertEqual(resolve_backend("auto", None), "auto")
        # Same resolved word, different meaning, and the difference shows in
        # what a profile is allowed to hold.
        self.assertIsNone(AgentPreferences().llm_backend)

    def test_a_profile_cannot_store_auto(self):
        """
        The invariant, committed deliberately, refused. Storing "auto" would
        make two spellings of "not chosen" — one absent, one a value — in the
        field added to argue against exactly that.
        """
        with self.assertRaises(ValueError) as caught:
            AgentPreferences(llm_backend="auto")
        self.assertIn("Leave it unset", str(caught.exception))

    def test_a_profile_can_store_a_real_rung(self):
        self.assertEqual(AgentPreferences(llm_backend="ollama").llm_backend,
                         "ollama")

    def test_an_empty_string_in_a_profile_reads_as_unset(self):
        """A form that submits a blank select has not chosen anything."""
        self.assertIsNone(AgentPreferences(llm_backend="").llm_backend)

    def test_an_empty_flag_is_no_opinion_and_not_a_rung(self):
        with no_env():
            self.assertEqual(resolve_backend("", profile_saying("ollama")),
                             "ollama")


class TestAnUnknownRungIsRefused(unittest.TestCase):
    """
    Silently detecting after being told exactly what to do is how a
    measurement ends up describing a rung it did not use.
    """

    def test_a_typo_on_the_flag_raises(self):
        with no_env(), self.assertRaises(UnknownBackend) as caught:
            resolve_backend("olama", None)
        self.assertIn("--backend", str(caught.exception))

    def test_a_typo_in_the_environment_raises_and_names_the_variable(self):
        with mock.patch.dict(os.environ, {"JOBSCOUT_LLM_BACKEND": "gemeni"}):
            with self.assertRaises(UnknownBackend) as caught:
                resolve_backend(None, None)
        self.assertIn("JOBSCOUT_LLM_BACKEND", str(caught.exception))

    def test_a_profile_refuses_a_rung_that_does_not_exist(self):
        with self.assertRaises(ValueError):
            AgentPreferences(llm_backend="llama")

    def test_case_and_padding_do_not_make_a_new_rung(self):
        with no_env():
            self.assertEqual(resolve_backend("  Ollama  ", None), "ollama")


class TestBothModelConsumersResolveTheSameWay(unittest.TestCase):
    """
    The two-paths check, written before the paths can diverge.

    `complete_json` serves resume import; `GenerationAgent` serves bullet
    rewriting. If one obeyed the flag while the other went on detecting, a run
    pinned to Ollama would import through Gemini and nothing would say so.
    """

    def test_both_call_the_one_resolver(self):
        sources = {
            "tools/generation/llm_backends.py": "complete_json",
            "agents/generation_agent.py": "GenerationAgent._resolve_backend",
            "agents/orchestrator.py": "backend_status",
        }
        for path, who in sources.items():
            body = (ROOT / path).read_text(encoding="utf-8")
            with self.subTest(who=who):
                self.assertIn("resolve_backend", body,
                              f"{who} does not go through config.resolve_backend")

    def test_nothing_outside_config_reads_the_constant(self):
        r"""
        The seam, closed the way `test_renderers_agree` closed the section
        builders — by making a fifth caller fail the build rather than by
        remembering to check.

        **The plan predicted two consumers and the code had four:**
        `GenerationAgent._resolve_backend`, `complete_json`, `backend_status`,
        and a caption in `app.py` telling users to edit `config.py`. The twin
        rule is not "check the other one", it is **count them**, and the count
        is reliably higher than the pair in mind.

        Parsed rather than grepped. Prose may name the constant — a docstring
        explaining the chain and a caption telling a user what pinned their
        rung are the opposite of bypassing it, and a text search flagged both.
        Only a real reference in code counts, which is what the syntax tree
        answers and a substring cannot.
        """
        import ast
        import subprocess

        # **Ask git which files are the repo's**, rather than walking the
        # filesystem. `rglob` finds everything under the directory, and the
        # README tells users to `python -m venv venv` right here — so every
        # contributor following the install instructions would have had this
        # fail on somebody else's vendored code. It failed on a nested clone
        # of this repo inside itself, which is the same shape.
        #
        # A test that walks a directory tests whatever happens to be in the
        # directory. `git ls-files` answers the question actually being asked:
        # which Python files does this project ship?
        listed = subprocess.run(
            ["git", "ls-files", "*.py"],
            cwd=ROOT, capture_output=True, text=True, check=False)
        if listed.returncode != 0:
            self.skipTest("not a git checkout, so the file list is unknowable")
        tracked = [line for line in listed.stdout.splitlines() if line.strip()]
        self.assertTrue(tracked, "git listed no Python files at all")

        offenders = []
        for relative in tracked:
            path = ROOT / relative
            if (relative == "config.py" or relative.startswith("tests/")
                    or not path.exists()):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                named = (isinstance(node, ast.Name) and node.id == "LLM_BACKEND")
                attribute = (isinstance(node, ast.Attribute)
                             and node.attr == "LLM_BACKEND")
                # An `from config import LLM_BACKEND` counts too: importing it
                # is how every one of the four callers began.
                imported = (isinstance(node, ast.ImportFrom)
                            and any(a.name == "LLM_BACKEND" for a in node.names))
                if named or attribute or imported:
                    offenders.append(
                        f"{relative}:{getattr(node, 'lineno', '?')}")

        self.assertEqual(offenders, [], "\n".join(
            ["these resolve the rung themselves instead of asking "
             "config.resolve_backend:"] + offenders))

    def test_they_agree_on_the_same_inputs(self):
        with no_env():
            for rung in ("gemini", "ollama", "none"):
                with self.subTest(rung=rung):
                    self.assertEqual(resolve_backend(rung, None),
                                     resolve_backend(rung, None))


class TestTwoModelsAreTwoAnswers(unittest.TestCase):
    r"""
    The cache key holds the rung **and**, where it matters, the model.

    R45 put the rung in the key after three llama3.1 replies were served to a
    run pinned to Gemini and read as a Gemini regression. The closing line of
    that module's docstring — "the rung, not the model id, so a fallback
    within a provider still hits" — was written when *provider* meant Gemini's
    model chain, where flash-lite answering for flash is the entire point. It
    does not survive a provider meaning "whatever you happened to pull":
    `llama3.1:8b` and `qwen2.5:7b` are both the `ollama` rung.

    Found while planning a two-model comparison, which would have served the
    first model's answers to the second and produced a table that was
    perfect, instant and entirely fictional. That failure mode has no error
    to notice, which is why it is asserted here rather than watched for.
    """

    def cache(self, tmp, backend, model):
        from tools.cache.llm_cache import LLMCache
        return LLMCache(cache_dir=tmp, enabled=True, backend=backend, model=model)

    def test_a_second_model_on_the_same_rung_misses(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            first = self.cache(tmp, "ollama", "llama3.1:8b")
            first.set("the same prompt", {"answer": "from llama"}, "llama3.1:8b")

            second = self.cache(tmp, "ollama", "qwen2.5:7b")
            self.assertIsNone(second.get("the same prompt"),
                              "one model was served the other's answer")

    def test_the_same_model_still_hits(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.cache(tmp, "ollama", "llama3.1:8b").set(
                "p", {"answer": "kept"}, "llama3.1:8b")
            again = self.cache(tmp, "ollama", "llama3.1:8b").get("p")
            self.assertEqual(again, {"answer": "kept"})

    def test_gemini_still_shares_across_its_fallback_chain(self):
        """
        The behaviour that must survive: `GENERATION_MODELS` is a chain, and
        flash-lite answering where flash answered yesterday is what the chain
        is for. Gemini passes no model, so its entries stay shared.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.cache(tmp, "gemini", "").set(
                "p", {"answer": "flash"}, "gemini-3.5-flash")
            served = self.cache(tmp, "gemini", "").get("p")
            self.assertEqual(served, {"answer": "flash"})

    def test_the_rung_is_still_in_the_key(self):
        """R45, held in place while the model is added beside it."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.cache(tmp, "ollama", "llama3.1:8b").set(
                "p", {"answer": "from llama"}, "llama3.1:8b")
            self.assertIsNone(self.cache(tmp, "gemini", "").get("p"))

    def test_the_agent_gives_the_cache_a_model_only_where_it_matters(self):
        from agents.generation_agent import GenerationAgent

        made = GenerationAgent.__new__(GenerationAgent)
        made.ollama_model = "llama3.1:8b"

        made.llm_backend = "ollama"
        self.assertEqual(made._cache_model(), "llama3.1:8b")

        made.llm_backend = "gemini"
        self.assertEqual(made._cache_model(), "",
                         "Gemini must keep sharing entries across its chain")

        made.llm_backend = "none"
        self.assertEqual(made._cache_model(), "")


class TestTheChoiceReachesTheRun(unittest.TestCase):
    """
    Screen to request to pipeline. Each hop is a parameter somebody has to
    remember to pass, which is the shape that loses a field — the project has
    lost `rarely_include`, `scraped_successfully`, a project link and a
    contact field exactly this way.
    """

    def test_the_request_carries_a_backend_and_defaults_to_no_opinion(self):
        from api.main import RunRequest

        self.assertEqual(RunRequest(profile="p").backend, "",
                         "the default must be 'no opinion', not a rung")
        self.assertEqual(RunRequest(profile="p", backend="ollama").backend,
                         "ollama")

    def test_the_endpoint_forwards_it_to_the_run(self):
        from unittest.mock import patch
        import api.main as main

        seen = {}

        def fake_start_run(profile, **kwargs):
            seen.update(kwargs)
            return "run-1"

        with patch.object(main, "start_run", fake_start_run):
            main.run_start(main.RunRequest(profile="p", backend="ollama"))
        self.assertEqual(seen.get("backend"), "ollama")

    def test_an_empty_choice_reaches_the_run_as_no_opinion(self):
        """
        `""` must arrive as `None`, not as the empty string — `resolve_backend`
        reads a falsy explicit as "nobody said", and passing `""` through
        happens to work only because it is falsy. Asserted so it stays true on
        purpose rather than by luck.
        """
        from unittest.mock import patch
        import api.main as main

        seen = {}
        with patch.object(main, "start_run",
                          lambda profile, **kw: seen.update(kw) or "run-1"):
            main.run_start(main.RunRequest(profile="p"))
        self.assertIsNone(seen.get("backend"))

    def test_the_screen_sends_the_field(self):
        source = (ROOT / "web" / "src" / "components" / "steps"
                  / "RunStep.tsx").read_text(encoding="utf-8")
        self.assertIn("backend: chosen", source,
                      "the Run screen collects a rung and does not send it")

    def test_the_screen_shows_a_rung_it_cannot_use_rather_than_hiding_it(self):
        """
        Hiding an unavailable rung is what kept Ollama a secret from the
        people it was built for. A disabled row that says "not running" tells
        somebody what to install; an absent row tells them nothing.
        """
        source = (ROOT / "web" / "src" / "components" / "steps"
                  / "RunStep.tsx").read_text(encoding="utf-8")
        self.assertIn("disabled={!ready}", source)
        self.assertIn("needs", source)


class TestTheChoicesAreTheLadder(unittest.TestCase):

    def test_every_rung_on_the_ladder_is_choosable(self):
        from tools.generation.llm_backends import LADDER
        for rung in LADDER:
            self.assertIn(rung, BACKEND_CHOICES,
                          f"{rung} exists but cannot be asked for")

    def test_auto_is_choosable_but_is_not_a_rung(self):
        from tools.generation.llm_backends import LADDER
        self.assertIn("auto", BACKEND_CHOICES)
        self.assertNotIn("auto", LADDER)


if __name__ == "__main__":
    unittest.main()

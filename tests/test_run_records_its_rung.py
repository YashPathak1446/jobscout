"""
A run says which rung wrote its bullets, in the run, not to a terminal.

Two passes over the same profile were compared against each other and one of
them was not the rung it was labelled with. `llm_backends.detect()` prefers a
local Ollama over nothing whenever no Gemini key is present, so on a machine
where Ollama is installed **"no key" is not "no model"** — and the only trace
of which rung ran was a log line nobody keeps.

That is not a tidiness problem. The free tier is the thing this project is
trying to make good, every measurement of it is a comparison against something
else, and a run that does not record its own rung cannot be compared with
another one later. The same class as R76: the rung has to be read from what
happened, not from what was configured.

Three places, because each is what somebody actually reads:

* every result record carries `rung` — one run can use more than one, since
  both model rungs fall back to verbatim when the model does not answer
* the run state carries `backend.configured` and `backend.used`
* `summary.md` says it above the fold, before anything a reader would compare

And a cache hit names the model that wrote the text rather than the word
"cache", which names where it was kept.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from agents.generation_agent import GenerationAgent  # noqa: E402


class Cache:
    """Enough of `LLMCache` to answer the two questions the agent asks."""

    def __init__(self, model=""):
        self.last_model = model
        self.enabled = True

    def get(self, prompt):
        return None

    def set(self, prompt, response, model):
        pass


def agent(backend="none", last_model=None, cache_model=""):
    made = GenerationAgent.__new__(GenerationAgent)
    made.llm_backend = backend
    made.last_model_used = last_model
    made.llm_cache = Cache(cache_model)
    return made


class TestTheRungIsWhatRanAndNotWhatWasConfigured(unittest.TestCase):

    def test_a_verbatim_payload_says_verbatim(self):
        self.assertEqual(agent()._rung_used({"_verbatim": True}), "verbatim")

    def test_a_fallback_under_a_configured_model_still_says_verbatim(self):
        """
        The case that made this necessary. The backend is Ollama, a model was
        asked, it did not answer, and the user's own bullets were written —
        so the run must not report Ollama as the author.
        """
        fell_back = agent(backend="ollama", last_model="llama3.1:latest")
        self.assertEqual(
            fell_back._rung_used({"_verbatim": True,
                                  "_verbatim_reason": "the ollama backend failed"}),
            "verbatim")

    def test_a_model_payload_names_the_model(self):
        wrote = agent(backend="ollama", last_model="llama3.1:latest")
        self.assertEqual(wrote._rung_used({"experiences": []}),
                         "llama3.1:latest")

    def test_a_stale_model_name_is_not_attributed_to_a_verbatim_resume(self):
        """
        `last_model_used` is per-agent, not per-resume: after job 1 is written
        by a model and job 2 falls back, it still holds job 1's answer. The
        `_verbatim` check is what stops that being read as job 2's author.
        """
        made = agent(backend="gemini", last_model="gemini-2.5-flash")
        self.assertEqual(made._rung_used({"_verbatim": True}), "verbatim")
        self.assertEqual(made._rung_used({"experiences": []}),
                         "gemini-2.5-flash")

    def test_nothing_useful_still_answers(self):
        self.assertEqual(agent()._rung_used(None), "unknown")
        self.assertEqual(agent(backend="")._rung_used({}), "unknown")


class TestACacheHitNamesTheWriterNotTheStorage(unittest.TestCase):
    """
    "cache" is where the text was kept. A run reporting it as the rung says
    nothing about who wrote the resume, which is the whole ambiguity this is
    here to remove — the first pass after adding the rung record reported
    `cache (5)` and was no more legible than before.
    """

    def test_the_cache_exposes_the_model_it_stored(self):
        from tools.cache.llm_cache import LLMCache
        self.assertTrue(hasattr(LLMCache("", enabled=False), "last_model"),
                        "the cache no longer says which model it holds")

    def test_a_cached_rung_reads_as_the_model_and_says_it_was_cached(self):
        made = agent(backend="ollama", last_model="llama3.1:latest (cached)")
        rung = made._rung_used({"experiences": []})
        self.assertIn("llama3.1", rung)
        self.assertIn("cached", rung)


class TestTheRunRecordsIt(unittest.TestCase):

    def test_the_summary_writes_the_rung_above_the_fold(self):
        """
        Above the discovery section, because a reader comparing two runs has
        to see it before reading either. Asserted on the source since building
        a whole run here would test the harness, not the record.
        """
        source = (ROOT / "agents" / "orchestrator.py").read_text(encoding="utf-8")
        self.assertIn("Bullets written by:", source)
        self.assertLess(source.index("Bullets written by:"),
                        source.index("## \U0001f50d Discovery"))

    def test_the_state_carries_both_configured_and_used(self):
        source = (ROOT / "agents" / "orchestrator.py").read_text(encoding="utf-8")
        self.assertIn("self.state['backend']", source)
        self.assertIn("'configured'", source)
        self.assertIn("'used'", source)

    def test_every_result_record_carries_a_rung(self):
        source = (ROOT / "agents" / "generation_agent.py").read_text(encoding="utf-8")
        self.assertIn('"rung": self._rung_used(tailored)', source)


if __name__ == "__main__":
    unittest.main()

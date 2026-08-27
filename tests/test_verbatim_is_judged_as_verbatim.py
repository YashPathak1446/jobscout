"""
A rung that may not rewrite a bullet is not judged as one that may.

The re-run of Priya Raghunathan, end to end on the free tier, came back **0
valid, 5 needs review** — five compiled one-page PDFs a person would have sent,
every one of them filed under "this went wrong". Two causes, and neither was
visible from any unit test in this suite because both need a whole run to
appear.

**The orphan zone was addressed to somebody who wasn't there.** The zone error
names two target ranges and asks for one of them, because
`_validate_bullet_length` exists to feed the repair loop — its own docstring
says so. On the no-model rung there is no model, no retry, and no permission
to rewrite: the text is the user's, `fit_bullet` already tried to compress it
and could not. Priya's Toast bullet is 126 characters. The error's only
remaining effect was to condemn the resume for a line the user had already
chosen to write that way.

**The rung was read from the settings, not from what happened.** Both model
rungs fall back to verbatim when the model does not answer, so a run
configured for Ollama can produce a verbatim resume — and it was then
validated against a budget nothing had spent. `_verbatim` is now stamped on
the payload by the tailor that wrote it, which is the only place that knows.

Overflow stays an error on every rung. A bullet past the maximum spills onto a
second page, which is a consequence rather than an opinion about typography.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.generation.validation import (  # noqa: E402
    LINE_1_END, LINE_2_WELL_FILLED_START, EXPERIENCE_BULLET_MAX_CHARS,
    validate_resume_output,
)

# 126 characters, which is Priya's Toast bullet to the character. Between
# `LINE_1_END` and `LINE_2_WELL_FILLED_START`: two lines, the second with
# sixteen characters on it.
ORPHAN = ("Built the restaurant onboarding API in Java and Kotlin, serving "
          "18K+ merchants and sustaining 2.5K requests per second at peak")

# 192 characters — Priya's Wayfair bullet, which fills two lines properly and
# is the reason her resume is not rejected outright on either rung.
GOOD = ("Led the migration of the checkout ledger from a single Postgres "
        "instance to a sharded topology, cutting p99 write latency from "
        "340ms to 48ms across 12 shards with no customer-visible downtime.")

OVERFLOW = GOOD + " " + GOOD + " " + GOOD


def payload(bullet, verbatim=False, count=1):
    data = {
        "experiences": [{"id": "exp_toast", "company": "Toast",
                         "title": "Senior Software Engineer",
                         "bullets": [bullet] * count}],
        "projects": [],
    }
    if verbatim:
        data["_verbatim"] = True
    return data


def budgets(count=1):
    return {"experiences": {"exp_toast": count}, "projects": {},
            "totals": {"experiences": count, "projects": 0, "overall": count}}


class TestTheFixtureIsWhatItClaims(unittest.TestCase):
    """If these drift, every assertion below is testing a different thing."""

    def test_the_orphan_bullet_is_in_the_orphan_zone(self):
        self.assertTrue(LINE_1_END < len(ORPHAN) < LINE_2_WELL_FILLED_START,
                        f"{len(ORPHAN)} chars is no longer an orphan")

    def test_the_good_bullet_fills_its_lines(self):
        self.assertGreaterEqual(len(GOOD), LINE_2_WELL_FILLED_START)

    def test_the_overflow_bullet_overflows(self):
        self.assertGreater(len(OVERFLOW), EXPERIENCE_BULLET_MAX_CHARS)


class TestAnOrphanIsAVerdictOnlyWhereSomethingCanActOnIt(unittest.TestCase):

    def test_the_model_path_still_fails_on_an_orphan(self):
        """
        Unchanged, and the point of the split. A model that missed the zone
        can be told to try again, and the repair loop is what tells it.
        """
        result = validate_resume_output(payload(ORPHAN), bullet_budgets=budgets())
        self.assertFalse(result.valid)
        self.assertTrue(any("orphan" in e for e in result.errors))

    def test_the_verbatim_path_reports_it_and_passes(self):
        """The regression, stated so it cannot come back quietly."""
        result = validate_resume_output(payload(ORPHAN, verbatim=True),
                                        bullet_budgets=budgets())
        self.assertTrue(result.valid,
                        f"a sendable resume was refused: {result.errors}")
        self.assertTrue(any("orphan" in w for w in result.warnings),
                        "the orphan was downgraded all the way to silence")

    def test_the_advice_does_not_address_a_model_that_is_not_there(self):
        """
        "Either compress to ≤110 OR expand to 180-213" is an instruction to a
        rewriter. On this rung the only rewriter is the person reading it.
        """
        result = validate_resume_output(payload(ORPHAN, verbatim=True),
                                        bullet_budgets=budgets())
        orphan_warning = next(w for w in result.warnings if "orphan" in w)
        self.assertNotIn("expand to", orphan_warning)
        self.assertIn("by hand", orphan_warning)

    def test_overflow_is_an_error_on_the_verbatim_path_too(self):
        """
        The line this fix must not cross. An orphan is untidy; an overflow is
        a second page.
        """
        result = validate_resume_output(payload(OVERFLOW, verbatim=True),
                                        bullet_budgets=budgets())
        self.assertFalse(result.valid)
        self.assertTrue(any("exceeds" in e for e in result.errors))

    def test_a_good_bullet_passes_on_both_rungs(self):
        for verbatim in (False, True):
            with self.subTest(verbatim=verbatim):
                result = validate_resume_output(payload(GOOD, verbatim=verbatim),
                                                bullet_budgets=budgets())
                self.assertTrue(result.valid, result.errors)


class TestTheRungIsReadFromWhatHappened(unittest.TestCase):
    """
    Not from `self.llm_backend`, which is what was configured. The two differ
    exactly when a model was asked and did not answer — the case where a
    stranger's run is most likely to be going wrong already.
    """

    def test_the_verbatim_tailor_stamps_every_payload(self):
        from agents.generation_agent import GenerationAgent

        class Component:
            id, bullets = "exp_toast", [ORPHAN]
            title = company = "Toast"
            dates = location = tech = name = url = ""

        agent = GenerationAgent.__new__(GenerationAgent)
        agent.resume_parser = type("P", (), {
            "get_experience_by_id": staticmethod(
                lambda cid: Component() if cid == "exp_toast" else None),
            "get_project_by_id": staticmethod(lambda cid: None),
        })()

        chosen = agent._verbatim_tailor(
            {"full_jd": ""}, {"experiences": ["exp_toast"], "projects": []},
            budgets())
        self.assertTrue(chosen.get("_verbatim"))

    def test_a_deliberate_keyless_run_carries_no_failure_reason(self):
        """
        `_verbatim` says which rung; `_verbatim_reason` says why, and only
        when the rung was not the one asked for. Collapsing the two would make
        a free-tier run look like a broken paid one, which is R47's finding.
        """
        from agents.generation_agent import GenerationAgent

        agent = GenerationAgent.__new__(GenerationAgent)
        agent.resume_parser = type("P", (), {
            "get_experience_by_id": staticmethod(lambda cid: None),
            "get_project_by_id": staticmethod(lambda cid: None),
        })()

        chosen = agent._verbatim_tailor({"full_jd": ""},
                                        {"experiences": [], "projects": []}, {})
        self.assertTrue(chosen.get("_verbatim"))
        self.assertIsNone(chosen.get("_verbatim_reason"))

        fell = agent._verbatim_tailor({"full_jd": ""},
                                      {"experiences": [], "projects": []}, {},
                                      reason="the ollama backend failed")
        self.assertTrue(fell.get("_verbatim"))
        self.assertIn("ollama", fell.get("_verbatim_reason"))


if __name__ == "__main__":
    unittest.main()

"""
What a finished run tells the person who started it.

A run that discovered five jobs, analysed none and wrote none reported
**"Finished"**. That is the last screen a first-time user sees, and it told
them the product worked when it had done nothing. Paired with the scoring
collapse fixed in the same commit, it would have presented to every new user
as "JobScout ran fine and found me no jobs" — no wrong output to notice, no
error to report, nothing to come back to.

Zero has three causes and the user can act on two:

    discovered == 0   nothing was found at all      -> widen the search
    analysed   == 0   found, none scored well enough -> the roles do not match
    generated  == 0   matched, nothing was written   -> this machine

The run registry now carries `discovered`, `enriched` and `threshold` so the
screen can tell them apart. Without those it could only report zero and call
it success, which is exactly what it did.

These tests mirror `outcome()` in `web/src/components/steps/RunStep.tsx`. The
frontend has no test runner yet; the branching is the part worth pinning, and
`test_web_controls.py` holds the source shape alongside.
"""


import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

RUN_STEP = ROOT / "web" / "src" / "components" / "steps" / "RunStep.tsx"


def outcome(state, result):
    """The same branching the screen does, in the order it does it."""
    if state == "failed":
        return "failed"
    if not result:
        return "unknown"
    if result["generated"] > 0:
        return "wrote"
    if result["discovered"] == 0:
        return "nothing_found"
    if result["analysed"] == 0:
        return "none_matched"
    return "none_written"


def run(discovered=0, analysed=0, generated=0, valid=0, threshold=40):
    return {"discovered": discovered, "enriched": discovered,
            "analysed": analysed, "generated": generated, "valid": valid,
            "threshold": threshold, "degraded": []}


class TestZeroIsNotFinished(unittest.TestCase):

    def test_the_run_that_started_this(self):
        """Five discovered, none analysed — the real one, from 2026-08-26."""
        self.assertEqual(outcome("finished", run(discovered=5)), "none_matched")

    def test_discovery_finding_nothing_is_its_own_answer(self):
        self.assertEqual(outcome("finished", run(discovered=0)), "nothing_found")

    def test_matching_but_writing_nothing_is_its_own_answer(self):
        self.assertEqual(
            outcome("finished", run(discovered=9, analysed=4)), "none_written")

    def test_a_real_result_is_still_a_success(self):
        self.assertEqual(
            outcome("finished", run(discovered=9, analysed=4, generated=2, valid=2)),
            "wrote")

    def test_one_resume_is_a_success_too(self):
        self.assertEqual(
            outcome("finished", run(discovered=5, analysed=1, generated=1, valid=1)),
            "wrote")

    def test_failure_outranks_everything(self):
        self.assertEqual(outcome("failed", run(discovered=5)), "failed")

    def test_no_two_zero_cases_share_an_answer(self):
        """Three problems, three answers. Collapsing any two loses the advice."""
        answers = {
            outcome("finished", run(discovered=0)),
            outcome("finished", run(discovered=5)),
            outcome("finished", run(discovered=5, analysed=3)),
        }
        self.assertEqual(len(answers), 3, answers)


class TestTheRegistryCarriesWhatTheScreenNeeds(unittest.TestCase):
    """
    The screen can only distinguish those cases if the run result holds the
    counts. It held `analysed`, `generated`, `valid` and `degraded` — enough
    to say zero, not enough to say why.
    """

    def test_the_finish_payload_records_discovery_and_the_threshold(self):
        source = (ROOT / "agents" / "orchestrator.py").read_text(encoding="utf-8")
        finish = source[source.index("registry.finish("):]
        finish = finish[:finish.index("output_dir=")]
        for field in ('"discovered"', '"enriched"', '"analysed"',
                      '"generated"', '"threshold"'):
            self.assertIn(field, finish,
                          f"the run result no longer carries {field}, so a run "
                          "that produced nothing cannot say which nothing")


@unittest.skipIf(not RUN_STEP.is_file(), "run screen not built")
class TestTheScreenBranchesOnAllThree(unittest.TestCase):

    def setUp(self):
        self.source = RUN_STEP.read_text(encoding="utf-8")

    def test_finished_is_not_a_single_headline(self):
        """
        The regression, stated plainly: a bare `done ? 'Finished'` is the bug.
        """
        self.assertNotIn("done ? 'Finished'", self.source)
        self.assertIn("function outcome(", self.source)

    def test_each_zero_case_has_its_own_headline(self):
        block = self.source[self.source.index("function outcome("):]
        block = block[:block.index("function Progress(")]
        for headline in ("No jobs found",
                         "none matched you well enough",
                         "no resumes were written"):
            self.assertIn(headline, block,
                          f"the {headline!r} case lost its own wording and now "
                          "shares one with another cause")

    def test_the_two_actionable_cases_say_what_to_do(self):
        """
        Advice is the difference between a diagnosis and a dead end. Two of
        the three zero cases are the user's to fix, so both name the screen
        they would fix it on; the third says plainly that it is not them.
        """
        block = self.source[self.source.index("function outcome("):]
        block = block[:block.index("function Progress(")]
        self.assertIn("Preferences screen", block)
        self.assertIn("target roles", block)
        self.assertIn("this machine rather than with your profile", block)

    def test_the_advice_is_rendered_and_not_just_computed(self):
        """
        The recurring bug in this codebase: computed and never read. An
        `advice` field nothing displays is worse than no field.
        """
        self.assertIn("outcome(status).advice", self.source)


if __name__ == "__main__":
    unittest.main()

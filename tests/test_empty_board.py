"""
An empty board says so and offers a run; a filtered one still blames the
filters (R123).

The list said "No jobs match these filters" whenever it was empty. On a first
visit that blamed filters nobody had set, and it offered no way to the run
that fills a board. Now there are three cases, and each claims only what is
known:
- nothing stored: "No jobs yet — run your first search", with a button to
  the wizard's Run step when there is a profile to run;
- jobs stored, none matching: the filter message with the stored count;
- counts not arrived: a neutral line, neither claim.

Source-level, since the web app has no test runner. It was also driven once
in Chromium against a hosted build (see R123).
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

BOARD = (ROOT / "web/src/components/Board.tsx").read_text(encoding="utf-8")
APP = (ROOT / "web/src/App.tsx").read_text(encoding="utf-8")
WIZARD = (ROOT / "web/src/components/Wizard.tsx").read_text(encoding="utf-8")


class TestTheThreeEmptyCases(unittest.TestCase):

    def test_nothing_stored_offers_the_first_run(self):
        at = BOARD.index("stats !== null && stats.total === 0")
        branch = BOARD[at:BOARD.index("No jobs match these filters.")]
        self.assertIn("No jobs yet — run your first search", branch)
        self.assertIn("onStartRun &&", branch)

    def test_the_filter_message_needs_known_counts(self):
        at = BOARD.index("No jobs match these filters.")
        self.assertIn("jobs.length === 0 && stats !== null ?", BOARD[at - 300:at])

    def test_unknown_counts_claim_neither(self):
        self.assertIn("No jobs to show.", BOARD)


class TestTheButtonOpensRun(unittest.TestCase):

    def test_app_opens_the_wizard_on_run_and_only_with_a_profile(self):
        self.assertIn("setWizardStep(STEPS.indexOf('Run'))", APP)
        self.assertRegex(APP, r"onStartRun=\{\s*profile\s*\?")
        self.assertIn("initialStep={wizardStep}", APP)

    def test_the_wizard_honours_it(self):
        self.assertIn("useState(initialStep ?? 0)", WIZARD)
        self.assertIn("'Run'", WIZARD)


if __name__ == "__main__":
    unittest.main()

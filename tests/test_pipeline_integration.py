"""
The pipeline driven the way the UI drives it (R25, R26).

Everything else here is a unit test. This one runs the whole orchestrator in
mock mode — zero API calls — through the same callbacks `app.py` passes, and
checks the results carry the fields the results screen renders.

It exists because the two bugs that would hurt most are both integration
bugs: a checkpoint falling through to `input()` and hanging the app, and a
result field the UI reads by a name generation does not write.
"""

import logging
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from agents.orchestrator import JobScoutOrchestrator, StageProgress  # noqa: E402

PROFILE = "yash_pathak"
FIXTURE = ROOT / "user_profiles" / f"{PROFILE}.json"


@unittest.skipUnless(FIXTURE.exists(), f"needs {PROFILE} profile; skipped on a clean clone")
class TestPipelineDrivenLikeTheUI(unittest.TestCase):
    """One mock run, shared across assertions — it is the slow test here."""

    @classmethod
    def setUpClass(cls):
        cls.output_dir = tempfile.mkdtemp()
        cls.ticks = []
        cls.checkpoints = []

        logging.disable(logging.CRITICAL)
        try:
            orchestrator = JobScoutOrchestrator(
                profile_name=PROFILE,
                mock_mode=True,                 # no API calls anywhere
                max_resumes=1,
                generate_pdf=False,             # no LaTeX needed
                output_dir=cls.output_dir,
                checkpoint=True,                # force the checkpoint path
            )
            cls.state = orchestrator.run(
                max_jobs=3,
                on_progress=cls.ticks.append,
                on_checkpoint=lambda stage, items: (
                    cls.checkpoints.append(stage) or True
                ),
            )
        finally:
            logging.disable(logging.NOTSET)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.output_dir, ignore_errors=True)

    def test_the_run_completes_and_returns_state(self):
        self.assertIsInstance(self.state, dict)

    def test_progress_ticks_arrive(self):
        self.assertTrue(self.ticks, "the UI would show an empty progress bar")
        self.assertTrue(all(isinstance(t, StageProgress) for t in self.ticks))

    def test_every_fraction_is_renderable(self):
        """st.progress rejects anything outside 0.0-1.0."""
        for tick in self.ticks:
            self.assertGreaterEqual(tick.fraction, 0.0)
            self.assertLessEqual(tick.fraction, 1.0)

    def test_checkpoints_are_answered_by_callback_not_stdin(self):
        # checkpoint=True with checkpoint_after_scoring defaulting to True
        # means the terminal prompt is one missing callback away. If this
        # list is empty, the run never asked — and a UI without a callback
        # would have hung on input() instead.
        self.assertTrue(self.checkpoints, "no checkpoint was routed through the callback")

    def test_results_carry_what_the_results_screen_renders(self):
        results = self.state.get("generation_results") or []
        self.assertTrue(results, "nothing to render")

        for item in results:
            for field in ("job", "status", "latex_path"):
                self.assertIn(field, item, f"app.py reads '{field}'")
            for field in ("title", "company"):
                self.assertIn(field, item["job"])

    def test_analysis_results_expose_the_score_the_ui_shows(self):
        for record in self.state.get("analysis_results") or []:
            self.assertIn("overall", record.get("score", {}))
            self.assertIn("id", record.get("job", {}))

    def test_generated_files_exist_where_the_state_says_they_do(self):
        """The download button reads these paths straight off the result."""
        for item in self.state.get("generation_results") or []:
            path = item.get("latex_path")
            if path:
                self.assertTrue(Path(path).exists(), f"missing generated file: {path}")


if __name__ == "__main__":
    unittest.main()

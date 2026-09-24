"""
A run's size is bounded by the server, not by the widget that asked (R110).

`POST /api/run` took `max_jobs` and `max_resumes` as given. React's input
stopped at 100 and Streamlit's sliders at 50 and 10, but only in the browser.
Each job is a scrape and an embedding. Each resume is LLM calls and one
`pdflatex` compile. `start_run`, the one entry point both UIs use, now refuses
anything outside `RUN_LIMITS` before a registry row exists, and the route
answers 400.

And `max_resumes=0` no longer means "the profile's number". The fallback
stays for the CLI without `--max-resumes` (`None`), and only for that.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from agents import orchestrator  # noqa: E402

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None

PROFILE = "priya_raghunathan"
REFUSED = {
    "max_jobs": (0, -1, 51, 500, True, "20", 2.5, None),
    "max_resumes": (0, -3, 11, 100, True, "3", None),
}


class _Home(unittest.TestCase):

    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, {"JOBSCOUT_HOME": self._home.name})
        self._env.start()
        profiles = Path(self._home.name) / "user_profiles"
        profiles.mkdir()
        shutil.copy(ROOT / "user_profiles" / f"{PROFILE}.json", profiles)

    def tearDown(self):
        self._env.stop()
        self._home.cleanup()

    def runs_recorded(self):
        return orchestrator.previous_runs(None) + orchestrator.active_runs(None)


class TestStartRun(_Home):

    def test_out_of_range_is_refused_before_anything_is_recorded(self):
        for field, values in REFUSED.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    with mock.patch("threading.Thread") as thread:
                        with self.assertRaises(orchestrator.RunSizeRefused) as caught:
                            orchestrator.start_run(None, PROFILE, **{field: value})
                    thread.assert_not_called()
                    self.assertIn(field, str(caught.exception))
        self.assertEqual(self.runs_recorded(), [])

    def test_the_bounds_themselves_are_accepted(self):
        for field, (lo, hi) in orchestrator.RUN_LIMITS.items():
            for value in (lo, hi):
                with self.subTest(field=field, value=value):
                    with mock.patch("threading.Thread"):
                        self.assertTrue(orchestrator.start_run(None, PROFILE,
                                                               **{field: value}))


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestTheRoute(_Home):

    def setUp(self):
        super().setUp()
        from api.main import app
        self.client = TestClient(app)

    def test_a_refused_size_is_a_400_that_names_the_field(self):
        # No thread patch here: the TestClient runs on threads itself. A
        # refused run never reaches one, and the registry says so.
        response = self.client.post("/api/run", json={
            "profile": PROFILE, "max_jobs": 500, "generate_pdf": False})
        self.assertEqual(response.status_code, 400)
        self.assertIn("max_jobs", response.json()["detail"])
        self.assertEqual(self.runs_recorded(), [])

    def test_health_carries_the_limits_start_run_enforces(self):
        limits = self.client.get("/api/health").json()["run_limits"]
        self.assertEqual(
            {f: (v["min"], v["max"]) for f, v in limits.items()},
            orchestrator.RUN_LIMITS)


class TestTheResumeCap(unittest.TestCase):
    """The profile's number is for the CLI's absent flag, not for a zero."""

    def cap(self, asked):
        run = orchestrator.JobScoutOrchestrator.__new__(
            orchestrator.JobScoutOrchestrator)
        run.max_resumes = asked
        run.profile = SimpleNamespace(
            agent_preferences=SimpleNamespace(max_jobs_to_generate=10))
        return run._resume_cap()

    def test_zero_means_zero(self):
        self.assertEqual(self.cap(0), 0)

    def test_a_given_number_is_used(self):
        self.assertEqual(self.cap(3), 3)

    def test_only_an_absent_one_falls_back_to_the_profile(self):
        self.assertEqual(self.cap(None), 10)


class TestTheScreensReadTheLimits(unittest.TestCase):
    """Source-level: both UIs take their bounds from the facade."""

    def test_streamlit_and_react_do_not_restate_them(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        run_step = (ROOT / "web/src/components/steps/RunStep.tsx").read_text(
            encoding="utf-8")
        self.assertIn('limits["max_jobs"]["max"]', app)
        self.assertIn('limits["max_resumes"]["max"]', app)
        self.assertIn("health?.run_limits.max_jobs", run_step)
        self.assertIn("health?.run_limits.max_resumes", run_step)
        self.assertNotIn("max={100}", run_step)


if __name__ == "__main__":
    unittest.main()

"""
A Gemini 503 that generation survives is not a Sentry event (R126).

Seen on the first live deploy: two "ServerError: This model is currently
experiencing high demand" events, tagged Unhandled on /api/run, with only
google-genai frames, from a run whose log shows the fallback from
gemini-3.5-flash to gemini-3.1-flash-lite working. The reporter was
sentry-sdk's own google-genai integration. It is enabled automatically when
google-genai is installed; it wraps `generate_content` and reports every
exception as unhandled before re-raising it, whatever the caller does next.
The one retry helper also logged "Max retries exceeded" at ERROR for a model
that the caller then moved past.

Each scenario runs in its own process (`tests/sentry_probe.py`), because the
SDK is process-global, with a capturing transport and a fake DSN: nothing is
sent anywhere. The two positive controls prove the capture is not blind.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent

try:
    import sentry_sdk  # noqa: F401
    import fastapi  # noqa: F401
    from google import genai  # noqa: F401
    MISSING = None
except ImportError as exc:  # pragma: no cover
    MISSING = str(exc)


@unittest.skipIf(MISSING, f"needs sentry-sdk, fastapi and google-genai: {MISSING}")
class TestWhatReachesSentry(unittest.TestCase):

    def probe(self, scenario):
        with tempfile.TemporaryDirectory() as home:
            Path(home, "user_profiles").mkdir()
            Path(home, "data", "master_resumes").mkdir(parents=True)
            shutil.copy(ROOT / "user_profiles" / "priya_raghunathan.json",
                        Path(home, "user_profiles"))
            shutil.copy(ROOT / "data" / "master_resumes" / "priya_raghunathan.tex",
                        Path(home, "data", "master_resumes"))
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("JOBSCOUT_", "SENTRY_"))}
            env.update(SENTRY_DSN="https://public@o0.ingest.sentry.io/0",
                       JOBSCOUT_HOME=home, JOBSCOUT_MODE="local")
            done = subprocess.run(
                [sys.executable, str(ROOT / "tests" / "sentry_probe.py"), scenario],
                capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=120)
        lines = [line for line in done.stdout.splitlines() if line.startswith("PROBE ")]
        self.assertTrue(lines, f"probe printed nothing:\n{done.stderr[-2000:]}")
        return json.loads(lines[-1][len("PROBE "):])

    def test_a_run_during_a_gemini_503_is_not_a_500_and_not_an_event(self):
        result = self.probe("api_run_503")
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["run_state"], "finished")
        self.assertEqual(result["events"], [])

    def test_a_handled_503_is_not_an_event(self):
        self.assertEqual(self.probe("handled_503")["events"], [])

    def test_a_models_retries_running_out_is_not_an_event(self):
        self.assertEqual(self.probe("handled_429")["events"], [])

    def test_every_model_exhausted_is_still_reported(self):
        events = self.probe("all_models_exhausted")["events"]
        self.assertEqual(len(events), 1)
        self.assertIn("Gemini tailoring failed", events[0]["message"])

    def test_a_request_that_fails_is_still_reported(self):
        result = self.probe("request_fails")
        self.assertEqual(result["status_code"], 500)
        self.assertEqual(len(result["events"]), 1, result["events"])


if __name__ == "__main__":
    unittest.main()

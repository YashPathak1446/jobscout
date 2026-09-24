"""
"Jobs enriched" counts jobs with a readable description (R125).

On the first live deploy the report said "Jobs enriched: 5" for a run in
which three of the five descriptions could not be read. It counted every job
enrichment returned. Now it counts readable ones, and names the rest, so the
difference is said, not subtracted in silence. The run record the run screen
reads counts the same way.
"""

import contextlib
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from agents import orchestrator  # noqa: E402

ENRICHED = ([{"scraped_successfully": True}] * 2
            + [{"scraped_successfully": False}] * 3)


class TestTheReport(unittest.TestCase):

    def report(self, enriched):
        run = orchestrator.JobScoutOrchestrator.__new__(
            orchestrator.JobScoutOrchestrator)
        run.profile = SimpleNamespace(personal_info=SimpleNamespace(name="Priya"))
        run.output_path = Path("outputs")
        run.state = {"discovered_jobs": [{}] * 5, "enriched_jobs": enriched,
                     "analysis_results": [], "scoring": None,
                     "generation_results": []}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            run._print_final_report()
        return [line.strip() for line in out.getvalue().splitlines()
                if "Jobs enriched" in line]

    def test_readable_jobs_are_counted_and_the_rest_named(self):
        self.assertEqual(self.report(ENRICHED),
                         ["Jobs enriched: 2 (3 more kept without a readable description)"])

    def test_all_readable_says_nothing_extra(self):
        self.assertEqual(self.report(ENRICHED[:2]), ["Jobs enriched: 2"])


class TestTheRunRecord(unittest.TestCase):

    def test_the_record_counts_readable_jobs(self):
        from tests.fixture_home import fixture_home

        class StubPipeline:
            profile = None

            def __init__(self, **kwargs):
                pass

            def run(self, **kwargs):
                return {"discovered_jobs": [{}] * 5, "enriched_jobs": ENRICHED}

        with fixture_home("priya_raghunathan"), \
                mock.patch.object(orchestrator, "JobScoutOrchestrator", StubPipeline):
            run_id = orchestrator.start_run(None, "priya_raghunathan")
            import threading
            import time
            deadline = time.monotonic() + 20
            status = None
            while time.monotonic() < deadline:
                status = orchestrator.run_status(None, run_id)
                if status and not status["active"]:
                    break
                time.sleep(0.02)
            for thread in threading.enumerate():
                if thread.name.endswith(run_id):
                    thread.join(20)
        self.assertEqual(status["result"]["enriched"], 2)
        self.assertEqual(status["result"]["discovered"], 5)


if __name__ == "__main__":
    unittest.main()

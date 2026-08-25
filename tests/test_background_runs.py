"""
Runs that outlive the tab that started them (R51).

R33 decided runs are background jobs, and the reason is narrow: the pipeline
takes minutes, it used to happen inside the request that asked for it, and a
browser reload therefore lost the progress bar and any way of knowing whether
the work was still going.

The guarantee worth testing is not "a thread was started" — it is that **the
answer comes from disk**. Anything held in a session survives exactly as badly
as the thing it replaced, so every test here throws away its handle on the run
and asks the registry cold.
"""

import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.jobs.run_registry import RunRegistry  # noqa: E402


class _RegistryTest(unittest.TestCase):

    def setUp(self):
        self.path = ROOT / "data" / "_runs_test.db"
        self.path.unlink(missing_ok=True)
        self.registry = RunRegistry(self.path)

    def tearDown(self):
        self.registry.close()
        self.path.unlink(missing_ok=True)


class TestARunIsFoundWithoutItsSession(_RegistryTest):
    """The reload case, which is the whole point."""

    def test_a_fresh_reader_sees_a_run_it_never_started(self):
        run_id = self.registry.create("jane")
        self.registry.progress(run_id, "discovery", 3, 20, "searching")

        # A different connection entirely — the browser has reloaded and this
        # process knows nothing but the database file.
        with RunRegistry(self.path) as elsewhere:
            found = elsewhere.get(run_id)

        self.assertEqual(found["stage"], "discovery")
        self.assertEqual(found["done"], 3)

    def test_active_runs_are_discoverable_with_no_id_at_all(self):
        """A reloaded tab does not even remember the id."""
        self.registry.create("jane")
        with RunRegistry(self.path) as elsewhere:
            self.assertEqual(len(elsewhere.active()), 1)

    def test_a_finished_run_is_no_longer_active(self):
        run_id = self.registry.create("jane")
        self.registry.finish(run_id, {"valid": 2})
        self.assertEqual(self.registry.active(), [])
        self.assertFalse(self.registry.get(run_id)["active"])

    def test_an_unknown_id_is_none_rather_than_an_error(self):
        """A stale bookmark should return the user to a Run button."""
        self.assertIsNone(self.registry.get("nope"))


class TestProgressIsReadable(_RegistryTest):

    def test_a_tick_updates_the_fraction(self):
        run_id = self.registry.create("jane")
        self.registry.progress(run_id, "analysis", 5, 20)
        self.assertAlmostEqual(self.registry.get(run_id)["fraction"], 0.25)

    def test_an_unknown_total_does_not_divide_by_zero(self):
        """Discovery cannot know its size up front (R26)."""
        run_id = self.registry.create("jane")
        self.registry.progress(run_id, "discovery", 0, 0, "searching")
        self.assertEqual(self.registry.get(run_id)["fraction"], 0.0)

    def test_the_first_tick_moves_it_out_of_queued(self):
        run_id = self.registry.create("jane")
        self.assertEqual(self.registry.get(run_id)["state"], "queued")
        self.registry.progress(run_id, "discovery")
        self.assertEqual(self.registry.get(run_id)["state"], "running")


class TestOutcomes(_RegistryTest):

    def test_a_finished_run_keeps_its_summary(self):
        run_id = self.registry.create("jane")
        self.registry.finish(run_id, {"valid": 3, "analysed": 20})
        self.assertEqual(self.registry.get(run_id)["result"]["valid"], 3)

    def test_a_run_that_generated_nothing_still_finished(self):
        """Zero resumes is a result, not an error."""
        run_id = self.registry.create("jane")
        self.registry.finish(run_id, {"valid": 0})
        self.assertEqual(self.registry.get(run_id)["state"], "finished")

    def test_a_failure_keeps_its_reason(self):
        run_id = self.registry.create("jane")
        self.registry.fail(run_id, "ProfileLoadError: countries required")
        found = self.registry.get(run_id)
        self.assertEqual(found["state"], "failed")
        self.assertIn("countries", found["error"])

    def test_the_degradation_reason_survives_the_run(self):
        """
        R47 put "your bullets were used because X" on the result. A background
        run has to carry it out too, or a reloaded page cannot say why.
        """
        run_id = self.registry.create("jane")
        self.registry.finish(run_id, {"degraded": ["Gemini could not be reached"]})
        self.assertEqual(self.registry.get(run_id)["result"]["degraded"],
                         ["Gemini could not be reached"])


class TestWrittenFromOneThreadReadFromAnother(_RegistryTest):
    """
    The worker writes while the request thread reads. sqlite3 refuses
    cross-thread use by default, which would surface as a run that appears to
    hang the moment anyone looked at it.
    """

    def test_a_worker_thread_can_write_while_the_main_thread_reads(self):
        run_id = self.registry.create("jane")
        errors = []

        def worker():
            try:
                for i in range(20):
                    self.registry.progress(run_id, "analysis", i, 20)
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=worker)
        thread.start()
        for _ in range(20):
            self.registry.get(run_id)
            time.sleep(0.005)
        thread.join(timeout=10)

        self.assertEqual(errors, [])
        self.assertEqual(self.registry.get(run_id)["done"], 19)


class TestTheFacadesEndToEnd(unittest.TestCase):
    """The functions the UI actually calls."""

    def setUp(self):
        import tools.jobs.run_registry as module
        self.path = ROOT / "data" / "_runs_facade_test.db"
        self.path.unlink(missing_ok=True)
        self._real = module.DEFAULT_DB
        module.DEFAULT_DB = self.path

    def tearDown(self):
        import tools.jobs.run_registry as module
        module.DEFAULT_DB = self._real
        self.path.unlink(missing_ok=True)

    def test_a_started_run_is_visible_to_the_facades(self):
        from agents.orchestrator import active_runs, recent_runs, run_status

        with RunRegistry(self.path) as registry:
            run_id = registry.create("jane")
            registry.progress(run_id, "discovery", 1, 10)

        self.assertEqual(run_status(run_id)["stage"], "discovery")
        self.assertEqual(len(active_runs()), 1)
        self.assertEqual(len(recent_runs()), 1)

    def test_run_status_of_nothing_is_none(self):
        from agents.orchestrator import run_status
        self.assertIsNone(run_status("nope"))


if __name__ == "__main__":
    unittest.main()

"""
One run per user, and no run that nothing is doing (R120, pilot plan A10).

Two things the pilot could not ship without:

- **A second start is refused while a run is going.** Five friends in one
  process under `--workers 1` is already five pipelines on one machine. The
  check is in `start_run`, the one entry point both UIs share, and it is one
  SQLite transaction, so two racing requests cannot both get through.
- **A run whose worker is gone is failed, with a reason.** A deploy kills
  every in-flight thread and leaves its row `queued`/`running` for good, which
  parks the run screen, and since the rule above, refuses the next run too.
  Q49 has the rest. The API reaps at startup, and every listing reaps.

Every test asks the registry cold, from disk, as `test_background_runs` does.
"""

import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from agents import orchestrator  # noqa: E402
from tools.jobs import run_registry  # noqa: E402
from tools.jobs.run_registry import RunAlreadyActive, RunRegistry  # noqa: E402

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None

PROFILE = "priya_raghunathan"
ANOTHER_PROCESS = "4242-deadbeef"


class _HeldPipeline:
    """A pipeline that runs until the test lets it go."""

    release = None

    def __init__(self, **kwargs):
        self.profile = None

    def run(self, **kwargs):
        _HeldPipeline.release.wait(20)
        return {}


class _Home(unittest.TestCase):

    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self.home = Path(self._home.name)
        self._env = mock.patch.dict(os.environ, {"JOBSCOUT_HOME": self._home.name})
        self._env.start()
        profiles = self.home / "user_profiles"
        profiles.mkdir()
        shutil.copy(ROOT / "user_profiles" / f"{PROFILE}.json", profiles)
        _HeldPipeline.release = threading.Event()
        self._pipeline = mock.patch.object(orchestrator, "JobScoutOrchestrator",
                                           _HeldPipeline)
        self._pipeline.start()

    def tearDown(self):
        _HeldPipeline.release.set()
        for thread in threading.enumerate():
            if thread.name.startswith("jobscout-run-"):
                thread.join(20)
        self._pipeline.stop()
        self._env.stop()
        self._home.cleanup()

    def row(self, run_id, user_id=None):
        with RunRegistry(run_registry.db_path(user_id)) as registry:
            return registry.get(run_id)

    def dead_row(self, user_id=None, *, seconds_silent=3600, owner=ANOTHER_PROCESS):
        """A row a process that no longer exists left `running`."""
        with RunRegistry(run_registry.db_path(user_id)) as registry:
            run_id = registry.claim(PROFILE, owner)
            registry.progress(run_id, "discovery", 0, 0, "searching")
            then = (datetime.now(timezone.utc)
                    - timedelta(seconds=seconds_silent)).isoformat()
            registry._db.execute(
                "UPDATE runs SET heartbeat_at=?, updated_at=? WHERE id=?",
                (then, then, run_id))
            registry._db.commit()
        return run_id

    def wait(self, run_id, seconds=20):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            run = self.row(run_id)
            if run and not run["active"]:
                return run
            time.sleep(0.02)
        self.fail(f"run {run_id} did not end in {seconds}s")


class TestOneRunPerUser(_Home):

    def test_a_second_concurrent_start_is_refused(self):
        first = orchestrator.start_run(None, PROFILE, generate_pdf=False)

        with self.assertRaises(orchestrator.RunInProgress) as refused:
            orchestrator.start_run(None, PROFILE, generate_pdf=False)

        self.assertIn("already have a run in progress", str(refused.exception))
        # Refused before a row: the registry holds the first run and only it.
        self.assertEqual([run["id"] for run in orchestrator.active_runs(None)],
                         [first])
        self.assertEqual(self.row(first)["state"], "queued")

    def test_a_different_profile_is_still_the_same_user(self):
        orchestrator.start_run(None, PROFILE, generate_pdf=False)
        with self.assertRaises(orchestrator.RunInProgress):
            orchestrator.start_run(None, "rohan_deshmukh", generate_pdf=False)

    def test_once_the_first_ends_the_next_starts(self):
        first = orchestrator.start_run(None, PROFILE, generate_pdf=False)
        _HeldPipeline.release.set()
        self.assertEqual(self.wait(first)["state"], "finished")

        second = orchestrator.start_run(None, PROFILE, generate_pdf=False)
        self.assertNotEqual(first, second)

    def test_another_users_run_does_not_block_mine(self):
        orchestrator.start_run("alice", PROFILE, generate_pdf=False)
        orchestrator.start_run("bob", PROFILE, generate_pdf=False)

    def test_two_racing_claims_admit_exactly_one(self):
        """The check and the insert are one transaction, across connections."""
        path = run_registry.db_path(None)
        RunRegistry(path).close()
        gate = threading.Barrier(8)
        won, lost = [], []

        def racer():
            with RunRegistry(path) as registry:
                gate.wait()
                try:
                    won.append(registry.claim(PROFILE, ANOTHER_PROCESS))
                except RunAlreadyActive:
                    lost.append(True)

        racers = [threading.Thread(target=racer) for _ in range(8)]
        for thread in racers:
            thread.start()
        for thread in racers:
            thread.join(20)
        self.assertEqual((len(won), len(lost)), (1, 7))


class TestAStaleRunIsReaped(_Home):

    def test_a_stale_running_record_is_reaped_and_a_new_run_starts(self):
        stale = self.dead_row()

        fresh = orchestrator.start_run(None, PROFILE, generate_pdf=False)

        reaped = self.row(stale)
        self.assertEqual(reaped["state"], "failed")
        self.assertEqual(reaped["error"], "interrupted — the server restarted")
        self.assertTrue(reaped["finished_at"])
        self.assertEqual([run["id"] for run in orchestrator.active_runs(None)],
                         [fresh])

    def test_listing_reaps(self):
        stale = self.dead_row()
        self.assertEqual(orchestrator.active_runs(None), [])
        self.assertEqual(self.row(stale)["state"], "failed")

    def test_recent_runs_reaps_too(self):
        stale = self.dead_row()
        [run] = orchestrator.recent_runs(None)
        self.assertEqual((run["id"], run["state"]), (stale, "failed"))

    def test_another_live_process_keeps_its_run(self):
        """
        Local mode: Streamlit and the API are two processes on one runs.db.
        A run whose heartbeat is recent is somebody's live run, not ours to
        fail, and it still counts against starting another.
        """
        live = self.dead_row(seconds_silent=5)
        self.assertEqual([run["id"] for run in orchestrator.active_runs(None)], [live])
        with self.assertRaises(orchestrator.RunInProgress):
            orchestrator.start_run(None, PROFILE, generate_pdf=False)

    def test_a_row_of_ours_with_no_thread_is_reaped_at_once(self):
        """Owned by this process, and no worker of ours on it: dead now."""
        orphan = self.dead_row(seconds_silent=0, owner=orchestrator._PROCESS)
        orchestrator.active_runs(None)
        self.assertEqual(self.row(orphan)["error"],
                         "interrupted — the run stopped without reporting")

    def test_our_own_running_worker_is_never_reaped(self):
        run_id = orchestrator.start_run(None, PROFILE, generate_pdf=False)
        with mock.patch.object(orchestrator, "RUN_STALE_SECONDS", -1):
            self.assertEqual([run["id"] for run in orchestrator.active_runs(None)],
                             [run_id])

    def test_a_reaped_run_stays_failed_when_its_worker_speaks(self):
        """Terminal is terminal: a late tick must not flip it back (Q49)."""
        stale = self.dead_row()
        orchestrator.active_runs(None)
        with RunRegistry(run_registry.db_path(None)) as registry:
            registry.progress(stale, "analysis", 1, 2, "late")
            registry.heartbeat(stale)
            registry.finish(stale, {"generated": 1})
            registry.fail(stale, "a different reason")
        row = self.row(stale)
        self.assertEqual((row["state"], row["error"]),
                         ("failed", "interrupted — the server restarted"))

    def test_a_runs_db_from_before_the_columns_is_migrated(self):
        import sqlite3
        path = run_registry.db_path(None)
        path.parent.mkdir(parents=True, exist_ok=True)
        old = sqlite3.connect(path)
        old.executescript(run_registry.SCHEMA.replace(
            ",\n    owner       TEXT,\n    heartbeat_at TEXT", ""))
        old.execute("INSERT INTO runs (id, profile, state, started_at, updated_at)"
                    " VALUES ('old', 'p', 'running', '2026-09-01T00:00:00+00:00',"
                    " '2026-09-01T00:00:00+00:00')")
        old.commit()
        old.close()

        self.assertEqual(orchestrator.active_runs(None), [])
        self.assertEqual(self.row("old")["state"], "failed")


class TestTheStartupSweep(_Home):

    def test_hosted_it_walks_every_partition_and_spares_no_foreign_run(self):
        from tests.signed_in import hosted

        # Five seconds silent: alive by heartbeat, dead because at boot in
        # hosted mode nothing else can be running a run.
        rows = {user: self.dead_row(user, seconds_silent=5)
                for user in (None, "alice", "bob")}
        (self.home / "users" / "carol").mkdir(parents=True)

        with hosted(self.home):
            self.assertEqual(orchestrator.reap_stale_runs(), 3)

        for user, run_id in rows.items():
            self.assertEqual(self.row(run_id, user)["state"], "failed", user)
        # Read, never created: carol had no runs.db and still has none.
        self.assertFalse(run_registry.db_path("carol").exists())

    def test_one_unreadable_registry_does_not_stop_the_rest(self):
        dead = self.dead_row("alice")
        broken = run_registry.db_path("bob")
        broken.parent.mkdir(parents=True)
        broken.write_bytes(b"not a database, and not recoverable")
        with self.assertLogs("agents.orchestrator", "ERROR"):
            self.assertEqual(orchestrator.reap_stale_runs(), 1)
        self.assertEqual(self.row(dead, "alice")["state"], "failed")

    def test_local_it_judges_by_heartbeat(self):
        alive = self.dead_row(seconds_silent=5)
        dead = self.dead_row("alice")
        self.assertEqual(orchestrator.reap_stale_runs(), 1)
        self.assertEqual(self.row(alive)["state"], "running")
        self.assertEqual(self.row(dead, "alice")["state"], "failed")


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestTheRoute(_Home):

    def test_a_second_start_is_a_409_that_says_why(self):
        from api.main import app
        client = TestClient(app)
        body = {"profile": PROFILE, "generate_pdf": False}

        self.assertEqual(client.post("/api/run", json=body).status_code, 200)
        second = client.post("/api/run", json=body)

        self.assertEqual(second.status_code, 409)
        self.assertIn("already have a run in progress", second.json()["detail"])

    def test_the_app_sweeps_when_it_starts(self):
        from api.main import app
        stale = self.dead_row()
        with TestClient(app):
            pass
        self.assertEqual(self.row(stale)["state"], "failed")


class TestReactShowsTheRefusal(unittest.TestCase):
    """Source-level, as `test_run_limits` reads the screens."""

    def test_the_run_screen_handles_a_409(self):
        run_step = (ROOT / "web/src/components/steps/RunStep.tsx").read_text(
            encoding="utf-8")
        api = (ROOT / "web/src/lib/api.ts").read_text(encoding="utf-8")
        self.assertIn("class ApiError", api)
        self.assertIn("status === 409", run_step)


if __name__ == "__main__":
    unittest.main()

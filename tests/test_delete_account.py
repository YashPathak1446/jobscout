"""
Deleting an account (pilot plan A6): nothing of the person survives, nothing of
anyone else goes, and there is one path that does it.

`test_no_byte_of_a_deleted_user_survives` is the plan's closing test. User B
is a real account with a real run behind it — invited, redeemed, signed in
through the route, a `--mock` pipeline started through `POST /api/run`, a job
marked applied — then deleted through `DELETE /api/account`. The whole data
home is then walked (`tests/residue.py`) for B's user id, B's email, and the
name on B's profile, in every path and every file's bytes. It fails on the
fifth store, because it asks the disk rather than a list of stores.

The walker proves itself first: before the deletion it must find B in the
account store's bytes and in B's tree, or a clean result afterwards would say
nothing.

User A is Rohan and user B is Priya, so neither's name can turn up in the
other's files and read as residue.
"""

import hashlib
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tests.residue import residue, spellings  # noqa: E402
from tests.signed_in import client, hosted, make_account  # noqa: E402

A_EMAIL, A_PROFILE = "rohan@example.com", "rohan_deshmukh"
B_EMAIL, B_PROFILE = "priya@example.com", "priya_raghunathan"


JOB = "https://boards.example.com/jobs/1"


class _Listing:
    """What discovery hands the store. Only the fields `record` reads."""

    def __init__(self, url):
        self.apply_url = self.id = url
        self.title = "Staff Engineer"
        self.company = "Example"
        self.location = "Boston, MA"
        self.source = "test"
        self.full_jd = "A Python role."


def _place(home: Path, profile: str) -> None:
    """A profile and its master resume, where the user's data lives."""
    (home / "user_profiles").mkdir(parents=True, exist_ok=True)
    (home / "data" / "master_resumes").mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "user_profiles" / f"{profile}.json",
                home / "user_profiles" / f"{profile}.json")
    shutil.copy(ROOT / "data" / "master_resumes" / f"{profile}.tex",
                home / "data" / "master_resumes" / f"{profile}.tex")


def _tree_digest(root: Path) -> dict:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def _mock_pipeline():
    """
    `start_run` has no mock switch, so the orchestrator it builds is swapped
    for one that is `--mock` with the `none` rung: zero API calls, and the
    registry, the worker thread and the output tree are all the real ones.
    """
    import agents.orchestrator as orchestrator

    real = orchestrator.JobScoutOrchestrator

    def mocked(*args, **kwargs):
        kwargs.update(mock_mode=True, backend="none")
        return real(*args, **kwargs)

    return mock.patch.object(orchestrator, "JobScoutOrchestrator", mocked)


class _Instance(unittest.TestCase):
    """A hosted instance with two accounts, each with a profile in place."""

    def setUp(self):
        from tools import paths

        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self._env = hosted(self.home)
        self._env.__enter__()
        import api.main as main
        self.main = main

        self.a = make_account(A_EMAIL)
        self.b = make_account(B_EMAIL)
        self.a_home, self.b_home = paths.user_home(self.a), paths.user_home(self.b)
        _place(self.a_home, A_PROFILE)
        _place(self.b_home, B_PROFILE)

    def tearDown(self):
        self._env.__exit__(None, None, None)
        self._tmp.cleanup()

    def _run(self, signed_in, profile):
        """A whole `--mock` run through the route, waited for."""
        with _mock_pipeline():
            response = signed_in.post("/api/run", json={
                "profile": profile, "generate_pdf": False, "max_jobs": 5,
                "max_resumes": 2})
            self.assertEqual(response.status_code, 200, response.text)
            run_id = response.json()["run_id"]
            deadline = time.time() + 60
            while time.time() < deadline:
                run = signed_in.get(f"/api/run/{run_id}").json()
                if not run["active"]:
                    break
                time.sleep(0.05)
        self.assertEqual(run["state"], "finished", run.get("error"))
        return run


class TestNoByteOfADeletedUserSurvives(_Instance):

    def setUp(self):
        super().setUp()
        self.owner_a = client(self.main.app, email=A_EMAIL)
        self.owner_b = client(self.main.app, email=B_EMAIL)
        self._run(self.owner_a, A_PROFILE)
        run = self._run(self.owner_b, B_PROFILE)
        self.assertGreater(run["result"]["generated"], 0,
                           "B's run wrote no resume, so the walk has less to find")
        # `--mock` discovery does not record to the board, so B's board row is
        # recorded as discovery would, and B marks it applied through the route.
        from tools.jobs.job_store import JobStore
        from tools.jobs.job_store import db_path as jobs_db

        store = JobStore(jobs_db(self.b))
        try:
            store.record([_Listing(JOB)])
        finally:
            store.close()
        self.assertEqual(self.owner_b.post("/api/job/status", json={
            "url": JOB, "status": "applied"}).status_code, 200)
        # Personal data from the profile, not only the account.
        self.needles = [self.b, B_EMAIL, *spellings("Priya Raghunathan"),
                        "priya.raghunathan@example.com"]

    def test_no_byte_of_a_deleted_user_survives(self):
        before = residue(self.home, self.needles)
        # The walker proves itself: it must see B in the global store and in
        # B's tree, or finding nothing afterwards is not evidence.
        self.assertTrue(any(hit.startswith("data/accounts.db:") for hit in before),
                        before)
        self.assertTrue(any(hit.startswith(f"users/{self.b}/outputs/")
                            for hit in before), before)
        files_before = sum(1 for p in self.b_home.rglob("*") if p.is_file())
        a_before = _tree_digest(self.a_home)

        response = self.owner_b.delete("/api/account")

        self.assertEqual(response.status_code, 200, response.text)
        removed = response.json()
        self.assertEqual(removed["account"], 1)
        self.assertEqual(removed["files"], files_before,
                         "the count returned is not what was removed")
        self.assertEqual(sum(removed["areas"].values()), removed["files"])
        self.assertIn("max-age=0", response.headers["set-cookie"].lower())

        left = residue(self.home, self.needles)
        self.assertEqual(left, [], "a deleted user survives here:\n" + "\n".join(left[:40]))
        self.assertFalse(self.b_home.exists())

        # Nothing of A's went, and A still gets in.
        self.assertEqual(_tree_digest(self.a_home), a_before)
        self.assertEqual(self.owner_a.get("/api/board").status_code, 200)
        self.assertNotEqual(residue(self.home, [self.a]), [],
                            "the walker cannot find the user it was not asked to "
                            "forget, so its silence about B means nothing")

    def test_the_deleted_session_is_refused_and_the_email_is_free(self):
        stolen = self.owner_b.cookies.get("jobscout_session")
        self.owner_b.delete("/api/account")
        replay = client(self.main.app)
        replay.cookies.set("jobscout_session", stolen)
        self.assertEqual(replay.get("/api/board").status_code, 401)
        # Signing in names nobody, and the email can be invited afresh.
        again = client(self.main.app).post(
            "/api/session", json={"email": B_EMAIL,
                                  "passphrase": "correct horse battery staple"})
        self.assertEqual(again.status_code, 401)
        self.assertNotEqual(make_account(B_EMAIL), self.b)


class TestTheDeletePath(_Instance):

    def test_a_live_run_refuses_the_deletion_and_deletes_nothing(self):
        from tools.jobs.run_registry import RunRegistry
        from tools.jobs.run_registry import db_path as runs_db

        registry = RunRegistry(runs_db(self.b))
        try:
            registry.create(B_PROFILE)
        finally:
            registry.close()
        signed_in = client(self.main.app, email=B_EMAIL)
        before = _tree_digest(self.b_home)

        response = signed_in.delete("/api/account")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(_tree_digest(self.b_home), before)
        self.assertEqual(signed_in.get("/api/board").status_code, 200)

    def test_the_operator_can_override_a_run_a_crash_left_running(self):
        from agents.orchestrator import delete_user_data
        from tools.jobs.run_registry import RunRegistry
        from tools.jobs.run_registry import db_path as runs_db

        registry = RunRegistry(runs_db(self.b))
        try:
            registry.create(B_PROFILE)
        finally:
            registry.close()
        removed = delete_user_data(self.b, ignore_active_runs=True)
        self.assertEqual(removed["account"], 1)
        self.assertFalse(self.b_home.exists())

    def test_nobody_is_zero_and_creates_nothing(self):
        from agents.orchestrator import delete_user_data
        from tools import paths

        removed = delete_user_data("0000000000000000")
        self.assertEqual((removed["account"], removed["files"]), (0, 0))
        self.assertFalse(paths.user_home("0000000000000000").exists())

    def test_a_half_finished_deletion_is_finished_by_the_next_one(self):
        """The row went, the tree did not: the second call removes the tree."""
        from agents.orchestrator import delete_user_data
        from tools import accounts

        accounts.delete(self.b)
        removed = delete_user_data(self.b)
        self.assertEqual(removed["account"], 0)
        self.assertGreater(removed["files"], 0)
        self.assertFalse(self.b_home.exists())

    def test_the_unscoped_home_is_never_a_user_to_delete(self):
        """In a checkout `user_home(None)` is the repository."""
        from agents.orchestrator import delete_user_data
        from tools import paths

        marker = self.home / "keep.txt"
        marker.write_text("the checkout", encoding="utf-8")
        for call in (lambda: delete_user_data(None),
                     lambda: paths.remove_user_home(None)):
            with self.assertRaises(ValueError):
                call()
        for bad in ("..", "../x", "", "A"):
            with self.subTest(bad), self.assertRaises(ValueError):
                delete_user_data(bad)
        self.assertTrue(marker.exists())
        self.assertTrue(self.a_home.exists() and self.b_home.exists())

    def test_local_mode_has_no_account_to_delete(self):
        """Local mode's `_caller` is `None`: the route must 404, not delete."""
        from fastapi.testclient import TestClient

        from tools import accounts

        marker = self.home / "keep.txt"
        marker.write_text("the checkout", encoding="utf-8")
        with mock.patch.dict(os.environ):
            os.environ.pop(accounts.MODE_ENV)
            response = TestClient(self.main.app, client=("127.0.0.1", 40000)
                                  ).delete("/api/account")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(marker.exists())


if __name__ == "__main__":
    unittest.main()

"""
A hosted account holds one profile (R109).

The board has no profile column: it is the user's, and every score, gate
verdict and applied/rejected mark on it was made for one resume. A second
profile in the same partition would be ranked against the first one's scores.
So a scoped `create_profile` refuses a second name, replacing the one it has
still works, and the unscoped layout (CLI, local mode) keeps any number.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts import init_profile  # noqa: E402
from tools import paths  # noqa: E402

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None

PRIYA = ROOT / "data" / "master_resumes" / "priya_raghunathan.tex"


class _Home(unittest.TestCase):

    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, {paths.HOME_ENV: self._home.name})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._home.cleanup()

    def resume_for(self, user_id) -> Path:
        """Priya's resume, placed in this user's own home as an upload is."""
        where = paths.user_home(user_id) / "data" / "master_resumes"
        where.mkdir(parents=True, exist_ok=True)
        return Path(shutil.copy(PRIYA, where / "resume.tex"))


class TestTheLimit(_Home):

    def test_one_when_scoped_and_none_unscoped(self):
        self.assertEqual(init_profile.profile_limit("alice"), 1)
        self.assertIsNone(init_profile.profile_limit(None))

    def test_a_scoped_account_cannot_add_a_second_name(self):
        resume = self.resume_for("alice")
        init_profile.create_profile("alice", resume, "first")
        with self.assertRaises(init_profile.ProfileLimit) as caught:
            init_profile.create_profile("alice", resume, "second")
        self.assertIn("first", str(caught.exception))
        self.assertFalse((init_profile.profiles_dir("alice") / "second.json").exists())

    def test_replacing_the_one_it_has_still_works(self):
        resume = self.resume_for("alice")
        init_profile.create_profile("alice", resume, "first")
        init_profile.create_profile("alice", resume, "first", force=True)
        # The R30 backup beside it is not a second profile.
        self.assertEqual(init_profile.list_available_profiles(user_id="alice"),
                         ["first"])

    def test_the_limit_is_per_account(self):
        init_profile.create_profile("alice", self.resume_for("alice"), "mine")
        init_profile.create_profile("bob", self.resume_for("bob"), "mine")

    def test_unscoped_keeps_any_number(self):
        resume = self.resume_for(None)
        init_profile.create_profile(None, resume, "first")
        init_profile.create_profile(None, resume, "second")
        self.assertEqual(init_profile.list_available_profiles(user_id=None),
                         ["first", "second"])


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestTheApiInLocalMode(_Home):
    """Local mode is unscoped: no limit, and health says so as `null`."""

    def test_health_reports_no_limit(self):
        from api.main import app
        self.assertIsNone(TestClient(app).get("/api/health").json()["profile_limit"])


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestTheApiWhenHosted(unittest.TestCase):
    """Through the route, signed in: a second name is a 409 that says why."""

    def setUp(self):
        from tests.signed_in import client, hosted, make_account

        self._tmp = tempfile.TemporaryDirectory()
        self._env = hosted(self._tmp.name)
        self._env.__enter__()
        import api.main as main

        self.user = make_account("owner@example.com")
        where = paths.user_home(self.user) / "data" / "master_resumes"
        where.mkdir(parents=True)
        shutil.copy(PRIYA, where / "upload.tex")
        self.api = client(main.app, email="owner@example.com")

    def tearDown(self):
        self._env.__exit__(None, None, None)
        self._tmp.cleanup()

    def create(self, name, force=False):
        return self.api.post("/api/profile", json={
            "name": name, "filename": "upload.tex", "force": force})

    def test_health_says_one(self):
        self.assertEqual(self.api.get("/api/health").json()["profile_limit"], 1)

    def test_a_second_name_is_a_409_and_a_replace_is_not(self):
        self.assertEqual(self.create("mine").status_code, 200)
        second = self.create("another")
        self.assertEqual(second.status_code, 409)
        self.assertIn("mine", second.json()["detail"])
        self.assertEqual(self.create("mine", force=True).status_code, 200)
        self.assertEqual(self.api.get("/api/health").json()["profiles"], ["mine"])


class TestTheWizardReadsTheLimit(unittest.TestCase):
    """Source-level: no web test runner. The screen must not offer a name the
    server will refuse."""

    def test_the_resume_step_fixes_the_name_when_the_account_is_full(self):
        wizard = (ROOT / "web/src/components/Wizard.tsx").read_text(encoding="utf-8")
        step = (ROOT / "web/src/components/steps/ResumeStep.tsx").read_text(
            encoding="utf-8")
        self.assertIn("profileLimit={profileLimit}", wizard)
        self.assertIn("profiles.length >= profileLimit", step)
        self.assertIn("full ? profiles[0] : typedName", step)


if __name__ == "__main__":
    unittest.main()

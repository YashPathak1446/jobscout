"""
A profile name is a name, never a path (R111).

`_profile_file` joined the name as given, so `POST /api/profile` with a name
like `../../<id>/user_profiles/x` wrote a profile into another account's
partition. It was reproduced over HTTP, signed in, before this change. The
planted profile also counted against the victim's R109 limit, so they could
no longer create one of their own.

Both checks now sit in one resolver that the loader and the importer share:
the name pattern, then the resolved path inside the profiles folder.

In the same R, a generated resume's filename is capped in bytes, because
scraped titles are text of any length.
"""

import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.profile import profile_loader  # noqa: E402
from tools.profile.profile_loader import BadProfileName, profile_file  # noqa: E402

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None

PRIYA = ROOT / "data" / "master_resumes" / "priya_raghunathan.tex"
ACCEPTED = ("jane_doe", "a", "priya_raghunathan", "senior_real", "x" * 40, "user_2")
REFUSED = ("", "../x", "../../bob/user_profiles/evil", "a/b", "a\\b", "/abs",
           "Jane", "jane-doe", "a.b", "..", ".", "x" * 41, "a b", "a\x00b",
           "résumé", None, 7)


class TestTheResolver(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "user_profiles"

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_name_is_accepted(self):
        for name in ACCEPTED:
            with self.subTest(name=name):
                self.assertEqual(profile_file(name, self.dir), self.dir / f"{name}.json")

    def test_anything_else_is_refused(self):
        for name in REFUSED:
            with self.subTest(name=name):
                with self.assertRaises(BadProfileName):
                    profile_file(name, self.dir)

    def test_the_loader_goes_through_it(self):
        self.dir.mkdir()
        with self.assertRaises(BadProfileName):
            profile_loader.load_profile("../x", str(self.dir), user_id=None)

    def test_the_importer_goes_through_it_and_makes_nothing(self):
        from scripts import init_profile
        with mock.patch.dict(os.environ, {"JOBSCOUT_HOME": self._tmp.name}):
            with self.assertRaises(BadProfileName):
                init_profile.create_profile("alice", PRIYA, "../../bob/user_profiles/x")
        self.assertFalse((Path(self._tmp.name) / "users").exists(),
                         "a refused name left a directory behind")


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestOverHttpWhenHosted(unittest.TestCase):
    """The reproduction from the audit, now refused, and what it used to cost."""

    def setUp(self):
        from tests.signed_in import client, hosted, make_account
        from tools import paths

        self._tmp = tempfile.TemporaryDirectory()
        self._env = hosted(self._tmp.name)
        self._env.__enter__()
        import api.main as main
        self.main = main

        self.a = make_account("a@example.com")
        self.b = make_account("b@example.com")
        for user in (self.a, self.b):
            uploads = paths.user_home(user) / "data" / "master_resumes"
            uploads.mkdir(parents=True)
            shutil.copy(PRIYA, uploads / "upload.tex")
        self.as_a = client(main.app, email="a@example.com")
        self.as_b = client(main.app, email="b@example.com")
        self.b_profiles = paths.user_home(self.b) / "user_profiles"

    def tearDown(self):
        self._env.__exit__(None, None, None)
        self._tmp.cleanup()

    def create(self, who, name, force=False):
        return who.post("/api/profile", json={
            "name": name, "filename": "upload.tex", "force": force})

    def test_planting_a_profile_in_another_account_is_refused(self):
        response = self.create(self.as_a, f"../../{self.b}/user_profiles/planted")
        self.assertEqual(response.status_code, 400)
        self.assertIn("not a usable profile name", response.json()["detail"])
        self.assertEqual(self.main.available_profiles(self.b), [])
        self.assertEqual(self.main.available_profiles(self.a), [])

    def test_a_cannot_overwrite_bs_existing_profile(self):
        self.assertEqual(self.create(self.as_b, "mine").status_code, 200)
        before = (self.b_profiles / "mine.json").read_bytes()
        response = self.create(self.as_a, f"../../{self.b}/user_profiles/mine",
                               force=True)
        self.assertEqual(response.status_code, 400)
        self.assertEqual((self.b_profiles / "mine.json").read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.b_profiles.iterdir()),
                         ["mine.json"], "no backup or second file appeared")

    def test_b_can_still_create_their_own_afterwards(self):
        """The planted-profile lockout: B's R109 limit is still B's own."""
        self.create(self.as_a, f"../../{self.b}/user_profiles/planted")
        self.assertEqual(self.create(self.as_b, "mine").status_code, 200)
        self.assertEqual(self.main.available_profiles(self.b), ["mine"])

    def test_a_bad_name_on_the_other_profile_routes_is_a_404(self):
        for method, url, body in (
                ("GET", "/api/profile/..", None),
                ("GET", "/api/profile/Jane", None),
                ("PATCH", "/api/profile/a.b", {"updates": {}}),
                ("PUT", "/api/profile/a.b/components",
                 {"importance": {}, "triggers": {}})):
            with self.subTest(method=method, url=url):
                response = self.as_a.request(method, url, json=body)
                self.assertEqual(response.status_code, 404, response.text)


class TestTheScreensSayItFirst(unittest.TestCase):

    def test_react_holds_the_same_pattern(self):
        step = (ROOT / "web/src/components/steps/ResumeStep.tsx").read_text(
            encoding="utf-8")
        copied = re.search(r"const PROFILE_NAME = /\^(.+)\$/", step).group(1)
        self.assertEqual(copied, profile_loader.PROFILE_NAME.pattern)
        self.assertIn("!nameOk", step)

    def test_streamlit_asks_the_importer(self):
        from scripts.init_profile import profile_name_problem
        self.assertIsNone(profile_name_problem("jane_doe"))
        self.assertIn("jane_doe", profile_name_problem("Jane Doe"))
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("bool(name_problem)", app)


class TestTheResumeFilename(unittest.TestCase):

    def filename(self, company, title, url="https://x.test/1", person="Jane Doe"):
        from agents.generation_agent import GenerationAgent
        agent = GenerationAgent.__new__(GenerationAgent)
        agent.profile = SimpleNamespace(personal_info=SimpleNamespace(name=person))
        return agent._generate_filename(company, title, url)

    def test_a_long_scraped_title_is_capped_in_bytes(self):
        from agents.generation_agent import FILENAME_MAX_BYTES
        name = self.filename("日本" * 200, "日本 " * 200)
        readable, digest = name.rsplit("_", 1)
        self.assertLessEqual(len(readable.encode("utf-8")), FILENAME_MAX_BYTES)
        self.assertEqual(len(digest), 8)
        self.assertLess(len(f"{name}.tex".encode("utf-8")), 255)
        name.encode("utf-8").decode("utf-8")  # never cut inside a character

    def test_an_ordinary_name_is_unchanged(self):
        self.assertTrue(self.filename("Acme", "Software Engineer II")
                        .startswith("Jane_Doe_Acme_Software_Engineer_II_"))

    def test_path_characters_never_survive(self):
        name = self.filename("../../x", "a/b\\c")
        self.assertNotIn("/", name)
        self.assertNotIn("\\", name)
        self.assertNotIn("..", name)


if __name__ == "__main__":
    unittest.main()

"""
Per-route authorization on a hosted instance (pilot plan A5).

**Authorization here is by partition, not by predicate.** No route checks that
a thing "belongs" to its caller. Each reads the caller's own stores (A3), and
somebody else's job, run, file, upload or profile is simply not in them. So the
claim these tests make is not "B gets a 403 for A's job" — a 403 would confirm
the job exists — but:

1. **Not found, indistinguishably.** B naming A's identifier gets a 404 whose
   status and body are byte-identical to the answer for the same identifier
   once A's data is gone entirely. Compared against a real absence, not a
   made-up id, so a detail string that echoes the name cannot pass by
   coincidence.
2. **Not listed.** Every listing B reads leaves A's items out.
3. **Not touched.** B's writes aimed at A's identifiers change no byte under
   A's home.

Each probe has a **positive control**: signed in as A, the same request finds
the thing. Without it, a probe that 404s for every caller — a typo in the
fixture, a route that broke — would pass rule 1 while proving nothing.

The door is tested separately: every `/api` route outside `OPEN_ROUTES` must
depend on `_caller`, checked by walking the app's routes rather than by
reading a list somebody maintains, and an anonymous or forged cookie gets the
same 401 on all of them.
"""

import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    from fastapi.testclient import TestClient  # noqa: F401
except ImportError:  # pragma: no cover - fastapi is optional for the CLI
    TestClient = None

from tests.signed_in import client, hosted, make_account  # noqa: E402

PROFILE = "priya_raghunathan"
JOB = "https://boards.example.com/jobs/1"
A_EMAIL = "a@example.com"
B_EMAIL = "b@example.com"

# Who probes A's data. The mutation check for this file is setting this to
# A_EMAIL: every rule-1 and rule-2 test must then fail, because A *can* see
# A's data. If one still passes, it was not testing ownership.
STRANGER = B_EMAIL


class _Listing:
    """What discovery hands the store. Only the fields `record` reads."""

    def __init__(self, url):
        self.apply_url = url
        self.id = url
        self.title = "Staff Engineer"
        self.company = "Example"
        self.location = "Boston, MA"
        self.source = "test"
        self.full_jd = "A Python role."


def _tree_digest(root: Path) -> dict:
    return {path.relative_to(root).as_posix():
            hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def _api_routes(app):
    """(method, path, route) for every /api route an app declares."""
    from fastapi.routing import APIRoute

    for route in app.routes:
        if isinstance(route, APIRoute) and route.path.startswith("/api"):
            for method in sorted(route.methods):
                yield method, route.path, route


def _unguarded(app, caller, open_routes) -> list:
    """Routes that neither name their caller nor are declared open."""
    missing = []
    for method, path, route in _api_routes(app):
        if (method, path) in open_routes:
            continue
        calls = {dep.call for dep in route.dependant.dependencies}
        if caller not in calls:
            missing.append(f"{method} {path}")
    return missing


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestEveryApiRouteNamesItsCaller(unittest.TestCase):
    """The R80 closing move: a route added without the dependency fails here."""

    def test_every_api_route_names_its_caller(self):
        import api.main as main
        self.assertEqual(_unguarded(main.app, main._caller, main.OPEN_ROUTES), [],
                         "these routes serve data without asking whose")

    def test_the_open_list_names_only_routes_that_exist(self):
        import api.main as main
        declared = {(m, p) for m, p, _ in _api_routes(main.app)}
        self.assertEqual(sorted(main.OPEN_ROUTES - declared), [])

    def test_the_walk_catches_what_it_exists_to_catch(self):
        from fastapi import Depends, FastAPI

        import api.main as main

        toy = FastAPI()

        @toy.get("/api/forgot")
        def forgot():
            return {}

        @toy.get("/api/remembered")
        def remembered(user=Depends(main._caller)):
            return {}

        self.assertEqual(_unguarded(toy, main._caller, set()), ["GET /api/forgot"])


def _probe_url(path: str) -> str:
    return path.replace("{name}", "x").replace("{run_id}", "x")


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestTheDoor(unittest.TestCase):
    """Hosted: nobody reaches a guarded route without a session that names them."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env = hosted(self._tmp.name)
        self._env.__enter__()
        import api.main as main
        self.main = main
        self.user = make_account(A_EMAIL)

    def tearDown(self):
        self._env.__exit__(None, None, None)
        self._tmp.cleanup()

    def _guarded(self):
        return [(m, p) for m, p, _ in _api_routes(self.main.app)
                if (m, p) not in self.main.OPEN_ROUTES]

    def _answers(self, cookie):
        anonymous = client(self.main.app)
        if cookie is not None:
            anonymous.cookies.set("jobscout_session", cookie)
        return {f"{m} {p}": (r.status_code, r.content)
                for m, p in self._guarded()
                for r in [anonymous.request(m, _probe_url(p), json={})]}

    def test_no_cookie_is_a_401_everywhere(self):
        answers = self._answers(None)
        wrong = {k: v[0] for k, v in answers.items() if v[0] != 401}
        self.assertEqual(wrong, {}, "these guarded routes answered a stranger")
        self.assertGreater(len(answers), 20, "the walk found too few routes")

    def test_every_bad_cookie_is_the_same_401(self):
        import time

        from tools import accounts

        good = accounts.issue_session(self.user)
        user, expiry, mac = good.split(".")
        bad = {
            "garbage": "not-a-session",
            "tampered user": f"{make_account(B_EMAIL)}.{expiry}.{mac}",
            "tampered mac": f"{user}.{expiry}.{'0' * len(mac)}",
            "expired": accounts.issue_session(
                self.user, now=time.time() - accounts.SESSION_TTL_SECONDS - 1),
        }
        baseline = self._answers(None)
        for label, cookie in bad.items():
            with self.subTest(label):
                self.assertEqual(self._answers(cookie), baseline,
                                 "a bad cookie was told something an absent one "
                                 "was not")

    def test_a_good_cookie_opens_the_door(self):
        signed_in = client(self.main.app, email=A_EMAIL)
        self.assertEqual(signed_in.get("/api/board").status_code, 200)
        self.assertEqual(signed_in.get("/api/session").json()["user"],
                         {"email": A_EMAIL})

    def test_signing_out_closes_it(self):
        signed_in = client(self.main.app, email=A_EMAIL)
        signed_in.delete("/api/session")
        self.assertEqual(signed_in.get("/api/board").status_code, 401)
        self.assertIsNone(signed_in.get("/api/session").json()["user"])

    def test_a_wrong_passphrase_and_an_unknown_email_are_one_answer(self):
        anonymous = client(self.main.app)
        wrong = anonymous.post("/api/session",
                               json={"email": A_EMAIL, "passphrase": "x" * 20})
        unknown = anonymous.post("/api/session",
                                 json={"email": "c@example.com", "passphrase": "x" * 20})
        self.assertEqual((wrong.status_code, wrong.content),
                         (unknown.status_code, unknown.content))
        self.assertEqual(wrong.status_code, 401)
        self.assertNotIn("set-cookie", wrong.headers)

    def test_the_cookie_cannot_be_read_by_script_or_sent_cross_site(self):
        response = client(self.main.app).post(
            "/api/session", json={"email": A_EMAIL,
                                  "passphrase": "correct horse battery staple"})
        cookie = response.headers["set-cookie"].lower()
        for flag in ("httponly", "secure", "samesite=strict", "path=/"):
            self.assertIn(flag, cookie)

    def test_redeeming_an_invite_signs_in(self):
        from tools import accounts

        _, code = accounts.invite()
        friend = client(self.main.app)
        response = friend.post("/api/account", json={
            "invite_code": code, "email": "friend@example.com",
            "passphrase": "correct horse battery staple"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(friend.get("/api/board").status_code, 200)
        again = client(self.main.app).post("/api/account", json={
            "invite_code": code, "email": "other@example.com",
            "passphrase": "correct horse battery staple"})
        self.assertEqual(again.status_code, 404)


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestAnotherUsersThingsAreNotFound(unittest.TestCase):
    """Rules 1–3 above, with A's data real and B signed in."""

    def setUp(self):
        from tools import paths
        from tools.jobs.job_store import JobStore
        from tools.jobs.job_store import db_path as jobs_db
        from tools.jobs.run_registry import RunRegistry
        from tools.jobs.run_registry import db_path as runs_db

        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self._env = hosted(self.home)
        self._env.__enter__()
        import api.main as main
        self.main = main

        self.a = make_account(A_EMAIL)
        self.b = make_account(B_EMAIL)
        self.a_home = paths.user_home(self.a)

        # A's profile and master resume.
        (self.a_home / "user_profiles").mkdir(parents=True)
        (self.a_home / "data" / "master_resumes").mkdir(parents=True)
        shutil.copy(ROOT / "user_profiles" / f"{PROFILE}.json",
                    self.a_home / "user_profiles" / f"{PROFILE}.json")
        master = ROOT / "data" / "master_resumes" / f"{PROFILE}.tex"
        if master.is_file():
            shutil.copy(master, self.a_home / "data" / "master_resumes")

        # A's board row, run, generated file and upload.
        store = JobStore(jobs_db(self.a))
        try:
            store.record([_Listing(JOB)])
        finally:
            store.close()
        registry = RunRegistry(runs_db(self.a))
        try:
            self.run_id = registry.create(PROFILE)
        finally:
            registry.close()
        generated = self.a_home / "outputs" / "2026-09-22" / "resume.pdf"
        generated.parent.mkdir(parents=True)
        generated.write_bytes(b"%PDF-1.4 A's resume")
        (generated.parent / "state.json").write_text("{}", encoding="utf-8")
        self.file_path = "outputs/2026-09-22/resume.pdf"
        (self.a_home / "data" / "master_resumes" / "upload.tex").write_text(
            "\\documentclass{article}", encoding="utf-8")

        self.owner = client(main.app, email=A_EMAIL)
        self.stranger = client(main.app, email=STRANGER)

    def tearDown(self):
        self._env.__exit__(None, None, None)
        self._tmp.cleanup()

    # Every request that names one of A's things. (method, url, body).
    def _probes(self):
        return {
            "job": ("GET", f"/api/job?url={JOB}", None),
            "job status": ("POST", "/api/job/status", {"url": JOB, "status": "applied"}),
            "run": ("GET", f"/api/run/{self.run_id}", None),
            "file": ("GET", f"/api/file?path={self.file_path}", None),
            "file by traversal": (
                "GET", f"/api/file?path=../{self.a}/{self.file_path}", None),
            "profile read": ("GET", f"/api/profile/{PROFILE}", None),
            "profile update": ("PATCH", f"/api/profile/{PROFILE}", {"updates": {}}),
            "components": ("PUT", f"/api/profile/{PROFILE}/components",
                           {"importance": {}, "triggers": {}}),
            "profile from upload": ("POST", "/api/profile",
                                    {"name": "mine", "filename": "upload.tex"}),
            "gate": ("POST", "/api/board/gate", {"profile": PROFILE}),
            "run start": ("POST", "/api/run",
                          {"profile": PROFILE, "generate_pdf": False}),
        }

    # The owner's positive controls: reads that must find the thing. Writes
    # are left out — a 200 there would change what the stranger's probe reads.
    OWNER_FINDS = ("job", "run", "file", "profile read")

    def _ask(self, who, probe):
        method, url, body = probe
        response = who.request(method, url, json=body)
        return response.status_code, response.content

    def test_the_owner_finds_each_thing(self):
        probes = self._probes()
        for label in self.OWNER_FINDS:
            with self.subTest(label):
                self.assertEqual(self._ask(self.owner, probes[label])[0], 200,
                                 "the fixture does not contain what the "
                                 "stranger's probe is meant to be refused")

    def test_a_stranger_gets_exactly_what_nobody_would(self):
        probes = self._probes()
        before = _tree_digest(self.a_home)
        theirs = {label: self._ask(self.stranger, probe)
                  for label, probe in probes.items()}
        self.assertEqual(_tree_digest(self.a_home), before,
                         "a stranger's request changed a byte of A's data")

        shutil.rmtree(self.a_home)
        nobodys = {label: self._ask(self.stranger, probe)
                   for label, probe in probes.items()}

        for label in probes:
            with self.subTest(label):
                self.assertEqual(theirs[label][0], 404,
                                 f"{label}: {theirs[label]}")
                self.assertEqual(theirs[label], nobodys[label],
                                 "the answer differs when the thing exists for "
                                 "someone else, which tells the caller it does")

    def test_a_stranger_starts_no_run(self):
        self._ask(self.stranger, self._probes()["run start"])
        self.assertEqual(self.stranger.get("/api/run").json()["active"], [])

    def test_no_listing_names_another_users_things(self):
        s = self.stranger
        self.assertEqual(s.get("/api/health").json()["profiles"], [])
        board = s.get("/api/board", params={"include_ineligible": True}).json()
        self.assertEqual((board["total"], board["jobs"]), (0, []))
        self.assertNotIn(JOB, s.get("/api/board/filters").text)
        self.assertNotIn(JOB, s.get("/api/board/ghosted", params={"after_days": 0}).text)
        make_account("c@example.com")
        empty = client(self.main.app, email="c@example.com")
        for listing in ("/api/board/stats", "/api/board/bands"):
            # `path` is the caller's own jobs.db, so it differs between any two
            # accounts and says nothing about A. That it is sent at all is Q47.
            mine, nothing = s.get(listing).json(), empty.get(listing).json()
            mine.pop("path", None)
            nothing.pop("path", None)
            self.assertEqual(mine, nothing,
                             f"{listing} differs from an account with nothing")
        self.assertNotIn(self.run_id, s.get("/api/run").text)
        self.assertNotIn(PROFILE, s.get("/api/run").text)
        self.assertNotIn("2026-09-22", s.get("/api/runs").text)

        # And the controls: the same listings, as A, do name them.
        o = self.owner
        self.assertEqual(o.get("/api/health").json()["profiles"], [PROFILE])
        self.assertEqual(o.get("/api/board").json()["total"], 1)
        self.assertIn(self.run_id, o.get("/api/run").text)
        self.assertIn("2026-09-22", o.get("/api/runs").text)


if __name__ == "__main__":
    unittest.main()

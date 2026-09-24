"""
The pilot's event log: who got how far, and nothing else (A8, R118).

Three claims, each pinned here:

- **each event is written once, at the moment it names**, through the route or
  facade a friend actually uses: redeeming an invite, importing a resume,
  starting and finishing a run, each resume, each applied/rejected mark;
- **nothing from another user's partition appears**, in the file or in the
  operator's summary;
- **no resume text and no key reaches the table**, including when the key is
  on the request and the resume was read by the model.
"""

import io
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from tests.signed_in import PASSPHRASE, client, hosted_env, make_account  # noqa: E402
from tests.test_request_key import (  # noqa: E402
    FIXTURE, KEY, MODEL_REPLY, RESUME_TEXT, FakeClient)
from tools.jobs import event_log  # noqa: E402

try:
    from fastapi.testclient import TestClient  # noqa: F401
except ImportError:  # pragma: no cover
    TestClient = None


class _Listing:
    """What discovery hands the store. Only the fields `record` reads."""

    def __init__(self, url):
        self.apply_url = self.id = url
        self.title, self.company = "Software Engineer", "Example"
        self.location, self.source = "Boston, MA", "test"
        self.full_jd = "A Python role."


class _Hosted(unittest.TestCase):
    """A hosted data home of its own, and no rung chosen by the environment."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        for patch in (
            mock.patch.dict(os.environ, {**hosted_env(self.home),
                                         "JOBSCOUT_LLM_BACKEND": ""}),
            mock.patch.object(config, "LLM_BACKEND", "auto"),
            mock.patch("tools.generation.llm_backends.ollama_is_running",
                       return_value=False),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

    def events(self, user):
        return [(row["event"], row["reason"]) for row in event_log.read(user)]

    def give_profile(self, user):
        from tools.paths import user_home
        home = user_home(user)
        (home / "user_profiles").mkdir(parents=True, exist_ok=True)
        (home / "data" / "master_resumes").mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / "user_profiles" / f"{FIXTURE}.json", home / "user_profiles")
        shutil.copy(ROOT / "data" / "master_resumes" / f"{FIXTURE}.tex",
                    home / "data" / "master_resumes")

    def give_job(self, user, url="https://example.com/a"):
        from tools.jobs.job_store import JobStore, db_path
        store = JobStore(db_path(user))
        try:
            store.record([_Listing(url)])
        finally:
            store.close()
        return url


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestTheAccountIsCreatedOnce(_Hosted):

    def redeem(self, code, email="friend@example.com"):
        from api.main import app
        response = client(app).post("/api/account", json={
            "invite_code": code, "email": email, "passphrase": PASSPHRASE})
        self.assertEqual(response.status_code, 200, response.text)

    def test_at_redeem_and_not_at_invite(self):
        from agents.orchestrator import invite_account
        user, code = invite_account()
        self.assertEqual(self.events(user), [], "an invite is not an account yet")
        self.redeem(code)
        self.assertEqual(self.events(user), [("account_created", None)])

    def test_a_reset_redeemed_is_not_a_second_account(self):
        from agents.orchestrator import invite_account, reset_passphrase
        user, code = invite_account()
        self.redeem(code)
        self.redeem(reset_passphrase(user))
        self.assertEqual(self.events(user), [("account_created", None)])


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestTheImportSaysWhichReaderReadIt(_Hosted):

    def setUp(self):
        super().setUp()
        from api.main import app
        self.user = make_account("friend@example.com")
        self.client = client(app, email="friend@example.com")

    def upload(self, name, body, key=None, fake=None):
        def gemini_client(explicit=None):
            return fake or FakeClient(reply=MODEL_REPLY)

        with mock.patch.object(config, "gemini_client", gemini_client), \
                mock.patch("tools.resume.resume_import.extract_text",
                           return_value=RESUME_TEXT):
            return self.client.post(
                "/api/resume/extract",
                data={"api_key": key} if key else {},
                files={"file": (name, body, "application/octet-stream")})

    def test_the_model_path(self):
        response = self.upload("cv.pdf", b"%PDF-1.7\n", key=KEY)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.events(self.user), [("resume_imported", "model")])

    def test_the_pattern_path(self):
        response = self.upload("cv.pdf", b"%PDF-1.7\n")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.events(self.user), [("resume_imported", "pattern")])

    def test_a_model_that_fails_is_the_pattern_path(self):
        # What read it, not what was asked to: the rung was Gemini.
        response = self.upload("cv.pdf", b"%PDF-1.7\n", key=KEY,
                               fake=FakeClient(error=RuntimeError("quota")))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.events(self.user), [("resume_imported", "pattern")])

    def test_a_latex_upload(self):
        tex = (ROOT / "data" / "master_resumes" / f"{FIXTURE}.tex").read_bytes()
        response = self.upload("cv.tex", tex)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.events(self.user), [("resume_imported", "tex")])

    def test_a_refused_import_is_not_an_import(self):
        response = self.upload("cv.pdf", b"%PDF-1.7\n", key="AQ.bad key")
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.events(self.user), [])


class TestARunIsStartedAndFinished(_Hosted):

    def setUp(self):
        super().setUp()
        self.user = make_account("friend@example.com")
        self.give_profile(self.user)

    def run_to_end(self, pipeline, api_key=""):
        from agents import orchestrator
        with mock.patch.object(orchestrator, "JobScoutOrchestrator", pipeline):
            run_id = orchestrator.start_run(self.user, FIXTURE, api_key=api_key,
                                            max_jobs=5, max_resumes=2,
                                            generate_pdf=False)
            for thread in threading.enumerate():
                if thread.name == f"jobscout-run-{run_id}":
                    thread.join(120)
            status = orchestrator.run_status(self.user, run_id)
        self.assertFalse(status["active"], "the run did not end")
        return status

    def test_started_when_asked_for_before_the_worker_runs(self):
        from agents import orchestrator
        with mock.patch("threading.Thread.start"):
            orchestrator.start_run(self.user, FIXTURE, max_jobs=5, max_resumes=2)
        self.assertEqual(self.events(self.user), [("run_started", None)])

    def test_a_run_that_finishes(self):
        from agents import orchestrator
        real = orchestrator.JobScoutOrchestrator

        def pipeline(**kwargs):
            return real(**{**kwargs, "mock_mode": True, "use_cache": False})

        status = self.run_to_end(pipeline)
        self.assertEqual(status["state"], "finished", status)
        result = status["result"]
        events = self.events(self.user)
        self.assertEqual(events[0], ("run_started", None))
        self.assertEqual(events[-1], ("run_finished", "ok"))
        self.assertEqual(events.count(("run_started", None)), 1)
        self.assertEqual(events.count(("run_finished", "ok")), 1)
        generated = [e for e in events if e[0] == "resume_generated"]
        self.assertGreater(len(generated), 0, "no resume was generated; test is blind")
        self.assertEqual(generated.count(("resume_generated", "valid")),
                         result["valid"])
        self.assertEqual(len(generated), result["generated"])

    def test_a_run_that_fails_records_the_class_and_not_the_message(self):
        class Failing:
            profile = None

            def __init__(self, **kwargs):
                pass

            def run(self, **kwargs):
                raise RuntimeError(f"could not reach https://jobs.example.com {KEY}")

        status = self.run_to_end(Failing, api_key=KEY)
        self.assertEqual(status["state"], "failed")
        self.assertEqual(self.events(self.user), [
            ("run_started", None), ("run_finished", "failed:RuntimeError")])


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestAJobIsMarked(_Hosted):

    def setUp(self):
        super().setUp()
        from api.main import app
        self.user = make_account("friend@example.com")
        self.client = client(app, email="friend@example.com")
        self.url = self.give_job(self.user)

    def mark(self, status, url=None):
        return self.client.post("/api/job/status",
                                json={"url": url or self.url, "status": status})

    def test_applied_and_rejected_each_once(self):
        self.assertEqual(self.mark("applied").status_code, 200)
        self.assertEqual(self.mark("rejected").status_code, 200)
        self.assertEqual(self.events(self.user), [
            ("job_marked", "applied"), ("job_marked", "rejected")])

    def test_other_statuses_and_unknown_jobs_are_not_marks(self):
        self.assertEqual(self.mark("seen").status_code, 200)
        self.assertEqual(self.mark("applied", "https://example.com/none").status_code,
                         404)
        self.assertEqual(self.events(self.user), [])


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestOnePartitionEach(_Hosted):

    def test_one_users_events_are_not_in_anothers(self):
        from agents.orchestrator import pilot_events
        from api.main import app
        alice = make_account("alice@example.com")
        bob = make_account("bob@example.com")
        url = self.give_job(alice)
        client(app, email="alice@example.com").post(
            "/api/job/status", json={"url": url, "status": "applied"})
        # Bob marks the same URL, which is not on his board: nothing.
        client(app, email="bob@example.com").post(
            "/api/job/status", json={"url": url, "status": "applied"})

        self.assertEqual(self.events(alice), [("job_marked", "applied")])
        self.assertEqual(self.events(bob), [])
        for row in event_log.read(alice):
            self.assertEqual(row["user_id"], alice)
        summary = {u["user_id"]: u["counts"] for u in pilot_events()}
        self.assertEqual(summary[alice], {"job_marked:applied": 1})
        self.assertEqual(summary[bob], {})

    def test_the_file_is_under_the_users_own_home(self):
        from tools.paths import user_home
        alice = make_account("alice@example.com")
        event_log.record(alice, "run_started")
        self.assertTrue(event_log.db_path(alice).is_relative_to(user_home(alice)))

    def test_the_unscoped_user_writes_nothing(self):
        # The checkout has no account, and nothing reads an event there.
        self.assertFalse(event_log.record(None, "run_started"))
        self.assertEqual(list(self.home.rglob("events.db")), [])


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestNoContentReachesTheTable(_Hosted):

    def test_a_model_import_and_a_run_with_a_key_leave_neither(self):
        """
        The import is read by the model with the key on the request, and the
        run holds the key and fails quoting it. Then the file's bytes are read:
        not a column, the whole file, so a free page or a journal counts too.
        """
        from agents import orchestrator
        from api.main import app
        user = make_account("friend@example.com")
        self.give_profile(user)
        signed_in = client(app, email="friend@example.com")
        with mock.patch.object(config, "gemini_client",
                               lambda explicit=None: FakeClient(reply=MODEL_REPLY)), \
                mock.patch("tools.resume.resume_import.extract_text",
                           return_value=RESUME_TEXT):
            response = signed_in.post(
                "/api/resume/extract", data={"api_key": KEY},
                files={"file": ("cv.pdf", b"%PDF-1.7\n", "application/pdf")})
        self.assertEqual(response.status_code, 200, response.text)

        class Failing:
            profile = None

            def __init__(self, **kwargs):
                pass

            def run(self, **kwargs):
                raise RuntimeError(f"{RESUME_TEXT[:200]} {KEY}")

        with mock.patch.object(orchestrator, "JobScoutOrchestrator", Failing):
            run_id = orchestrator.start_run(user, FIXTURE, api_key=KEY,
                                            max_jobs=5, max_resumes=2)
            deadline = time.monotonic() + 30
            while orchestrator.run_status(user, run_id)["active"]:
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.02)

        self.assertEqual(self.events(user), [
            ("resume_imported", "model"), ("run_started", None),
            ("run_finished", "failed:RuntimeError")])
        stored = event_log.db_path(user).read_bytes()
        self.assertNotIn(KEY.encode(), stored)
        self.assertNotIn(MODEL_REPLY["contact"]["name"].encode(), stored)
        self.assertNotIn(b"Built the thing that shipped", stored)
        for line in RESUME_TEXT.splitlines():
            if len(line.strip()) >= 12:
                self.assertNotIn(line.strip().encode("utf-8"), stored, line)

    def test_the_store_refuses_content_rather_than_trimming_it(self):
        user = "someone"
        for event, reason in (("resume_imported", RESUME_TEXT[:40]),
                              ("run_finished", f"failed:{KEY}"),
                              ("run_finished", "failed: boom at https://x"),
                              ("job_marked", "seen"),
                              ("resume_text", None)):
            with self.subTest(event=event, reason=reason):
                with self.assertRaises(ValueError):
                    event_log.record(user, event, reason)
        self.assertEqual(event_log.read(user), [])


class TestTheSummary(unittest.TestCase):

    def at(self, days):
        start = datetime(2026, 10, 1, tzinfo=timezone.utc)
        return (start + timedelta(days=days)).isoformat()

    def row(self, event, reason=None, days=0):
        return {"user_id": "u", "event": event, "reason": reason, "at": self.at(days)}

    def test_the_criterion_inside_and_outside_the_first_week(self):
        base = [self.row("account_created"), self.row("run_started", days=1),
                self.row("run_finished", "ok", days=1)]
        inside = event_log.summarise(base + [self.row("job_marked", "rejected", 6)])
        late = event_log.summarise(base + [self.row("job_marked", "applied", 8)])
        self.assertIs(inside["met_in_first_week"], True)
        self.assertIs(late["met_in_first_week"], False)

    def test_a_failed_run_is_not_a_completed_one(self):
        rows = [self.row("account_created"),
                self.row("run_finished", "failed:RuntimeError", 1),
                self.row("job_marked", "applied", 2)]
        summary = event_log.summarise(rows)
        self.assertIs(summary["met_in_first_week"], False)
        self.assertEqual(summary["counts"]["run_finished:failed"], 1)

    def test_no_creation_event_is_unknown_not_no(self):
        self.assertIsNone(event_log.summarise([])["met_in_first_week"])
        self.assertIsNone(event_log.summarise(
            [self.row("run_finished", "ok")])["met_in_first_week"])


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestAdminEvents(_Hosted):

    def test_prints_each_user_and_the_criterion_count(self):
        from scripts import admin
        alice = make_account("alice@example.com")
        make_account("bob@example.com")
        event_log.record(alice, "account_created")
        event_log.record(alice, "resume_imported", "pattern")
        event_log.record(alice, "run_started")
        event_log.record(alice, "run_finished", "ok")
        event_log.record(alice, "job_marked", "applied")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(admin.main(["events"]), 0)
        text = out.getvalue()
        self.assertIn("alice@example.com", text)
        self.assertIn("bob@example.com", text)
        self.assertIn("furthest: marked   first-week criterion: yes", text)
        self.assertIn("furthest: none   first-week criterion: unknown", text)
        self.assertIn("import pattern 1", text)
        self.assertIn("2 account(s); 1 met the first-week criterion", text)


if __name__ == "__main__":
    unittest.main()

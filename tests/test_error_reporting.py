"""
Sentry, hosted backend only, with the key scrubbed (A9, R119).

The key is planted where a careless setup would send it: in an exception's
message, in a frame's locals, in a log line, in a breadcrumb written while the
key was held and sent after it was released, and in a request's headers and
cookies. Events are caught by a transport that keeps them, so nothing leaves
the machine, and each assertion reads the whole serialized event rather than
the field the scrub was written for.
"""

import json
import logging
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

import sentry_sdk  # noqa: E402
from sentry_sdk.transport import Transport  # noqa: E402

from config import key_in_use  # noqa: E402
from tools import error_reporting  # noqa: E402

ROOT = Path(__file__).parent.parent
KEY = "AIzaSyD-this-is-a-planted-key-0123456789"
DSN = "https://public@sentry.invalid/1"


class _Kept(Transport):
    """A transport that keeps every event instead of sending it."""

    def __init__(self, options=None):
        super().__init__(options)
        self.events = []

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.type in ("event", "error"):
                self.events.append(item.payload.json)


def _stop_sentry():
    client = sentry_sdk.get_client()
    if client.is_active():
        client.close()
    sentry_sdk.get_global_scope().set_client(None)
    sentry_sdk.get_isolation_scope().clear()
    sentry_sdk.get_current_scope().clear()


class SentryCase(unittest.TestCase):
    """Starts Sentry through `start_error_reporting`, with events kept here."""

    def setUp(self):
        _stop_sentry()
        self.kept = _Kept()
        real_init = sentry_sdk.init
        # The options under test are the module's own: only the transport is
        # swapped, so a missing option here is missing in production.
        patch = mock.patch.object(
            sentry_sdk, "init",
            side_effect=lambda **options: real_init(transport=self.kept, **options))
        patch.start()
        self.addCleanup(patch.stop)
        with mock.patch.dict(os.environ, {error_reporting.DSN_ENV_VAR: DSN}):
            self.assertTrue(error_reporting.start_error_reporting())
        self.addCleanup(_stop_sentry)

    def sent(self):
        return json.dumps(self.kept.events)


class TestAKeyInUseNeverReachesAnEvent(SentryCase):

    def test_an_exception_quoting_the_key_in_its_message_and_locals(self):
        def fails(api_key):
            secret = f"Bearer {api_key}"  # noqa: F841 — a local that holds it
            raise RuntimeError(f"401: key {api_key} rejected")

        with key_in_use(KEY):
            try:
                fails(KEY)
            except RuntimeError:
                sentry_sdk.capture_exception()

        self.assertEqual(len(self.kept.events), 1)
        self.assertNotIn(KEY, self.sent())
        # The event is there, and says what broke.
        self.assertIn("401: key [your key] rejected", self.sent())

    def test_locals_are_absent(self):
        # Built at run time: Sentry sends source lines as context, which is
        # code, and a literal here would be in them whatever happened to vars.
        email = "".join(["priya", "@", "example.com"])

        def fails(api_key):
            resume = f"Priya Raghunathan, {email}"  # noqa: F841
            raise ValueError("boom")

        try:
            fails(KEY)
        except ValueError:
            sentry_sdk.capture_exception()

        frames = self.kept.events[0]["exception"]["values"][0]["stacktrace"]["frames"]
        self.assertTrue(frames)
        for frame in frames:
            self.assertNotIn("vars", frame)
        self.assertNotIn(email, self.sent())

    def test_an_error_logged_with_the_key_the_way_a_failed_run_is(self):
        # `start_run`'s worker logs "Background run failed" with the traceback
        # while it holds the key. The log integration builds the event from
        # the exception object, not from the record the log factory scrubbed.
        log = logging.getLogger("agents.orchestrator")
        with key_in_use(KEY):
            try:
                raise RuntimeError(f"Gemini said: bad key {KEY}")
            except RuntimeError:
                log.exception("Background run failed with %s", KEY)

        self.assertEqual(len(self.kept.events), 1)
        self.assertNotIn(KEY, self.sent())

    def test_a_breadcrumb_written_while_held_is_clean_after_release(self):
        # A breadcrumb rides the *next* event. By then the run may have
        # released the key, so `before_send` alone would not know it.
        with key_in_use(KEY):
            crumb = {"category": "http", "message": f"GET ?key={KEY}"}
            sentry_sdk.add_breadcrumb(crumb)
        sentry_sdk.capture_message("later")

        self.assertIn("GET ?key=[your key]", self.sent())
        self.assertNotIn(KEY, self.sent())

    def test_logging_below_warning_leaves_no_breadcrumb(self):
        log = logging.getLogger("tools.jobs")
        log.info("an info line")
        log.warning("a warning line")
        sentry_sdk.capture_message("then this")

        self.assertNotIn("an info line", self.sent())
        self.assertIn("a warning line", self.sent())


class TestARequestSendsNoHeadersCookiesOrBody(SentryCase):

    def test_a_500_from_a_route(self):
        from fastapi import FastAPI, Form
        from fastapi.testclient import TestClient

        app = FastAPI()

        # The key is in the header and the body, and released before Sentry's
        # middleware sees the exception, so the scrub cannot know it here.
        # Only dropping the headers and never reading the body keeps it out.
        # (An exception that carries the key out of `key_in_use` is Q71.)
        @app.post("/boom")
        def boom(api_key: str = Form("")):
            with key_in_use(api_key):
                raise RuntimeError("model refused the request")

        # Built at run time, out of the source lines Sentry sends as context.
        cookie = "-".join(["signed", "session", "cookie"])
        resume = "".join(["Pri", "ya"])
        client = TestClient(app, raise_server_exceptions=False)
        client.cookies.set("jobscout_session", cookie)
        response = client.post(
            "/boom", data={"api_key": KEY},
            headers={"Authorization": f"Bearer {KEY}", "X-Resume": resume})
        self.assertEqual(response.status_code, 500)

        self.assertEqual(len(self.kept.events), 1)
        request = self.kept.events[0]["request"]
        self.assertNotIn("headers", request)
        self.assertNotIn("cookies", request)
        # `send_default_pii=False`: no client address, no user.
        self.assertNotIn("env", request)
        self.assertNotIn("user", self.kept.events[0])
        # Sent as an empty field, never as the body.
        self.assertFalse(request.get("data"))
        self.assertNotIn(KEY, self.sent())
        self.assertNotIn(cookie, self.sent())
        self.assertNotIn(resume, self.sent())


class TestWithoutADsnNothingStarts(unittest.TestCase):

    def setUp(self):
        _stop_sentry()

    def test_no_dsn_no_init(self):
        for unset in ({}, {error_reporting.DSN_ENV_VAR: ""},
                      {error_reporting.DSN_ENV_VAR: "   "}):
            env = {k: v for k, v in os.environ.items()
                   if k != error_reporting.DSN_ENV_VAR}
            env.update(unset)
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(sentry_sdk, "init") as init:
                self.assertFalse(error_reporting.start_error_reporting())
            init.assert_not_called()
            self.assertFalse(sentry_sdk.get_client().is_active())

    def test_a_dsn_without_the_package_refuses_to_start(self):
        with mock.patch.dict(os.environ, {error_reporting.DSN_ENV_VAR: DSN}), \
                mock.patch.dict(sys.modules, {"sentry_sdk": None}):
            with self.assertRaises(RuntimeError):
                error_reporting.start_error_reporting()

    def test_the_api_starts_it_before_the_app_is_built(self):
        source = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
        self.assertLess(source.index("\nstart_error_reporting()"),
                        source.index("\napp = FastAPI("))


if __name__ == "__main__":
    unittest.main()

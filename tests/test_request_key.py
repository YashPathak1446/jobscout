"""
A key the browser sends is used, refused when unsendable, and never kept (R117).

A hosted user's Gemini key lives in their browser and arrives in a request
body (Q58). Three things follow, each pinned here:

- the resume-extract request uses the key it carries, because a hosted import
  reads none from the environment (R113);
- a key that cannot be sent is refused there with R101's message, rather than
  quietly read by pattern;
- the key never reaches a log line, an error message, a run record or a file
  under the data home, even when an upstream error quotes it back. The tests
  make the model's error echo the key on purpose: a key that is merely never
  written proves nothing about the paths that write exception text.
"""

import io
import json
import logging
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402

try:
    from fastapi.testclient import TestClient  # noqa: F401
except ImportError:  # pragma: no cover
    TestClient = None

from tests.signed_in import client, hosted_env, make_account  # noqa: E402

# No format assumed (R101's correction): only that it is sendable.
KEY = "AQ.test-request-key-7f3c91d2e5b8a4f60c1e9d7b2a5f8c3e1d4"
FIXTURE = "priya_raghunathan"
RESUME_TEXT = (ROOT / "tests" / "fixtures" / "resume_two_degrees_non_us.txt").read_text(
    encoding="utf-8")

# A reply shaped like the model's, so the import takes the model branch.
MODEL_REPLY = {
    "contact": {"name": "Test Person", "email": "test@example.com"},
    "education": [{"school": "Lakeside University", "degree": "BS Computer Science"}],
    "experiences": [{"company": "Acme", "title": "Engineer", "dates": "2020 - 2024",
                     "bullets": ["Built the thing that shipped."]}],
    "projects": [],
    "skills": {"Languages": "Python"},
}


class FakeClient:
    """A `genai.Client` stand-in that records nothing but answers or raises."""

    def __init__(self, reply=None, error=None):
        self.models = SimpleNamespace(generate_content=self._generate)
        self._reply, self._error = reply, error

    def _generate(self, model, contents):
        if self._error is not None:
            raise self._error
        return SimpleNamespace(text=json.dumps(self._reply))


class CapturedLogs:
    """Every log record from every logger, rendered as a handler would."""

    def __enter__(self):
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.setFormatter(logging.Formatter("%(name)s %(message)s"))
        self.root = logging.getLogger()
        self.level = self.root.level
        self.root.addHandler(self.handler)
        self.root.setLevel(logging.DEBUG)
        return self

    def __exit__(self, *exc):
        self.root.removeHandler(self.handler)
        self.root.setLevel(self.level)

    @property
    def text(self):
        self.handler.flush()
        return self.stream.getvalue()


def files_holding(home: Path, secret: str) -> list:
    """Every file under `home` whose bytes contain `secret`."""
    needle = secret.encode("utf-8")
    return sorted(str(p.relative_to(home)) for p in home.rglob("*")
                  if p.is_file() and needle in p.read_bytes())


class _HostedHome(unittest.TestCase):
    """A hosted instance, one signed-in account, and a clean rung chain."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        patches = [
            # Nothing but the request may choose the rung or supply a key.
            mock.patch.dict("os.environ", {**hosted_env(self.home),
                                           "JOBSCOUT_LLM_BACKEND": ""}),
            mock.patch.object(config, "LLM_BACKEND", "auto"),
            mock.patch("tools.generation.llm_backends.ollama_is_running",
                       return_value=False),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.user = make_account("friend@example.com")

    def assertNowhere(self, secret, logs: str):
        self.assertNotIn(secret, logs, "the key reached a log line")
        self.assertEqual(files_holding(self.home, secret), [],
                         "the key was written to disk")


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestTheImportUsesTheKeyItIsSent(_HostedHome):

    def setUp(self):
        super().setUp()
        from api.main import app
        self.client = client(app, email="friend@example.com")

    def extract(self, key=None, fake=None):
        """POST a PDF upload; the PDF's text is the committed fixture's."""
        used = []

        def gemini_client(explicit=None):
            used.append(explicit)
            problem = config.gemini_key_problem(explicit)
            if problem:
                raise config.ApiKeyProblem(problem)
            return fake or FakeClient(reply=MODEL_REPLY)

        data = {"api_key": key} if key is not None else {}
        with mock.patch.object(config, "gemini_client", gemini_client), \
                mock.patch("tools.resume.resume_import.extract_text",
                           return_value=RESUME_TEXT), \
                CapturedLogs() as logs:
            response = self.client.post(
                "/api/resume/extract", data=data,
                files={"file": ("cv.pdf", b"%PDF-1.7\n%fixture\n", "application/pdf")})
        return response, used, logs.text

    def test_the_request_key_reaches_the_model(self):
        response, used, _ = self.extract(KEY)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(used, [KEY])
        self.assertEqual(response.json()["schema"]["_extraction"]["read_by"], "model")

    def test_no_key_on_a_hosted_import_is_the_pattern_reader(self):
        # The environment's key is not the request's (R113), so none is used.
        with mock.patch.dict("os.environ", {"GOOGLE_API_KEY": "operator-key"}):
            response, used, _ = self.extract()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(used, [])
        self.assertEqual(response.json()["schema"]["_extraction"]["read_by"],
                         "pattern")

    def test_an_unsendable_key_is_refused_with_the_reason(self):
        for bad, words in (("AQ.abc—note", "U+2014"),
                           ("AQ.abc def", "space"),
                           ('"AQ.abc"', "quote")):
            with self.subTest(key=bad):
                response, used, _ = self.extract(bad)
                self.assertEqual(response.status_code, 422, response.text)
                detail = response.json()["detail"]
                self.assertEqual(detail, config.gemini_key_problem(bad))
                self.assertIn(words, detail)
                self.assertEqual(used, [], "a refused key was still handed on")

    def test_a_key_the_model_echoes_is_in_no_message_log_or_file(self):
        # An upstream error that quotes the key: the import falls back to the
        # pattern reader and says why, and the why must not carry the key.
        echo = RuntimeError(f"API key {KEY} not valid. Please pass a valid key.")
        response, used, logs = self.extract(KEY, fake=FakeClient(error=echo))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(used, [KEY])
        why = response.json()["schema"]["_extraction"]["why"]
        self.assertIn(config.REDACTED_KEY, why, "the test did not reach the echo")
        self.assertNotIn(KEY, response.text)
        self.assertNowhere(KEY, logs)

    def test_a_key_cut_by_the_messages_length_limit_is_still_scrubbed(self):
        # The why keeps 160 characters of the error. Placed so the cut falls
        # inside the key: scrubbing after cutting would leave half of it.
        prefix = "x" * (160 - len("every Gemini model failed (") - 20)
        echo = RuntimeError(f"{prefix}{KEY}")
        response, _, logs = self.extract(KEY, fake=FakeClient(error=echo))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(KEY[:20], response.text)
        self.assertNowhere(KEY[:20], logs)

    def test_a_crash_that_quotes_the_key_is_scrubbed_from_the_error(self):
        with mock.patch("scripts.init_profile._extract_resume",
                        side_effect=RuntimeError(f"boom {KEY}")):
            response, _, logs = self.extract(KEY)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(KEY, response.text)
        self.assertIn(config.REDACTED_KEY, response.json()["detail"])

    def test_a_malformed_run_request_does_not_echo_its_body(self):
        # FastAPI's default 422 puts a missing field's whole body in `input`.
        response = self.client.post("/api/run", json={"api_key": KEY})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(KEY, response.text)
        self.assertIn("profile", response.text)


class TestARunLeavesNoKey(_HostedHome):

    def setUp(self):
        super().setUp()
        from tools.paths import user_home
        home = user_home(self.user)
        (home / "user_profiles").mkdir(parents=True, exist_ok=True)
        (home / "data" / "master_resumes").mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / "user_profiles" / f"{FIXTURE}.json", home / "user_profiles")
        shutil.copy(ROOT / "data" / "master_resumes" / f"{FIXTURE}.tex",
                    home / "data" / "master_resumes")

    def run_to_end(self, pipeline):
        from agents import orchestrator
        with mock.patch.object(orchestrator, "JobScoutOrchestrator", pipeline), \
                CapturedLogs() as logs:
            run_id = orchestrator.start_run(self.user, FIXTURE, api_key=KEY,
                                            max_jobs=5, max_resumes=2,
                                            generate_pdf=False)
            deadline = time.monotonic() + 120
            status = None
            while time.monotonic() < deadline:
                status = orchestrator.run_status(self.user, run_id)
                if status and not status["active"]:
                    break
                time.sleep(0.05)
            for thread in threading.enumerate():
                if thread.name == f"jobscout-run-{run_id}":
                    thread.join(30)
        self.assertIsNotNone(status)
        self.assertFalse(status["active"], "the run did not end")
        return status, logs.text

    def test_a_real_pipeline_whose_model_quotes_the_key(self):
        """
        The whole mock pipeline, except that generation is live and Gemini's
        error quotes the key. So the key is written as exception text into
        every place a failed rewrite is reported: the resume's reason,
        `state.json`, the run record, the log.
        """
        from agents import generation_agent, orchestrator

        real_pipeline = orchestrator.JobScoutOrchestrator
        real_agent = orchestrator.GenerationAgent
        clients = []

        def pipeline(**kwargs):
            return real_pipeline(**{**kwargs, "mock_mode": True, "use_cache": False})

        def live_generation(*args, **kwargs):
            return real_agent(*args, **{**kwargs, "mock_mode": False})

        def gemini_client(explicit=None):
            clients.append(explicit)
            return FakeClient(error=RuntimeError(f"401 key {explicit} rejected"))

        with mock.patch.object(orchestrator, "GenerationAgent", live_generation), \
                mock.patch.object(generation_agent, "gemini_client", gemini_client):
            status, logs = self.run_to_end(pipeline)

        self.assertEqual(status["state"], "finished", status)
        self.assertIn(KEY, clients, "the run never used the key; test is blind")
        degraded = " ".join(status["result"]["degraded"])
        self.assertIn(config.REDACTED_KEY, degraded,
                      "no failure text reached the record; test is blind")
        self.assertNotIn(KEY, json.dumps(status))
        self.assertNowhere(KEY, logs)

    def test_a_run_that_fails_quoting_the_key(self):
        class Failing:
            profile = None

            def __init__(self, **kwargs):
                pass

            def run(self, **kwargs):
                logging.getLogger("jobscout.test").warning("about to fail with %s", KEY)
                raise RuntimeError(f"upstream refused {KEY}")

        status, logs = self.run_to_end(Failing)
        self.assertEqual(status["state"], "failed")
        self.assertIn(config.REDACTED_KEY, status["error"])
        self.assertNotIn(KEY, json.dumps(status))
        self.assertIn("about to fail with", logs, "the log was not captured")
        self.assertNowhere(KEY, logs)


class TestTwoUsersRunningAtOnce(_HostedHome):
    """
    Two users' runs, in two threads, each with its own key, both held at once.

    The scrubber's registry has to hold every key in use, not the latest one:
    a single "current key" slot would be overwritten by the second run to
    start, and the first run's key would then be written as plain text by
    its own thread. Each run's model error quotes that run's key, and it
    raises only once both keys are held, so the overlap is certain rather
    than hoped for.
    """

    OTHER_KEY = "AQ.second-user-key-0b9e4d2c7a1f8e3b6d5c4a2f9e8d7c6b5a4"

    def setUp(self):
        super().setUp()
        from tools.paths import user_home
        self.other = make_account("other@example.com")
        for user in (self.user, self.other):
            home = user_home(user)
            (home / "user_profiles").mkdir(parents=True, exist_ok=True)
            (home / "data" / "master_resumes").mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / "user_profiles" / f"{FIXTURE}.json",
                        home / "user_profiles")
            shutil.copy(ROOT / "data" / "master_resumes" / f"{FIXTURE}.tex",
                        home / "data" / "master_resumes")

    def test_neither_key_reaches_a_log_record_or_file(self):
        from agents import generation_agent, orchestrator

        real_pipeline = orchestrator.JobScoutOrchestrator
        real_agent = orchestrator.GenerationAgent
        seen, lock, both = set(), threading.Lock(), threading.Event()

        def pipeline(**kwargs):
            return real_pipeline(**{**kwargs, "mock_mode": True, "use_cache": False})

        def live_generation(*args, **kwargs):
            return real_agent(*args, **{**kwargs, "mock_mode": False})

        def gemini_client(explicit=None):
            with lock:
                seen.add(explicit)
                if {KEY, self.OTHER_KEY} <= seen:
                    both.set()
            # Nobody echoes a key until both runs are holding theirs.
            both.wait(30)
            return FakeClient(error=RuntimeError(f"401 key {explicit} rejected"))

        runs = {}
        with mock.patch.object(orchestrator, "JobScoutOrchestrator", pipeline), \
                mock.patch.object(orchestrator, "GenerationAgent", live_generation), \
                mock.patch.object(generation_agent, "gemini_client", gemini_client), \
                CapturedLogs() as logs:
            for user, key in ((self.user, KEY), (self.other, self.OTHER_KEY)):
                runs[user] = orchestrator.start_run(
                    user, FIXTURE, api_key=key, max_jobs=5, max_resumes=2,
                    generate_pdf=False)
            for user, run_id in runs.items():
                for thread in threading.enumerate():
                    if thread.name == f"jobscout-run-{run_id}":
                        thread.join(120)
            statuses = {user: orchestrator.run_status(user, run_id)
                        for user, run_id in runs.items()}

        self.assertTrue(both.is_set(), "the runs never overlapped; test is blind")
        for user, status in statuses.items():
            with self.subTest(user=user):
                self.assertEqual(status["state"], "finished", status)
                self.assertIn(config.REDACTED_KEY,
                              " ".join(status["result"]["degraded"]),
                              "no failure text reached the record; test is blind")
                self.assertNotIn(KEY, json.dumps(status))
                self.assertNotIn(self.OTHER_KEY, json.dumps(status))
        self.assertIn(config.REDACTED_KEY, logs.text, "the log was not captured")
        self.assertNowhere(KEY, logs.text)
        self.assertNowhere(self.OTHER_KEY, logs.text)
        # Both released afterwards: the registry is a hold, not a history.
        self.assertEqual(config.redact_keys(KEY + self.OTHER_KEY),
                         KEY + self.OTHER_KEY)


class TestTheScrubber(unittest.TestCase):

    def test_only_while_in_use(self):
        text = f"x {KEY} y"
        self.assertEqual(config.redact_keys(text), text)
        with config.key_in_use(KEY):
            self.assertEqual(config.redact_keys(text), f"x {config.REDACTED_KEY} y")
            with config.key_in_use(KEY):
                pass
            # Counted, so a second holder ending does not release the first.
            self.assertNotIn(KEY, config.redact_keys(text))
        self.assertEqual(config.redact_keys(text), text)

    def test_a_named_key_is_scrubbed_without_being_held(self):
        self.assertNotIn(KEY, config.redact_keys(f"a {KEY}", KEY))

    def test_an_empty_key_holds_nothing(self):
        with config.key_in_use(""):
            self.assertEqual(config.redact_keys("abc"), "abc")

    def test_a_traceback_is_scrubbed_too(self):
        with CapturedLogs() as logs, config.key_in_use(KEY):
            try:
                raise ValueError(f"inner {KEY}")
            except ValueError:
                logging.getLogger("jobscout.test").exception("failed")
        self.assertIn("ValueError: inner", logs.text)
        self.assertNotIn(KEY, logs.text)


class TestThePageSendsAndKeepsTheKey(unittest.TestCase):
    """Source-level: no frontend runner here, so the wiring is read."""

    WEB = ROOT / "web" / "src"

    def read(self, path):
        return (self.WEB / path).read_text(encoding="utf-8")

    def test_the_extract_request_carries_the_key_in_its_body(self):
        api = self.read("lib/api.ts")
        self.assertIn("form.append('api_key', key)", api)
        self.assertIn("api.extractResume(file, apiKey)",
                      self.read("components/steps/ResumeStep.tsx"))

    def test_every_storage_call_is_guarded(self):
        store = self.read("lib/keyStore.ts")
        calls = store.count("window.localStorage.")
        self.assertEqual(calls, 3)
        self.assertEqual(store.count("try {"), 2)
        self.assertEqual(store.count("} catch {"), 2)
        # Nothing else touches storage directly.
        for path in self.WEB.rglob("*.ts*"):
            if path.name != "keyStore.ts":
                self.assertNotIn("localStorage", path.read_text(encoding="utf-8"),
                                 path.name)

    def test_the_key_step_comes_before_the_resume(self):
        wizard = self.read("components/Wizard.tsx")
        self.assertLess(wizard.index("'Key'"), wizard.index("'Resume'"))
        step = self.read("components/steps/KeyStep.tsx")
        self.assertIn("https://aistudio.google.com/app/apikey", step)
        self.assertIn("Forget key", step)
        self.assertIn("The server never stores it.", step)

    def test_the_key_page_says_what_the_free_tier_does_with_your_data(self):
        step = self.read("components/steps/KeyStep.tsx")
        self.assertIn("https://ai.google.dev/gemini-api/terms", step)
        self.assertIn("On the free tier, Google may use what you send it", step)
        self.assertIn("resume and the job descriptions", step)

    def test_the_key_page_says_the_free_tier_asks_for_no_personal_data(self):
        # Q69. JSX joins lines, so the check is on the words, not the layout.
        step = " ".join(self.read("components/steps/KeyStep.tsx").split())
        self.assertIn("Google's free-tier terms ask you not to send personal "
                      "information, and your resume is personal information.", step)
        self.assertIn("Without a key, everything except bullet rewriting works "
                      "and nothing goes to Google", step)
        self.assertIn("A paid key isn't used this way.", step)
        # Exact only when hosted: a local instance also reads GOOGLE_API_KEY.
        self.assertIn("mode === 'local'", step)
        self.assertIn("unless this machine has GOOGLE_API_KEY set", step)


class TestAHostedPageOffersNothingLocal(unittest.TestCase):
    """
    Q68: a hosted instance cannot reach an Ollama on the friend's machine.

    Source-level, like the class above. Each check names the mode reaching the
    place it is used, because a component that is never told the mode shows
    the local copy everywhere and still typechecks.
    """

    WEB = ROOT / "web" / "src"

    def read(self, path):
        return (self.WEB / path).read_text(encoding="utf-8")

    def test_the_mode_reaches_every_place_that_says_local(self):
        self.assertIn("mode={session.mode}", self.read("App.tsx"))
        wizard = self.read("components/Wizard.tsx")
        self.assertEqual(wizard.count("mode={mode}"), 2)  # KeyStep and RunStep
        self.assertIn("<BackendPanel mode={mode}",
                      self.read("components/steps/KeyStep.tsx"))

    def test_the_subtitle_says_locally_only_when_local(self):
        wizard = self.read("components/Wizard.tsx")
        self.assertIn("{mode === 'local' ? ', locally.' : '.'}", wizard)
        self.assertNotIn("each one,\n            locally.", wizard)

    def test_the_keyless_advice_names_ollama_only_when_local(self):
        panel = self.read("components/BackendPanel.tsx")
        hosted = panel.index("none && mode === 'hosted'")
        self.assertLess(hosted, panel.index("<strong>Ollama</strong> locally"))

    def test_the_rung_list_drops_ollama_when_hosted(self):
        run = self.read("components/steps/RunStep.tsx")
        self.assertIn("!(mode === 'hosted' && value === 'ollama')", run)


class TestTheKeyStepSaysOneThingForGemini(unittest.TestCase):
    """
    R128. The Key step's Gemini alert is its headline and nothing else: the
    shared description's "the backend every measurement in this project
    used" is the project's history, not something a user chooses on.
    """

    PANEL = ROOT / "web" / "src" / "components" / "BackendPanel.tsx"

    def test_gemini_skips_the_description(self):
        panel = self.PANEL.read_text(encoding="utf-8")
        self.assertIn("gemini: 'Bullets will be rewritten by Google Gemini.'", panel)
        skip = panel.index("chosen === 'gemini' ? null :")
        self.assertLess(skip, panel.index("<p>{backend.description}</p>"))


if __name__ == "__main__":
    unittest.main()

"""
The OpenAI-compatible rung, against a server that actually answers (A1).

Two of the ladder's four rungs — `ollama` and `openai` — are one adapter with
a different base URL, and neither had ever completed a call. Detection was
tested; the completion was tested against its parsing only. So the rung this
project recommends to anyone without an API key was, in the strict sense,
never known to work.

This closes the plumbing half. A stdlib HTTP server binds loopback on an
ephemeral port and speaks the two shapes that matter: Ollama's `/api/tags` and
the OpenAI `/v1/chat/completions` response envelope. That is a real request
over a real socket through the real code path — it just does not need a 5 GB
download or an internet connection, and it runs in CI forever.

What it deliberately does **not** prove is bullet *quality* from a small local
model — a fake server returns what the test told it to. Only a real Ollama
answers that, and when one finally ran it produced two things this file could
never have caught: a wrapper nobody predicted, and fabricated resume content.
See R44, and read it before loosening anything here.
"""

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.generation import llm_backends  # noqa: E402

# What the fake server will claim to have pulled, and what it will reply.
PULLED = "llama3.1:latest"
REPLY = {"contact": {"name": "Jane Doe"}, "ok": True}


class _Handler(BaseHTTPRequestHandler):
    """Enough of Ollama and OpenAI to exercise the adapter honestly."""

    # Set per-test to bend the server's behaviour.
    models = [PULLED]
    content = json.dumps(REPLY)
    status = 200

    def _send(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self._send({"models": [{"name": n} for n in type(self).models]})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8")
        type(self).last_request = json.loads(raw) if raw else {}
        type(self).last_headers = dict(self.headers)

        if not self.path.endswith("/chat/completions"):
            self._send({"error": "not found"}, 404)
            return
        if type(self).status != 200:
            self._send({"error": "upstream said no"}, type(self).status)
            return

        self._send({"choices": [{"message": {"content": type(self).content}}]})

    def log_message(self, *args):
        """Silence. The test runner's output is not an access log."""


class _Server:
    """A loopback server on an ephemeral port, for the length of one test."""

    def __init__(self):
        self.httpd = HTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def api_url(self):
        """Ollama's native API root, where /api/tags lives."""
        return f"http://127.0.0.1:{self.port}"

    @property
    def base_url(self):
        """The OpenAI-compatible root, where /chat/completions lives."""
        return f"http://127.0.0.1:{self.port}/v1"

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


class _ServedTest(unittest.TestCase):

    def setUp(self):
        _Handler.models = [PULLED]
        _Handler.content = json.dumps(REPLY)
        _Handler.status = 200
        _Handler.last_request = None
        _Handler.last_headers = {}
        self.server = _Server()

    def tearDown(self):
        self.server.stop()


class TestDetectionAgainstALiveServer(_ServedTest):

    def test_a_served_model_list_is_read(self):
        self.assertEqual(llm_backends.ollama_models(self.server.api_url), [PULLED])

    def test_a_server_with_models_counts_as_running(self):
        self.assertTrue(llm_backends.ollama_is_running(self.server.api_url))

    def test_a_server_with_nothing_pulled_does_not(self):
        """Up and useless is not available. This is a real 200 with no models."""
        _Handler.models = []
        self.assertFalse(llm_backends.ollama_is_running(self.server.api_url))

    def test_detect_picks_ollama_when_only_ollama_is_there(self):
        self.assertEqual(
            llm_backends.detect(gemini_key="", openai_key="",
                                ollama_url=self.server.api_url),
            "ollama")

    def test_the_model_is_resolved_from_what_the_server_reports(self):
        """R42's fix, now against a server rather than a list literal."""
        _Handler.models = ["mistral:latest"]
        self.assertEqual(
            llm_backends.resolve_ollama_model(self.server.api_url, "llama3.1"),
            "mistral:latest")


class TestTheCompletionActuallyCompletes(_ServedTest):
    """The half that had never run."""

    def test_a_prompt_goes_out_and_parsed_json_comes_back(self):
        result = llm_backends.call_chat_json(
            "read this resume", self.server.base_url, PULLED)
        self.assertEqual(result, REPLY)

    def test_the_request_carries_the_model_and_the_prompt(self):
        llm_backends.call_chat_json("a prompt", self.server.base_url, PULLED)
        sent = _Handler.last_request

        self.assertEqual(sent["model"], PULLED)
        self.assertEqual(sent["messages"][0]["content"], "a prompt")
        self.assertFalse(sent["stream"], "streaming would break the parse")

    def test_a_fenced_reply_is_unwrapped(self):
        """
        Small local models fence their output far more often than Gemini
        does, which is the single most common reason a local reply fails to
        parse. This is the first test to prove the unwrapping works on a
        reply that arrived over a socket.
        """
        _Handler.content = "```json\n" + json.dumps(REPLY) + "\n```"
        result = llm_backends.call_chat_json("x", self.server.base_url, PULLED)
        self.assertEqual(result, REPLY)

    def test_an_api_key_is_sent_as_a_bearer_token(self):
        """The `openai` rung's only difference from `ollama`."""
        llm_backends.call_chat_json("x", self.server.base_url, PULLED,
                                    api_key="sk-test")
        self.assertEqual(_Handler.last_headers.get("Authorization"),
                         "Bearer sk-test")

    def test_no_key_sends_no_authorization_header(self):
        """Ollama has no account, so an empty Bearer would be a lie."""
        llm_backends.call_chat_json("x", self.server.base_url, PULLED)
        self.assertNotIn("Authorization", _Handler.last_headers)

    def test_a_server_error_raises_so_the_caller_can_fall_down_the_ladder(self):
        _Handler.status = 500
        with self.assertRaises(Exception):
            llm_backends.call_chat_json("x", self.server.base_url, PULLED)

    def test_an_unparseable_reply_raises_rather_than_returning_junk(self):
        _Handler.content = "I'm afraid I can't do that."
        with self.assertRaises(ValueError):
            llm_backends.call_chat_json("x", self.server.base_url, PULLED)


class TestTheWholeRungEndToEnd(_ServedTest):
    """
    `complete_json` is what resume import calls, so this is the path a real
    keyless user takes.
    """

    def setUp(self):
        super().setUp()
        import config
        self.config = config
        self.saved = (config.LLM_BACKEND, config.OLLAMA_API_URL,
                      config.OLLAMA_BASE_URL, config.OLLAMA_MODEL)
        config.LLM_BACKEND = "ollama"
        config.OLLAMA_API_URL = self.server.api_url
        config.OLLAMA_BASE_URL = self.server.base_url
        config.OLLAMA_MODEL = "llama3.1"

    def tearDown(self):
        (self.config.LLM_BACKEND, self.config.OLLAMA_API_URL,
         self.config.OLLAMA_BASE_URL, self.config.OLLAMA_MODEL) = self.saved
        super().tearDown()

    def test_complete_json_returns_a_parsed_object(self):
        self.assertEqual(llm_backends.complete_json("extract this"), REPLY)

    def test_it_calls_the_model_the_server_actually_has(self):
        """
        The A2 bug, end to end: config asks for `llama3.1`, the server has
        `llama3.1:latest`, and the call must not 404 on the difference.
        """
        llm_backends.complete_json("extract this")
        self.assertEqual(_Handler.last_request["model"], PULLED)

    def test_a_server_with_no_models_says_so_rather_than_going_quiet(self):
        """
        R47: this used to return None, which is what a deliberately keyless
        run returns. An Ollama that is up with nothing pulled is a
        misconfiguration the user can fix, and it now says which.
        """
        _Handler.models = []
        with self.assertRaises(llm_backends.BackendFailure) as caught:
            llm_backends.complete_json("extract this")
        self.assertIn("no model pulled", str(caught.exception))

    def test_resume_extraction_runs_on_this_rung(self):
        """
        The rung's actual job. `to_schema` hands the adapter a prompt and
        expects a schema back — which is how a keyless user gets a resume
        read at all.
        """
        from tools.resume import resume_import

        _Handler.content = json.dumps({
            "contact": {"name": "Jane Doe", "email": "jane@example.com"},
            "education": [],
            "experiences": [{"company": "Acme", "title": "Engineer",
                             "bullets": ["Did a thing"]}],
            "projects": [],
            "skills": {},
        })

        schema = resume_import.to_schema("some resume text",
                                         agent=llm_backends.complete_json)

        self.assertEqual(schema["contact"]["name"], "Jane Doe")
        self.assertEqual(len(schema["experiences"]), 1)


if __name__ == "__main__":
    unittest.main()


class TestWrapperStripping(unittest.TestCase):
    """
    R44: what a real model actually wrapped its JSON in.

    R43 tested this against a fake server, and a fake server returns exactly
    what the test told it to — so it only ever proved the stripper handles the
    wrapper the test already knew about. The first real reply from
    llama3.1:8b used a different one.
    """

    def _parse(self, raw):
        return json.loads(llm_backends._strip_code_fence(raw))

    def test_a_triple_backtick_fence_is_stripped(self):
        self.assertEqual(self._parse('```json\n{"n": 1}\n```'), {"n": 1})

    def test_a_single_backtick_span_is_stripped(self):
        """The real failure: every Ollama call died on this."""
        self.assertEqual(self._parse('`{"n": 1}`'), {"n": 1})

    def test_a_double_backtick_span_is_stripped(self):
        self.assertEqual(self._parse('``{"n": 1}``'), {"n": 1})

    def test_surrounding_whitespace_does_not_defeat_it(self):
        self.assertEqual(self._parse('  `{"n": 1}`  '), {"n": 1})

    def test_bare_json_is_left_alone(self):
        self.assertEqual(self._parse('{"n": 1}'), {"n": 1})

    def test_a_prose_preamble_is_deliberately_not_unwrapped(self):
        """
        This one must keep failing until there is a fabrication check.

        llama3.1:8b prefixes "Here is the rewritten JSON output:" — and the
        JSON behind that preamble invented metrics, a date and technologies
        that were never on the resume. Refusing to parse it is what sends
        generation to the verbatim floor, which uses the user's real bullets.
        If this test ever fails, read R44 before "fixing" it.
        """
        raw = 'Here is the rewritten JSON output:\n\n```\n{"n": 1}\n```'
        with self.assertRaises(ValueError):
            self._parse(raw)

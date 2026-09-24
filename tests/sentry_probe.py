"""
Run one Sentry scenario in a fresh process and print what would have been sent.

Not a test module (discovery collects `test*.py`); `test_handled_fallbacks_stay_quiet`
runs it as a subprocess, because the Sentry SDK is process-global: it patches
libraries once and keeps a client, and a scenario must not leak into the
suite's other tests or into the next scenario.

    python tests/sentry_probe.py <scenario>

Prints one JSON line: {"events": [...mechanism/message per event...], ...}.
Needs SENTRY_DSN set (a fake one: nothing is sent, a capturing transport
stands in for the network) and JOBSCOUT_HOME pointing at a scratch data home.
"""

import json
import logging
import sys
import threading
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sentry_sdk  # noqa: E402
from sentry_sdk.transport import Transport  # noqa: E402

EVENTS = []


class Capture(Transport):
    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.type == "event" and item.payload.json:
                EVENTS.append(item.payload.json)


def _install():
    real = sentry_sdk.init
    sentry_sdk.init = lambda **kw: real(transport=Capture, **kw)
    from tools.error_reporting import start_error_reporting
    assert start_error_reporting(), "SENTRY_DSN not set"


def _gemini_503(self, *args, **kwargs):
    from google.genai import errors
    raise errors.ServerError(503, {"error": {
        "code": 503, "status": "UNAVAILABLE",
        "message": "This model is currently experiencing high demand."}})


def _handled_503():
    """What generation does: the call fails, the fallback catches it."""
    import config
    from google.genai import _api_client, errors
    with mock.patch.object(_api_client.BaseApiClient, "request", _gemini_503):
        try:
            config.gemini_client("AQ.probe").models.generate_content(
                model="gemini-3.5-flash", contents="hi")
        except errors.ServerError:
            pass


def _handled_429_retries():
    """The retry helper running out on one model, before the next is tried."""
    from tools.cache import rate_limiter
    with mock.patch.object(rate_limiter.time, "sleep"):
        try:
            rate_limiter.retry_with_backoff(
                lambda: (_ for _ in ()).throw(RuntimeError("429 RESOURCE_EXHAUSTED")),
                max_retries=1, base_delay=0)
        except rate_limiter.RateLimitError:
            pass


def _wait(run_id):
    from agents import orchestrator
    deadline = time.monotonic() + 20
    status = None
    while time.monotonic() < deadline:
        status = orchestrator.run_status(None, run_id)
        if status and not status["active"]:
            break
        time.sleep(0.02)
    for thread in threading.enumerate():
        if thread.name.endswith(run_id):
            thread.join(20)
    return status


def scenario(name):
    from fastapi.testclient import TestClient
    import api.main as main
    from agents import orchestrator

    out = {}
    if name == "handled_503":
        _handled_503()
    elif name == "handled_429":
        _handled_429_retries()
    elif name == "api_run_503":
        class Pipeline:
            profile = None

            def __init__(self, **kwargs):
                pass

            def run(self, **kwargs):
                _handled_503()          # flash overloaded, caught
                _handled_429_retries()  # a model's retries run out, caught
                return {"generation_results": [{"status": "valid"}]}

        with mock.patch.object(orchestrator, "JobScoutOrchestrator", Pipeline):
            response = TestClient(main.app).post("/api/run", json={
                "profile": "priya_raghunathan", "generate_pdf": False,
                "api_key": "AQ.probe"})
            out["status_code"] = response.status_code
            out["run_state"] = _wait(response.json()["run_id"])["state"]
    elif name == "all_models_exhausted":
        # generation_agent's line when every model failed: still reported.
        logging.getLogger("agents.generation_agent").error(
            "   ❌ Gemini tailoring failed: ServerError: 503 UNAVAILABLE")
    elif name == "request_fails":
        with mock.patch.object(main, "start_run", side_effect=RuntimeError("boom")):
            response = TestClient(main.app, raise_server_exceptions=False).post(
                "/api/run", json={"profile": "priya_raghunathan"})
            out["status_code"] = response.status_code
    else:
        raise SystemExit(f"unknown scenario {name}")
    return out


if __name__ == "__main__":
    _install()
    result = scenario(sys.argv[1])
    sentry_sdk.flush(5)
    result["events"] = [
        {"mechanism": ((e.get("exception") or {}).get("values") or [{}])[-1]
         .get("mechanism"),
         "message": (e.get("logentry") or {}).get("message") or e.get("message")}
        for e in EVENTS]
    print("PROBE " + json.dumps(result))

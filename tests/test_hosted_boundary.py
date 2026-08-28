r"""
What changes about `api/main.py` the moment it is not on localhost.

Two things, and they are easy to conflate. The API now **serves the frontend**
from its own origin, and it now **has a door on it**.

The door exists because of something that was invisible while it worked: the
CORS list pinned the browser to `localhost:5173`, and that line — not any
deliberate decision — was the only reason nineteen unauthenticated endpoints
were unreachable. Deploying requires changing it. So a shared secret goes in
front until managed auth lands.

**This is authentication and not authorization**, and the tests say so in as
many words, because the gap between them is what ships broken: knowing the
password is not the same as owning the data. With one user those coincide.
The day there are two, every endpoint needs its own check and nothing in this
file will have started providing one.
"""

import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

SECRET = "correct-horse-battery-staple"


def _app(secret=None):
    """A freshly-imported app, because the gate reads the env at request time."""
    import api.main as main
    importlib.reload(main)
    return main


class TestTheDoorIsOnlyThereWhenAsked(unittest.TestCase):
    """
    A local run must be completely unaffected.

    The gate is scaffolding for one week of one deployed instance. If it made
    `uvicorn api.main:app` prompt for a password on a laptop, it would be a
    tax on the only workflow that exists today.
    """

    def test_nothing_is_gated_without_the_variable(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JOBSCOUT_ACCESS_SECRET", None)
            client = TestClient(_app().app)
            self.assertEqual(client.get("/api/health").status_code, 200)

    def test_the_variable_closes_everything(self):
        with mock.patch.dict(os.environ, {"JOBSCOUT_ACCESS_SECRET": SECRET}):
            client = TestClient(_app().app)
            self.assertEqual(client.get("/api/health").status_code, 401)
            self.assertEqual(
                client.get("/api/board").status_code, 401,
                "a second endpoint must not need its own guard — the "
                "middleware covers every route or it covers none reliably")

    def test_the_right_password_gets_in_and_a_wrong_one_does_not(self):
        with mock.patch.dict(os.environ, {"JOBSCOUT_ACCESS_SECRET": SECRET}):
            client = TestClient(_app().app)
            self.assertEqual(
                client.get("/api/health", auth=("any", SECRET)).status_code, 200)
            self.assertEqual(
                client.get("/api/health", auth=("any", "wrong")).status_code, 401)

    def test_a_missing_or_malformed_header_is_refused_not_crashed(self):
        """
        Garbage in the Authorization header is a 401, never a 500.

        A traceback here would be a stack trace served to an unauthenticated
        caller, which is a worse disclosure than the endpoint it was guarding.
        """
        with mock.patch.dict(os.environ, {"JOBSCOUT_ACCESS_SECRET": SECRET}):
            client = TestClient(_app().app)
            for header in ("", "Basic", "Basic !!!not-base64!!!",
                           "Bearer something", "Basic " + "eA=="):
                with self.subTest(header=header):
                    response = client.get(
                        "/api/health", headers={"Authorization": header})
                    self.assertEqual(response.status_code, 401)


class TestTheHealthCheckSaysNothingAboutThePerson(unittest.TestCase):
    """
    A liveness endpoint runs unauthenticated by definition, so its body is
    published. `/api/health` lists profile names, which are people's names.
    """

    def test_liveness_is_reachable_through_the_gate(self):
        with mock.patch.dict(os.environ, {"JOBSCOUT_ACCESS_SECRET": SECRET}):
            client = TestClient(_app().app)
            response = client.get("/healthz")
            self.assertEqual(response.status_code, 200,
                             "the host cannot health-check a gated endpoint")

    def test_liveness_leaks_nothing(self):
        with mock.patch.dict(os.environ, {"JOBSCOUT_ACCESS_SECRET": SECRET}):
            client = TestClient(_app().app)
            body = client.get("/healthz").json()
            self.assertEqual(body, {"ok": True})
            for leaky in ("profiles", "backend", "pdflatex"):
                self.assertNotIn(leaky, body,
                                 "/healthz must not become /api/health")


class TestServingTheFrontendDoesNotShadowTheApi(unittest.TestCase):
    """
    A mount at "/" matches every path. Declared before the routes it would
    swallow them, and the frontend would talk to a 404 that looked like a
    backend outage.
    """

    def test_the_static_mount_is_declared_after_every_api_route(self):
        source = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
        mount = source.index('app.mount("/"')
        last_route = source.rindex("@app.get(\"/api/")
        self.assertGreater(
            mount, last_route,
            "the static mount is declared before an /api route, so it "
            "swallows it — mount last, always")

    def test_the_api_still_answers_with_a_frontend_present(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JOBSCOUT_ACCESS_SECRET", None)
            main = _app()
            client = TestClient(main.app)
            self.assertEqual(client.get("/api/health").status_code, 200)

    def test_a_missing_build_is_a_normal_state(self):
        """
        `web/dist` is absent in a fresh checkout and absent from the wheel.

        Importing the API must not depend on someone having run `npm run
        build`, or the test suite and the CLI break on a machine that has
        never touched the frontend.
        """
        with mock.patch.dict(
                os.environ, {"JOBSCOUT_WEB_DIST": str(ROOT / "does-not-exist")}):
            main = _app()
            client = TestClient(main.app)
            self.assertEqual(client.get("/api/health").status_code, 200)
            self.assertEqual(client.get("/").status_code, 404)


class TestTheWriterAndTheReaderAgreeOnWhereOutputsLive(unittest.TestCase):
    r"""
    One root, two callers, and they are in different files.

    `JobScoutOrchestrator` writes generated resumes; `/api/file` serves them.
    Until this deploy both computed the location separately — the writer from
    `Path(output_dir)` and the reader from `Path.cwd() / "outputs"` — which
    are the same directory on a laptop and different ones in a container,
    where the working directory is an image layer and outputs live on a
    volume.

    The failure would have been silent in the worst way: `data/` on the volume
    so runs.db and the board survive a deploy, and every PDF the board links
    to gone. A job list that remembers everything and can produce nothing.

    This is the known fork in this codebase — a fix landing on the path the
    author walks — so the test is that the two agree, not that either is
    right on its own.
    """

    def test_both_sides_resolve_the_same_directory(self):
        from agents.orchestrator import outputs_root as writer_side
        import api.main as main
        importlib.reload(main)

        self.assertEqual(writer_side().resolve(),
                         main.outputs_root().resolve(),
                         "the writer and the reader disagree about where "
                         "generated resumes live")

    def test_a_relative_default_is_anchored_not_left_to_the_cwd(self):
        """
        The property that makes a container work, stated directly.

        `outputs_root()` must be absolute regardless of where the process was
        started from, or a `cd` changes where resumes are written.
        """
        from tools.paths import outputs_root
        self.assertTrue(outputs_root().is_absolute())
        self.assertTrue(outputs_root("outputs").is_absolute())

    def test_an_explicit_absolute_path_is_honoured(self):
        from tools.paths import outputs_root
        explicit = Path(ROOT / "some" / "elsewhere").resolve()
        self.assertEqual(outputs_root(str(explicit)), explicit)

    def test_the_data_home_moves_the_outputs_with_it(self):
        """
        `JOBSCOUT_HOME=/data` in the container has to carry outputs too.

        If it moved `data/` and left `outputs/` behind, the volume would hold
        the database and the image would hold the PDFs — which is exactly the
        split that loses them.
        """
        import tools.paths as paths
        with mock.patch.dict(os.environ, {"JOBSCOUT_HOME": str(ROOT / "tmp-home")}):
            importlib.reload(paths)
            self.assertEqual(paths.outputs_root(),
                             Path(ROOT / "tmp-home") / "outputs")
        importlib.reload(paths)


if __name__ == "__main__":
    unittest.main()

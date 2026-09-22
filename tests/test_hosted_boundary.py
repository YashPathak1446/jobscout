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
import tempfile
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

        # Unscoped and scoped both: since A3 the reader is
        # `user_outputs_root(user)`, and a fork that agrees for one user and
        # not the other is the two-paths shape again.
        for user in (None, "alice"):
            self.assertEqual(writer_side(user_id=user).resolve(),
                             main.user_outputs_root(user).resolve(),
                             f"the writer and the reader disagree about where "
                             f"generated resumes live (user {user!r})")

    def test_a_relative_default_is_anchored_not_left_to_the_cwd(self):
        """
        The property that makes a container work, stated directly.

        `outputs_root()` must be absolute regardless of where the process was
        started from, or a `cd` changes where resumes are written.
        """
        from tools.paths import outputs_root
        self.assertTrue(outputs_root(user_id=None).is_absolute())
        self.assertTrue(outputs_root("outputs", user_id=None).is_absolute())

    def test_an_explicit_absolute_path_is_honoured(self):
        from tools.paths import outputs_root
        explicit = Path(ROOT / "some" / "elsewhere").resolve()
        self.assertEqual(outputs_root(str(explicit), user_id=None), explicit)

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
            self.assertEqual(paths.outputs_root(user_id=None),
                             Path(ROOT / "tmp-home") / "outputs")
        importlib.reload(paths)

    def test_the_upload_writer_and_reader_agree(self):
        """
        The same fork as this class's other tests, one directory over.

        `extract_resume` **writes** an uploaded resume through
        `init_profile.resume_dir`; `_resolve_upload` **reads** it back on the
        wizard's confirm step. `api/main.py` once recomputed that root as
        `Path.cwd() / "data" / "master_resumes"` — identical in a checkout,
        `/app/data/...` against `/data/data/...` in the container, where the
        upload 404s on a file the previous request just saved.

        This is the fifth site of R86's bug and the only one the acceptance
        run cannot see: the harness calls `create_profile` directly and never
        walks `POST /api/profile`. So the gate stayed green on an instance
        where nobody could onboard.

        **The data home has to be moved for this test to mean anything.** In a
        checkout `Path.cwd()` and `data_home()` are the same directory, so
        comparing the two roots here passes against the broken code and proves
        nothing — the first draft of this test did exactly that. Pointing
        `JOBSCOUT_HOME` somewhere else reproduces the container, where the two
        diverge, which is the only place the bug exists.

        Since A3 the root is a function of the user rather than an import-time
        constant, so there is nothing to reload — and the reader holding the
        writer's *function* is the claim, not two values that happen to match.
        """
        import scripts.init_profile as init_profile
        import api.main as main

        self.assertIs(main.resume_dir, init_profile.resume_dir,
                      "the module that reads an upload back resolves its "
                      "directory some other way than the module that wrote it")

        with tempfile.TemporaryDirectory() as home:
            with mock.patch.dict(os.environ, {"JOBSCOUT_HOME": home}):
                for user, expected in (
                        (None, Path(home) / "data" / "master_resumes"),
                        ("alice", Path(home) / "users" / "alice" / "data"
                         / "master_resumes")):
                    self.assertEqual(main.resume_dir(user), expected)
                    self.assertNotEqual(
                        main.resume_dir(user),
                        Path.cwd() / "data" / "master_resumes",
                        "the reader is resolving uploads against the working "
                        "directory, which is an image layer in the container "
                        "and not where the writer put the file")


class TestTheShippingImageKeepsItsDataOffTheImageLayer(unittest.TestCase):
    r"""
    A guard that used to be two conditions and is now one.

    `paths.in_checkout()` is `pyproject.toml is_file() AND tests/ is_dir()`.
    The shipping image now carries `tests/fixtures/` — the acceptance gate is
    the deploy's exit condition and reads its frozen corpus from
    `ROOT/tests/fixtures/`, so without it the gate cannot run on the instance
    at all. That makes the second condition True in `runtime`.

    What remains between the container and a data home at `/app` is
    `pyproject.toml` not being copied. If it ever were, `in_checkout()` would
    go True and every profile, database and generated PDF would be written
    into an image layer that is replaced on the next deploy.

    `JOBSCOUT_HOME=/data` outranks `in_checkout()` and is set in both the
    Dockerfile and fly.toml, so this is defence in depth rather than the only
    thing standing there. It is a test and not a comment because the comment
    that described the old two-condition guard was wrong the moment the
    fixtures COPY landed, and nobody was editing it.
    """

    def test_the_runtime_stage_never_copies_pyproject(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        marker = "FROM runtime AS verify"
        self.assertIn(marker, dockerfile,
                      "the verify stage is how this test knows where the "
                      "shipping image ends")
        runtime_half = dockerfile.split(marker)[0]

        # COPY lines only. The prose above that *explains* this trap names
        # pyproject.toml, and an explanation of a rule is not a breach of it
        # (R80) — matching the whole text would fail on its own documentation.
        copied = [line.strip() for line in runtime_half.splitlines()
                  if line.strip().upper().startswith("COPY")]

        offenders = [line for line in copied if "pyproject.toml" in line]
        self.assertEqual(offenders, [],
                         "copying pyproject.toml into the shipping image "
                         "flips paths.in_checkout() to True and moves the "
                         "data home to /app, an image layer replaced on "
                         "every deploy")

    def test_the_gate_can_find_its_corpus_in_the_shipping_image(self):
        """
        The other half: the COPY that thinned the guard has to still be there.

        If someone removes it to restore the old two-condition guard, the
        deploy goes back to shipping an image whose acceptance run dies on a
        missing corpus — which is what this whole arrangement exists to fix.
        """
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        runtime_half = dockerfile.split("FROM runtime AS verify")[0]

        self.assertIn("COPY tests/fixtures/", runtime_half,
                      "the shipping image cannot run scripts/acceptance.py "
                      "without tests/fixtures/ — see acceptance.py:69")


if __name__ == "__main__":
    unittest.main()

r"""
The scope seam: every store answers "whose?" (pilot plan A3).

`test_two_users.py` says what a second person must not be able to do to the
first. This module pins the mechanism that makes that true, and the rules that
keep it true once nobody is looking at it:

* **The seam itself.** `tools.paths.user_home(user_id)` has no default. `None`
  is the unscoped layout — the checkout — and is `data_home()` itself; a string
  is `data_home()/users/<id>/`; leaving the argument out is a `TypeError`.
* **Every store is per user**, including the ones with no error path. The
  embedding cache was a module-level singleton, and wrong vectors for the right
  text still produce a plausible score — so its test counts API calls, which
  is the only place the difference shows.
* **The closing rule (the R80 shape).** Four caches were found by reading; a
  fifth will be found by this test, because it walks the syntax tree of every
  module a hosted request can reach and fails on a path resolved at import or
  a directory spelled as a literal. It checks itself against known-bad source
  first, so the mutation proof is part of the suite rather than a claim in a
  commit message.
* **The gap A5 closes, counted.** `api/main.py` passes `None` as the user at
  every call site, because there is no session yet. The expected failure below
  says so in the only form that cannot be quietly forgotten.
"""

import ast
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools import paths  # noqa: E402

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - fastapi is optional for the CLI
    TestClient = None


class _MovedHome(unittest.TestCase):
    """A data home of its own, so nothing here touches the checkout's."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.home = Path(self._dir.name)
        self._env = mock.patch.dict(os.environ, {paths.HOME_ENV: str(self.home)})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._dir.cleanup()


class TestTheSeam(_MovedHome):

    def test_unscoped_is_the_data_home_itself(self):
        self.assertEqual(paths.user_home(None), paths.data_home())

    def test_a_scoped_user_lives_under_users(self):
        self.assertEqual(paths.user_home("alice"),
                         self.home / paths.USERS_DIR / "alice")

    def test_an_omitted_user_is_an_error_not_a_default(self):
        """An ambient default is unknown rendered as a value."""
        with self.assertRaises(TypeError):
            paths.user_home()                                   # noqa
        with self.assertRaises(TypeError):
            paths.user_path("data", "jobs.db")                  # noqa
        with self.assertRaises(TypeError):
            paths.outputs_root()                                # noqa

    def test_the_old_positional_spelling_cannot_become_a_user(self):
        """
        `user_path("data", "jobs.db")` was the whole signature before A3. Had
        the id become the first positional argument, that call would have
        quietly made "data" a user. Keyword-only is what prevents it.
        """
        with self.assertRaises(TypeError):
            paths.user_path("data", "jobs.db", None)            # noqa

    def test_an_id_that_is_not_an_id_is_refused(self):
        for bad in ("..", "../bob", "a/b", "a\\b", "", "Alice", "a.b",
                    "https://x.test/1", "x" * 65, 7, b"alice"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    paths.user_home(bad)

    def test_a_stored_path_resolves_inside_its_owners_home(self):
        self.assertEqual(
            paths.stored_path("data/master_resumes/x.tex", user_id="alice"),
            self.home / "users" / "alice" / "data" / "master_resumes" / "x.tex")
        self.assertEqual(
            paths.stored_path("data/master_resumes/x.tex", user_id=None),
            self.home / "data" / "master_resumes" / "x.tex")

    def test_a_scoped_user_cannot_point_at_someone_elses_file(self):
        """
        Absolute paths are honoured unscoped — a CLI user may keep their resume
        anywhere — and refused scoped, or one profile field reads another
        person's resume.
        """
        bob = self.home / "users" / "bob" / "data" / "master_resumes" / "b.tex"
        self.assertEqual(paths.stored_path(str(bob), user_id=None), bob)
        with self.assertRaises(ValueError):
            paths.stored_path(str(bob), user_id="alice")


class TestEveryStoreIsPerUser(_MovedHome):

    def test_a_run_id_is_not_found_in_someone_elses_registry(self):
        from agents.orchestrator import _registry, run_status

        with _registry("alice") as registry:
            run_id = registry.create("alices_profile")

        self.assertIsNotNone(run_status("alice", run_id))
        self.assertIsNone(run_status("bob", run_id),
                          "one user can read another's run by guessing its id")
        self.assertIsNone(run_status(None, run_id))

    def test_a_past_run_outside_your_outputs_cannot_be_opened(self):
        from agents.orchestrator import load_run, user_outputs_root

        theirs = user_outputs_root("bob") / "2026-09-22"
        theirs.mkdir(parents=True)
        (theirs / "state.json").write_text('{"profile": "bob"}', encoding="utf-8")

        self.assertEqual(load_run("bob", str(theirs))["profile"], "bob")
        with self.assertRaises(ValueError):
            load_run("alice", str(theirs))

    def test_the_learned_company_list_is_per_user(self):
        """Decided 2026-09-22: B's discovery must not move with A's searches."""
        from tools.search.ats_search import harvest_slugs, load_companies

        harvest_slugs(["https://boards.greenhouse.io/zz-alice-only/jobs/1"],
                      user_id="alice")

        self.assertIn("zz-alice-only",
                      load_companies(user_id="alice").get("greenhouse", []))
        self.assertNotIn("zz-alice-only",
                         load_companies(user_id="bob").get("greenhouse", []),
                         "one user's learned slugs reached another's discovery")
        self.assertNotIn("zz-alice-only",
                         load_companies(user_id=None).get("greenhouse", []))

    def test_profiles_written_for_one_user_are_listed_for_that_user_only(self):
        from agents.orchestrator import available_profiles
        from scripts import init_profile

        where = init_profile.profiles_dir("alice")
        where.mkdir(parents=True)
        (where / "alices.json").write_text("{}", encoding="utf-8")

        self.assertEqual(available_profiles("alice"), ["alices"])
        self.assertEqual(available_profiles("bob"), [])

    def test_the_writer_and_the_loader_resolve_profiles_one_way(self):
        """R86's shape: two spellings of one directory, until a container."""
        from scripts import init_profile
        from tools.profile.profile_loader import profiles_dir

        for user in (None, "alice"):
            self.assertEqual(init_profile.profiles_dir(user), profiles_dir(user))

    def test_every_cache_directory_moves_with_its_user(self):
        import config
        from tools.cache import embedding_cache, job_cache

        for resolve in (config.llm_cache_dir, config.embedding_cache_dir,
                        job_cache.cache_dir, embedding_cache.cache_dir):
            with self.subTest(cache=resolve.__module__ + "." + resolve.__name__):
                alice = resolve("alice")
                self.assertEqual(alice.relative_to(self.home).parts[:2],
                                 ("users", "alice"))
                self.assertNotEqual(alice, resolve("bob"))
                self.assertNotEqual(alice, resolve(None))


class TestTheEmbeddingCacheIsNotOnePerProcess(_MovedHome):
    """
    The landmine (A3): `_EMBEDDING_CACHE` was built by whichever request came
    first and inherited by every later user in the process.

    **This has no error path**, so it is tested where the difference shows:
    how many times the embedding API is actually asked. A second user
    embedding the same text must be a miss in *their* cache. Served from the
    first user's, they get a vector — a correct one here, which is what makes
    the failure invisible in a score, and a stale or wrong-model one in
    general.
    """

    def setUp(self):
        super().setUp()
        import google.genai as genai
        import tools.resume.embedding_scorer as scorer

        self.calls = []
        calls = self.calls

        class FakeClient:
            def __init__(self, api_key=None):
                self.models = self

            def embed_content(self, **kwargs):
                calls.append(kwargs["contents"])

                class R:
                    embeddings = [type("V", (), {"values": [0.6, 0.8]})()]
                return R()

        self.scorer = scorer
        for patcher in (
            mock.patch.object(genai, "Client", FakeClient),
            # Two dimensions so the stub vector passes R28's length guard.
            mock.patch.object(scorer, "active_backend",
                              lambda: ("gemini", "test-model", 2)),
            # A fresh memo, so nothing here outlives the test.
            mock.patch.object(scorer, "_EMBEDDING_CACHES", {}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_second_user_does_not_read_the_first_users_vectors(self):
        self.scorer._get_embedding("same text", user_id="alice")
        self.scorer._get_embedding("same text", user_id="alice")
        self.assertEqual(len(self.calls), 1, "a user's own cache must still hit")

        self.scorer._get_embedding("same text", user_id="bob")
        self.assertEqual(
            len(self.calls), 2,
            "the second user was served the first user's cached vector")

    def test_each_users_vectors_are_written_under_their_own_home(self):
        import config

        self.scorer._get_embedding("some text", user_id="alice")

        self.assertTrue(any(config.embedding_cache_dir("alice").iterdir()))
        self.assertFalse(config.embedding_cache_dir("bob").exists())
        self.assertFalse(config.embedding_cache_dir(None).exists())

    def test_one_user_gets_one_cache(self):
        """The memo still memoises — per directory, not per process."""
        self.assertIs(self.scorer._embedding_cache("alice"),
                      self.scorer._embedding_cache("alice"))
        self.assertIsNot(self.scorer._embedding_cache("alice"),
                         self.scorer._embedding_cache("bob"))


# --------------------------------------------------------------------------
# The closing rule
# --------------------------------------------------------------------------

# Every module a hosted request can reach. `test_ui_contract` pins the views
# to `agents.orchestrator` and `scripts.init_profile`, and those import only
# from `agents/`, `tools/` and `config`. The other scripts are CLI entry points
# — the unscoped layout by definition — and are not reachable from a request.
REACHABLE = ("tools/**/*.py", "agents/*.py", "config.py",
             "scripts/init_profile.py", "api/main.py", "app.py")

# The functions that resolve user data. A call to one of these at module level
# ran before anybody said whose data it was, so it can only ever be one
# person's.
RESOLVERS = {"user_path", "user_home", "data_home", "outputs_root",
             "stored_path", "db_path", "cache_dir", "learned_file",
             "profiles_dir", "resume_dir", "llm_cache_dir",
             "embedding_cache_dir", "user_outputs_root"}

# Names that hold a location. A string literal bound to one is a path that
# did not come from `tools.paths` — which is what all four caches were.
LOCATION = re.compile(r"(?i)(.*_(dir|db|file|home|root)$|^cache.*|^profiles$)")

# Every exemption, with why. An entry that stops matching fails the build too.
EXEMPT = {
    # The resolver itself: `users` is the name of the directory it builds.
    ("tools/paths.py", "USERS_DIR"):
        "the partition's own directory name, inside the resolver",
    # A *name* under the user's home, never resolved on its own: every one of
    # these reaches `paths.outputs_root(output_dir, user_id=...)`, which is
    # what anchors it (and what `test_hosted_boundary` holds to that).
    ("tools/paths.py", "outputs_root.output_dir"):
        "a name anchored by outputs_root itself",
    ("agents/orchestrator.py", "previous_runs.output_dir"):
        "passed to outputs_root(output_dir, user_id=user_id)",
    ("agents/orchestrator.py", "start_run.output_dir"):
        "passed to JobScoutOrchestrator, which anchors it via outputs_root",
    ("agents/orchestrator.py", "__init__.output_dir"):
        "passed to outputs_root(output_dir, user_id=user_id)",
}


def _violations(source: str, where: str) -> list:
    """(where, name, why) for each path this source resolves outside the seam."""
    found = []
    tree = ast.parse(source)

    def callee(node):
        return (node.func.attr if isinstance(node.func, ast.Attribute)
                else getattr(node.func, "id", None))

    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        targets = [t.id for t in (node.targets if isinstance(node, ast.Assign)
                                  else [node.target])
                   if isinstance(t, ast.Name)]
        for inner in ast.walk(node.value):
            if isinstance(inner, ast.Call) and callee(inner) in RESOLVERS:
                for name in targets:
                    found.append((where, name, f"resolved at import by "
                                               f"{callee(inner)}() (line {node.lineno})"))
        if (isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            for name in targets:
                if LOCATION.match(name):
                    found.append((where, name, f"the literal {node.value.value!r} "
                                               f"(line {node.lineno})"))

    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = fn.args
        positional = args.posonlyargs + args.args
        pairs = list(zip(positional[len(positional) - len(args.defaults):],
                         args.defaults))
        pairs += [(a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults)
                  if d is not None]
        for arg, default in pairs:
            if (isinstance(default, ast.Constant) and isinstance(default.value, str)
                    and LOCATION.match(arg.arg)):
                found.append((where, f"{fn.name}.{arg.arg}",
                              f"defaults to the literal {default.value!r} "
                              f"(line {fn.lineno})"))
    return found


class TestTheClosingRule(unittest.TestCase):

    def test_the_rule_catches_what_it_exists_to_catch(self):
        """
        The mutation proof, kept. Each of these is a shape a store has
        actually had in this repository; the rule must flag every one, or a
        green run of the test below proves nothing.
        """
        cases = {
            "cache #5, a literal": 'DEFAULT_CACHE_DIR = "cache"\n',
            "a constructor default": 'def __init__(self, cache_dir: str = ".cache/new"): pass\n',
            "a store resolved at import":
                'DEFAULT_DB = paths.user_path("data", "x.db", user_id=None)\n',
            "the pre-A3 spelling": 'LEARNED_FILE = paths.user_path("data", "a.json")\n',
            "the profiles constant": 'PROFILES = user_path("user_profiles", user_id=None)\n',
            "a keyword-only default": 'def f(*, llm_dir="x"): pass\n',
        }
        for label, source in cases.items():
            with self.subTest(label):
                self.assertTrue(_violations(source, "<mutation>"),
                                f"the rule does not see {label}")

        # And it does not fire on what the seam produces.
        self.assertEqual(_violations(
            "def cache_dir(user_id):\n"
            "    return paths.user_path('cache', user_id=user_id)\n", "<ok>"), [])

    def test_no_store_resolves_a_path_outside_paths(self):
        found = []
        for pattern in REACHABLE:
            for path in sorted(ROOT.glob(pattern)):
                where = path.relative_to(ROOT).as_posix()
                found += _violations(path.read_text(encoding="utf-8"), where)

        unexplained = [v for v in found if (v[0], v[1]) not in EXEMPT]
        self.assertEqual(
            unexplained, [],
            "a store resolves a path that did not come from tools.paths for a "
            "named user. Resolve it per call through a `*(user_id)` function "
            "(see job_store.db_path); if it genuinely is not user data, add it "
            "to EXEMPT with the reason.")

        stale = sorted(set(EXEMPT) - {(v[0], v[1]) for v in found})
        self.assertEqual(stale, [], "EXEMPT names something that no longer exists")


# --------------------------------------------------------------------------
# The gap A5 closes
# --------------------------------------------------------------------------

API = ROOT / "api" / "main.py"

# The calls in api/main.py whose first argument is the user. Collected from
# the facade rather than listed by hand, so a scoped function added later is
# counted without anyone remembering to add it here.
def _scoped_callees() -> set:
    import inspect

    import agents.orchestrator as orchestrator
    from scripts import init_profile

    names = set()
    for module in (orchestrator, init_profile):
        for name, value in vars(module).items():
            if inspect.isfunction(value) and value.__module__ == module.__name__:
                params = list(inspect.signature(value).parameters)
                if params and params[0] == "user_id":
                    names.add(name)
    return names | {"_resolve_upload"}


def _unscoped_call_sites() -> list:
    """Every call in api/main.py that passes `None` as the user."""
    scoped = _scoped_callees()
    sites = []
    for node in ast.walk(ast.parse(API.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        name = (node.func.attr if isinstance(node.func, ast.Attribute)
                else getattr(node.func, "id", None))
        if name not in scoped:
            continue
        user = node.args[0] if node.args else next(
            (k.value for k in node.keywords if k.arg == "user_id"), None)
        if isinstance(user, ast.Constant) and user.value is None:
            sites.append(f"api/main.py:{node.lineno} {name}(None, ...)")
    return sites


# Board and run routes a hosted request reaches without a body, and the
# facade calls each makes. Returns shaped so each route completes.
_PROBES = ("/api/health", "/api/board", "/api/board/stats", "/api/board/filters",
           "/api/board/bands", "/api/board/ghosted", "/api/run", "/api/runs")
_RETURNS = {"board_total": 0, "board_jobs": [], "board_stats": {},
            "board_filters": {}, "score_bands": {}, "ghosted_jobs": [],
            "active_runs": [], "previous_runs": [], "available_profiles": []}


def _users_served_in_hosted_mode() -> tuple:
    """
    (route -> the user argument every facade call it made received, and the
    id of the account the probe was signed in as).

    Hosted mode for real: a data home of its own, an account in it, and a
    session cookie minted by signing in through the route. Each route is
    probed once with that cookie, so the answer to "who was served" can be
    compared with who asked.
    """
    import api.main as main
    from tests.signed_in import client, hosted, make_account

    served = {route: [] for route in _PROBES}
    current = {}

    def recorder(name):
        def call(user_id, *args, **kwargs):
            served[current["route"]].append((name, user_id))
            return _RETURNS[name]
        return call

    with tempfile.TemporaryDirectory() as home, hosted(home):
        caller = make_account("probe@example.com")
        signed_in = client(main.app, email="probe@example.com")
        patches = [mock.patch.object(main, name, recorder(name)) for name in _RETURNS]
        # Not a scoped call, and on a Linux box without LaTeX `find_pdflatex`
        # raises rather than returning None (logged as its own finding).
        patches.append(mock.patch.object(main, "pdflatex_available", lambda: False))
        for p in patches:
            p.start()
        try:
            for route in _PROBES:
                current["route"] = route
                signed_in.get(route)
        finally:
            for p in reversed(patches):
                p.stop()
    return served, caller


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestHostedModeNamesItsCaller(unittest.TestCase):
    """
    Until A5, `api/main.py` served every caller as `None` — one directory for
    everybody — because there was no session to name a caller with. On
    localhost that is correct. Hosted, it was the partition built and not used.

    Counted two ways, so neither can be satisfied by accident: statically (no
    call site passes a literal `None`, which is mode-blind by construction) and
    at runtime (with `JOBSCOUT_MODE=hosted`, no facade call a route makes
    receives anyone but the signed-in caller). Local mode still gets `None`,
    out of `api.main._caller` rather than a literal at a call site.
    """

    def test_the_count_is_counting_something(self):
        """
        Keeps the expected failure below honest. An expected failure that fails
        because the harness broke looks exactly like one that fails because the
        gap is real; this passes now and after A5, and only a broken harness
        fails it.
        """
        self.assertIn("board_jobs", _scoped_callees())
        served, _ = _users_served_in_hosted_mode()
        silent = [route for route, calls in served.items() if not calls]
        self.assertEqual(silent, [], "these routes reached no facade call, so "
                                     "the hosted-mode probe says nothing about them")

    # Flipped at A5: the session names the caller. Stronger than "not None",
    # which a route serving the wrong user would also pass — every call must
    # be served as exactly the account that signed in.
    def test_hosted_mode_has_no_unscoped_call_site(self):
        self.assertEqual(_unscoped_call_sites(), [],
                         "api/main.py serves these calls as the unscoped user")
        served, caller = _users_served_in_hosted_mode()
        wrong = sorted({f"{route} -> {name}({user!r})"
                        for route, calls in served.items()
                        for name, user in calls if user != caller})
        self.assertEqual(wrong, [],
                         f"in hosted mode these routes serve someone other than "
                         f"the caller ({caller!r})")


# --------------------------------------------------------------------------
# The instrument
# --------------------------------------------------------------------------

class TestThePathSnapshotHolds(unittest.TestCase):
    """
    `scripts/path_snapshot.py verify` is how A3's hard constraint — the
    unscoped layout does not move — is checked, and how every later stage
    re-checks it. It must pass, and it must not create what it reports.
    """

    def test_the_unscoped_layout_has_not_moved(self):
        from scripts import path_snapshot
        self.assertEqual(path_snapshot.verify(), [])

    def test_resolving_creates_nothing(self):
        from scripts import path_snapshot

        with tempfile.TemporaryDirectory() as home:
            with mock.patch.dict(os.environ, {paths.HOME_ENV: home}):
                path_snapshot.snapshot(None)
                path_snapshot.snapshot(path_snapshot.PROBE_USER)
                self.assertEqual(list(Path(home).iterdir()), [],
                                 "the snapshot made the directories it reports")


if __name__ == "__main__":
    unittest.main()

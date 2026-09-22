r"""
Two people on one instance, before anything is partitioned (pilot plan A2).

JobScout has had exactly one user, and every store it owns is addressed as
though that will stay true: one `data/jobs.db`, one `data/runs.db`, one
`user_profiles/`, one `outputs/<date>/`. None of that is a bug for one person
and all of it is a bug for two, so the four tests here put two people into one
data home and assert what a second user must not be able to do to the first.

**The six assertions here are `unittest.expectedFailure`, each with a comment
naming the stage that should flip it.** They are written now, before the fix,
because a test written after the partition would be checking that the code
does what it does; these say what the partition is *for*. That is the whole
deliverable of A2 -- nothing here ships a fix.

Expected-failure rather than deleted-until-A3 so the suite stays green on the
way there, and rather than commented out so that fixing one is *noisy*: an
expected failure that passes is an unexpected success, which `unittest` counts
against `wasSuccessful()`. Whoever lands A3 gets a red build telling them to
drop the decorator, instead of a silently-passing test nobody re-reads.

Two people, not two homes. `JOBSCOUT_HOME` points both users at **one**
directory on purpose: pointing A and B at separate homes is the fix wearing a
test's clothes, and all four would pass today against unchanged code. The
partition A3 adds goes *inside* this home, so these tests keep their setup and
flip to green without being rewritten to agree with the implementation.

A3 does have to touch the call sites, because every facade function named here
grows a leading `user_id`. The assertions are the load-bearing half and must
survive that edit unchanged; a diff that weakens one of them has abandoned the
test rather than satisfied it.

The second user is **Rohan Deshmukh**, imported by `scripts/init_profile` from
`tests/fixtures/resume_two_degrees_non_us.txt` -- a stranger's resume this
repository did not write -- and deliberately *not* derived from Priya, who is
invented here and would therefore agree with us (R77, R78). The pair differ in
what `gate_fingerprint` hashes (`job_filter.py:775-800`): Priya answers
`years_experience: 6`, Rohan's is `None`, the unanswered state a freshly
imported profile actually carries. Without that difference test 1 cannot fire
at all, so it is asserted below rather than assumed.

## What a red test here does and does not prove yet

Six assertions fail today. Setting `USER_B = USER_A` -- collapsing the two
people into one and changing nothing else -- separates them into two groups,
and the difference matters when reading a failure:

**Discriminating now.** The storm (A2.1) and the overwritten `state.json`
(A2.3b) both go green under that mutation. They fail because a *second person*
exists, which is the claim they make.

**Not discriminating yet**, and red under the mutation too:

* A2.2's bands. `score_bands()` takes no user, so "B's scores moved A's bands"
  and "A scored eight more jobs" are the same call today. The assertion names
  the invariant A3 creates; it cannot isolate it before the seam exists.
* A2.3a's shared directory. `outputs_root(...) / date` has keyed on the date
  alone since it was written, so one person running twice in a day already
  collapses into one directory. Two users is where that stops being a display
  limit and starts losing someone else's record -- which is what its companion
  above measures.
* Both of A2.4's. There is no session, so there is no caller to be the wrong
  one. These need the partition (A3) *and* identity (A5/A6) before the
  assertion can tell "mine" from "theirs".

Stated rather than tidied away: a test that fails for the right reason only
after two more stages is still worth writing now, but it is not evidence of
today's bug on its own, and reading it as though it were is how a suite ends
up agreeing with itself.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - fastapi is optional for the CLI
    TestClient = None

# Each fixture user's id is their profile's name, so one constant names both
# the person and the profile they import under. Both match the user-id pattern
# `tools.paths` enforces; the mutation check below collapses the *person*, and
# the profile collapses with them, which is what "the same user" means.
USER_A = "priya_raghunathan"
USER_B = "rohan_deshmukh"


def _as_the_api_serves(user):
    """
    Whose data a request from `user` is served as, today.

    `None` for every caller until A5/A6: there is no session, so `api/main.py`
    passes the unscoped user at every call site (and
    `test_hosted_mode_has_no_unscoped_call_site` counts them). A5 replaces
    this body with the caller's identity; the assertions below do not change.

    It exists because after A3 a run recorded under A's *own* id lives in A's
    own `runs.db`, which the API never reads — so the API tests would pass
    against an unscoped API simply by reading an empty third home. That is a
    green that proves nothing about the route, and the mutation check exists
    to catch exactly that. Recording A's run the way the API records it keeps
    those tests red for the reason they name.
    """
    return None


class _Listing:
    """What discovery hands the store. Only the fields `record` reads."""

    def __init__(self, url, title="Software Engineer", jd="A Python role."):
        self.apply_url = url
        self.id = url
        self.title = title
        self.company = "Example"
        self.location = "Boston, MA"
        self.source = "test"
        self.full_jd = jd


class _OneInstance(unittest.TestCase):
    """
    One data home, two users in it -- the hosted instance as it stands today.

    Each user's profile and master resume are placed where that user's data
    lives, and once more in the unscoped home, which is where the API serves
    every caller from until A5 (`_as_the_api_serves`). Before A3 the unscoped
    home was the only one; the per-user copies are what the partition reads.

    Nothing is reloaded. Until A3 the two stores resolved their path at import
    time and this class had to reload both under the moved home; since A3
    every path is a function of the user, resolved per call, and follows
    `JOBSCOUT_HOME` without help.
    """

    def setUp(self):
        from tools import paths

        self._dir = tempfile.TemporaryDirectory()
        self.home = Path(self._dir.name)

        self._env = mock.patch.dict(os.environ,
                                    {"JOBSCOUT_HOME": str(self.home)})
        self._env.start()

        for name in (USER_A, USER_B):
            for owner in (None, name):
                where = paths.user_home(owner)
                (where / "user_profiles").mkdir(parents=True, exist_ok=True)
                (where / "data" / "master_resumes").mkdir(parents=True,
                                                          exist_ok=True)
                shutil.copy(ROOT / "user_profiles" / f"{name}.json",
                            where / "user_profiles" / f"{name}.json")
                master = ROOT / "data" / "master_resumes" / f"{name}.tex"
                if master.is_file():
                    shutil.copy(
                        master,
                        where / "data" / "master_resumes" / f"{name}.tex")

    def tearDown(self):
        self._env.stop()
        self._dir.cleanup()

    def _store(self, user):
        from tools.jobs.job_store import JobStore, db_path
        return JobStore(db_path(user))


class TestTheGateIsNotRejudgedForEveryUserInTurn(_OneInstance):
    """
    A2.1 -- the write storm.

    `job_store.refresh_gate` (`:205-232`) re-judges every row whose stored
    `gate_checked` differs from the fingerprint it is handed, and both UIs call
    it before each board render because after the first pass it is meant to
    match nothing. With two profiles sharing one `jobs.db` the fingerprints
    alternate, so every render re-judges the whole table and overwrites the
    other user's `gate_reason` on the way through -- an O(n) write per page
    view and the wrong eligibility for both people.

    **Predicted failure:** the third call returns 2 (every row), not 0.
    """

    def setUp(self):
        super().setUp()
        # Both people discovered the same two postings, as two people
        # searching for similar roles will.
        for user in (USER_A, USER_B):
            store = self._store(user)
            try:
                store.record([
                    _Listing("https://example.com/a", "Engineer I",
                             "An entry-level role in Python."),
                    _Listing("https://example.com/b", "Engineer II",
                             "A backend role in Python and Go."),
                ])
            finally:
                store.close()

    def test_the_two_profiles_are_judged_differently(self):
        """
        The precondition. Identical fingerprints would make the storm test
        below pass for a reason that has nothing to do with partitioning.
        """
        from tools.jobs.job_filter import gate_fingerprint
        from tools.profile import load_profile

        self.assertNotEqual(gate_fingerprint(load_profile(USER_A, user_id=None)),
                            gate_fingerprint(load_profile(USER_B, user_id=None)),
                            "the two fixture users hash the same, so the "
                            "storm test below cannot fire")

    # Flipped at A3: `refresh_board_gate` is scoped to one user's store,
    # so B's fingerprint never touches A's rows and the third call matches
    # nothing.
    def test_returning_to_the_first_user_rejudges_nothing(self):
        from agents.orchestrator import refresh_board_gate

        self.assertEqual(refresh_board_gate(USER_A, USER_A), 2,
                         "the first pass should judge both rows")
        refresh_board_gate(USER_B, USER_B)

        self.assertEqual(
            refresh_board_gate(USER_A, USER_A), 0,
            "a second user rendering their board invalidated the first "
            "user's verdicts; every render is now a write over the whole "
            "table")


class TestOneUsersScoresDoNotMoveAnothersBands(_OneInstance):
    """
    A2.2 -- the quartiles.

    `job_store.score_bands` (`:414-448`) cuts quartiles over every scored row
    in the table, and its docstring says why that must be per-person: "a resume
    and a corpus this has never seen will produce a different band of raw
    similarities, and constants tuned to one person would be wrong for everyone
    else." Two users in one table makes the docstring's own claim false -- B's
    corpus re-labels A's matches.

    **Predicted failure:** A's bands move the moment B is scored -- `n` doubles
    to 16 and `high` jumps from A's ceiling to B's.
    """

    def _score(self, user, prefix, score):
        store = self._store(user)
        try:
            listings = [_Listing(f"https://example.com/{prefix}{i}")
                        for i in range(8)]
            store.record(listings)
            for listing in listings:
                store.set_score(listing.apply_url, score)
        finally:
            store.close()

    # Flipped at A3: each user has their own `jobs.db`, so the quartiles
    # are cut over one person's scores again — which `score_bands`' own
    # docstring already claimed they were.
    def test_the_first_users_bands_are_unchanged_by_the_second(self):
        from agents.orchestrator import score_bands

        self._score(USER_A, "a", 40.0)
        before = score_bands(USER_A)
        self.assertTrue(before, "8 scored jobs should be enough to band")

        self._score(USER_B, "b", 90.0)

        self.assertEqual(
            before, score_bands(USER_A),
            "a second user's scores re-cut the first user's quartiles, so "
            "every match on A's board is relabelled by work A did not do")


class TestTwoRunsOnOneDayAreTwoRuns(_OneInstance):
    """
    A2.3 -- the shared output directory.

    `JobScoutOrchestrator.__init__` (`:672-675`) stamps the output path with
    the date and nothing else: `outputs_root(output_dir) / "%Y-%m-%d"`. Two
    people running on the same day land in one directory, and `_save_state`
    writes `state.json` into it -- so the second run silently replaces the
    first's record of what it found, and `previous_runs` (`:73-112`), which
    walks one directory per date, can only ever report one of them.

    The orchestrator is constructed and its state written directly rather than
    run: the collision is decided in `__init__`, and a full run would prove the
    same thing through minutes of pipeline. `backend="none"` is passed
    explicitly because an unpinned rung falls through to live detection (R80).

    **Predicted failure:** one directory, holding B's profile name, for both.

    The first assertion is *not* `len(previous_runs()) == 2`, which is how the
    plan words it and which no partitioned world can satisfy: once A3 scopes
    `outputs_root` per user, A's listing holds A's one run and B's holds B's,
    and neither is ever two. The durable claim underneath it is that the two
    runs occupy two directories — today they occupy one, which is what makes
    the count wrong and the overwrite below possible.
    """

    def _run(self, user):
        from agents.orchestrator import JobScoutOrchestrator
        orchestrator = JobScoutOrchestrator(profile_name=user, user_id=user,
                                            backend="none", generate_pdf=False)
        orchestrator._save_state()
        return orchestrator.output_path

    # Flipped at A3: `outputs_root` is scoped per user, so the date no
    # longer has to be unique across everybody.
    def test_each_run_gets_its_own_directory(self):
        from agents.orchestrator import previous_runs

        mine = self._run(USER_A)
        theirs = self._run(USER_B)

        self.assertNotEqual(
            mine.resolve(), theirs.resolve(),
            "two people who ran on the same day share one output directory, "
            "so each writes over the other's resumes and state")
        self.assertEqual(
            len(previous_runs(USER_A)), 1,
            "a partitioned listing shows its own user exactly one run")

    # Flipped at A3, same seam: the roots differ, so there is no shared
    # `state.json` for the second run to land on.
    def test_the_first_users_state_survives_the_second_run(self):
        from agents.orchestrator import load_run

        path = self._run(USER_A)
        self._run(USER_B)

        self.assertEqual(
            load_run(USER_A, str(path))["profile"], USER_A,
            "the second run overwrote the first user's state.json -- their "
            "record of what was found and generated is gone")


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestOneUsersRunsDoNotCrossTheWireToAnother(_OneInstance):
    """
    A2.4 -- what the run endpoints hand a stranger.

    The plan writes this item as "`GET /api/runs` as B -> A's `output_dir` and
    `error` strings are absent". Two corrections, neither of which changes what
    is wrong, both stated because a test that quietly re-aimed would leave the
    plan's version standing:

    * `output_dir` and `error` are columns of `data/runs.db`, surfaced by
      `RunRegistry.recent()`. **No route serves `recent()`** -- its facade
      wrapper `recent_runs` has no caller in either UI, and A1's contract test
      fails the build if `api/main.py` imports it. `GET /api/runs` is
      `previous_runs`, which reads `outputs/` off disk and returns
      `{date, path, jobs, resumes}`. So the assertions below are written
      against the fields the two run listings actually carry: the run's
      `profile` on `GET /api/run`, and its directory on `GET /api/runs`.
    * **"As B" cannot be expressed yet** -- there is no session, so there is no
      B. That is not a gap in the test, it is the finding: every caller of
      these routes today is every user at once, and the request below is B's
      only in the sense that B is who would make it.

    **Predicted failure:** `GET /api/run` lists A's run to a caller who did not
    start it, and `GET /api/runs` names the directory A wrote.
    """

    def setUp(self):
        super().setUp()
        import api.main
        self.client = TestClient(api.main.app)

    # Expected to flip at A5/A6. A3 is necessary and not sufficient:
    # partitioning `runs.db` gives the facade a user to scope to, but
    # this route has no caller identity to hand it until the session
    # cookie exists.
    @unittest.expectedFailure
    def test_the_active_list_names_no_run_the_caller_did_not_start(self):
        from tools.jobs.run_registry import RunRegistry, db_path

        registry = RunRegistry(db_path(_as_the_api_serves(USER_A)))
        try:
            registry.create(USER_A)
        finally:
            registry.close()

        active = self.client.get("/api/run").json()["active"]

        self.assertNotIn(
            USER_A, {run["profile"] for run in active},
            "a caller who started nothing is told what another user is "
            "running, including the profile name they imported it under")

    # Expected to flip at A5/A6, same reason as its sibling above.
    @unittest.expectedFailure
    def test_the_past_list_names_no_directory_another_user_wrote(self):
        from agents.orchestrator import JobScoutOrchestrator

        theirs = JobScoutOrchestrator(profile_name=USER_A,
                                      user_id=_as_the_api_serves(USER_A),
                                      backend="none", generate_pdf=False)
        theirs._save_state()

        listed = {Path(run["path"]).resolve()
                  for run in self.client.get("/api/runs").json()}

        self.assertNotIn(
            theirs.output_path.resolve(), listed,
            "the past-runs list hands out the path another user's resumes "
            "were written to")


if __name__ == "__main__":
    unittest.main()

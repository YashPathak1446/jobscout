"""
The board accumulates; the gates ran once (R62 / Q22).

Every gate this project has built — R54's experience floor, R55's country
check, R56's eligibility — runs between enrichment and analysis. That is right
for a pipeline, which is a pass over new work, and wrong for a board, which
accumulates. A gate shipped on Tuesday never saw a job scored on Monday.

Measured after R61's purge: of 69 scored jobs in the store, **26 (38%) would be
excluded by the gates as they stood** — and they held the entire top of the
board. Samsara's 8+ years role sat at 55.8 because it was scored before R54
existed.

So the verdict is stored per row and recomputed when it goes stale. What makes
it stale is not a date: it is a change to the gate's own code, or to the parts
of the profile the gate reads. Both are folded into one fingerprint, and the
fingerprint is *derived* rather than declared — a `GATE_VERSION` constant
somebody must remember to bump is the same shape as the field nobody read
(R31) and the flag nobody consulted (R61).
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.jobs.job_filter import (  # noqa: E402
    HIDDEN, SHOWN, UNDECIDABLE, gate_fingerprint, gate_verdict)
from tools.jobs.job_store import JobStore  # noqa: E402


class _Locations:
    def __init__(self, countries=("United States",)):
        self.countries = list(countries)
        self.states_priority = []
        self.states_acceptable = []
        self.remote_ok = True


class _Prefs:
    def __init__(self, seniority=("new grad", "entry level", "junior"),
                 countries=("United States",)):
        self.seniority = list(seniority)
        self.exclude_keywords = []
        self.target_roles = []
        self.locations = _Locations(countries)


class _Personal:
    # A citizen without a clearance who has answered every question: the
    # shape these tests were written against, stated in A4's terms.
    def __init__(self, us_person="yes", needs_sponsorship="no",
                 holds_clearance="no"):
        self.work_authorization = {"us_person": us_person,
                                   "needs_sponsorship": needs_sponsorship,
                                   "holds_clearance": holds_clearance}


class _Profile:
    def __init__(self, seniority=("new grad", "entry level", "junior"),
                 countries=("United States",), **personal):
        self.job_preferences = _Prefs(seniority, countries)
        self.personal_info = _Personal(**personal)


# A body long enough to count as read (`posting_facts.READABLE_MIN_CHARS`).
# Below it, a posting that states nothing is undecidable rather than clean.
READABLE = "We build developer tools in Python and Go for small teams. " * 10


def row(full_jd="", location="San Francisco, CA"):
    return {"url": "u", "full_jd": full_jd, "location": location}


class TestTheVerdict(unittest.TestCase):
    """What a stored row is judged on."""

    def test_a_clean_posting_passes(self):
        self.assertEqual(
            gate_verdict(row(READABLE + "Great entry-level role."), _Profile()).state,
            SHOWN)

    def test_the_experience_floor_still_applies(self):
        verdict = gate_verdict(row("Requires 8+ years of experience."), _Profile())
        self.assertEqual(verdict.state, HIDDEN)
        self.assertIn("8+ years", verdict.reason)

    def test_the_country_gate_applies_to_a_stored_row(self):
        """
        R55 runs in discovery, against a `JobListing`. The board holds rows, so
        the check has to be reachable from one — otherwise a job scored before
        R55 keeps its place on the board forever.
        """
        verdict = gate_verdict(row(location="Sao Paulo, BR"), _Profile())
        self.assertEqual(verdict.state, HIDDEN)
        self.assertIn("Brazil", verdict.reason)

    def test_a_clearance_requirement_applies(self):
        verdict = gate_verdict(
            row("Candidates will not be considered who do not hold an active "
                "TS/SCI clearance."), _Profile())
        self.assertEqual(verdict.state, HIDDEN)
        self.assertIn("clearance", verdict.reason)

    def test_an_empty_row_is_undecidable_not_eligible(self):
        """
        It used to return "" — the same answer as a posting read in full that
        rules nobody out. A4: nothing was read, so nothing is known.
        """
        self.assertEqual(gate_verdict(row(), _Profile()).state, UNDECIDABLE)

    def test_the_profile_decides(self):
        """The same posting, two profiles, two verdicts."""
        posting = row(READABLE + "Requires 8+ years of experience.")
        self.assertEqual(gate_verdict(posting, _Profile()).state, HIDDEN)
        self.assertEqual(
            gate_verdict(posting, _Profile(seniority=("staff",))).state, SHOWN)


class TestTheFingerprint(unittest.TestCase):
    """Stale means the code changed or the profile did."""

    def test_it_is_stable_for_the_same_inputs(self):
        self.assertEqual(gate_fingerprint(_Profile()),
                         gate_fingerprint(_Profile()))

    def test_changing_the_seniority_range_changes_it(self):
        self.assertNotEqual(gate_fingerprint(_Profile()),
                            gate_fingerprint(_Profile(seniority=("senior",))))

    def test_changing_preferred_countries_changes_it(self):
        self.assertNotEqual(gate_fingerprint(_Profile()),
                            gate_fingerprint(_Profile(countries=("Canada",))))

    def test_gaining_a_clearance_changes_it(self):
        self.assertNotEqual(
            gate_fingerprint(_Profile()),
            gate_fingerprint(_Profile(holds_clearance="yes")))

    def test_changing_citizenship_changes_it(self):
        self.assertNotEqual(gate_fingerprint(_Profile()),
                            gate_fingerprint(_Profile(us_person="no")))

    def test_answering_a_question_changes_it(self):
        """unknown -> yes is a change, or the badge never clears."""
        for field in ("us_person", "needs_sponsorship", "holds_clearance"):
            before = _Profile(**{field: "unknown"})
            self.assertNotEqual(gate_fingerprint(before),
                                gate_fingerprint(_Profile()), field)

    def test_it_covers_the_readability_rule(self):
        """`judge_body` reads posting_facts, so its source is gate source."""
        from tools.jobs.job_filter import _gate_source
        self.assertIn("READABLE_MIN_CHARS", _gate_source())

    def test_it_covers_the_gate_source_too(self):
        """
        The half a hand-maintained constant would miss. If this ever stops
        being true, editing a gate silently leaves every stored verdict wrong.
        """
        import tools.jobs.job_filter as module

        original = module._gate_source
        try:
            module._gate_source = lambda: "different source"
            changed = gate_fingerprint(_Profile())
        finally:
            module._gate_source = original
        self.assertNotEqual(changed, gate_fingerprint(_Profile()))

    def test_a_profile_missing_fields_does_not_raise(self):
        gate_fingerprint(object())


class TestRefreshingTheStore(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.dir.name) / "jobs.db")

        class _Listing:
            def __init__(self, url, title, jd):
                self.apply_url = url
                self.id = url
                self.title = title
                self.company = "Example"
                self.location = "San Francisco, CA"
                self.source = "test"
                self.full_jd = jd

        self.store.record([
            _Listing("u-ok", "Engineer I", READABLE + "An entry-level role."),
            _Listing("u-bad", "Engineer", "Requires 8+ years of experience."),
        ])
        for url in ("u-ok", "u-bad"):
            self.store.set_score(url, 55.0)

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def _refresh(self, profile=None):
        profile = profile or _Profile()
        return self.store.refresh_gate(
            gate_fingerprint(profile), lambda r: gate_verdict(r, profile))

    def test_the_first_pass_judges_everything(self):
        self.assertEqual(self._refresh(), 2)

    def test_a_second_pass_judges_nothing(self):
        """What makes it cheap enough to call before every render."""
        self._refresh()
        self.assertEqual(self._refresh(), 0)

    def test_a_changed_profile_makes_every_row_stale_again(self):
        self._refresh()
        self.assertEqual(self._refresh(_Profile(seniority=("staff",))), 2)

    def test_the_verdict_is_stored(self):
        self._refresh()
        self.assertEqual(self.store.get("u-ok")["gate_verdict"], SHOWN)
        self.assertEqual(self.store.get("u-ok")["gate_reason"], "")
        self.assertEqual(self.store.get("u-bad")["gate_verdict"], HIDDEN)
        self.assertIn("8+ years", self.store.get("u-bad")["gate_reason"])

    def test_a_verdict_can_be_reversed_by_the_profile(self):
        self._refresh()
        self._refresh(_Profile(seniority=("staff",)))
        # A body this short states a floor and nothing else, so with the
        # floor gone it is undecidable, not clean.
        self.assertEqual(self.store.get("u-bad")["gate_verdict"], UNDECIDABLE)


class TestTheBoardFilter(unittest.TestCase):
    """
    Filtered in SQL, not after the fact.

    Filtering a page the database already sliced turns a page of twenty into a
    page of twelve, and the board is paged.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.dir.name) / "jobs.db")

        class _Listing:
            def __init__(self, url, jd):
                self.apply_url = url
                self.id = url
                self.title = "Engineer"
                self.company = "Example"
                self.location = "San Francisco, CA"
                self.source = "test"
                self.full_jd = jd

        self.store.record([
            _Listing("u-ok", READABLE + "An entry-level role."),
            _Listing("u-bad", "Requires 8+ years of experience."),
            _Listing("u-thin", "Backend engineer, Python."),
        ])
        for url in ("u-ok", "u-bad", "u-thin"):
            self.store.set_score(url, 55.0)

        profile = _Profile()
        self.store.refresh_gate(gate_fingerprint(profile),
                                lambda r: gate_verdict(r, profile))

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def test_eligible_only(self):
        """Undecidable is shown: never silently hidden (A4)."""
        urls = {r["url"] for r in self.store.query(eligible=True)}
        self.assertEqual(urls, {"u-ok", "u-thin"})

    def test_unconfirmed_only(self):
        urls = {r["url"] for r in self.store.query(unconfirmed=True)}
        self.assertEqual(urls, {"u-thin"})
        self.assertEqual(self.store.count(eligible=True, unconfirmed=True), 1)

    def test_ineligible_only(self):
        urls = {r["url"] for r in self.store.query(eligible=False)}
        self.assertEqual(urls, {"u-bad"})

    def test_no_filter_returns_all_three(self):
        self.assertEqual(len(self.store.query()), 3)

    def test_the_count_agrees_with_the_rows(self):
        self.assertEqual(self.store.count(eligible=True),
                         len(self.store.query(eligible=True)))

    def test_an_unjudged_row_counts_as_eligible(self):
        """
        An unrun gate must not empty the board. A row with no verdict is shown,
        which is how the board behaved before any of this existed.
        """
        class _New:
            apply_url = "u-new"
            id = "u-new"
            title = "Engineer"
            company = "Example"
            location = "Remote"
            source = "test"
            full_jd = "Requires 8+ years of experience."

        self.store.record([_New()])
        urls = {r["url"] for r in self.store.query(eligible=True)}
        self.assertIn("u-new", urls)

    def test_a_row_judged_before_the_verdict_column_keeps_its_verdict(self):
        """
        A store from before A4 has `gate_reason` and no `gate_verdict`. The
        upgrade carries the old encoding over — a reason meant hidden, ""
        meant shown — so nothing is lost or promoted before the next refresh.
        """
        import sqlite3

        path = Path(self.dir.name) / "old.db"
        db = sqlite3.connect(str(path))
        db.execute("CREATE TABLE jobs (url TEXT PRIMARY KEY, job_id TEXT,"
                   " title TEXT, company TEXT, location TEXT, source TEXT,"
                   " full_jd TEXT, score REAL, status TEXT NOT NULL DEFAULT 'new',"
                   " first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,"
                   " scored_at TEXT, resume_tex TEXT, resume_pdf TEXT,"
                   " run_date TEXT, selection TEXT, gate_reason TEXT,"
                   " gate_checked TEXT)")
        for url, reason in (("old-hidden", "asks for 8+ years"),
                            ("old-shown", ""), ("old-unjudged", None)):
            db.execute("INSERT INTO jobs (url, first_seen, last_seen,"
                       " gate_reason) VALUES (?, 't', 't', ?)", (url, reason))
        db.commit()
        db.close()

        store = JobStore(path)
        try:
            self.assertEqual({r["url"] for r in store.query(eligible=False)},
                             {"old-hidden"})
            self.assertEqual({r["url"] for r in store.query(eligible=True)},
                             {"old-shown", "old-unjudged"})
            self.assertEqual(store.get("old-hidden")["gate_verdict"], HIDDEN)
            self.assertEqual(store.get("old-shown")["gate_verdict"], SHOWN)
            self.assertIsNone(store.get("old-unjudged")["gate_verdict"])
        finally:
            store.close()


class TestAgainstTheRealStore(unittest.TestCase):
    """Skipped on a clean clone."""

    def test_the_gate_hides_some_of_the_board_but_not_most_of_it(self):
        if not (ROOT / "data" / "jobs.db").exists():
            self.skipTest("needs a real job store")
        if not (ROOT / "user_profiles" / "yash_pathak.json").exists():
            self.skipTest("needs a real profile")

        from agents.orchestrator import board_total, refresh_board_gate

        refresh_board_gate(None, "yash_pathak")
        shown = board_total(None)
        everything = board_total(None, include_ineligible=True)

        self.assertLess(shown, everything, "the gate hides nothing at all")
        self.assertGreater(shown, everything / 3,
                           "the gate hides most of the board — too aggressive")


class _Posting:
    """What discovery hands the store. Only the fields `record` reads."""

    def __init__(self, url, jd):
        self.apply_url = url
        self.id = url
        self.title = "DevOps Engineer"
        self.company = "Example"
        self.location = "Washington, DC"
        self.source = "test"
        self.full_jd = jd


class TestTheReactBoardIsJudged(unittest.TestCase):
    """
    Every re-judge the board ever got came from Streamlit's render (A4).

    `refresh_board_gate` was called in exactly two places: `app.py` before
    each board render, and `POST /api/board/gate`, which no screen called.
    `GET /api/board` names no profile, so it cannot re-judge on its own, and
    a row no gate has judged reads as shown. So on the React board — the one
    the friends get — nothing was ever judged: every row eligible, no badge,
    and an About-you answer that should clear a badge left it standing.

    Judged now at the two moments a verdict can go stale from the React side:
    a profile save, and a run writing new rows. Both walk the real HTTP route
    or the real orchestrator, in a data home of their own.
    """

    CLEARANCE_JD = ("DevOps Engineer. Requirements: 2+ years with Kubernetes. "
                    "Must hold an active Top Secret security clearance. "
                    + "We build infrastructure for public-sector customers. " * 8)

    def setUp(self):
        import os
        import shutil
        from unittest import mock

        self._dir = tempfile.TemporaryDirectory()
        home = Path(self._dir.name)
        (home / "user_profiles").mkdir()
        (home / "data" / "master_resumes").mkdir(parents=True)
        for name, where in (("priya_raghunathan.json", "user_profiles"),
                            ("priya_raghunathan.tex", "data/master_resumes")):
            source = (ROOT / where / name)
            if not source.is_file():
                self.skipTest(f"needs {where}/{name}")
            shutil.copy(source, home / where / name)

        self._env = mock.patch.dict(os.environ, {"JOBSCOUT_HOME": str(home)})
        self._env.start()
        self.addCleanup(self._env.stop)
        self.addCleanup(self._dir.cleanup)

        from tools.jobs.job_store import db_path
        self.db = db_path(None)
        store = JobStore(self.db)
        store.record([_Posting("https://x.test/cleared", self.CLEARANCE_JD)])
        store.close()

    def _verdict(self):
        store = JobStore(self.db)
        try:
            return store.get("https://x.test/cleared")["gate_verdict"]
        finally:
            store.close()

    def _patch(self, holds_clearance):
        from fastapi.testclient import TestClient
        import api.main as main
        return TestClient(main.app).patch(
            "/api/profile/priya_raghunathan",
            json={"updates": {"personal_info": {"work_authorization": {
                "holds_clearance": holds_clearance}}}})

    def test_saving_an_answer_rejudges_the_board(self):
        from agents.orchestrator import refresh_board_gate
        refresh_board_gate(None, "priya_raghunathan")
        self.assertEqual(self._verdict(), UNDECIDABLE,
                         "precondition: an unanswered clearance question")

        response = self._patch("no")

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.json()["rejudged"], 1)
        self.assertEqual(self._verdict(), HIDDEN,
                         "the answer was saved and the badge outlived it")

    def test_a_save_never_fails_because_the_rejudge_did(self):
        from unittest import mock
        import agents.orchestrator as orchestrator

        with mock.patch.object(orchestrator, "_board",
                               side_effect=OSError("store unavailable")):
            response = self._patch("no")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rejudged"], 0)

    def test_a_run_judges_the_rows_discovery_wrote(self):
        from unittest import mock
        import agents.orchestrator as orchestrator

        seen = []
        real = orchestrator.refresh_board_gate
        with mock.patch.object(
                orchestrator, "refresh_board_gate",
                side_effect=lambda user, profile: seen.append((user, profile))
                or real(user, profile)):
            run = orchestrator.JobScoutOrchestrator(
                profile_name="priya_raghunathan", user_id=None, mock_mode=True,
                generate_pdf=False, max_resumes=1, backend="none")
            with mock.patch.object(run, "_run_enrichment"), \
                    mock.patch.object(run, "_run_analysis"), \
                    mock.patch.object(run, "_run_generation"), \
                    mock.patch.object(run, "_generate_summary"), \
                    mock.patch.object(run, "_print_final_report"):
                run.run(max_jobs=1)

        self.assertEqual(seen, [(None, "priya_raghunathan")])
        self.assertEqual(self._verdict(), UNDECIDABLE,
                         "the row discovery left on the board was never judged")


if __name__ == "__main__":
    unittest.main()

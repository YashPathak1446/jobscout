"""
Why this resume looks like this (R57).

`_composite_score` has always built all five terms for every component, and
`select_components` has always returned them as `score_breakdown`. They went to
one INFO line per run and a per-date JSON file nothing read. The board could
not show them: it reads a SQLite row, and the row had nowhere to put them.

The interesting part is not carrying the numbers across. It is that printing
them would not be an explanation. Embedding similarity is ~0.6 for everything
and dwarfs every other term, so "largest term" answers "semantic similarity"
every time. The question worth answering is which term *changed the outcome* —
remove it, and does this component still beat the best one left out?

That distinction is not academic. On the real Samsara run:

    101gen.ai   always=+0.30, final=1.25, cutoff 0.74
                -> the rule is not decisive; it wins by half a point without it

The old reasoning string for that component read "Always included (profile
rule)", which names a cause that did not cause anything.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.jobs.job_store import JobStore  # noqa: E402
from tools.resume.selection_report import (  # noqa: E402
    NEAR_TIE,
    build_selection_report,
    describe,
)


def terms(embedding=0.6, keyword=0.0, conditional=0.0, importance=0.05,
          always=0.0):
    return {
        "embedding": embedding, "keyword": keyword, "conditional": conditional,
        "importance": importance, "always": always,
        "final": embedding + keyword + conditional + importance + always,
    }


def selected(experiences=(), projects=(), breakdown=None, **extra):
    payload = {
        "experiences": list(experiences),
        "projects": list(projects),
        "score_breakdown": breakdown or {},
    }
    payload.update(extra)
    return payload


class TestTheCounterfactual(unittest.TestCase):
    """A term is decisive when removing it changes the selection."""

    def test_a_rule_that_changed_nothing_is_not_reported_as_the_cause(self):
        """
        The 101gen.ai case. always=+0.30 and it wins by 0.51 without it, so
        naming the rule would be false — which is what the old string did.
        """
        report = build_selection_report(selected(
            experiences=["exp_a"],
            breakdown={
                "exp_a": terms(embedding=0.95, always=0.30, importance=0.15),
                "exp_b": terms(embedding=0.60, importance=0.05),
            },
        ), {"exp_a": "A", "exp_b": "B"})

        picked = report["picked"][0]
        self.assertEqual(picked["decisive"], [])
        self.assertIn("No rule of yours was needed", describe(picked))

    def test_a_rule_that_did_change_it_is_reported(self):
        report = build_selection_report(selected(
            experiences=["exp_a"],
            breakdown={
                "exp_a": terms(embedding=0.50, always=0.30, importance=0.05),
                "exp_b": terms(embedding=0.70, importance=0.05),
            },
        ), {})

        picked = report["picked"][0]
        self.assertEqual(picked["decisive"], ["always"])
        self.assertIn("always-include rule", describe(picked))

    def test_every_positive_term_is_decisive_at_a_dead_heat(self):
        """
        The last slot, where the margin is zero: each term alone is enough to
        lose it. The wording has to say "without either" rather than "without
        it", because each was tested alone rather than in combination.
        """
        report = build_selection_report(selected(
            experiences=["exp_a"],
            breakdown={
                "exp_a": terms(embedding=0.50, keyword=0.10, importance=0.15),
                "exp_b": terms(embedding=0.75, importance=0.00),
            },
        ), {})

        picked = report["picked"][0]
        self.assertEqual(set(picked["decisive"]), {"keyword", "importance"})
        self.assertIn("without either", describe(picked))

    def test_a_zero_term_is_never_decisive(self):
        report = build_selection_report(selected(
            experiences=["exp_a"],
            breakdown={"exp_a": terms(embedding=0.90), "exp_b": terms()},
        ), {})
        self.assertNotIn("conditional", report["picked"][0]["decisive"])


class TestKindsAreScoredSeparately(unittest.TestCase):
    """
    Experiences compete with experiences.

    Mixing them would put a project in the experience cutoff and corrupt every
    counterfactual on the row — silently, since the arithmetic still works.
    """

    def test_a_project_does_not_set_the_experience_cutoff(self):
        report = build_selection_report(selected(
            experiences=["exp_a"],
            projects=["proj_a"],
            breakdown={
                "exp_a": terms(embedding=0.60),
                "exp_b": terms(embedding=0.10),
                "proj_a": terms(embedding=0.95),
                "proj_b": terms(embedding=0.90),
            },
        ), {})

        experience = [e for e in report["picked"] if e["kind"] == "experience"][0]
        # Against exp_b (0.15), not against proj_b (0.95).
        self.assertAlmostEqual(experience["margin"], 0.50, places=2)

    def test_each_kind_reports_its_own_near_misses(self):
        report = build_selection_report(selected(
            experiences=["exp_a"], projects=["proj_a"],
            breakdown={
                "exp_a": terms(), "exp_b": terms(embedding=0.1),
                "proj_a": terms(), "proj_b": terms(embedding=0.1),
            },
        ), {})
        kinds = {e["kind"] for e in report["passed_over"]}
        self.assertEqual(kinds, {"experience", "project"})


class TestNearTies(unittest.TestCase):
    """Q17's case: a 0.033 gap presented as a verdict."""

    def test_a_close_win_is_flagged(self):
        report = build_selection_report(selected(
            experiences=["exp_a"],
            breakdown={
                "exp_a": terms(embedding=0.656),
                "exp_b": terms(embedding=0.623),
            },
        ), {})
        picked = report["picked"][0]
        self.assertTrue(picked["near_tie"])
        self.assertLess(picked["margin"], NEAR_TIE)

    def test_a_clear_win_is_not(self):
        report = build_selection_report(selected(
            experiences=["exp_a"],
            breakdown={"exp_a": terms(embedding=0.9), "exp_b": terms(embedding=0.2)},
        ), {})
        self.assertFalse(report["picked"][0]["near_tie"])

    def test_the_near_tie_sentence_says_the_runner_up_was_defensible(self):
        entry = {"decisive": [], "near_tie": True, "margin": 0.03}
        self.assertIn("near-tie", describe(entry))

    def test_a_close_loss_is_flagged_too(self):
        report = build_selection_report(selected(
            experiences=["exp_a"],
            breakdown={
                "exp_a": terms(embedding=0.66), "exp_b": terms(embedding=0.65),
            },
        ), {})
        self.assertTrue(report["passed_over"][0]["near_tie"])


class TestDegenerateInputs(unittest.TestCase):
    """A report that raises costs a resume, so it must not raise."""

    def test_no_breakdown(self):
        report = build_selection_report({"experiences": ["exp_a"]}, {})
        self.assertEqual(report["picked"], [])

    def test_empty_selection(self):
        self.assertEqual(build_selection_report({}, {})["picked"], [])
        self.assertEqual(build_selection_report(None, {})["picked"], [])

    def test_a_component_selected_but_never_scored(self):
        """`always_include` can name a component scoring never reached."""
        report = build_selection_report(selected(
            experiences=["exp_a", "exp_ghost"],
            breakdown={"exp_a": terms()},
        ), {})
        self.assertEqual(len(report["picked"]), 1)

    def test_nothing_was_left_out(self):
        """Everything selected means nothing was displaced, so margin is the score."""
        report = build_selection_report(selected(
            experiences=["exp_a"], breakdown={"exp_a": terms()},
        ), {})
        picked = report["picked"][0]
        self.assertFalse(picked["near_tie"])
        self.assertEqual(picked["margin"], picked["final"])

    def test_an_unlabelled_component_falls_back_to_its_id(self):
        report = build_selection_report(selected(
            experiences=["exp_a"], breakdown={"exp_a": terms()},
        ), {})
        self.assertEqual(report["picked"][0]["label"], "exp_a")


class TestItSurvivesTheStore(unittest.TestCase):
    """The board reads SQLite, so the report has to land there intact."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.dir.name) / "jobs.db")

        class _Listing:
            apply_url = "https://example.com/job/1"
            id = "1"
            title = "Engineer"
            company = "Example"
            location = "Remote"
            source = "test"
            full_jd = "python"

        self.url = _Listing.apply_url
        self.store.record([_Listing()])

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def test_a_report_round_trips(self):
        report = build_selection_report(selected(
            experiences=["exp_a"],
            breakdown={"exp_a": terms(), "exp_b": terms(embedding=0.1)},
            jd_keywords=["python", "aws"],
        ), {"exp_a": "Engineer @ Example"})

        self.store.set_score(self.url, 55.0, selection=report)
        back = self.store.selection(self.url)

        self.assertEqual(back["picked"][0]["label"], "Engineer @ Example")
        self.assertEqual(back["jd_keywords"], ["python", "aws"])

    def test_a_score_without_a_report_still_works(self):
        self.store.set_score(self.url, 42.0)
        self.assertIsNone(self.store.selection(self.url))
        self.assertEqual(self.store.get(self.url)["score"], 42.0)

    def test_the_board_row_carries_it(self):
        self.store.set_score(self.url, 55.0, selection={"picked": [{"id": "x"}]})
        row = [r for r in self.store.query() if r["url"] == self.url][0]
        self.assertTrue(row["selection"])

    def test_unreadable_json_reads_as_absent_rather_than_raising(self):
        self.store._db.execute(
            "UPDATE jobs SET selection = ? WHERE url = ?", ("{not json", self.url))
        self.store._db.commit()
        self.assertIsNone(self.store.selection(self.url))

    def test_an_unknown_url_has_no_report(self):
        self.assertIsNone(self.store.selection("https://example.com/nope"))


class TestTheMigration(unittest.TestCase):
    """
    `CREATE TABLE IF NOT EXISTS` is a no-op on a database that already exists.

    Everybody the store was built for already has one — 106 rows in the
    author's — so a new column reaches nobody without an ALTER.
    """

    def test_an_older_database_gains_the_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.db"

            import sqlite3
            old = sqlite3.connect(str(path))
            old.execute(
                "CREATE TABLE jobs (url TEXT PRIMARY KEY, job_id TEXT,"
                " title TEXT NOT NULL, company TEXT, location TEXT,"
                " source TEXT, full_jd TEXT, score REAL,"
                " status TEXT NOT NULL DEFAULT 'new', first_seen TEXT NOT NULL,"
                " last_seen TEXT NOT NULL, scored_at TEXT, resume_tex TEXT,"
                " resume_pdf TEXT, run_date TEXT)")
            old.execute(
                "INSERT INTO jobs (url, title, first_seen, last_seen)"
                " VALUES ('u', 't', 'now', 'now')")
            old.commit()
            old.close()

            store = JobStore(path)
            try:
                columns = {row["name"] for row in
                           store._db.execute("PRAGMA table_info(jobs)")}
                self.assertIn("selection", columns)
                # And the row that was already there is still there.
                self.assertIsNotNone(store.get("u"))
            finally:
                store.close()

    def test_migrating_twice_is_harmless(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.db"
            for _ in range(2):
                store = JobStore(path)
                store.close()
            store = JobStore(path)
            try:
                columns = [row["name"] for row in
                           store._db.execute("PRAGMA table_info(jobs)")]
                self.assertEqual(columns.count("selection"), 1)
            finally:
                store.close()


class TestAgainstTheRealRun(unittest.TestCase):
    """Skipped on a clean clone."""

    def setUp(self):
        path = ROOT / "outputs" / "2026-08-25" / "analysis_results.json"
        if not path.exists():
            self.skipTest("needs a real analysis run")
        self.results = json.loads(path.read_text(encoding="utf-8"))

    def test_every_job_produces_a_report(self):
        for result in self.results:
            report = build_selection_report(result["selected_components"], {})
            self.assertTrue(report["picked"], result["job"].get("title"))

    def test_the_always_include_rule_is_not_credited_where_it_did_not_matter(self):
        """
        101gen.ai carries always=+0.30 on every job in the run and outscores
        the field without it every time. The old reasoning string called the
        rule the reason on all of them.
        """
        for result in self.results:
            report = build_selection_report(result["selected_components"], {})
            for entry in report["picked"]:
                if entry["id"] == "exp_101gen_ai":
                    self.assertNotIn("always", entry["decisive"])

    def test_reports_are_json_safe(self):
        for result in self.results[:5]:
            report = build_selection_report(result["selected_components"], {})
            json.dumps(report)


if __name__ == "__main__":
    unittest.main()

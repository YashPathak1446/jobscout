"""
The board as a log rather than a list (R48).

Two things separate them. A list shows what you have; a log shows what has
*happened* — so it needs the filters to find one row among thousands, and it
needs to know when each thing changed.

Every filter here already existed in the store and had never been offered to a
screen. The history table is new, and it exists for one reason: "ghosted"
means applied-and-silent-since, which is a fact about time. Without a record of
when a status changed, the board could offer a `ghosted` button and would be
asking the user to do the arithmetic — which is the work a log is for.
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.jobs.job_store import JobStore  # noqa: E402


class _Listing:
    def __init__(self, url, title="Software Engineer", company="Acme",
                 source="ats_greenhouse"):
        self.apply_url = url
        self.id = url
        self.title = title
        self.company = company
        self.location = "Remote"
        self.source = source
        self.full_jd = "a job"


class _StoreTest(unittest.TestCase):

    def setUp(self):
        self.path = ROOT / "data" / "_log_test.db"
        self.path.unlink(missing_ok=True)
        self.store = JobStore(self.path)

    def tearDown(self):
        self.store.close()
        self.path.unlink(missing_ok=True)


class TestFindingOneRowAmongMany(_StoreTest):
    """R46 took the board from three employers to forty-nine."""

    def setUp(self):
        super().setUp()
        self.store.record([
            _Listing("https://x.test/1", "Backend Engineer", "Affirm"),
            _Listing("https://x.test/2", "Frontend Engineer", "Airbnb"),
            _Listing("https://x.test/3", "Backend Engineer", "Modal", "ats_ashby"),
            _Listing("https://x.test/4", "ML Engineer", "Modal", "ats_ashby"),
        ])

    def test_filtering_by_one_company(self):
        self.assertEqual(len(self.store.query(company="Modal")), 2)

    def test_filtering_by_several_companies(self):
        found = self.store.query(company=["Affirm", "Airbnb"])
        self.assertEqual({row["company"] for row in found}, {"Affirm", "Airbnb"})

    def test_filtering_by_source(self):
        self.assertEqual(len(self.store.query(source="ats_ashby")), 2)

    def test_searching_titles(self):
        self.assertEqual(len(self.store.query(search="backend")), 2)

    def test_search_is_case_insensitive(self):
        self.assertEqual(len(self.store.query(search="BACKEND")), 2)

    def test_searching_companies_too(self):
        self.assertEqual(len(self.store.query(search="modal")), 2)

    def test_a_wildcard_in_the_search_box_is_a_literal(self):
        """
        Typing `%` should find jobs containing a percent sign, not every job.
        An unescaped LIKE would quietly return the whole table.
        """
        self.store.record([_Listing("https://x.test/5", "Engineer (100% remote)")])
        found = self.store.query(search="100%")
        self.assertEqual(len(found), 1)
        self.assertIn("100%", found[0]["title"])

    def test_an_underscore_is_a_literal_too(self):
        self.assertEqual(len(self.store.query(search="_")), 0)

    def test_filters_combine(self):
        found = self.store.query(company="Modal", search="backend")
        self.assertEqual(len(found), 1)


class TestPagingSaysHowMuchIsHidden(_StoreTest):
    """
    A page cap with no total looks exactly like running out of jobs — the
    silent-truncation shape this project keeps finding.
    """

    def setUp(self):
        super().setUp()
        self.store.record([_Listing(f"https://x.test/{i}") for i in range(30)])

    def test_a_page_returns_only_its_window(self):
        self.assertEqual(len(self.store.query(limit=10)), 10)

    def test_the_second_page_is_different_rows(self):
        first = {r["url"] for r in self.store.query(limit=10, offset=0)}
        second = {r["url"] for r in self.store.query(limit=10, offset=10)}
        self.assertFalse(first & second)

    def test_the_count_ignores_the_window(self):
        self.assertEqual(self.store.count(), 30)

    def test_the_count_respects_the_filters(self):
        self.store.record([_Listing("https://y.test/1", company="Modal")])
        self.assertEqual(self.store.count(company="Modal"), 1)

    def test_an_unknown_sort_falls_back_rather_than_raising(self):
        """A stale bookmark in a UI should not be an error."""
        self.assertEqual(len(self.store.query(sort="; DROP TABLE jobs", limit=5)), 5)
        self.assertEqual(self.store.count(), 30, "table intact")


class TestFacetsComeFromTheData(_StoreTest):

    def setUp(self):
        super().setUp()
        self.store.record([
            _Listing("https://x.test/1", company="Affirm"),
            _Listing("https://x.test/2", company="Affirm"),
            _Listing("https://x.test/3", company="Modal", source="ats_ashby"),
        ])

    def test_companies_are_listed_commonest_first(self):
        companies = self.store.facets()["companies"]
        self.assertEqual(companies[0]["value"], "Affirm")
        self.assertEqual(companies[0]["count"], 2)

    def test_sources_are_listed(self):
        sources = {s["value"] for s in self.store.facets()["sources"]}
        self.assertEqual(sources, {"ats_greenhouse", "ats_ashby"})


class TestStatusHistory(_StoreTest):

    def setUp(self):
        super().setUp()
        self.url = "https://x.test/1"
        self.store.record([_Listing(self.url)])

    def test_each_change_is_recorded_in_order(self):
        for status in ("seen", "applied", "rejected"):
            self.store.set_status(self.url, status)
        self.assertEqual([h["status"] for h in self.store.history(self.url)],
                         ["seen", "applied", "rejected"])

    def test_a_job_nobody_touched_has_no_history(self):
        self.assertEqual(self.store.history(self.url), [])

    def test_the_most_recent_entry_into_a_status_wins(self):
        """Applied, rejected, applied again — the second date is the live one."""
        self.store.set_status(self.url, "applied")
        first = self.store.status_changed_at(self.url, "applied")
        self.store.set_status(self.url, "rejected")
        self.store.set_status(self.url, "applied")
        self.assertGreaterEqual(
            self.store.status_changed_at(self.url, "applied"), first)

    def test_a_rejected_status_is_still_refused(self):
        with self.assertRaises(ValueError):
            self.store.set_status(self.url, "interviewing")

    def test_a_refused_status_writes_no_history(self):
        with self.assertRaises(ValueError):
            self.store.set_status(self.url, "interviewing")
        self.assertEqual(self.store.history(self.url), [])


class TestGhostingIsDerived(_StoreTest):
    """
    Never a button. Ghosting is what happens while nobody does anything, so a
    stored status would go stale the moment a reply arrived — and would need
    the user to notice the anniversary in the first place.
    """

    def setUp(self):
        super().setUp()
        self.url = "https://x.test/1"
        self.store.record([_Listing(self.url)])

    def _applied_days_ago(self, days, url=None, status="applied"):
        url = url or self.url
        self.store.set_status(url, status)
        when = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        self.store._db.execute(
            "UPDATE status_history SET changed_at = ? WHERE url = ? AND status = ?",
            (when, url, status))
        self.store._db.commit()

    def test_a_long_silence_counts(self):
        self._applied_days_ago(40)
        self.assertEqual(len(self.store.ghosted(28)), 1)

    def test_a_recent_application_does_not(self):
        self._applied_days_ago(3)
        self.assertEqual(self.store.ghosted(28), [])

    def test_the_window_is_adjustable(self):
        self._applied_days_ago(10)
        self.assertEqual(len(self.store.ghosted(7)), 1)
        self.assertEqual(self.store.ghosted(28), [])

    def test_a_job_that_moved_on_is_not_ghosted(self):
        """A reply arrived, so the silence ended — by construction."""
        self._applied_days_ago(40)
        self.store.set_status(self.url, "rejected")
        self.assertEqual(self.store.ghosted(28), [])

    def test_a_job_never_applied_to_is_not_ghosted(self):
        self._applied_days_ago(40, status="seen")
        self.assertEqual(self.store.ghosted(28), [])

    def test_the_row_carries_when_it_was_applied_to(self):
        self._applied_days_ago(40)
        self.assertIn("applied_at", self.store.ghosted(28)[0])


class TestTheFacadeDoesNotMisreadZero(unittest.TestCase):
    """
    `after_days or DEFAULT` treats a threshold of 0 as "not supplied", so
    asking for everything applied-to answered a different question. Caught by
    running it, not by reading it.
    """

    def test_zero_days_is_a_real_window(self):
        import agents.orchestrator as orchestrator
        import tools.jobs.job_store as job_store

        path = ROOT / "data" / "_log_facade_test.db"
        path.unlink(missing_ok=True)
        store = JobStore(path)
        store.record([_Listing("https://x.test/1")])
        store.set_status("https://x.test/1", "applied")
        store.close()

        real = job_store.DEFAULT_DB
        job_store.DEFAULT_DB = path
        try:
            self.assertEqual(len(orchestrator.ghosted_jobs(after_days=0)), 1)
            self.assertEqual(orchestrator.ghosted_jobs(), [])
        finally:
            job_store.DEFAULT_DB = real
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()


class TestScoreBands(_StoreTest):
    """
    R49: the number is normalised against a window far wider than reality.

    95 scored jobs across seven runs spanned 44 to 59 on a 0-100 scale — 15%
    of it — so every job reads as "about 53". Re-cutting the calibration would
    fix the look and break the meaning, because `scoring_threshold` gates the
    pipeline at 40 and moving the scale moves that gate silently (R24). So the
    scale stays and the presentation divides it, from the user's own data.
    """

    def _with_scores(self, values):
        for i, value in enumerate(values):
            url = f"https://x.test/{i}"
            self.store.record([_Listing(url)])
            self.store.set_score(url, value)

    def test_too_few_scores_means_no_bands(self):
        """A quartile over three jobs is not information."""
        self._with_scores([50.0, 52.0, 54.0])
        self.assertEqual(self.store.score_bands(), {})

    def test_bands_appear_once_there_is_enough_to_divide(self):
        self._with_scores([40 + i for i in range(12)])
        bands = self.store.score_bands()
        self.assertIn("strong", bands)
        self.assertIn("typical", bands)
        self.assertEqual(bands["n"], 12)

    def test_the_strong_cut_is_above_the_typical_cut(self):
        self._with_scores([40 + i for i in range(20)])
        bands = self.store.score_bands()
        self.assertGreater(bands["strong"], bands["typical"])

    def test_bands_calibrate_to_the_data_they_are_given(self):
        """
        The whole reason these are computed rather than constants: a different
        resume against a different corpus lands in a different band of raw
        similarities, and hardcoded cuts would be wrong for everyone but the
        person they were tuned on.
        """
        self._with_scores([10 + i for i in range(20)])
        low = self.store.score_bands()

        self.tearDown()
        self.setUp()
        self._with_scores([80 + i for i in range(20)])
        high = self.store.score_bands()

        self.assertLess(low["strong"], high["typical"])

    def test_unscored_jobs_are_not_counted_as_zero(self):
        self._with_scores([40 + i for i in range(10)])
        self.store.record([_Listing("https://unscored.test/1")])
        self.assertEqual(self.store.score_bands()["n"], 10)

    def test_the_range_is_reported(self):
        self._with_scores([44.0] + [50.0] * 8 + [59.0])
        bands = self.store.score_bands()
        self.assertEqual(bands["low"], 44.0)
        self.assertEqual(bands["high"], 59.0)

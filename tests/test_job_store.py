"""
The durable job store (R35).

`job_cache` remembers a URL for seven days so the same posting does not repeat
between runs, then forgets. That is right for a run log and wrong for a board:
a tracker is built to forget, a board must never lose anything.

The rule these tests exist to protect: **a job's status belongs to the user.**
Re-running discovery must never reset what someone recorded about a job.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.jobs.job_store import STATUSES, JobStore  # noqa: E402
from tools.search.job_listing import JobListing  # noqa: E402


def listing(url, title="Software Engineer", company="ACME", jd="a description"):
    return JobListing(
        id=f"id_{url}", title=title, company=company, location="Remote",
        description="", apply_url=url, salary_min=None, salary_max=None,
        created="", source="ats_greenhouse", full_jd=jd,
    )


class _StoreTest(unittest.TestCase):
    def setUp(self):
        self.store = JobStore(Path(tempfile.mkdtemp()) / "jobs.db")

    def tearDown(self):
        self.store.close()


class TestRecording(_StoreTest):

    def test_records_new_jobs(self):
        result = self.store.record([listing("u1"), listing("u2")])
        self.assertEqual(result, {"added": 2, "updated": 0})
        self.assertEqual(self.store.stats()["total"], 2)

    def test_the_same_job_is_updated_not_duplicated(self):
        self.store.record([listing("u1")])
        result = self.store.record([listing("u1")])
        self.assertEqual(result, {"added": 0, "updated": 1})
        self.assertEqual(self.store.stats()["total"], 1)

    def test_jobs_without_an_apply_url_are_skipped(self):
        # The URL is the natural key; without one there is nothing to dedup on.
        self.assertEqual(self.store.record([listing("")]), {"added": 0, "updated": 0})

    def test_recording_nothing_is_safe(self):
        self.assertEqual(self.store.record([]), {"added": 0, "updated": 0})
        self.assertEqual(self.store.record(None), {"added": 0, "updated": 0})

    def test_a_missing_description_gets_filled_in_later(self):
        self.store.record([listing("u1", jd="")])
        self.store.record([listing("u1", jd="now we have one")])
        self.assertEqual(self.store.get("u1")["full_jd"], "now we have one")

    def test_an_empty_rediscovery_does_not_wipe_a_good_description(self):
        self.store.record([listing("u1", jd="the real thing")])
        self.store.record([listing("u1", jd="")])
        self.assertEqual(self.store.get("u1")["full_jd"], "the real thing")

    def test_first_seen_survives_rediscovery(self):
        self.store.record([listing("u1")])
        first = self.store.get("u1")["first_seen"]
        self.store.record([listing("u1")])
        self.assertEqual(self.store.get("u1")["first_seen"], first)


class TestUserStateIsSacred(_StoreTest):
    """The whole reason this is not the job cache."""

    def test_rediscovery_does_not_reset_status(self):
        self.store.record([listing("u1")])
        self.store.set_status("u1", "applied")
        self.store.record([listing("u1")])
        self.assertEqual(self.store.get("u1")["status"], "applied")

    def test_rediscovery_does_not_reset_score_or_resume(self):
        self.store.record([listing("u1")])
        self.store.set_score("u1", 71.5)
        self.store.attach_resume("u1", tex_path="a.tex", pdf_path="a.pdf")
        self.store.record([listing("u1")])

        row = self.store.get("u1")
        self.assertEqual(row["score"], 71.5)
        self.assertEqual(row["resume_pdf"], "a.pdf")

    def test_an_unknown_status_is_refused(self):
        self.store.record([listing("u1")])
        with self.assertRaises(ValueError):
            self.store.set_status("u1", "definitely-not-a-status")

    def test_every_documented_status_is_accepted(self):
        self.store.record([listing("u1")])
        for status in STATUSES:
            self.store.set_status("u1", status)
            self.assertEqual(self.store.get("u1")["status"], status)

    def test_attaching_only_a_pdf_leaves_the_tex_alone(self):
        self.store.record([listing("u1")])
        self.store.attach_resume("u1", tex_path="a.tex")
        self.store.attach_resume("u1", pdf_path="a.pdf")
        row = self.store.get("u1")
        self.assertEqual(row["resume_tex"], "a.tex")
        self.assertEqual(row["resume_pdf"], "a.pdf")


class TestQuerying(_StoreTest):

    def setUp(self):
        super().setUp()
        self.store.record([listing(f"u{i}", company="ACME" if i < 3 else "Other")
                           for i in range(5)])
        self.store.set_score("u0", 90.0)
        self.store.set_score("u1", 50.0)
        self.store.set_status("u1", "applied")
        self.store.attach_resume("u0", tex_path="a.tex")

    def test_scored_jobs_come_first_and_best_first(self):
        rows = self.store.query()
        self.assertEqual(rows[0]["url"], "u0")
        self.assertEqual(rows[1]["url"], "u1")
        # Unscored must sink, not sort as though they scored zero.
        self.assertIsNone(rows[2]["score"])

    def test_filters_by_status(self):
        self.assertEqual([r["url"] for r in self.store.query(status="applied")], ["u1"])

    def test_filters_by_minimum_score(self):
        self.assertEqual([r["url"] for r in self.store.query(min_score=60)], ["u0"])

    def test_filters_by_company(self):
        self.assertEqual(len(self.store.query(company="Other")), 2)

    def test_filters_to_unscored(self):
        self.assertEqual(len(self.store.query(unscored=True)), 3)

    def test_filters_by_whether_a_resume_exists(self):
        self.assertEqual([r["url"] for r in self.store.query(has_resume=True)], ["u0"])
        self.assertEqual(len(self.store.query(has_resume=False)), 4)

    def test_respects_the_limit(self):
        self.assertEqual(len(self.store.query(limit=2)), 2)

    def test_unprocessed_urls_are_the_ones_not_yet_scored(self):
        self.assertEqual(self.store.unprocessed_urls(), {"u2", "u3", "u4"})

    def test_stats_summarise_the_board(self):
        stats = self.store.stats()
        self.assertEqual(stats["total"], 5)
        self.assertEqual(stats["scored"], 2)
        self.assertEqual(stats["with_resume"], 1)
        self.assertEqual(stats["by_status"]["applied"], 1)


class TestPersistence(unittest.TestCase):

    def test_a_store_survives_being_closed_and_reopened(self):
        """A board that forgets on restart is the thing this replaces."""
        path = Path(tempfile.mkdtemp()) / "jobs.db"
        with JobStore(path) as store:
            store.record([listing("u1")])
            store.set_status("u1", "applied")

        with JobStore(path) as reopened:
            self.assertEqual(reopened.get("u1")["status"], "applied")


if __name__ == "__main__":
    unittest.main()

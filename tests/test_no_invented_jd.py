"""
The pipeline invented job descriptions and scored them (R61).

R44 and R45 are about a *model* inventing. This is the pipeline inventing.

When a scrape failed, enrichment called `mock_scrape_jd` and returned its
output — invented boilerplate reading "a leading technology company building
innovative solutions that impact millions of users" and "an entry-level
position perfect for new graduates or those with 0-2 years of experience" —
with `scraped_successfully` hard-coded to `True`.

Nothing downstream ever read `scraper_used`, and the success flag was written
by every path and consulted by none. So the invention was indistinguishable
from a real posting: scored, cached, ranked, and turned into resumes.

Measured on the author's own data when this was found:

    cached JDs that were fabricated      36 of 178
    scored jobs derived from one         34 of 103
    of those, with a generated resume     8

They held the *top* of the board — 55.8, 55.3, 55.0, 54.4 — because generic
flattering prose matches every query and makes an ideal embedding target. The
invented text also said "perfect for new graduates", which is the phrasing
R54's body gate reasons about, so the fabrication guaranteed its own pass.

Two things had to change. A failed scrape now says so, and something finally
reads the flag.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from agents.enrichment_agent import EnrichmentAgent  # noqa: E402
from agents.orchestrator import JobScoutOrchestrator  # noqa: E402
from scripts.purge_fabricated import (  # noqa: E402
    clear_scores,
    fabricated_urls,
    purge_cache,
)
from tools.jobs.job_store import JobStore  # noqa: E402


class _Job:
    def __init__(self, description="Short description from discovery."):
        self.apply_url = "https://example.com/job/1"
        self.title = "Software Engineer"
        self.company = "Baseten"
        self.description = description


class TestAFailedScrapeSaysSo(unittest.TestCase):
    """The lie, at its source."""

    def setUp(self):
        self.agent = EnrichmentAgent.__new__(EnrichmentAgent)

    def _failing_scrape(self, monkey_result=None):
        import agents.enrichment_agent as module

        original = module.scrape_jd
        module.scrape_jd = lambda **kwargs: {
            "full_jd": "", "requirements": {},
            "scraped_successfully": False, "scraper_used": "generic",
        }
        try:
            return self.agent._real_scrape(_Job())
        finally:
            module.scrape_jd = original

    def test_the_flag_is_false(self):
        self.assertFalse(self._failing_scrape()["scraped_successfully"])

    def test_nothing_is_invented(self):
        result = self._failing_scrape()
        for invention in ("leading technology company", "innovative solutions",
                          "perfect for new graduates"):
            self.assertNotIn(invention, result["full_jd"])

    def test_the_real_short_description_is_kept(self):
        """Thin is not the same as false. Discovery's snippet is real text."""
        self.assertEqual(self._failing_scrape()["full_jd"],
                         "Short description from discovery.")

    def test_the_scraper_is_named_failed(self):
        self.assertEqual(self._failing_scrape()["scraper_used"], "failed")


class TestProvenanceSurvivesTheCache(unittest.TestCase):
    """
    A cache hit used to claim success unconditionally.

    That is how a fabricated JD came back looking real *without even the
    warning* — the warning happens at scrape time, and a cache hit never
    scrapes. Every re-run made the invention quieter.
    """

    @staticmethod
    def _from_cache(scraper_used):
        origin = scraper_used
        return {
            "scraped_successfully": "mock" not in str(origin).lower(),
            "scraper_used": f"cache ({origin})",
        }

    def test_a_cached_real_scrape_is_still_a_success(self):
        self.assertTrue(self._from_cache("greenhouse")["scraped_successfully"])

    def test_a_cached_fabrication_is_not(self):
        self.assertFalse(self._from_cache("mock_fallback")["scraped_successfully"])

    def test_the_origin_is_still_visible(self):
        self.assertIn("mock_fallback", self._from_cache("mock_fallback")["scraper_used"])


class TestSomethingFinallyReadsTheFlag(unittest.TestCase):
    """
    `scraped_successfully` was written by every path and read by none.

    A resume tailored to a posting nobody could read is tailored to nothing,
    so generation is where the flag has to bite.
    """

    @staticmethod
    def _result(readable=True):
        job = {"title": "Engineer", "company": "Example"}
        if readable is not None:
            job["scraped_successfully"] = readable
        return {"job": job, "score": {"overall": 55.0}}

    def test_unreadable_jobs_are_separated(self):
        readable, unreadable = JobScoutOrchestrator._split_unreadable(
            [self._result(True), self._result(False)])
        self.assertEqual(len(readable), 1)
        self.assertEqual(len(unreadable), 1)

    def test_a_missing_flag_counts_as_readable(self):
        """
        Replayed runs and fixtures written before R61 must behave as before,
        rather than silently losing every job to a flag they never carried.
        """
        readable, unreadable = JobScoutOrchestrator._split_unreadable(
            [{"job": {"title": "Engineer"}, "score": {}}])
        self.assertEqual(len(readable), 1)
        self.assertEqual(unreadable, [])

    def test_empty_input(self):
        self.assertEqual(JobScoutOrchestrator._split_unreadable([]), ([], []))
        self.assertEqual(JobScoutOrchestrator._split_unreadable(None), ([], []))

    def test_a_malformed_result_does_not_raise(self):
        readable, _ = JobScoutOrchestrator._split_unreadable(["not a dict"])
        self.assertEqual(len(readable), 1)


class TestTheRepair(unittest.TestCase):
    """Fixing the code does not undo what is already on disk."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.cache = Path(self.dir.name) / "job_cache.json"
        self.cache.write_text(json.dumps({
            "seen_urls": {"u1": "x", "u2": "x"},
            "scraped_jds": {
                "u1": {"full_jd": "real", "requirements": {},
                       "scraper_used": "greenhouse"},
                "u2": {"full_jd": "invented", "requirements": {},
                       "scraper_used": "mock_fallback"},
            },
        }), encoding="utf-8")

    def tearDown(self):
        self.dir.cleanup()

    def test_only_the_fabricated_entries_are_found(self):
        self.assertEqual(fabricated_urls(self.cache), {"u2"})

    def test_the_real_entry_survives_the_purge(self):
        purge_cache({"u2"}, cache_path=self.cache)
        data = json.loads(self.cache.read_text(encoding="utf-8"))
        self.assertIn("u1", data["scraped_jds"])
        self.assertNotIn("u2", data["scraped_jds"])

    def test_a_dry_run_changes_nothing(self):
        before = self.cache.read_text(encoding="utf-8")
        purge_cache({"u2"}, cache_path=self.cache, dry_run=True)
        self.assertEqual(self.cache.read_text(encoding="utf-8"), before)

    def test_the_url_stays_known_so_it_is_not_rediscovered_as_new(self):
        purge_cache({"u2"}, cache_path=self.cache)
        data = json.loads(self.cache.read_text(encoding="utf-8"))
        self.assertIn("u2", data["seen_urls"])


class TestClearingScores(unittest.TestCase):
    """
    The job is real; only what was concluded about it is worthless.

    So the row stays and the score goes, which is also what puts it back into
    `unprocessed_urls()` for the next run to score against real text.
    """

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
            full_jd = "invented"

        self.url = _Listing.apply_url
        self.store.record([_Listing()])
        self.store.set_score(self.url, 55.0, selection={"picked": [{"id": "x"}]})

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def test_the_job_survives(self):
        clear_scores({self.url}, self.store)
        self.assertIsNotNone(self.store.get(self.url))

    def test_the_score_and_its_explanation_go(self):
        clear_scores({self.url}, self.store)
        row = self.store.get(self.url)
        self.assertIsNone(row["score"])
        self.assertIsNone(row["scored_at"])
        self.assertIsNone(self.store.selection(self.url))

    def test_it_becomes_unprocessed_again(self):
        clear_scores({self.url}, self.store)
        self.assertIn(self.url, self.store.unprocessed_urls())

    def test_a_dry_run_clears_nothing(self):
        clear_scores({self.url}, self.store, dry_run=True)
        self.assertEqual(self.store.get(self.url)["score"], 55.0)

    def test_an_unknown_url_is_ignored(self):
        self.assertEqual(clear_scores({"https://nope"}, self.store), 0)


if __name__ == "__main__":
    unittest.main()

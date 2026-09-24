"""
One posting, two letter cases, two resumes (R127).

SmartRecruiters served the same Experian posting as
`jobs.smartrecruiters.com/experian/...` and `jobs.smartrecruiters.com/Experian/...`.
Discovery deduplicated on the raw URL, so both reached the board and both got
a resume. The fix compares URLs by `url_key` — scheme, host and path
case-folded, query kept — and leaves the stored URL exactly as first found.

On a board that already holds both copies nothing is deleted; what stops is a
third.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from agents import discovery_agent  # noqa: E402
from agents.discovery_agent import DiscoveryAgent  # noqa: E402
from tools.jobs import job_store  # noqa: E402
from tools.jobs.job_store import JobStore, url_key  # noqa: E402
from tools.profile import load_profile  # noqa: E402
from tools.search.job_listing import JobListing  # noqa: E402

LOWER = ("https://jobs.smartrecruiters.com/experian/"
         "744000081234567-software-engineer-ii")
UPPER = ("https://jobs.smartrecruiters.com/Experian/"
         "744000081234567-software-engineer-ii")


def listing(url, jd="a description"):
    return JobListing(
        id=f"id_{url}", title="Software Engineer II", company="Experian",
        location="Remote", description="", apply_url=url, salary_min=None,
        salary_max=None, created="", source="ats_smartrecruiters", full_jd=jd,
    )


class TestUrlKey(unittest.TestCase):

    def test_the_experian_pair_is_one_key(self):
        self.assertEqual(url_key(LOWER), url_key(UPPER))

    def test_the_host_is_case_folded(self):
        self.assertEqual(url_key("https://JOBS.SmartRecruiters.com/x"),
                         url_key("https://jobs.smartrecruiters.com/x"))

    def test_the_query_keeps_its_case(self):
        # An identifier in a query string is not ours to fold.
        self.assertNotEqual(url_key("https://x.com/apply?id=AbC"),
                            url_key("https://x.com/apply?id=abc"))

    def test_different_postings_stay_different(self):
        self.assertNotEqual(url_key(LOWER), url_key(LOWER.replace("567", "568")))


class TestTheStore(unittest.TestCase):

    def setUp(self):
        self.store = JobStore(Path(tempfile.mkdtemp()) / "jobs.db")

    def tearDown(self):
        self.store.close()

    def urls(self):
        return sorted(r["url"] for r in
                      self.store._db.execute("SELECT url FROM jobs"))

    def test_the_second_case_updates_the_first(self):
        self.store.record([listing(LOWER)])
        result = self.store.record([listing(UPPER)])
        self.assertEqual(result, {"added": 0, "updated": 1})
        self.assertEqual(self.urls(), [LOWER])

    def test_both_cases_in_one_batch_are_one_job(self):
        result = self.store.record([listing(UPPER), listing(LOWER)])
        self.assertEqual(result, {"added": 1, "updated": 1})

    def test_the_stored_url_is_the_one_first_found(self):
        self.store.record([listing(UPPER)])
        self.store.record([listing(LOWER)])
        self.assertEqual(self.urls(), [UPPER])
        self.assertEqual(self.store.stored_url(LOWER), UPPER)

    def test_a_missing_description_is_filled_through_the_other_case(self):
        self.store.record([listing(LOWER, jd="")])
        self.store.record([listing(UPPER, jd="the real thing")])
        self.assertEqual(self.store.get(LOWER)["full_jd"], "the real thing")

    def test_an_unknown_url_has_no_stored_url(self):
        self.assertIsNone(self.store.stored_url(LOWER))

    def test_a_query_differing_in_case_is_another_job(self):
        self.store.record([listing("https://x.com/apply?id=AbC")])
        self.store.record([listing("https://x.com/apply?id=abc")])
        self.assertEqual(len(self.urls()), 2)

    def test_an_existing_pair_is_kept_and_not_joined_by_a_third(self):
        # A board from before R127, holding both copies: seeded past `record`.
        for url in (LOWER, UPPER):
            self.store._db.execute(
                "INSERT INTO jobs (url, title, status, first_seen, last_seen)"
                " VALUES (?, 't', 'new', '2026-09-01', '2026-09-01')", (url,))
        self.store._db.commit()
        third = LOWER.replace("experian", "EXPERIAN")
        result = self.store.record([listing(third)])
        self.assertEqual(result, {"added": 0, "updated": 1})
        self.assertEqual(self.urls(), sorted([LOWER, UPPER]))
        # Each existing copy still answers to itself.
        self.assertEqual(self.store.stored_url(UPPER), UPPER)
        self.assertEqual(self.store.stored_url(LOWER), LOWER)


class TestDiscovery(unittest.TestCase):
    """The run path: one job reaches generation, under the board's URL."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        patcher = mock.patch.dict(os.environ, {"JOBSCOUT_HOME": self.home})
        patcher.start()
        self.addCleanup(patcher.stop)
        # Priya, not the legacy fixture; only the source list is narrowed.
        profile = load_profile("priya_raghunathan", str(ROOT / "user_profiles"),
                               user_id=None)
        profile.agent_preferences.discovery_sources = ["ats"]
        self.agent = DiscoveryAgent(profile, user_id=None)

    def run_with(self, found):
        def search():
            self.agent._deduplicate_and_add([listing(u) for u in found])
        with mock.patch.object(self.agent, "_search_ats", search), \
             mock.patch.object(self.agent, "_filter_by_profile", lambda jobs: jobs), \
             mock.patch.object(discovery_agent, "harvest_slugs", lambda *a, **k: None):
            return self.agent.discover_jobs(max_jobs=10)

    def test_one_run_finding_both_cases_yields_one_job(self):
        jobs = self.run_with([LOWER, UPPER])
        self.assertEqual([j.apply_url for j in jobs], [LOWER])

    def test_a_later_run_in_the_other_case_carries_the_stored_url(self):
        self.run_with([LOWER])
        self.agent.all_jobs, self.agent.seen_urls = [], set()
        jobs = self.run_with([UPPER])
        # Still unscored, so it is processed — under the URL its score and
        # resume will be written to.
        self.assertEqual([j.apply_url for j in jobs], [LOWER])
        with JobStore(job_store.db_path(None)) as store:
            self.assertEqual(store.stats()["total"], 1)


if __name__ == "__main__":
    unittest.main()

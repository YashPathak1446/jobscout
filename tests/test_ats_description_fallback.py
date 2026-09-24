"""
A failed page scrape uses the ATS API's own description, when discovery has
one (R124).

On the first live deploy, all three Ashby jobs (Vanta) were logged "no
description could be read" and given no resume. Discovery had fetched them
from Ashby's posting API, which returns `descriptionPlain`: the full job
description. `_listing` keeps that as `full_jd`, and nothing in enrichment
read it. Enrichment scraped the job page instead, and when that failed it fell
back to `description`, the first 300 characters. So the jobs were scored on a
snippet and marked unreadable, with their full text on the listing.

Why the page scrape failed on Fly is not established. This container's proxy
refuses Ashby, and the fix does not depend on it: a job whose scrape works is
untouched, and a failed one uses the first-party text it already has.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import agents.enrichment_agent as module  # noqa: E402
from agents.enrichment_agent import EnrichmentAgent  # noqa: E402
from tools.scraping.jd_scraper import MIN_JD_LENGTH  # noqa: E402

FULL = ("About Vanta. We are hiring a Senior Software Engineer, Identity. "
        "Requirements: 5+ years building backend services in Go or Python. ") * 8


class _Job:
    def __init__(self, full_jd="", source="ats_ashby"):
        self.apply_url = "https://jobs.ashbyhq.com/vanta/abc"
        self.title = "Backend Senior Software Engineer, Identity"
        self.company = "Vanta"
        self.source = source
        self.full_jd = full_jd
        self.description = full_jd[:300]


FAILED = {"full_jd": "", "requirements": {}, "scraped_successfully": False,
          "scraper_used": "generic"}
SCRAPED = {"full_jd": "From the page. " * 30, "requirements": {},
           "scraped_successfully": True, "scraper_used": "ashby"}


class TestAFailedScrapeUsesTheApiText(unittest.TestCase):

    def setUp(self):
        self.agent = EnrichmentAgent.__new__(EnrichmentAgent)

    def scrape(self, job, page):
        with mock.patch.object(module, "scrape_jd", return_value=dict(page)):
            return self.agent._real_scrape(job)

    def test_the_full_api_description_is_used_and_readable(self):
        self.assertGreaterEqual(len(FULL.strip()), MIN_JD_LENGTH)
        result = self.scrape(_Job(FULL), FAILED)
        self.assertTrue(result["scraped_successfully"])
        self.assertEqual(result["full_jd"], FULL.strip())
        self.assertEqual(result["scraper_used"], "ats_api (ats_ashby)")
        self.assertIn("must_have", result["requirements"])

    def test_it_is_not_the_300_character_snippet(self):
        self.assertGreater(len(self.scrape(_Job(FULL), FAILED)["full_jd"]), 300)

    def test_a_working_scrape_is_untouched(self):
        result = self.scrape(_Job(FULL), SCRAPED)
        self.assertEqual(result["scraper_used"], "ashby")
        self.assertEqual(result["full_jd"], SCRAPED["full_jd"])

    def test_no_api_text_still_fails_honestly(self):
        """R61 unchanged: nothing invented, the snippet kept, the flag false."""
        for job in (_Job(""), _Job("Too short to be a description.")):
            with self.subTest(full_jd=job.full_jd):
                result = self.scrape(job, FAILED)
                self.assertFalse(result["scraped_successfully"])
                self.assertEqual(result["scraper_used"], "failed")
                self.assertEqual(result["full_jd"], job.description)

    def test_a_listing_without_the_field_is_the_old_path(self):
        """Non-ATS sources build listings with no `full_jd`."""
        job = _Job(FULL)
        del job.full_jd
        self.assertFalse(self.scrape(job, FAILED)["scraped_successfully"])


class TestDiscoveryDoesKeepTheFullText(unittest.TestCase):
    """The field this reads is the one Ashby's discovery writes."""

    def test_ashby_listing_carries_the_full_description(self):
        from tools.search import ats_search
        payload = {"jobs": [{"id": "abc", "title": "Engineer", "location": "Remote",
                             "jobUrl": "https://jobs.ashbyhq.com/vanta/abc",
                             "descriptionPlain": FULL}]}
        with mock.patch.object(ats_search, "_fetch", return_value=payload):
            listing = ats_search._ashby("vanta")[0]
        self.assertEqual(listing.full_jd, FULL.strip())
        self.assertEqual(listing.description, FULL.strip()[:300])
        self.assertEqual(listing.source, "ats_ashby")


if __name__ == "__main__":
    unittest.main()

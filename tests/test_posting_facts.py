"""
Facts a posting states about itself (R64, kept by R66).

Written for the public board and kept when the board was dropped, because
the shape is what a multi-user product needs anyway: **one posting is read
against many people**, so what it demands should be extracted once and
compared per-user rather than re-derived for each.

The load-bearing part is that every fact carries its basis.
`required_years` returns None both when a posting states no floor and when
the text could not be read. Collapsing those is harmless in a gate and not
in a filter: a five-years role whose floor failed to parse looks exactly
like a role that asks for nothing.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.jobs.posting_facts import (  # noqa: E402
    READABLE_MIN_CHARS,
    classify_level,
    demands_facet,
    posting_facts,
    years_facet,
)

BODY = "We are hiring an engineer. " * 40          # comfortably readable
THIN = "Backend Engineer at Example Corp."          # what a failed scrape leaves


def store_row(**over):
    row = {
        "url": "https://example.com/job/1",
        "title": "Software Engineer",
        "company": "Example",
        "location": "San Francisco, CA",
        "source": "ats_greenhouse",
        "first_seen": "2026-08-25T10:00:00+00:00",
        "full_jd": BODY,
        "score": 55.3,
        "status": "applied",
        "scored_at": "2026-08-25T11:00:00+00:00",
        "selection": '{"picked": []}',
        "resume_tex": "C:/Users/someone/resume.tex",
        "resume_pdf": "C:/Users/someone/resume.pdf",
        "gate_reason": "asks for 8+ years",
        "gate_checked": "abc123",
    }
    row.update(over)
    return row


class TestTheThreeStates(unittest.TestCase):
    """The distinction a gate did not need and a filter does."""

    def test_a_stated_floor(self):
        years, basis = years_facet(BODY + " Requires 5+ years of experience.")
        self.assertEqual((years, basis), (5, "stated"))

    def test_a_body_that_asks_for_none(self):
        years, basis = years_facet(BODY)
        self.assertEqual((years, basis), (None, "none_stated"))

    def test_a_body_too_thin_to_read(self):
        self.assertEqual(years_facet(THIN), (None, "unknown"))

    def test_experience_asked_for_in_words_is_unknown_not_none(self):
        """
        "Several years of experience" states a requirement this code cannot
        turn into a number. Reporting that as "asks for none" would put the
        posting in the early-career view on the strength of a parser failure.
        """
        years, basis = years_facet(BODY + " Several years of experience required.")
        self.assertEqual((years, basis), (None, "unknown"))

    def test_the_threshold_separates_real_bodies_from_summaries(self):
        """
        Calibrated rather than guessed: real bodies in the store start at 818
        characters, failed-scrape summaries top out at 300, and nothing lands
        between. If this constant ever drifts into that range the separation
        stops being clean.
        """
        self.assertGreater(READABLE_MIN_CHARS, 300)
        self.assertLess(READABLE_MIN_CHARS, 818)

    def test_demands_from_a_thin_body_are_unknown_not_absent(self):
        demands, basis = demands_facet(THIN)
        self.assertEqual(basis, "unknown")
        self.assertFalse(any(demands.values()))

    def test_demands_from_a_real_body_are_read(self):
        _, basis = demands_facet(BODY)
        self.assertEqual(basis, "read")


class TestDemandsAreProfileFree(unittest.TestCase):
    """The detection half of R56's gate, with the judgement removed."""

    def test_a_clearance_you_must_hold(self):
        demands, _ = demands_facet(
            BODY + " Candidates will not be considered who do not hold an "
                   "active TS/SCI clearance.")
        self.assertTrue(demands["clearance_held"])

    def test_a_clearance_you_could_obtain_is_a_us_person_demand(self):
        """R56's held-vs-obtainable rule has to survive the split."""
        demands, _ = demands_facet(
            BODY + " An active TS/SCI clearance, or eligibility to obtain one.")
        self.assertFalse(demands["clearance_held"])
        self.assertTrue(demands["us_person"])

    def test_equal_opportunity_boilerplate_is_still_skipped(self):
        demands, _ = demands_facet(
            BODY + " We do not discriminate on the basis of citizenship status "
                   "or any characteristic protected by US federal law.")
        self.assertFalse(any(demands.values()))

    def test_no_sponsorship(self):
        demands, _ = demands_facet(
            BODY + " We are unable to provide visa sponsorship.")
        self.assertTrue(demands["no_sponsorship"])


class TestLevel(unittest.TestCase):
    def test_a_senior_title_wins(self):
        self.assertEqual(classify_level("Senior Engineer", None, "none_stated", False),
                         "senior")

    def test_a_high_floor_is_senior(self):
        self.assertEqual(classify_level("Engineer", 8, "stated", False), "senior")

    def test_a_middling_floor_is_mid(self):
        self.assertEqual(classify_level("Engineer", 3, "stated", False), "mid")

    def test_a_low_floor_is_entry(self):
        self.assertEqual(classify_level("Engineer", 1, "stated", False), "entry")

    def test_saying_nothing_is_unspecified_not_entry(self):
        """
        Inventing "entry" for a posting that never said would put senior roles
        in the view most visitors start on.
        """
        self.assertEqual(classify_level("Engineer", None, "none_stated", False),
                         "unspecified")

    def test_excluding_new_grads_is_at_least_mid(self):
        self.assertEqual(classify_level("Engineer", None, "none_stated", True),
                         "mid")


class TestAgainstTheRealPostings(unittest.TestCase):
    """Skipped on a clean clone."""

    def setUp(self):
        path = ROOT / "baselines" / "2026-08-25-pre-r53" / "enriched_jobs.json"
        if not path.exists():
            self.skipTest("needs the frozen baseline")
        self.jobs = json.loads(path.read_text(encoding="utf-8"))

    def _row(self, company, needle=""):
        for job in self.jobs:
            if job.get("company") == company and needle in str(job.get("title")):
                return posting_facts({
                    "url": job.get("apply_url"), "title": job.get("title"),
                    "company": job.get("company"), "location": job.get("location"),
                    "source": job.get("source"), "first_seen": "2026-08-25",
                    "full_jd": job.get("full_jd"),
                })
        return None

    def test_samsara_states_eight_years(self):
        row = self._row("Samsara", "Finance")
        if row is None:
            self.skipTest("posting not in this baseline")
        self.assertEqual(row["years_required"], 8)
        self.assertEqual(row["years_basis"], "stated")
        self.assertEqual(row["level"], "senior")

    def test_scale_ai_devops_demands_a_clearance_in_hand(self):
        row = self._row("Scale AI", "DevOps")
        if row is None:
            self.skipTest("posting not in this baseline")
        self.assertTrue(row["demands"]["clearance_held"])

    def test_scale_ai_forward_deployed_demands_only_us_person_status(self):
        row = self._row("Scale AI", "Forward Deployed")
        if row is None:
            self.skipTest("posting not in this baseline")
        self.assertFalse(row["demands"]["clearance_held"])
        self.assertTrue(row["demands"]["us_person"])

    def test_databricks_excludes_early_career(self):
        row = self._row("Databricks")
        if row is None:
            self.skipTest("posting not in this baseline")
        self.assertTrue(row["excludes_entry_level"])

    def test_experian_is_in_brazil(self):
        row = self._row("Experian")
        if row is None:
            self.skipTest("posting not in this baseline")
        self.assertEqual(row["country"], "Brazil")

    def test_every_posting_produces_a_row_without_raising(self):
        for job in self.jobs:
            posting_facts({"url": job.get("apply_url"), "title": job.get("title"),
                       "company": job.get("company"),
                       "location": job.get("location"),
                       "source": job.get("source"), "first_seen": "x",
                       "full_jd": job.get("full_jd")})


if __name__ == "__main__":
    unittest.main()

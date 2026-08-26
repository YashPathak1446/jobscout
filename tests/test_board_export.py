"""
Facts about the posting, not verdicts about the reader (R64).

Every gate this project built answers "does this rule *you* out", which needs a
profile. R60 planned for the public board to apply R56's gate; it cannot,
because a public board has no visitor. So the board states what a posting asks
for and the reader filters.

Two things carry the weight here.

**Every facet carries its basis.** `required_years` returns None both when a
posting states no floor and when the text could not be read. Under a gate that
collapse was harmless — it meant a job slipped through. Under a *filter* it is
not: a five-years role whose floor failed to parse lands in the early-career
view looking like it belongs there.

**Nothing personal leaves the store.** The board links out rather than
mirroring, because the job description is the employer's prose (R60), and the
score, status and resume paths are one person's. `FORBIDDEN_FIELDS` is asserted
rather than assumed, because "true by construction" is exactly what was true of
`scraped_successfully` before R61.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.export_board import (  # noqa: E402
    FORBIDDEN_FIELDS,
    build_payload,
    check_no_personal_data,
)
from tools.jobs.board_export import (  # noqa: E402
    DEFAULT_PRESET,
    READABLE_MIN_CHARS,
    SCHEMA_VERSION,
    build_row,
    build_rows,
    classify_level,
    demands_facet,
    summarise_facets,
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


class TestNothingPersonalLeaves(unittest.TestCase):
    """The reason this module exists as a seam rather than a query."""

    def setUp(self):
        self.payload = build_payload([store_row()])
        self.job = self.payload["jobs"][0]

    def test_no_forbidden_field_is_present(self):
        for field in FORBIDDEN_FIELDS:
            self.assertNotIn(field, self.job)

    def test_the_check_agrees(self):
        self.assertEqual(check_no_personal_data(self.payload), [])

    def test_the_check_catches_a_leak(self):
        """The guard has to be able to fail, or it is decoration."""
        leaked = {"jobs": [{"url": "u", "full_jd": "the employer's prose"}]}
        self.assertEqual(check_no_personal_data(leaked), ["full_jd"])

    def test_the_job_description_does_not_appear_anywhere_in_the_payload(self):
        """
        Not just the field — the text. The board links out precisely so that
        the employer's prose is never republished.
        """
        marker = "UNIQUEMARKERPHRASE"
        payload = build_payload([store_row(full_jd=BODY + " " + marker)])
        self.assertNotIn(marker, json.dumps(payload))

    def test_the_apply_url_does_survive(self):
        """Linking out only works if the link is there."""
        self.assertEqual(self.job["url"], "https://example.com/job/1")


class TestThePayload(unittest.TestCase):
    def setUp(self):
        self.payload = build_payload([store_row(), store_row(
            url="https://example.com/job/2", title="Senior Engineer")])

    def test_it_carries_a_schema_version(self):
        self.assertEqual(self.payload["schema_version"], SCHEMA_VERSION)

    def test_the_default_preset_travels_with_the_data(self):
        """
        So the default view can change without a deploy. Facets were chosen
        over gates because early-career is a default rather than a hard filter,
        and this is where that default lives.
        """
        self.assertEqual(self.payload["default_preset"], DEFAULT_PRESET)
        self.assertTrue(DEFAULT_PRESET["include_unknown_years"],
                        "unknown must stay visible, per R62")

    def test_it_is_json_serialisable(self):
        json.dumps(self.payload)

    def test_first_seen_is_not_called_posted_at(self):
        """
        It is when this crawler first saw the posting, not when the employer
        published it — `ats_search` sets `created` to the crawl time, so no
        true posting date exists to export. The name has to say so.
        """
        job = self.payload["jobs"][0]
        self.assertIn("first_seen", job)
        self.assertNotIn("posted_at", job)


class TestTheFacetSummary(unittest.TestCase):
    """Counts that decide which controls are worth building."""

    def test_it_counts_the_bases(self):
        rows = build_rows([store_row(),
                           store_row(full_jd=THIN),
                           store_row(full_jd=BODY + " Requires 5+ years of experience.")])
        summary = summarise_facets(rows)
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["years_basis"]["unknown"], 1)
        self.assertEqual(summary["years_basis"]["stated"], 1)
        self.assertEqual(summary["years_basis"]["none_stated"], 1)

    def test_it_reports_the_distribution(self):
        rows = build_rows([
            store_row(full_jd=BODY + " Requires 5+ years of experience."),
            store_row(full_jd=BODY + " Requires 5+ years of experience."),
        ])
        self.assertEqual(summarise_facets(rows)["years_distribution"], {5: 2})

    def test_an_empty_store_summarises_to_zero(self):
        self.assertEqual(summarise_facets([])["total"], 0)


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
                return build_row({
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
            build_row({"url": job.get("apply_url"), "title": job.get("title"),
                       "company": job.get("company"),
                       "location": job.get("location"),
                       "source": job.get("source"), "first_seen": "x",
                       "full_jd": job.get("full_jd")})


if __name__ == "__main__":
    unittest.main()

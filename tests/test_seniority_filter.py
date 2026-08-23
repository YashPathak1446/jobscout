"""
Seniority filtering, driven by the profile rather than a constant (R34).

The gate used to compare every posting against a hardcoded entry-level list,
so a senior or mid-level user had their entire range excluded no matter what
their profile said. `job_preferences.seniority` had existed since the schema
was written and was read by nothing but a print statement — the same dead
field shape as `rarely_include` (R31).
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.jobs.job_filter import (  # noqa: E402
    SENIORITY_SYNONYMS,
    accepted_seniority_terms,
    evaluate,
)
from tools.search.job_listing import JobListing  # noqa: E402


def job(title, description=""):
    return JobListing(
        id="x", title=title, company="ACME", location="Remote",
        description=description, apply_url="https://example.test/1",
        salary_min=None, salary_max=None, created="", source="test",
    )


class _Locations:
    remote_ok = True
    countries = ["United States"]
    cities = []
    exclude_countries = []


class _Prefs:
    def __init__(self, seniority, roles=("Software Engineer",), excludes=()):
        self.seniority = list(seniority)
        self.target_roles = list(roles)
        self.exclude_keywords = list(excludes)
        self.locations = _Locations()
        self.job_recency_hours = 168


class _Profile:
    def __init__(self, prefs):
        self.job_preferences = prefs


class TestAcceptedTerms(unittest.TestCase):

    def test_expands_a_level_into_the_phrasings_ads_use(self):
        terms = accepted_seniority_terms(["new grad"])
        self.assertIn("new grad", terms)
        self.assertIn("recent graduate", terms)
        self.assertIn("early career", terms)

    def test_combines_several_levels(self):
        terms = accepted_seniority_terms(["junior", "senior"])
        self.assertIn("junior", terms)
        self.assertIn("senior", terms)

    def test_an_unknown_level_falls_back_to_matching_itself(self):
        # A profile may name a level this map has never heard of.
        self.assertIn("archmage", accepted_seniority_terms(["Archmage"]))

    def test_blank_entries_are_ignored(self):
        self.assertEqual(accepted_seniority_terms(["", "   ", None]), [])

    def test_no_levels_yields_no_terms(self):
        self.assertEqual(accepted_seniority_terms([]), [])
        self.assertEqual(accepted_seniority_terms(None), [])

    def test_every_documented_level_has_synonyms(self):
        for level, synonyms in SENIORITY_SYNONYMS.items():
            self.assertTrue(synonyms, f"{level} has no phrasings")
            self.assertIn(level, accepted_seniority_terms([level]),
                          f"{level} should match its own name")


class TestSeniorityGate(unittest.TestCase):

    def test_a_new_grad_profile_still_excludes_senior_roles(self):
        profile = _Profile(_Prefs(["new grad", "entry level", "junior"]))
        decision = evaluate(job("Senior Software Engineer"), profile)
        self.assertTrue(decision.exclude)
        self.assertIn("Seniority", decision.reason)

    def test_a_senior_profile_accepts_senior_roles(self):
        """The point of the change: a senior user can see senior jobs."""
        profile = _Profile(_Prefs(["mid", "senior", "staff"]))
        self.assertFalse(evaluate(job("Senior Software Engineer"), profile).exclude)
        self.assertFalse(evaluate(job("Staff Software Engineer"), profile).exclude)

    def test_a_senior_profile_still_sees_untitled_levels(self):
        # Nothing senior in the title means nothing to gate on.
        profile = _Profile(_Prefs(["mid", "senior"]))
        self.assertFalse(evaluate(job("Software Engineer"), profile).exclude)

    def test_a_new_grad_profile_accepts_an_entry_role(self):
        profile = _Profile(_Prefs(["new grad", "entry level", "junior"]))
        self.assertFalse(evaluate(job("Software Engineer, New Grad"), profile).exclude)

    def test_a_senior_title_with_accepted_wording_survives(self):
        # "Senior" in the title but the ad also says new grad — borderline,
        # and the old code kept these too.
        profile = _Profile(_Prefs(["new grad"]))
        listing = job("Senior Software Engineer", "great for a new grad")
        self.assertFalse(evaluate(listing, profile).exclude)

    def test_exclude_keywords_still_win_outright(self):
        profile = _Profile(_Prefs(["senior"], excludes=["senior"]))
        decision = evaluate(job("Senior Software Engineer"), profile)
        self.assertTrue(decision.exclude)
        self.assertIn("Excluded keyword", decision.reason)

    def test_the_reason_names_the_profile_range(self):
        """A rejection the user cannot explain is a rejection they cannot fix."""
        profile = _Profile(_Prefs(["new grad", "junior"]))
        reason = evaluate(job("Principal Engineer"), profile).reason
        self.assertIn("new grad", reason)


if __name__ == "__main__":
    unittest.main()

"""
Discovery searched for "new grad" whoever you were (R66).

R34 made the seniority *gate* read `job_preferences.seniority`, and roadmap
item 13 recorded the work as done — "`build_serper_query(role, seniority,
site)` is already parameterised and the caller simply passes `new grad`". The
caller kept passing it. So for a mid-level user every keyword query hunted
new-grad roles, and the gate then discarded what came back: a discovery pool
filtered twice, once by a constant nobody had noticed.

The query builder needed no changes. Only the two call sites did.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.jobs.job_filter import (  # noqa: E402
    primary_seniority_term,
    wants_early_career,
)
from tools.search.serper_search import build_serper_query  # noqa: E402


class _Prefs:
    def __init__(self, seniority):
        self.seniority = list(seniority)


class _Profile:
    def __init__(self, *seniority):
        self.job_preferences = _Prefs(seniority)


class TestTheTermAQueryGets(unittest.TestCase):
    def test_a_new_grad_profile_still_searches_for_new_grad(self):
        """The old behaviour has to survive for the user it was right for."""
        profile = _Profile("new grad", "entry level", "junior")
        self.assertEqual(primary_seniority_term(profile), "new grad")

    def test_a_mid_level_profile_does_not(self):
        self.assertEqual(primary_seniority_term(_Profile("mid", "senior")), "mid")

    def test_a_senior_profile_does_not(self):
        self.assertEqual(primary_seniority_term(_Profile("senior", "staff")), "senior")

    def test_the_first_level_wins_because_the_list_is_ordered_by_preference(self):
        self.assertEqual(primary_seniority_term(_Profile("junior", "mid")), "junior")

    def test_no_opinion_produces_no_term(self):
        """
        Empty rather than a default: `build_serper_query` omits an empty
        seniority, and an unfiltered role search beats a wrong one.
        """
        self.assertEqual(primary_seniority_term(_Profile()), "")

    def test_blank_entries_are_skipped(self):
        self.assertEqual(primary_seniority_term(_Profile("", "  ", "mid")), "mid")

    def test_a_profile_without_the_field_does_not_raise(self):
        self.assertEqual(primary_seniority_term(object()), "")


class TestTheQueryItself(unittest.TestCase):
    """The bug, stated as the thing that must not come back."""

    def test_a_mid_level_search_does_not_say_new_grad(self):
        query = build_serper_query(
            "Backend Engineer",
            primary_seniority_term(_Profile("mid", "senior")),
            "greenhouse.io")
        self.assertNotIn("new grad", query)
        self.assertIn("mid", query)
        self.assertIn("Backend Engineer", query)

    def test_a_new_grad_search_still_does(self):
        query = build_serper_query(
            "Software Engineer",
            primary_seniority_term(_Profile("new grad")),
            "greenhouse.io")
        self.assertIn("new grad", query)

    def test_an_empty_term_leaves_the_role_unqualified(self):
        query = build_serper_query("Data Engineer", primary_seniority_term(_Profile()))
        self.assertEqual(query.strip(), "Data Engineer")


class TestWhoNewGradSourcesAreFor(unittest.TestCase):
    """
    `github_newgrad` is curated new-grad lists and has no senior equivalent, so
    for a profile that does not accept those levels it fills the pool with
    postings the gate immediately discards.
    """

    def test_an_early_career_profile_wants_them(self):
        self.assertTrue(wants_early_career(_Profile("new grad", "entry level")))
        self.assertTrue(wants_early_career(_Profile("junior")))

    def test_a_mid_or_senior_profile_does_not(self):
        self.assertFalse(wants_early_career(_Profile("mid", "senior")))
        self.assertFalse(wants_early_career(_Profile("staff", "lead")))

    def test_a_range_that_reaches_down_still_does(self):
        self.assertTrue(wants_early_career(_Profile("entry level", "mid", "senior")))

    def test_case_and_spacing_do_not_matter(self):
        self.assertTrue(wants_early_career(_Profile("  New Grad  ")))

    def test_an_unset_range_is_not_treated_as_early_career(self):
        self.assertFalse(wants_early_career(_Profile()))
        self.assertFalse(wants_early_career(object()))


class TestTheRealProfileIsUnaffected(unittest.TestCase):
    """Skipped on a clean clone. The author's own searches must not change."""

    def test_the_existing_profile_still_searches_for_new_grad(self):
        if not (ROOT / "user_profiles" / "yash_pathak.json").exists():
            self.skipTest("needs a real profile")

        from tools.profile import load_profile

        profile = load_profile("yash_pathak")
        self.assertEqual(primary_seniority_term(profile), "new grad")
        self.assertTrue(wants_early_career(profile))


if __name__ == "__main__":
    unittest.main()

"""
Reading the requirement the title hides (R54).

Discovery's filter reads the *title*, deliberately: it runs before enrichment
so it needs no JD, which is what protects the scraping budget. The cost is
that a clean title can sit over a disqualifying body, and in one real run
three of eight generated resumes went to postings that ruled the candidate out
in their second paragraph.

The hard part is not finding "years" or "new graduate" — it is telling the
disqualifying use apart from the identical words in a job worth keeping. These
five sentences are all real, and a keyword rule gets every one of them wrong:

    8+ years of relevant experience                            exclude
    5+ years of software engineering experience                exclude
    not intended for internship, new graduate, or entry-level  exclude
    entry-level position perfect for new graduates, 0-2 years  KEEP
    3-5+ years of QA automation experience                     KEEP (floor 3)
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.jobs.job_filter import (  # noqa: E402
    body_disqualifiers,
    excludes_entry_level,
    required_years,
)


class _Prefs:
    def __init__(self, seniority):
        self.seniority = seniority


class _Profile:
    def __init__(self, seniority=("new grad", "entry level", "junior")):
        self.job_preferences = _Prefs(list(seniority))


class TestReadingTheYearsFloor(unittest.TestCase):
    """The floor, not the ceiling: what you must clear to be considered."""

    def test_a_plus_form(self):
        self.assertEqual(required_years("8+ years of relevant experience"), 8)

    def test_a_range_takes_its_lower_bound(self):
        self.assertEqual(required_years("2-3 years of experience"), 2)

    def test_a_range_with_an_open_top_still_takes_the_lower_bound(self):
        """
        The real one that caught a false positive: "3-5+ years" was read as a
        floor of 5, and a job the candidate qualifies for was dropped.
        """
        self.assertEqual(
            required_years("3-5+ years of QA automation experience"), 3)

    def test_at_least(self):
        self.assertEqual(required_years("at least 6 years of experience"), 6)

    def test_minimum_of(self):
        self.assertEqual(required_years("minimum of 4 years experience"), 4)

    def test_the_lowest_floor_wins_when_several_are_listed(self):
        """
        "5+ years backend, 2+ years with Go" — the smallest is what you must
        clear to apply. Taking the largest would reject on a nice-to-have.
        """
        text = ("5+ years of backend experience. Also 2+ years of "
                "experience with Go.")
        self.assertEqual(required_years(text), 2)

    def test_years_without_an_experience_word_is_not_a_requirement(self):
        """"grew revenue 40% in 3 years" is an achievement, not a bar."""
        self.assertIsNone(required_years("grew revenue 40% in 3 years"))

    def test_no_years_at_all(self):
        self.assertIsNone(required_years("We want a curious engineer."))

    def test_empty_text(self):
        self.assertIsNone(required_years(""))


class TestTellingExclusionFromInvitation(unittest.TestCase):
    """
    The same words mean opposite things. "new graduate" appears in both the
    job that excludes you and the job that wants you.
    """

    def test_an_explicit_exclusion_is_caught(self):
        self.assertTrue(excludes_entry_level(
            "This role is for experienced engineers. It is not intended for "
            "internship, new graduate, or entry-level applicants."))

    def test_an_invitation_is_not(self):
        """Elastic and Baseten both read like this, and both are good matches."""
        self.assertFalse(excludes_entry_level(
            "This is an entry-level position perfect for new graduates or "
            "those with 0-2 years of experience."))

    def test_mentioning_new_grads_positively_elsewhere_is_not_exclusion(self):
        self.assertFalse(excludes_entry_level(
            "We hire new graduates every year and support them well."))

    def test_not_open_to(self):
        self.assertTrue(excludes_entry_level(
            "This posting is not open to entry-level candidates."))

    def test_cannot_consider(self):
        self.assertTrue(excludes_entry_level(
            "We cannot consider new grad applicants for this req."))

    def test_a_distant_negation_does_not_count(self):
        """
        A "not" three paragraphs earlier is about something else. The cue has
        to be close enough to plausibly govern the term.
        """
        text = ("We do not offer visa sponsorship. " + "x" * 300 +
                " This is a great role for new graduates.")
        self.assertFalse(excludes_entry_level(text))


class TestTheGateAsAWhole(unittest.TestCase):

    def test_a_senior_requirement_disqualifies(self):
        reasons = body_disqualifiers("8+ years of relevant experience",
                                     _Profile())
        self.assertTrue(reasons)
        self.assertIn("8", reasons[0])

    def test_an_entry_level_posting_survives(self):
        self.assertEqual(body_disqualifiers(
            "entry-level position, 0-2 years of experience", _Profile()), [])

    def test_a_junior_profile_tolerates_three_years(self):
        self.assertEqual(
            body_disqualifiers("3 years of experience required", _Profile()), [])

    def test_a_mid_level_profile_tolerates_five(self):
        profile = _Profile(("mid",))
        self.assertEqual(
            body_disqualifiers("5+ years of experience", profile), [])

    def test_the_same_posting_is_judged_against_the_profile(self):
        """Not a global rule: a senior candidate is not excluded by 8+ years."""
        text = "8+ years of engineering experience"
        self.assertTrue(body_disqualifiers(text, _Profile()))
        self.assertEqual(body_disqualifiers(text, _Profile(("senior",))), [])

    def test_an_unknown_seniority_range_does_not_reject_everything(self):
        """
        A profile naming levels this map has never heard of should fall back to
        permissive. A gate that silently drops every job because it could not
        read the profile is worse than no gate.
        """
        profile = _Profile(("wizard",))
        self.assertEqual(body_disqualifiers("9+ years of experience", profile), [])

    def test_an_empty_jd_disqualifies_nothing(self):
        self.assertEqual(body_disqualifiers("", _Profile()), [])

    def test_both_reasons_can_fire_together(self):
        text = ("10+ years of experience required. Not intended for new "
                "graduate applicants.")
        self.assertEqual(len(body_disqualifiers(text, _Profile())), 2)


class TestAgainstTheRealPostings(unittest.TestCase):
    """
    The five JDs a human reviewed by hand, from outputs/2026-08-25.

    Skipped on a clean clone; when the file is there this is the case that
    actually mattered.
    """

    EXPECTED = {
        "Samsara": True, "Databricks": True, "Elastic": False, "Baseten": False,
    }

    def setUp(self):
        import json

        # The frozen copy, not `outputs/` — a live output directory is
        # overwritten by the next run, and these assert facts about one
        # specific run. Verified by `scripts/baseline.py verify --all`.
        path = ROOT / "baselines" / "2026-08-25-pre-r53" / "enriched_jobs.json"
        if not path.exists():
            self.skipTest("needs a real enriched run")
        self.jobs = json.loads(path.read_text(encoding="utf-8"))

        from tools.profile import load_profile
        if not (ROOT / "user_profiles" / "yash_pathak.json").exists():
            self.skipTest("needs a real profile")
        self.profile = load_profile("yash_pathak")

    def _first(self, company, needle=""):
        for job in self.jobs:
            if job.get("company") == company and needle in str(job.get("title")):
                return job
        return None

    def test_each_reviewed_posting_gets_the_verdict_a_human_gave_it(self):
        for company, should_drop in self.EXPECTED.items():
            job = self._first(company)
            if job is None:
                continue
            reasons = body_disqualifiers(job.get("full_jd", ""), self.profile)
            self.assertEqual(
                bool(reasons), should_drop,
                f"{company}: expected drop={should_drop}, got {reasons}")

    def test_the_scale_ai_forward_deployed_role_is_dropped(self):
        job = self._first("Scale AI", "Forward Deployed")
        if job is None:
            self.skipTest("posting not in this run")
        self.assertTrue(body_disqualifiers(job.get("full_jd", ""), self.profile))

    def test_the_gate_does_not_empty_the_run(self):
        """
        A filter that removes almost everything is a bug, not a filter. Four
        of thirty-five when this was written.
        """
        dropped = sum(1 for job in self.jobs
                      if body_disqualifiers(job.get("full_jd", ""), self.profile))
        self.assertLess(dropped, len(self.jobs) / 3,
                        f"{dropped}/{len(self.jobs)} dropped — too aggressive")


if __name__ == "__main__":
    unittest.main()

"""
Asking the question a person can answer (R68).

The wizard used to ask a stranger to pick a *range of seniority levels* —
"new grad, entry level, junior" — which is modelling work pushed onto them, and
which `YEARS_BY_LEVEL` then converted straight back into a number of years.
Years is the fact somebody knows about themselves.

**The override is the delicate part.** Someone with six years who disagrees
with the derived range and narrows it to mid-level must keep that choice when
they later edit an unrelated screen. So the derivation never writes into
`seniority`: emptiness *is* the flag, exactly as R15's `merge_importance`
treats a component the profile does not mention. A field recomputed on save is
a field that loses your answer.

The tolerance constant was chosen to reproduce measured behaviour rather than
to look tidy — `years + 3` is what the old level map already produced at both
points a real profile had been measured at.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.jobs.job_filter import (  # noqa: E402
    YEARS_BY_LEVEL,
    YEARS_TOLERANCE,
    _tolerated_years,
    derive_levels,
    effective_seniority,
    primary_seniority_term,
    wants_early_career,
)


class _Locations:
    countries = ["United States"]
    exclude_countries = []
    states_priority = []
    states_acceptable = []
    cities = []
    remote_ok = True
    willing_to_relocate = True


class _Prefs:
    def __init__(self, years=None, seniority=()):
        self.years_experience = years
        self.seniority = list(seniority)
        self.exclude_keywords = []
        self.target_roles = []
        self.locations = _Locations()


class _Profile:
    def __init__(self, years=None, seniority=()):
        self.job_preferences = _Prefs(years, seniority)


class TestDerivingLevels(unittest.TestCase):
    def test_a_new_graduate(self):
        self.assertEqual(derive_levels(0), ["new grad", "entry level"])

    def test_a_few_years_in(self):
        self.assertEqual(derive_levels(3), ["junior", "mid"])

    def test_mid_career(self):
        self.assertEqual(derive_levels(6), ["mid", "senior"])

    def test_a_long_career_tops_out(self):
        self.assertEqual(derive_levels(12), ["staff", "lead"])
        self.assertEqual(derive_levels(30), ["staff", "lead"])

    def test_two_levels_because_people_apply_upward(self):
        """Someone three years in reads both junior and mid postings."""
        for years in range(0, 15):
            self.assertEqual(len(derive_levels(years)), 2, years)

    def test_nothing_stated_derives_nothing(self):
        self.assertEqual(derive_levels(None), [])

    def test_nonsense_does_not_raise(self):
        self.assertEqual(derive_levels("some"), [])
        self.assertEqual(derive_levels(-4), ["new grad", "entry level"])


class TestTheOverrideSurvives(unittest.TestCase):
    """
    The failure this design exists to prevent.

    If the derivation wrote its result into `seniority`, then editing any other
    field would recompute and silently discard a deliberate choice.
    """

    def test_an_empty_range_is_derived(self):
        self.assertEqual(effective_seniority(_Profile(years=6)),
                         ["mid", "senior"])

    def test_a_stated_range_wins_over_the_derivation(self):
        profile = _Profile(years=6, seniority=["mid"])
        self.assertEqual(effective_seniority(profile), ["mid"])

    def test_it_survives_a_change_to_years(self):
        """
        Editing the number must not silently re-derive over a choice the user
        made deliberately — nothing writes into `seniority`, so it cannot.
        """
        profile = _Profile(years=6, seniority=["mid"])
        profile.job_preferences.years_experience = 12
        self.assertEqual(effective_seniority(profile), ["mid"])

    def test_blank_entries_do_not_count_as_an_override(self):
        profile = _Profile(years=0, seniority=["", "   "])
        self.assertEqual(effective_seniority(profile), ["new grad", "entry level"])

    def test_no_years_and_no_levels_is_no_opinion(self):
        self.assertEqual(effective_seniority(_Profile()), [])


class TestTolerance(unittest.TestCase):
    """
    `years + 3`, chosen to reproduce the old lookup rather than to be neat.
    """

    def test_it_matches_the_old_map_for_a_new_graduate(self):
        self.assertEqual(_tolerated_years(_Profile(years=0)),
                         YEARS_BY_LEVEL["junior"])

    def test_it_matches_the_old_map_for_a_mid_level_range(self):
        """5 years derived [mid, senior], which the old map tolerated at 8."""
        self.assertEqual(_tolerated_years(_Profile(years=5)),
                         YEARS_BY_LEVEL["senior"])

    def test_it_scales_past_the_map(self):
        self.assertEqual(_tolerated_years(_Profile(years=20)),
                         20 + YEARS_TOLERANCE)

    def test_an_explicit_range_still_resolves_through_the_map(self):
        """
        A hand-tuned profile keeps the behaviour it was tuned with, because it
        never asked the years question.
        """
        profile = _Profile(seniority=["new grad", "entry level", "junior"])
        self.assertEqual(_tolerated_years(profile), YEARS_BY_LEVEL["junior"])

    def test_a_profile_with_no_opinion_tolerates_everything(self):
        """Rejecting every posting is the worse failure, so silence is wide."""
        self.assertEqual(_tolerated_years(_Profile()), max(YEARS_BY_LEVEL.values()))


class TestWhatTheDerivedRangeFeeds(unittest.TestCase):
    """Every consumer reads the effective range, not the raw field."""

    def test_the_search_term_follows_the_years(self):
        self.assertEqual(primary_seniority_term(_Profile(years=8)), "senior")
        self.assertEqual(primary_seniority_term(_Profile(years=0)), "new grad")

    def test_new_grad_sources_follow_the_years(self):
        self.assertTrue(wants_early_career(_Profile(years=1)))
        self.assertFalse(wants_early_career(_Profile(years=9)))

    def test_an_override_redirects_them_too(self):
        profile = _Profile(years=0, seniority=["senior"])
        self.assertEqual(primary_seniority_term(profile), "senior")
        self.assertFalse(wants_early_career(profile))

    def test_the_gate_fingerprint_covers_years(self):
        """
        R62 re-judges the board when the gate's inputs change. Years is now one
        of them, so changing it must invalidate stored verdicts.
        """
        from tools.jobs.job_filter import gate_fingerprint

        a, b = _Profile(years=2), _Profile(years=9)
        for profile in (a, b):
            profile.personal_info = type("P", (), {
                "us_citizen": True, "permanent_resident": False,
                "holds_security_clearance": False})()
        self.assertNotEqual(gate_fingerprint(a), gate_fingerprint(b))


class TestTheAuthorsProfileIsUnchanged(unittest.TestCase):
    """Skipped on a clean clone. An explicit range means nothing moved."""

    def test_same_levels_and_same_tolerance_as_before(self):
        if not (ROOT / "user_profiles" / "yash_pathak.json").exists():
            self.skipTest("needs a real profile")

        from tools.profile import load_profile

        profile = load_profile("yash_pathak")
        self.assertEqual(effective_seniority(profile),
                         ["new grad", "entry level", "junior"])
        self.assertEqual(_tolerated_years(profile), 3)

    def test_the_same_postings_are_still_dropped(self):
        """
        R54's gate was measured against this corpus. Changing what feeds it
        must not change what it does.
        """
        import json

        corpus = ROOT / "baselines" / "2026-08-25-pre-r53" / "enriched_jobs.json"
        if not corpus.exists() or not (ROOT / "user_profiles" / "yash_pathak.json").exists():
            self.skipTest("needs the frozen baseline and a real profile")

        from tools.jobs.job_filter import body_disqualifiers
        from tools.profile import load_profile

        profile = load_profile("yash_pathak")
        dropped = {job["company"] for job in json.loads(corpus.read_text(encoding="utf-8"))
                   if body_disqualifiers(job.get("full_jd", ""), profile)}
        self.assertEqual(dropped, {"Samsara", "Databricks", "Scale AI", "Okta"})


if __name__ == "__main__":
    unittest.main()

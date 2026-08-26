"""
Two location preferences the profile asked for and nothing read (R68).

`exclude_countries` was declared and never consulted. `willing_to_relocate` was
worse: the wizard *asked* for it and no code anywhere looked at the answer —
a question put to a user for nothing, which for a paying one is a broken
promise rather than dead code.

**Relocation is a gate, not a weight**, and R55 is the reason. A weighted
location penalty gets outrun by vocabulary overlap: that is exactly how a São
Paulo posting scored 54% against a profile asking for the United States. So
"somewhere I would have to move to" excludes rather than deducts.

**And it is guarded.** A profile naming no cities and no priority states has
expressed no location preference; gating on the flag alone would empty the
board. That is R55's lesson pointed the other way — there an unknown country
silently passed a filter built to catch it, here an unstated preference would
silently catch everything.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.jobs.job_filter import evaluate  # noqa: E402


class _Locations:
    def __init__(self, countries=("United States",), exclude=(), priority=(),
                 acceptable=(), cities=(), remote_ok=True, relocate=True):
        self.countries = list(countries)
        self.exclude_countries = list(exclude)
        self.states_priority = list(priority)
        self.states_acceptable = list(acceptable)
        self.cities = list(cities)
        self.remote_ok = remote_ok
        self.willing_to_relocate = relocate


class _Prefs:
    def __init__(self, locations):
        self.locations = locations
        self.seniority = ["new grad", "entry level", "junior"]
        self.years_experience = None
        self.exclude_keywords = []
        self.target_roles = ["Software Engineer"]


class _Profile:
    def __init__(self, **kwargs):
        self.job_preferences = _Prefs(_Locations(**kwargs))


class _Job:
    def __init__(self, location, title="Software Engineer", description=""):
        self.title = title
        self.company = "Example"
        self.location = location
        self.description = description


class TestExcludedCountries(unittest.TestCase):
    def test_a_named_country_is_excluded(self):
        profile = _Profile(countries=[], exclude=["Canada"])
        decision = evaluate(_Job("Toronto, ON, Canada"), profile)
        self.assertTrue(decision.exclude)
        self.assertIn("excluded", decision.reason)

    def test_it_works_without_a_whitelist(self):
        """
        The narrower statement. A user who names no preferred countries but
        rules one out has still said something, and the whitelist below would
        never reach it.
        """
        profile = _Profile(countries=[], exclude=["Canada"])
        self.assertFalse(evaluate(_Job("Austin, TX"), profile).exclude)

    def test_an_unlisted_country_is_untouched(self):
        profile = _Profile(countries=[], exclude=["Canada"])
        self.assertFalse(evaluate(_Job("Berlin, Germany"), profile).exclude)


class TestNotWillingToRelocate(unittest.TestCase):
    def setUp(self):
        self.staying = dict(priority=["California"], relocate=False)

    def test_a_job_outside_the_named_places_is_excluded(self):
        decision = evaluate(_Job("Austin, TX"), _Profile(**self.staying))
        self.assertTrue(decision.exclude)
        self.assertIn("not willing to relocate", decision.reason)

    def test_a_job_inside_them_is_kept(self):
        self.assertFalse(
            evaluate(_Job("San Francisco, CA"), _Profile(**self.staying)).exclude)

    def test_remote_is_never_relocation(self):
        """You do not move house for a remote job."""
        self.assertFalse(
            evaluate(_Job("Remote (US)"), _Profile(**self.staying)).exclude)

    def test_willing_to_relocate_changes_nothing(self):
        profile = _Profile(priority=["California"], relocate=True)
        self.assertFalse(evaluate(_Job("Austin, TX"), profile).exclude)

    def test_an_acceptable_state_is_not_relocation(self):
        profile = _Profile(priority=["California"], acceptable=["Texas"],
                           relocate=False)
        self.assertFalse(evaluate(_Job("Austin, TX"), profile).exclude)


class TestTheGuard(unittest.TestCase):
    """
    A profile that has named nowhere has expressed no preference, and the flag
    must have nothing to act on — otherwise it excludes the entire board.
    """

    def test_no_named_places_means_the_flag_does_nothing(self):
        profile = _Profile(priority=[], cities=[], relocate=False)
        self.assertFalse(evaluate(_Job("Austin, TX"), profile).exclude)

    def test_a_named_city_is_enough_to_arm_it(self):
        profile = _Profile(priority=[], cities=["San Francisco"], relocate=False)
        self.assertTrue(evaluate(_Job("Austin, TX"), profile).exclude)

    def test_it_cannot_empty_a_board(self):
        """
        The failure mode stated as a property: with nowhere named, nothing is
        excluded on relocation however many postings are checked.
        """
        profile = _Profile(priority=[], cities=[], relocate=False)
        places = ["Austin, TX", "Seattle, WA", "New York, NY", "Boston, MA",
                  "Denver, CO", "Remote (US)"]
        excluded = [p for p in places if evaluate(_Job(p), profile).exclude]
        self.assertEqual(excluded, [])


if __name__ == "__main__":
    unittest.main()

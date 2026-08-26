"""
The template is the starting point for every profile anyone ever builds.

It was one person's. CLAUDE.md says the new-grad constraint is gone and the
code should not assume it; `user_profiles/template.json` was still assuming
it, three layers under anywhere anyone looks.

Found by importing a stranger's resume and reading what came out. Priya
Raghunathan, Staff Software Engineer at Wayfair, six years in, graduated 2018.
Her freshly built profile:

    exclude_keywords : ["senior", "staff", "principal", "5+ years", ...]
    years_experience : 0
    states_priority  : ["California", "New York"]

**It excluded "senior" and "staff" — the two words in her own job title.**
Discovery would have filtered out every role she is qualified for, and the
board would have looked empty rather than wrong. R68 fixed exactly this in the
wizard, where `_exclude_options(years)` offers exclusions relative to where
the user sits; nothing fixed the file the wizard starts from, because the
author's own profile was built before that code existed and never rebuilt.

`years_experience: 0` is the same mistake in the invariant's terms: zero years
is a value, and what the template knows about a new arrival is nothing.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

TEMPLATE = ROOT / "user_profiles" / "template.json"

# Words that name a level. A template that ships any of these has decided, on
# behalf of somebody it has never met, what they are worth.
LEVEL_WORDS = {
    "junior", "entry", "entry level", "new grad", "new graduate", "graduate",
    "mid", "mid-level", "senior", "staff", "principal", "lead", "director",
    "1+ years", "2+ years", "3+ years", "5+ years", "7+ years", "10+ years",
}


class TestTheTemplatePresumesNoLevel(unittest.TestCase):

    def setUp(self):
        self.profile = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        self.prefs = self.profile["job_preferences"]

    def test_it_excludes_no_seniority(self):
        excluded = {w.lower().strip() for w in self.prefs["exclude_keywords"]}
        presumed = sorted(excluded & LEVEL_WORDS)
        self.assertEqual(
            presumed, [],
            f"the template excludes {presumed} for everyone who ever uses it. "
            "A staff engineer importing a resume would filter out their own "
            "level and see an empty board.")

    def test_it_claims_no_seniority_either(self):
        """The other direction. Presuming senior is as wrong as presuming new."""
        self.assertEqual(self.prefs.get("seniority"), [])

    def test_years_of_experience_is_unknown_not_zero(self):
        """
        Zero is a value: it says new graduate. The template knows nothing
        about the person about to use it, and the schema types this field
        `Optional[int]` precisely so that "nothing" is expressible.
        """
        self.assertIsNone(self.prefs.get("years_experience"))

    def test_it_prefers_nobody_elses_geography(self):
        locations = self.prefs["locations"]
        self.assertEqual(locations.get("states_priority"), [])
        self.assertEqual(locations.get("states_acceptable"), [])

    def test_what_it_does_exclude_applies_to_everyone(self):
        """
        Not an empty list — the two that are true regardless of level. Keeping
        them is what stops this test being read as "exclude nothing".
        """
        excluded = {w.lower() for w in self.prefs["exclude_keywords"]}
        self.assertIn("phd required", excluded)
        self.assertIn("security clearance required", excluded)

    def test_the_template_still_loads(self):
        from tools.profile.profile_schema import UserProfile
        UserProfile(**self.profile)


class TestABuiltProfileInheritsNoLevel(unittest.TestCase):
    """
    The template is only half of it: `build_profile` copies the template and
    never touches `job_preferences`, so whatever is in there reaches the
    finished profile untouched. This is the assertion at the other end.
    """

    def test_build_profile_does_not_reintroduce_a_level(self):
        import inspect
        from scripts import init_profile

        source = inspect.getsource(init_profile.build_profile)
        for word in ("exclude_keywords", "seniority", "years_experience"):
            self.assertNotIn(
                word, source,
                f"build_profile now writes {word}; if it derives a level from "
                "the resume that may be an improvement, but this test and the "
                "template above both need to know about it")


if __name__ == "__main__":
    unittest.main()

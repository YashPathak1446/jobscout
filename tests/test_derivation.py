"""
Profile derivation from the resume (R15, R16).

These decide what a brand-new user's profile looks like before they touch
anything, so a regression here degrades onboarding silently — the profile
still loads, it is just wrong.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.profile.derivation import (  # noqa: E402
    DEFAULT_HIGH_COUNT,
    DEFAULT_MEDIUM_COUNT,
    _graduation_from_dates,
    derive_component_importance,
    derive_personal_info,
    merge_importance,
)


class TestImportanceFromResumeOrder(unittest.TestCase):
    """Top-2 high, next-4 medium — boundaries chosen by measurement (R15)."""

    def test_assigns_tiers_by_position(self):
        ids = [f"proj_{i}" for i in range(10)]
        tiers = derive_component_importance(ids)
        self.assertEqual(tiers["proj_0"], "high")
        self.assertEqual(tiers["proj_1"], "high")
        self.assertEqual(tiers["proj_2"], "medium")
        self.assertEqual(tiers["proj_5"], "medium")
        self.assertEqual(tiers["proj_6"], "low")

    def test_tier_counts_match_the_documented_rule(self):
        ids = [f"p{i}" for i in range(12)]
        tiers = derive_component_importance(ids)
        self.assertEqual(sum(t == "high" for t in tiers.values()), DEFAULT_HIGH_COUNT)
        self.assertEqual(sum(t == "medium" for t in tiers.values()), DEFAULT_MEDIUM_COUNT)

    def test_handles_fewer_components_than_tiers(self):
        tiers = derive_component_importance(["only_one"])
        self.assertEqual(tiers, {"only_one": "high"})

    def test_handles_no_components(self):
        self.assertEqual(derive_component_importance([]), {})


class TestMergeImportance(unittest.TestCase):
    """Derived values are defaults; anything stated in the profile wins."""

    def test_profile_value_overrides_the_derived_one(self):
        merged = merge_importance({"a": "low"}, {"a": "high", "b": "medium"})
        self.assertEqual(merged["a"], "low")

    def test_derived_value_fills_a_gap(self):
        merged = merge_importance({"a": "low"}, {"a": "high", "b": "medium"})
        self.assertEqual(merged["b"], "medium")

    def test_no_profile_map_leaves_the_derived_map_intact(self):
        derived = {"a": "high"}
        self.assertEqual(merge_importance(None, derived), derived)


class TestGraduationParsing(unittest.TestCase):
    """
    Fails to blank rather than guessing — a wrong graduation date silently
    changes which jobs a user is eligible for.
    """

    def test_reads_the_end_of_a_range(self):
        self.assertEqual(
            _graduation_from_dates("Sep. 2021 – June 2025"),
            ("June 2025", "Spring 2025"),
        )

    def test_handles_a_plain_hyphen(self):
        self.assertEqual(
            _graduation_from_dates("Aug 2020 - Dec 2024"),
            ("Dec 2024", "Fall 2024"),
        )

    def test_handles_the_word_to(self):
        self.assertEqual(
            _graduation_from_dates("2019 to May 2023"),
            ("May 2023", "Spring 2023"),
        )

    def test_ongoing_study_yields_nothing_rather_than_the_start_date(self):
        # Returning "Sept 2022" here would report a current student as
        # already graduated.
        self.assertEqual(_graduation_from_dates("Sept 2022 – Present"), ("", ""))

    def test_strips_qualifiers_and_still_finds_the_month(self):
        # A three-letter probe used to match "Exp" and lose the month.
        self.assertEqual(
            _graduation_from_dates("Expected May 2026"),
            ("May 2026", "Spring 2026"),
        )

    def test_year_without_a_month_gives_no_term(self):
        self.assertEqual(_graduation_from_dates("Aug 2021 – 2025"), ("2025", ""))

    def test_empty_input(self):
        self.assertEqual(_graduation_from_dates(""), ("", ""))

    def test_june_is_spring_not_summer(self):
        # Commencement is June at plenty of schools; the term is still Spring.
        _, term = _graduation_from_dates("Sep 2021 - June 2025")
        self.assertTrue(term.startswith("Spring"))


class _FakeResume:
    name = "Jane Doe"
    email = "jane@example.com"
    phone = "555-0100"
    github_url = "https://github.com/janedoe"
    linkedin_url = "https://linkedin.com/in/janedoe"
    education_school = "Example University"
    education_degree = "Bachelor of Science in Computer Science"
    education_dates = "Sep. 2021 – June 2025"


class TestPersonalInfoDerivation(unittest.TestCase):
    def test_derives_the_header_fields(self):
        info = derive_personal_info(_FakeResume())
        self.assertEqual(info["name"], "Jane Doe")
        self.assertEqual(info["email"], "jane@example.com")
        self.assertEqual(info["school"], "Example University")
        self.assertEqual(info["graduation_date"], "June 2025")
        self.assertEqual(info["graduation_term"], "Spring 2025")

    def test_omits_fields_a_resume_cannot_state(self):
        # Legal and eligibility meaning: an address line is where you live,
        # not where you are allowed to work.
        info = derive_personal_info(_FakeResume())
        for field in ("location", "visa_status", "us_citizen", "permanent_resident"):
            self.assertNotIn(field, info)

    def test_omits_empty_values_rather_than_writing_blanks(self):
        class Sparse:
            name = "Jane"
            email = ""
            education_dates = ""

        info = derive_personal_info(Sparse())
        self.assertIn("name", info)
        self.assertNotIn("email", info)
        self.assertNotIn("graduation_date", info)


if __name__ == "__main__":
    unittest.main()

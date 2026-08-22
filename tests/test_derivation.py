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
    derive_conditional_triggers,
    derive_personal_info,
    merge_conditional_triggers,
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


class _FakeComponent:
    """Minimum surface derive_conditional_triggers reads."""

    def __init__(self, comp_id, tech="", keywords=()):
        self.id = comp_id
        self.tech = tech
        self.keywords = list(keywords)


class TestConditionalTriggerDerivation(unittest.TestCase):
    """The last DERIVED field (R21). A bootstrapped user gets these or nothing."""

    def test_derives_triggers_from_the_tech_stack(self):
        comps = [
            _FakeComponent("proj_a", tech="Angular, TypeScript, OAuth 2.0"),
            _FakeComponent("proj_b", tech="Blender, OpenCV"),
        ]
        out = derive_conditional_triggers(comps)
        self.assertIn("angular", out["proj_a"])
        self.assertIn("blender", out["proj_b"])

    def test_drops_terms_carried_by_too_much_of_the_pool(self):
        # python in 3 of 4 is 75%, well past the 0.4 ratio; it cannot
        # discriminate between components, which is the whole job of a trigger.
        comps = [
            _FakeComponent("p1", tech="Python, Django"),
            _FakeComponent("p2", tech="Python, Flask"),
            _FakeComponent("p3", tech="Python, NumPy"),
            _FakeComponent("p4", tech="Rust"),
        ]
        out = derive_conditional_triggers(comps)
        for comp_id, triggers in out.items():
            self.assertNotIn("python", triggers, f"python survived on {comp_id}")
        self.assertIn("django", out["p1"])

    def test_a_term_unique_to_one_component_survives(self):
        comps = [
            _FakeComponent("p1", tech="Python, Django"),
            _FakeComponent("p2", tech="Python, Flask"),
        ]
        out = derive_conditional_triggers(comps)
        self.assertIn("django", out["p1"])
        self.assertIn("flask", out["p2"])

    def test_prunes_a_compound_when_its_part_is_already_a_trigger(self):
        # The tech stack contributes "oauth 2.0" and the keyword vocabulary
        # contributes "oauth" — which is exactly how the real resume produces
        # both. Keeping the pair would score two hits for one listed
        # technology, and R14 counts per hit.
        comps = [
            _FakeComponent("p1", tech="OAuth 2.0", keywords=["OAuth"]),
            _FakeComponent("p2", tech="Rust"),
        ]
        out = derive_conditional_triggers(comps)
        self.assertIn("oauth", out["p1"])
        self.assertNotIn("oauth 2.0", out["p1"])

    def test_component_name_is_never_a_trigger_source(self):
        # Names yield 'resume' and 'computer', which every JD contains. Only
        # vocabulary-controlled terms may become triggers.
        comp = _FakeComponent("proj_search_engine", tech="BeautifulSoup")
        comp.name = "Search Engine Resume Computer"
        out = derive_conditional_triggers([comp, _FakeComponent("p2", tech="Rust")])
        for banned in ("search", "engine", "resume", "computer"):
            self.assertNotIn(banned, out["proj_search_engine"])

    def test_component_with_nothing_distinctive_is_omitted(self):
        # An empty rule is indistinguishable from one that never matched,
        # which is the silence R17 set out to remove.
        comps = [_FakeComponent("p1", tech="Python"), _FakeComponent("p2", tech="Python")]
        self.assertEqual(derive_conditional_triggers(comps), {})

    def test_generic_terms_are_excluded(self):
        comps = [_FakeComponent("p1", tech="Backend, Rust"), _FakeComponent("p2", tech="Go")]
        self.assertNotIn("backend", out_p1 := derive_conditional_triggers(comps)["p1"])
        self.assertIn("rust", out_p1)

    def test_empty_pool_derives_nothing(self):
        self.assertEqual(derive_conditional_triggers([]), {})

    def test_experiences_derive_from_keywords_without_a_tech_stack(self):
        comps = [
            _FakeComponent("exp_a", keywords=["Kubernetes", "Terraform"]),
            _FakeComponent("exp_b", keywords=["PyTorch"]),
        ]
        out = derive_conditional_triggers(comps)
        self.assertIn("kubernetes", out["exp_a"])
        self.assertIn("pytorch", out["exp_b"])


class TestMergeConditionalTriggers(unittest.TestCase):
    """Same contract as merge_importance: anything explicit wins."""

    def test_hand_authored_rule_survives_untouched(self):
        hand = {"p1": {"include_if_jd_contains": ["radiology"], "description": "mine"}}
        merged = merge_conditional_triggers(hand, {"p1": ["pytorch"], "p2": ["rust"]})
        self.assertEqual(merged["p1"]["include_if_jd_contains"], ["radiology"])
        self.assertEqual(merged["p1"]["description"], "mine")

    def test_components_the_profile_omits_take_the_derived_rule(self):
        merged = merge_conditional_triggers({"p1": {"include_if_jd_contains": ["x"],
                                                    "description": "mine"}},
                                            {"p1": ["pytorch"], "p2": ["rust"]})
        self.assertEqual(merged["p2"]["include_if_jd_contains"], ["rust"])

    def test_derived_rules_carry_the_schema_required_description(self):
        merged = merge_conditional_triggers(None, {"p1": ["rust"]})
        self.assertTrue(merged["p1"]["description"])

    def test_derived_rules_validate_against_the_schema(self):
        from tools.profile.profile_schema import ConditionalInclusion
        merged = merge_conditional_triggers(None, {"p1": ["rust", "go"]})
        rule = ConditionalInclusion(**merged["p1"])
        self.assertEqual(rule.include_if_jd_contains, ["rust", "go"])


if __name__ == "__main__":
    unittest.main()

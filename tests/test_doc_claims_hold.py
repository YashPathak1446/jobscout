"""
The decision log says the code does things. This checks that it does.

`known_questions.md` is this project's planning substrate — sessions read it to
decide what to work on — so an entry describing a state the code never reached
costs a whole session. That has now happened three times:

    item 13   said discovery seniority was parameterised. The gate was; the
              query still passed the literal "new grad" (R66).
    Q2        said PDF/DOCX import was "not yet built" two days after it
              shipped, and a deferred-work list repeated it (R66).
    R55       said US state abbreviations were removed from `COUNTRY_CODES`.
              The comparison was case-mismatched and removed nothing; the
              codes it named were safe only because they had also been struck
              by hand. Four survived, and "Boston, MA" read as Morocco (R68).

Three is a pattern, and the pattern has a shape: **a claim that something is
removed, guarded or wired, sitting on top of an outcome that looked right for
another reason.** Prose cannot check itself, so the load-bearing claims live
here as assertions instead.

Add to this when a decision entry claims a code state that a future reader
would otherwise have to take on trust.
"""

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def source_of(relative: str) -> str:
    """A file's text with comment-only lines dropped.

    The first version of this audit reported two false failures, because a
    comment *referencing* a removed thing looks identical to the thing.
    """
    lines = (ROOT / relative).read_text(encoding="utf-8").splitlines()
    return "\n".join(l for l in lines if not l.lstrip().startswith("#"))


class TestRemovalsActuallyRemoved(unittest.TestCase):
    """Claims that something is gone. The class that failed in R68."""

    def test_r55_no_us_state_code_is_read_as_a_country(self):
        from tools.jobs.location_matcher import (
            COUNTRY_CODES, _AMBIGUOUS_WITH_US_STATES)

        collisions = sorted(set(COUNTRY_CODES) & _AMBIGUOUS_WITH_US_STATES)
        self.assertEqual(collisions, [],
                         f"{collisions} would read US cities as foreign")

    def test_r55_the_guard_compares_like_with_like(self):
        """
        The specific defect: lower-case abbreviations against upper-case codes,
        so the filter matched nothing and looked correct.
        """
        from tools.jobs.location_matcher import _AMBIGUOUS_WITH_US_STATES

        self.assertTrue(all(a == a.upper() for a in _AMBIGUOUS_WITH_US_STATES))

    def test_r66_and_r68_dead_profile_fields_are_gone(self):
        from tools.profile.profile_schema import JobPreferences

        dead = {"graduation_eligibility", "experience_level", "comments",
                "job_recency_hours", "citizenship_restrictions"}
        self.assertEqual(dead & set(JobPreferences.model_fields), set())

    def test_r61_the_real_scrape_path_cannot_reach_the_mock(self):
        body = source_of("agents/enrichment_agent.py").split("def _real_scrape")[1]
        self.assertNotIn("mock_scrape_jd", body)

    def test_r66_no_literal_new_grad_in_a_search_query(self):
        source = source_of("agents/discovery_agent.py")
        self.assertNotIn('build_serper_query(role, "new grad"', source)
        self.assertNotIn('f"{role} new grad"', source)


class TestThingsClaimedToBeWired(unittest.TestCase):
    """Claims that something is read. The dead-field class."""

    def test_q2_pdf_and_docx_import_is_built(self):
        from tools.resume.resume_import import SUPPORTED
        self.assertTrue({".pdf", ".docx"} <= SUPPORTED)

    def test_r62_the_gate_fingerprint_covers_what_the_gate_reads(self):
        """
        A stored verdict goes stale when the profile fields the gate reads
        change. If a field is added to the gate and not the fingerprint, the
        board keeps judging under the old answer.
        """
        from tools.jobs.job_filter import gate_fingerprint

        class _P:
            class job_preferences:
                seniority = []
                years_experience = 2
                exclude_keywords = []

                class locations:
                    countries = ["United States"]

            class personal_info:
                us_citizen = True
                permanent_resident = False
                holds_security_clearance = False

        before = gate_fingerprint(_P)
        _P.job_preferences.years_experience = 9
        self.assertNotEqual(before, gate_fingerprint(_P))

    def test_r68_relocation_and_excluded_countries_are_read(self):
        source = source_of("tools/jobs/job_filter.py")
        self.assertIn("willing_to_relocate", source)
        self.assertIn("exclude_countries", source)

    def test_r67_the_job_score_is_not_embedding_alone(self):
        from tools.resume.embedding_scorer import KEYWORD_WEIGHT
        self.assertGreater(KEYWORD_WEIGHT, 0)


class TestClaimsAboutRendering(unittest.TestCase):
    def test_r69_both_escape_tables_agree(self):
        from agents.generation_agent import GenerationAgent
        from tools.resume.tex_renderer import escape

        sample = "p99 <5ms >1s ~2min 94.2% R&D snake_case"
        self.assertEqual(
            GenerationAgent._escape_latex_impl(GenerationAgent, sample),
            escape(sample))

    def test_r69_the_template_still_avoids_t1(self):
        preamble = ROOT / "data" / "templates" / "base_preamble.tex"
        active = [l for l in preamble.read_text(encoding="utf-8").splitlines()
                  if "fontenc" in l and not l.lstrip().startswith("%")]
        self.assertEqual(active, [])


class TestTheDocDoesNotContradictItself(unittest.TestCase):
    """
    Cheap structural checks on the log itself.

    Not a substitute for reading it, but they catch the two ways it has gone
    wrong mechanically: an entry marked resolved by an R-number that was never
    written, and a duplicated number.
    """

    def setUp(self):
        path = ROOT / "known_questions.md"
        if not path.exists():
            self.skipTest("no decision log")
        self.text = path.read_text(encoding="utf-8")

    def test_every_resolution_referenced_exists(self):
        headings = set(re.findall(r"^## (R\d+)\.", self.text, re.M))
        referenced = set(re.findall(r"RESOLVED \((R\d+)\)", self.text))
        missing = sorted(referenced - headings)
        self.assertEqual(missing, [],
                         f"entries point at resolutions that were never written: {missing}")

    def test_no_resolution_number_is_reused(self):
        numbers = re.findall(r"^## (R\d+)\.", self.text, re.M)
        duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
        self.assertEqual(duplicates, [])

    def test_no_open_question_claims_a_resolution(self):
        """A heading cannot be both open and resolved."""
        for heading in re.findall(r"^## (Q\d+)\.(.*)$", self.text, re.M):
            name, rest = heading
            if "RESOLVED" in rest:
                continue
            self.assertNotIn("**Status:** Resolved", rest, name)


if __name__ == "__main__":
    unittest.main()

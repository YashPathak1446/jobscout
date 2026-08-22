"""
Keyword matching — the term-vs-substring distinction (R18).

These are the cases that were silently wrong before word boundaries: a JD
saying "scalable" credited Scala, "antitrust" credited Rust, and "email" or
"training" credited AI on essentially every job description.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.resume.latex_parser import (  # noqa: E402
    TECH_KEYWORDS,
    build_tech_vocabulary,
    split_skill_list,
    term_matches,
)


class TestTermMatches(unittest.TestCase):
    """Word boundaries, with a documented escape hatch for + and #."""

    def test_rejects_substring_inside_a_longer_word(self):
        # Each of these was a real false positive in the 20-JD baseline.
        for term, text in [
            ("java", "we use javascript daily"),
            ("scala", "designing scalable systems"),
            ("rust", "the antitrust lawsuit"),
            ("bert", "gilbert family foundation"),
            ("ai", "please maintain the training docs"),
            ("rag", "storage and coverage metrics"),
            ("go", "government contracts"),
        ]:
            with self.subTest(term=term):
                self.assertFalse(term_matches(term, text))

    def test_accepts_the_term_standing_alone(self):
        for term, text in [
            ("java", "java and python"),
            ("scala", "scala and spark"),
            ("rust", "rust and go"),
            ("ai", "ai research team"),
            ("go", "go, rust, or python"),
        ]:
            with self.subTest(term=term):
                self.assertTrue(term_matches(term, text))

    def test_keeps_containments_that_should_match(self):
        # A non-word character still counts as a boundary, so these survive.
        self.assertTrue(term_matches("github", "github actions workflow"))
        self.assertTrue(term_matches("html", "html/css basics"))
        self.assertTrue(term_matches("agile", "agile/scrum process"))

    def test_plus_and_hash_terms_fall_back_to_substring(self):
        # \b cannot work after "++" — the boundary sits between two non-word
        # characters and never matches.
        self.assertTrue(term_matches("c++", "java, c++, python"))
        self.assertTrue(term_matches("c#", "c# and .net"))

    def test_dotted_names_are_matched_whole(self):
        self.assertTrue(term_matches("node.js", "node.js backend"))
        self.assertTrue(term_matches("next.js", "built with next.js"))

    def test_vocabulary_carries_the_terms_boundaries_would_otherwise_lose(self):
        # Boundaries stop 'angular' matching 'angularjs' and 'bert' matching
        # 'distilbert'. Both are real product names, so the fix was to add
        # them rather than weaken the matcher.
        self.assertIn("angularjs", TECH_KEYWORDS)
        self.assertIn("distilbert", TECH_KEYWORDS)
        self.assertTrue(term_matches("angularjs", "angularjs or vue"))
        self.assertTrue(term_matches("distilbert", "fine-tuned distilbert model"))


class TestSkillListSplitting(unittest.TestCase):
    """Parenthesised groups, which a naive comma split mangles."""

    def test_expands_a_parenthesised_group_into_head_plus_members(self):
        tokens = split_skill_list("AWS (EC2, S3, Lambda), Docker")
        for expected in ("aws", "ec2", "s3", "lambda", "docker"):
            self.assertIn(expected, tokens)

    def test_does_not_produce_fragments(self):
        # The bug this prevents: "AWS (EC2" and "Lambda)" as separate tokens.
        tokens = split_skill_list("AWS (EC2, S3), Docker")
        self.assertNotIn("aws (ec2", tokens)
        self.assertNotIn("s3)", tokens)

    def test_slash_joined_skills_contribute_their_parts(self):
        tokens = split_skill_list("C/C++, HTML/CSS")
        self.assertIn("c++", tokens)
        self.assertIn("html", tokens)
        self.assertIn("css", tokens)

    def test_two_character_slash_parts_are_not_emitted(self):
        # "ci/cd" must not contribute "ci", which would match "specific".
        tokens = split_skill_list("CI/CD, Docker")
        self.assertIn("ci/cd", tokens)
        self.assertNotIn("ci", tokens)
        self.assertNotIn("cd", tokens)

    def test_strips_latex_residue(self):
        tokens = split_skill_list("Git, Agile/Scrum}")
        self.assertIn("agile/scrum", tokens)
        self.assertNotIn("agile/scrum}", tokens)


class TestVocabularyBuild(unittest.TestCase):
    def test_union_keeps_base_terms_and_adds_user_skills(self):
        vocab = build_tech_vocabulary({"Frontend": "React, Ionic, Figma"})
        self.assertIn("backend", vocab)        # from the curated base
        self.assertIn("figma", vocab)          # from the user's skills
        self.assertIn("ionic", vocab)

    def test_handles_no_skills_section(self):
        self.assertEqual(
            sorted(build_tech_vocabulary({})),
            sorted({k.lower() for k in TECH_KEYWORDS}),
        )


if __name__ == "__main__":
    unittest.main()

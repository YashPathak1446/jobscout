"""
Skill groups laid out on one line are read as the groups they are (R103).

A PDF often puts `Languages: … | Cloud: … | Data: …` on a single extracted
line. The pattern reader took the first label and folded the other two, labels
and all, into its value, so three groups imported as one.

The split is structural and conservative: an explicit separator, and every
piece labelled. Anything short of that stays one line for a person to
correct, because the pattern reader never guesses at content.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.resume.resume_import import _heuristic_skills, heuristic_schema  # noqa: E402


class TestLabelledGroupsOnOneLine(unittest.TestCase):

    def test_pipe_separated_groups_are_three_categories(self):
        self.assertEqual(
            _heuristic_skills(["Languages: Python, Go | Cloud: AWS, GCP | Data: Kafka"]),
            {"Languages": "Python, Go", "Cloud": "AWS, GCP", "Data": "Kafka"})

    def test_bullet_and_semicolon_separators_too(self):
        for sep in (" • ", " · ", "; "):
            with self.subTest(sep=sep):
                self.assertEqual(
                    list(_heuristic_skills([f"Languages: Python{sep}Cloud: AWS"])),
                    ["Languages", "Cloud"])

    def test_one_group_per_line_is_unchanged(self):
        self.assertEqual(_heuristic_skills(["Languages: Python, Go", "Cloud: AWS"]),
                         {"Languages": "Python, Go", "Cloud": "AWS"})

    def test_through_the_whole_pattern_reader(self):
        text = ("Test Person\ntest@example.com\n\nExperience\nAcme - Engineer\n"
                "Built it\n\nSkills\nLanguages: Python | Cloud: AWS | Data: Kafka\n")
        self.assertEqual(list(heuristic_schema(text)["skills"]),
                         ["Languages", "Cloud", "Data"])


class TestTheModelPathTheSameWay(unittest.TestCase):
    """Twin path: a reply with one `Skills` group holding labelled groups."""

    def read(self, skills):
        from tools.resume import resume_import
        return resume_import.to_schema(
            "Jane\njane@example.com\n", agent=lambda prompt: {
                "experiences": [{"company": "Acme", "bullets": ["x"]}], "skills": skills})

    def test_one_group_of_labelled_groups_is_split(self):
        self.assertEqual(self.read({"Skills": "Languages: Python; Cloud: AWS"})["skills"],
                         {"Languages": "Python", "Cloud": "AWS"})

    def test_a_plain_single_group_is_kept(self):
        self.assertEqual(self.read({"Skills": "Python, Go"})["skills"],
                         {"Skills": "Python, Go"})

    def test_several_groups_are_left_as_the_model_gave_them(self):
        given = {"Languages": "Python | Cloud: AWS", "Data": "Kafka"}
        self.assertEqual(self.read(dict(given))["skills"], given)


class TestNothingIsGuessed(unittest.TestCase):

    def test_separated_values_without_labels_stay_one_list(self):
        self.assertEqual(_heuristic_skills(["Python | Go | AWS"]),
                         {"Skills": "Python | Go | AWS"})

    def test_a_partly_labelled_line_is_not_split(self):
        self.assertEqual(_heuristic_skills(["Languages: Python | Go | Cloud: AWS"]),
                         {"Languages": "Python | Go | Cloud: AWS"})

    def test_labels_with_no_separator_are_left_for_a_person(self):
        self.assertEqual(_heuristic_skills(["Languages: Python, Go Cloud: AWS"]),
                         {"Languages": "Python, Go Cloud: AWS"})


if __name__ == "__main__":
    unittest.main()

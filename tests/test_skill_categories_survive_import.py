r"""
The skills section arrives as categories and has to stay categories.

Priya's PDF says this, four labelled rows:

    Languages: Java, Kotlin, Python, Go, SQL, TypeScript
    Data: PostgreSQL, Kafka, Spark, Redis, Snowflake
    Infrastructure: AWS, Kubernetes, Terraform, Datadog, PagerDuty
    Practices: Distributed systems, on-call, contract testing, mentoring

The no-model floor read them as `{"Skills": ", ".join(lines)}` — every row
concatenated into one value. Generation then did exactly what it is supposed
to do with a category: reordered it by relevance to the posting and cut it to
one line. What came out was

    Skills: Python, Go, TypeScript, mentoring, Kotlin, Spark,
            contract testing, Languages: Java, SQL

which advertises "Languages: Java" as a skill and loses three quarters of what
she can do. Nothing downstream was wrong. The schema is
`{"Category": "comma, separated"}` and a `Label: values` line already *is*
one — the structure was in the source and the join threw it away before
anything could use it.

Third of the three defects the Priya pass left on the page, after the score
that divided her three jobs by a cap of five and the budget that gave those
jobs one bullet each.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.resume.resume_import import heuristic_schema  # noqa: E402

PRIYA = """Priya Raghunathan
Boston, MA
priya.raghunathan@example.com
(617) 555-0142
Skills
Languages: Java, Kotlin, Python, Go, SQL, TypeScript
Data: PostgreSQL, Kafka, Spark, Redis, Snowflake
Infrastructure: AWS, Kubernetes, Terraform, Datadog, PagerDuty
Practices: Distributed systems, on-call, contract testing, mentoring
"""


def skills(text):
    return heuristic_schema(text)["skills"]


class TestLabelledRowsBecomeCategories(unittest.TestCase):

    def setUp(self):
        self.skills = skills(PRIYA)

    def test_all_four_categories_survive_with_their_names(self):
        self.assertEqual(list(self.skills),
                         ["Languages", "Data", "Infrastructure", "Practices"])

    def test_the_values_are_the_values_and_not_the_labels(self):
        self.assertEqual(self.skills["Data"],
                         "PostgreSQL, Kafka, Spark, Redis, Snowflake")

    def test_no_label_ends_up_inside_a_list_of_skills(self):
        """The visible symptom: `Languages: Java` offered as one skill."""
        for values in self.skills.values():
            self.assertNotIn(":", values)

    def test_nothing_she_wrote_is_dropped(self):
        joined = " ".join(self.skills.values())
        for skill in ("Kotlin", "Snowflake", "Terraform", "on-call"):
            self.assertIn(skill, joined)


class TestTheShapesThatAreNotCategories(unittest.TestCase):

    def test_an_unlabelled_section_is_one_category_as_before(self):
        """
        A resume that lists skills without grouping them still works, and the
        category is not invented — `Skills` is the heading the section already
        had.
        """
        self.assertEqual(
            skills("Skills\nPython, Go, Kubernetes, Terraform\n"),
            {"Skills": "Python, Go, Kubernetes, Terraform"})

    def test_a_continuation_line_joins_the_category_above_it(self):
        """
        A long row wraps in the PDF and extracts as two lines. The second one
        belongs to the label above, not to a category of its own.
        """
        self.assertEqual(
            skills("Skills\nLanguages: Java, Kotlin, Python\nGo, SQL, TypeScript\n"),
            {"Languages": "Java, Kotlin, Python, Go, SQL, TypeScript"})

    def test_a_sentence_with_a_colon_does_not_become_a_category(self):
        """
        A bullet that wandered into the section under a misread heading has a
        colon in it too. The label has to be short to count as one, or the
        skills section fills up with prose.
        """
        stray = ("Built the ingestion pipeline in Python: it reads PubMed "
                 "full text and indexes it")
        self.assertEqual(skills(f"Skills\n{stray}\n"), {"Skills": stray})

    def test_a_resume_with_no_skills_section_gets_no_categories(self):
        self.assertEqual(skills("Priya Raghunathan\nBoston, MA\n"), {})


if __name__ == "__main__":
    unittest.main()

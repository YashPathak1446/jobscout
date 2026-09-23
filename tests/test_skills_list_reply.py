"""
A model's skills sent as a list are imported, not dropped (R100's regression).

R100 kept a reply section by section and dropped any section of the wrong
type. For `skills`, the prompt asks for `{"Category": "a, b"}`, and a list of
strings is the same content in the other container. Dropping it threw away
every skill such a reply held, and said nothing. One skill group, or none,
was what the author's import showed.

A list of strings becomes one `Skills` category, which the confirmation
screen shows for splitting. Any section still dropped for its shape is now
named in the import's reason, never dropped in silence.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.resume import resume_import as importer  # noqa: E402

TEXT = "Jane Doe\njane@example.com\n\nExperience\nAcme - Engineer\nBuilt it\n"
JOB = {"company": "Acme", "title": "Engineer", "bullets": ["Built it"]}


def read(reply):
    return importer.to_schema(TEXT, agent=lambda prompt: reply)


class TestSkillsAsAList(unittest.TestCase):

    def test_a_list_of_strings_becomes_one_category(self):
        schema = read({"experiences": [JOB], "skills": ["Python", "Go", " AWS "]})
        self.assertEqual(schema["skills"], {"Skills": "Python, Go, AWS"})
        self.assertEqual(schema["_extraction"]["read_by"], "model")

    def test_the_dict_shape_is_unchanged(self):
        schema = read({"experiences": [JOB], "skills": {"Languages": "Python", "Cloud": "AWS"}})
        self.assertEqual(schema["skills"], {"Languages": "Python", "Cloud": "AWS"})

    def test_a_list_of_objects_is_not_guessed_at_but_is_named(self):
        schema = read({"experiences": [JOB],
                       "skills": [{"category": "Languages", "items": ["Python"]}]})
        self.assertEqual(schema["skills"], {})
        why = schema["_extraction"]["why"]
        self.assertIn("skills", why)
        self.assertIn("not imported", why)

    def test_any_section_dropped_for_its_shape_is_named(self):
        schema = read({"experiences": [JOB], "education": "State U, 2020"})
        self.assertIn("education", schema["_extraction"]["why"])

    def test_nothing_dropped_means_nothing_said_about_it(self):
        schema = read({"contact": {"name": "J"}, "experiences": [JOB],
                       "skills": ["Python"]})
        self.assertIsNone(schema["_extraction"]["why"])


if __name__ == "__main__":
    unittest.main()

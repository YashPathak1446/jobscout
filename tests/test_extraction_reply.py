"""
A model's reply to a resume is kept for what it contains (R100).

A working key imported a six-year resume as zero experiences, zero projects
and zero skill groups. `gemini-3.5-flash` answered 503, `gemini-3.1-flash-lite`
answered 200, and `to_schema` threw the whole reply away because it had no
truthy `contact` block. Then the confirmation screen said "most likely because
no model was available to read it". A model had answered.

Three rules replace that:

* a reply is judged section by section. A missing contact block is filled by
  the pattern reader (the one section it is good at) and flagged, and the rest
  of the reply is kept;
* structure is unwrapped, content is never guessed: a one-item list, a
  single-key wrapper, capitalised section names. A section of the wrong type
  is dropped, not fatal;
* the result records who read it and why, and both UIs show that instead of
  a cause nobody checked. The log describes a reply's shape, never its words.
"""

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.resume import resume_import as importer  # noqa: E402

TEXT = """Jane Doe
jane@example.com | 555-123-4567

Experience
Acme Corp - Software Engineer
Built a REST API in Python
"""

EXPERIENCE = {"company": "Acme Corp", "title": "Software Engineer",
              "bullets": ["Built a REST API in Python"]}


def read(reply):
    return importer.to_schema(TEXT, agent=lambda prompt: reply)


class TestAReplyIsKeptForWhatItHolds(unittest.TestCase):

    def test_no_contact_block_keeps_the_experiences(self):
        """The run that found this: everything but contact, thrown away."""
        schema = read({"experiences": [EXPERIENCE], "skills": {"Languages": "Python"}})

        self.assertEqual(len(schema["experiences"]), 1)
        self.assertEqual(schema["skills"], {"Languages": "Python"})
        self.assertEqual(schema["contact"]["email"], "jane@example.com",
                         "the missing contact block is read by pattern")
        self.assertEqual(schema["_extraction"]["read_by"], "model")
        self.assertIn("no contact details", schema["_extraction"]["why"])

    def test_an_empty_contact_block_is_treated_as_missing(self):
        schema = read({"contact": {"name": ""}, "experiences": [EXPERIENCE]})
        self.assertEqual(schema["contact"]["email"], "jane@example.com")
        self.assertEqual(len(schema["experiences"]), 1)

    def test_a_complete_reply_needs_no_note(self):
        schema = read({"contact": {"name": "Model Said"}, "experiences": [EXPERIENCE]})
        self.assertEqual(schema["contact"]["name"], "Model Said")
        self.assertEqual(schema["_extraction"], {"read_by": "model", "why": None})


class TestStructureIsUnwrappedContentIsNot(unittest.TestCase):

    def test_a_one_item_list(self):
        self.assertEqual(len(read([{"experiences": [EXPERIENCE]}])["experiences"]), 1)

    def test_a_single_key_wrapper(self):
        schema = read({"resume": {"contact": {"name": "M"}, "experiences": [EXPERIENCE]}})
        self.assertEqual(len(schema["experiences"]), 1)
        self.assertEqual(schema["contact"]["name"], "M")

    def test_capitalised_section_names(self):
        self.assertEqual(len(read({"Experiences": [EXPERIENCE]})["experiences"]), 1)

    def test_a_section_of_the_wrong_type_is_dropped_not_fatal(self):
        schema = read({"contact": "Jane Doe, jane@example.com",
                       "experiences": [EXPERIENCE]})
        self.assertEqual(len(schema["experiences"]), 1)
        self.assertEqual(schema["_extraction"]["read_by"], "model")
        self.assertNotIn("could not be reached", schema["_extraction"]["why"] or "")

    def test_a_reply_with_no_section_falls_to_the_pattern_reader_and_says_so(self):
        schema = read({"summary": "A strong engineer."})
        self.assertEqual(schema["_extraction"]["read_by"], "pattern")
        why = schema["_extraction"]["why"]
        self.assertIn("A model answered", why)
        self.assertIn("summary: str", why, "the shape is named")
        self.assertNotIn("strong engineer", why, "the content is not")


class TestTheCauseIsRecordedNotGuessed(unittest.TestCase):

    def test_no_model_says_no_model(self):
        why = read(None)["_extraction"]["why"]
        self.assertIn("No model is configured", why)

    def test_a_failed_call_says_it_failed(self):
        def broken(prompt):
            raise RuntimeError("503 UNAVAILABLE")
        schema = importer.to_schema(TEXT, agent=broken)
        self.assertEqual(schema["_extraction"]["read_by"], "pattern")
        self.assertIn("could not be reached", schema["_extraction"]["why"])
        self.assertIn("503", schema["_extraction"]["why"])

    def test_the_shape_never_carries_a_value(self):
        shape = importer._shape({"contact": {"name": "Jane Doe"},
                                 "experiences": [EXPERIENCE], "note": "hello"})
        self.assertEqual(shape, "{contact: dict[1], experiences: list[1], note: str}")
        self.assertNotIn("Jane", shape)

    def test_neither_ui_guesses_a_cause_any_more(self):
        """Walked as string constants, so a comment explaining the change is not a hit."""
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        strings = " ".join(n.value for n in ast.walk(tree)
                           if isinstance(n, ast.Constant) and isinstance(n.value, str))
        self.assertNotIn("most likely because no model", strings)

        tsx = (ROOT / "web/src/components/ImportConfirm.tsx").read_text(encoding="utf-8")
        rendered = "\n".join(line for line in tsx.splitlines()
                             if not line.strip().startswith("//"))
        self.assertNotIn("Most likely because no model", rendered)
        self.assertIn("_extraction", tsx)


if __name__ == "__main__":
    unittest.main()

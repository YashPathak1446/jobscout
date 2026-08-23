"""
Reading PDF and DOCX resumes into the schema (R39).

Requiring a LaTeX master resume excluded almost everyone. This covers the
parts of import that do not need a model: text extraction, the heuristic
floor, and the normalisation every caller relies on.

The model path is exercised by hand against a real PDF — see R39 — because
mocking a model here would only test the mock.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.resume import resume_import as importer  # noqa: E402

RESUME_TEXT = """Jane Doe
jane@example.com | 555-123-4567
https://github.com/janedoe | https://www.linkedin.com/in/janedoe

Education
State University, B.S. Computer Science, 2021-2025

Experience
Acme Corp - Software Engineer Intern
Built a REST API in Python

Technical Skills
Python, C++, Docker
"""


class TestTextExtraction(unittest.TestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_reads_a_text_file(self):
        path = self.dir / "resume.txt"
        path.write_text(RESUME_TEXT, encoding="utf-8")
        self.assertIn("Jane Doe", importer.extract_text(path))

    def test_reads_a_tex_file_without_converting_it(self):
        path = self.dir / "resume.tex"
        path.write_text(r"\documentclass{article}", encoding="utf-8")
        self.assertIn("documentclass", importer.extract_text(path))

    def test_an_unsupported_format_says_what_is_supported(self):
        path = self.dir / "resume.pages"
        path.write_text("x", encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            importer.extract_text(path)
        self.assertIn("pdf", str(caught.exception))

    def test_a_short_document_is_not_worth_a_model_call(self):
        path = self.dir / "tiny.txt"
        path.write_text("Jane Doe", encoding="utf-8")
        self.assertFalse(importer.looks_extractable(path))

    def test_a_real_resume_is_worth_a_model_call(self):
        path = self.dir / "resume.txt"
        path.write_text(RESUME_TEXT * 3, encoding="utf-8")
        self.assertTrue(importer.looks_extractable(path))

    def test_a_missing_file_does_not_crash_the_check(self):
        self.assertFalse(importer.looks_extractable(self.dir / "nope.pdf"))


class TestTidying(unittest.TestCase):

    def test_runs_of_spaces_collapse(self):
        self.assertEqual(importer._tidy("a     b"), "a b")

    def test_ligatures_are_expanded(self):
        # PDF extraction emits these as single glyphs and they break keyword
        # matching wherever they land.
        self.assertIn("fi", importer._tidy("classiﬁed"))

    def test_excess_blank_lines_collapse(self):
        self.assertEqual(importer._tidy("a\n\n\n\n\nb"), "a\n\nb")


class TestHeuristicFloor(unittest.TestCase):
    """No model. Contact details have shapes; the rest is a rough cut."""

    def setUp(self):
        self.schema = importer.heuristic_schema(RESUME_TEXT)

    def test_finds_contact_details_by_shape(self):
        contact = self.schema["contact"]
        self.assertEqual(contact["email"], "jane@example.com")
        self.assertIn("janedoe", contact["github"])
        self.assertIn("janedoe", contact["linkedin"])
        self.assertTrue(contact["phone"])

    def test_takes_the_name_from_the_first_non_contact_line(self):
        self.assertEqual(self.schema["contact"]["name"], "Jane Doe")

    def test_finds_the_skills_section(self):
        self.assertTrue(self.schema["skills"])

    def test_keeps_what_it_could_not_split_for_the_confirmation_screen(self):
        # Better to show a user unsplit text than to silently drop it.
        self.assertIn("_unparsed", self.schema)

    def test_empty_input_does_not_raise(self):
        self.assertEqual(importer.heuristic_schema("")["contact"], {})


class TestNormalisation(unittest.TestCase):
    """Callers should never have to defend against a missing key."""

    def test_every_section_is_present_even_when_absent_upstream(self):
        out = importer._normalise({})
        for key in ("contact", "education", "experiences", "projects", "skills"):
            self.assertIn(key, out)

    def test_empty_bullets_are_dropped(self):
        out = importer._normalise(
            {"experiences": [{"company": "A", "bullets": ["x", "", None]}]})
        self.assertEqual(out["experiences"][0]["bullets"], ["x"])

    def test_missing_bullets_become_an_empty_list(self):
        out = importer._normalise({"projects": [{"name": "P"}]})
        self.assertEqual(out["projects"][0]["bullets"], [])


class TestSchemaFallback(unittest.TestCase):

    def test_no_model_falls_through_to_heuristics(self):
        schema = importer.to_schema(RESUME_TEXT, agent=None)
        self.assertEqual(schema["contact"]["email"], "jane@example.com")

    def test_a_model_returning_nothing_falls_through(self):
        schema = importer.to_schema(RESUME_TEXT, agent=lambda prompt: None)
        self.assertEqual(schema["contact"]["email"], "jane@example.com")

    def test_a_model_that_raises_falls_through(self):
        def broken(prompt):
            raise RuntimeError("quota")

        schema = importer.to_schema(RESUME_TEXT, agent=broken)
        self.assertEqual(schema["contact"]["email"], "jane@example.com")

    def test_a_good_model_answer_is_used(self):
        answer = {"contact": {"name": "Model Said"}, "experiences": []}
        schema = importer.to_schema(RESUME_TEXT, agent=lambda prompt: answer)
        self.assertEqual(schema["contact"]["name"], "Model Said")

    def test_the_prompt_forbids_inventing_content(self):
        """The one instruction that matters most on someone's resume."""
        prompt = importer.EXTRACTION_PROMPT.lower()
        self.assertIn("do not invent", prompt)
        self.assertIn("verbatim", prompt)


if __name__ == "__main__":
    unittest.main()

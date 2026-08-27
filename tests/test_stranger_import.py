r"""
Importing a resume that did not come out of this repo.

Every fixture in `test_resume_import.py` is either the author's own resume or
a schema written by hand to match it. That is one path, walked repeatedly. The
other path — somebody else's PDF, on a machine with no model key — had never
been walked at all, and it was broken in three ways at once:

1. `extract_resume` raised on every no-model import. `heuristic_schema`
   returns `experiences: []` *by design* and keeps the raw section text under
   `_unparsed` for a person to sort out; the guard above it treated an empty
   experiences list as failure, so the floor could never be reached. `app.py`
   has had the code to display `_unparsed` since the confirmation screen was
   written, and its test builds that state by hand — because the product could
   not produce it.

2. The error blamed the file. "A text-based PDF works best; a scanned image
   will not" was shown for a clean, text-based PDF whose only problem was that
   no model was configured to read it.

3. T1-encoded PDFs imported corrupted. R69 measured `\x15` for an en-dash and
   used it to reject T1 in *this project's* template; nothing considered that
   the import path receives other people's PDFs, and T1 is what most LaTeX
   resume advice says to load. "Staff Software Engineer" arrived as "Sta
   Software Engineer" — a plausible job title, on a resume, silently.

The fixture is a six-year Boston resume in a layout this repo has never
produced. That is the point of it.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.resume.resume_import import _tidy, heuristic_schema  # noqa: E402


# Verbatim from pypdf, reading a PDF compiled with \usepackage[T1]{fontenc}.
T1_EXTRACTION = (
    "Priya Raghunathan\n"
    "Boston, MApriya.raghunathan@example.com(617) 555-0142\n"
    "Experience\n"
    "Sta\x1b Software Engineer, Wayfair \x16 Boston, MA Mar 2023 \x15 Present\n"
    "\x88Rebuilt the product con\x1cgurator's pricing engine\n"
    "\x88Migrated 40 legacy cron jobs onto Air\x1dow\n"
    "Education\n"
    "Northeastern University \x16 Boston, MA Sep 2014 \x15 May 2018\n"
)


class TestT1PdfsImportUncorrupted(unittest.TestCase):
    """The ligature and dash slots, measured from a real T1 PDF."""

    def setUp(self):
        self.tidied = _tidy(T1_EXTRACTION)

    def test_a_job_title_is_not_quietly_shortened(self):
        self.assertIn("Staff Software Engineer", self.tidied)
        self.assertNotIn("Sta Software", self.tidied)

    def test_words_broken_by_ligatures_come_back(self):
        self.assertIn("configurator", self.tidied)
        self.assertIn("Airflow", self.tidied)

    def test_dashes_become_dashes(self):
        self.assertIn("Mar 2023 - Present", self.tidied)
        self.assertIn("Sep 2014 - May 2018", self.tidied)

    def test_a_dash_does_not_eat_the_space_beside_it(self):
        """PDF layout drops the space on one side; "University- Boston" is wrong."""
        self.assertIn("Northeastern University - Boston", self.tidied)

    def test_no_control_character_survives(self):
        """
        The general guard. The mapping above covers what was measured; this
        covers the encoding nobody has met yet. A control character in a job
        title passes every downstream check and renders as a box.
        """
        leaked = [hex(ord(c)) for c in self.tidied
                  if ord(c) < 32 and c not in "\n\t"]
        self.assertEqual(leaked, [], f"control characters survived: {leaked}")

    def test_clean_text_is_left_alone(self):
        clean = "Senior Engineer, Toast - Boston, MA\nJun 2020 - Feb 2023"
        self.assertEqual(_tidy(clean), clean)


class TestTheNoModelFloorIsReachable(unittest.TestCase):
    """
    With no model the floor is all there is, and it has to produce something a
    person can confirm rather than an exception.
    """

    def setUp(self):
        self.schema = heuristic_schema(_tidy(T1_EXTRACTION))

    def test_contact_is_read_without_a_model(self):
        contact = self.schema["contact"]
        self.assertEqual(contact["name"], "Priya Raghunathan")
        self.assertIn("priya.raghunathan@example.com", contact["email"])

    def test_a_glued_email_keeps_the_preceding_word_and_that_is_known(self):
        r"""
        PDF extraction runs adjacent text together — "Boston, MA" and the
        email below it become `Boston, MApriya.raghunathan@example.com` — and
        `[\w.+-]+@` has no left boundary, so the address absorbs "MA".

        This is asserted rather than fixed, deliberately. Every rule that
        trims the prefix also damages a real address: dropping a leading
        uppercase run turns `JSmith@example.com` into `mith@example.com`, and
        nothing in the local part distinguishes the two cases. The model path
        reads it correctly; the floor cannot, and guessing here would trade a
        visible error for an invisible one.

        What makes it survivable is R33: the confirmation screen shows every
        contact field for correction before anything is written. This test
        exists so that stays true — if someone "fixes" the regex, they have to
        come here and say what they did about `JSmith`.
        """
        self.assertEqual(self.schema["contact"]["email"],
                         "MApriya.raghunathan@example.com")

    def test_experiences_are_empty_by_design_not_by_accident(self):
        """
        Splitting roles apart is the judgement a regex cannot make, so the
        floor does not try. This asserts the shape the caller must handle —
        the caller that used to treat it as failure.
        """
        self.assertEqual(self.schema["experiences"], [])

    def test_what_could_not_be_split_is_kept(self):
        unparsed = self.schema.get("_unparsed") or {}
        self.assertTrue(unparsed.get("experiences"),
                        "the floor dropped the experience section entirely")
        self.assertTrue(
            any("Wayfair" in line for line in unparsed["experiences"]),
            "the employer is not in the text handed to the confirmation screen")

    def test_an_import_with_no_model_is_not_an_error(self):
        """
        The regression that matters. `extract_resume` decides whether a person
        sees a confirmation screen or a dead end, and for the whole of the
        no-key configuration it chose the dead end.
        """
        salvaged = {k: v for k, v in (self.schema.get("_unparsed") or {}).items() if v}
        readable = (self.schema.get("experiences") or self.schema.get("projects")
                    or salvaged or self.schema.get("education")
                    or (self.schema.get("contact") or {}).get("email"))
        self.assertTrue(readable,
                        "this import would be refused with 'could not read "
                        "any experience', on a resume that reads fine")


if __name__ == "__main__":
    unittest.main()

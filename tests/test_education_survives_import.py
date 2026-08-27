"""
The degree was discarded, not missing.

Priya Raghunathan's imported resume rendered its education as

    \\resumeSubheading
      {Northeastern University - Boston, MA Sep 2014 - May 2018}{}
      {}{}

Four fields collapsed into one, and "Bachelor of Science in Computer
Engineering" appeared nowhere on the page.

This looked like the arity disagreement R70 fixed for experiences, and it is
not. Both ends agree on four: `tex_renderer._education` writes
`{school}{location}{degree}{dates}` and the parser reads exactly those back.
The collapse happened before either of them, in one line of the heuristic
floor:

    "education": [{"school": s} for s in sections.get("education", [])[:1]]

`[:1]` keeps the first line, and the degree was on the second — so it was
thrown away rather than never found. Whatever remained went into `school`
whole, and the other three keys were absent from the dict entirely.

Two fixes, and the second is the one that lasts. The floor now returns all
four fields and places what it can by shape — a date range and a "City, ST"
have forms; a school and a degree are told apart by vocabulary. And education
is on the confirmation screen, which it never was, so anything placed wrongly
can be moved by the person whose resume it is (R33).
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.resume.resume_import import _heuristic_education  # noqa: E402

CONFIRM = ROOT / "web" / "src" / "components" / "ImportConfirm.tsx"

#: The four fields both the renderer and the parser agree on.
FIELDS = {"school", "location", "degree", "dates"}


class TestTheFloorFillsAllFourFields(unittest.TestCase):

    def test_the_shape_is_always_the_agreed_one(self):
        """
        Missing keys are how the collapse reached the renderer: `.get('degree')`
        on a dict with no degree is an empty brace, and nothing complains.
        """
        for lines in (["Anywhere University"],
                      ["A", "B", "C", "D"],
                      ["MIT", "M.S. in EECS, Cambridge, MA, 2019 - 2021"]):
            entry = _heuristic_education(lines)[0]
            self.assertEqual(set(entry), FIELDS, f"for {lines}")

    def test_nothing_in_produces_nothing_out(self):
        self.assertEqual(_heuristic_education([]), [])
        self.assertEqual(_heuristic_education(None), [])

    def test_the_degree_on_a_second_line_is_not_discarded(self):
        """The exact failure: `[:1]` threw this line away."""
        entry = _heuristic_education([
            "Northeastern University - Boston, MA Sep 2014 - May 2018",
            "Bachelor of Science in Computer Engineering",
        ])[0]
        self.assertEqual(entry["degree"],
                         "Bachelor of Science in Computer Engineering")

    def test_the_priya_line_splits_into_its_parts(self):
        entry = _heuristic_education([
            "Northeastern University - Boston, MA Sep 2014 - May 2018",
            "Bachelor of Science in Computer Engineering",
        ])[0]
        self.assertEqual(entry["school"], "Northeastern University")
        self.assertEqual(entry["location"], "Boston, MA")
        self.assertEqual(entry["dates"], "Sep 2014 - May 2018")

    def test_one_field_per_line_is_left_alone(self):
        entry = _heuristic_education([
            "University of California, Irvine",
            "Irvine, CA",
            "Bachelor of Science in Computer Science",
            "Sep. 2021 - June 2025",
        ])[0]
        self.assertEqual(entry["school"], "University of California, Irvine")
        self.assertEqual(entry["location"], "Irvine, CA")
        self.assertEqual(entry["dates"], "Sep. 2021 - June 2025")
        self.assertIn("Computer Science", entry["degree"])

    def test_a_state_code_is_not_read_as_a_masters_degree(self):
        r"""
        "Boston, MA" matched a bare `m\.?a\.?` in the first draft and put the
        whole university line in the degree field. Abbreviations that collide
        with state codes are off the list.
        """
        entry = _heuristic_education(["Boston College - Boston, MA 2016 - 2020"])[0]
        self.assertEqual(entry["degree"], "")
        self.assertEqual(entry["location"], "Boston, MA")

    def test_a_school_name_is_not_eaten_by_the_location(self):
        """
        The location is anchored on the state code and grows leftwards; an
        unbounded city pattern claimed "Northeastern University - Boston, MA"
        entire and left the school empty.
        """
        entry = _heuristic_education(["Northeastern University - Boston, MA"])[0]
        self.assertEqual(entry["school"], "Northeastern University")

    def test_a_line_that_is_only_a_school_stays_a_school(self):
        entry = _heuristic_education(["Some College 2020 - Present"])[0]
        self.assertEqual(entry["school"], "Some College")
        self.assertEqual(entry["dates"], "2020 - Present")

    def test_nothing_is_ever_dropped(self):
        """
        Unplaceable text lands in `school`, where it is visible and editable,
        rather than being discarded. That is the whole difference between this
        and what it replaced.
        """
        lines = ["Strange Institute", "Somewhere odd", "2001 - 2005"]
        entry = _heuristic_education(lines)[0]
        joined = " ".join(entry.values())
        for line in lines:
            for word in line.split():
                self.assertIn(word, joined)


@unittest.skipIf(not CONFIRM.is_file(), "no confirmation screen in this checkout")
class TestEducationCanBeCorrected(unittest.TestCase):
    """
    The durable half. However well the floor splits a line, it will sometimes
    be wrong — and until now the screen showed contact, experiences and
    projects, so education was the one thing extracted and never confirmed.
    """

    def setUp(self):
        self.source = CONFIRM.read_text(encoding="utf-8")

    def test_the_screen_renders_education(self):
        self.assertIn(">Education<", self.source.replace("\n", ""))
        self.assertIn("education-${index}-${field}", self.source)

    def test_a_school_can_be_added_and_removed(self):
        self.assertIn("addEducation", self.source)
        self.assertIn("dropEducation", self.source)

    def test_the_form_offers_exactly_the_fields_the_renderer_writes(self):
        """
        A field the renderer ignores is a field someone fills in for nothing.
        """
        import re
        listed = re.search(r"\['school'([^\]]*)\]", self.source)
        self.assertIsNotNone(listed, "the education field list is gone")
        offered = {"school"} | {f.strip().strip("'")
                                for f in listed.group(1).split(",") if f.strip()}
        self.assertEqual(offered, FIELDS)


if __name__ == "__main__":
    unittest.main()

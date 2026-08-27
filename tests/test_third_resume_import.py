r"""
A third resume, shaped like neither of the two this repo was built against.

Yash's is a `.tex` he wrote. Priya's is a PDF, but one invented to test the
importer — so it could only ever contain the problems somebody thought of. The
third is a real resume from outside the project, and one run of the pattern
reader over it found four things at once.

What made it different, and what each one broke:

* **`Research/Projects` as a heading.** Section matching was `startswith`, so
  that line began with neither "project" nor anything else known and was not a
  heading at all. Thirty-six lines of projects *and* the publications below
  them were filed under Experience — the section above — and offered on the
  confirmation screen as work history.
* **`Publications` after it.** An unrecognised heading did not end the section
  above it, so two conference papers became project bullets.
* **Two degrees.** `_heuristic_education` built exactly one entry. A masters
  and a bachelors merged into a record that was **wrong rather than missing**:
  both universities concatenated into `school`, the bachelors degree filed
  under the masters' dates. A blank field is visibly blank on the confirmation
  screen; a plausible sentence is not.
* **"Masters".** `\bmaster\b` does not match it. Only "Bachelor of ..." was
  ever recognised as a degree, which is why the two-degree merge scrambled the
  way it did rather than simply splitting badly.

And one the repo made for itself: `extract_text` appends the PDF's link
targets under `LINKS FOUND IN THIS DOCUMENT:` so the **model** can recover a
URL the visible text does not carry. The pattern reader has no such
instruction. After R75 taught it that `Label: values` is a skill category, the
appendix arrived on the page as a category named `https` holding three URLs,
with the marker line glued onto the end of the real skills. An affordance
built for one path, reaching the path that could not use it.

These use inline text rather than the PDF, which is real and stays local.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.resume.resume_import import (  # noqa: E402
    _heuristic_education, _split_sections, heuristic_schema,
)

# The shape, not the person: same section order, same line breaks, no real
# contact details.
THIRD = """Alex Moreau
Education
Riverside Institute of Technology,Northfield Northfield, MN
Masters of Science in Computer Science Aug. 2025 - May 2027
Eastbourne University Bristol, United Kingdom
Bachelor of Technology in Computer Science and Engineering Aug. 2021 - May 2025
Experience
ML Intern Jan 2025 - April 2025
Halden Systems Bristol, United Kingdom
- Built an authentication pipeline with behavioural biometrics.
Research/Projects
TrailSpecies Sep 2025 - Dec 2025
- Developed a full-stack web application using Next.js and React.
Publications
Interpretable Cost Models, ICDDS 2024
Technical Skills
Languages: Python, JavaScript, C/C++, SQL (Postgres), HTML/CSS, R
Frameworks: React, Node.js, Flask, FastAPI
LINKS FOUND IN THIS DOCUMENT:
https://www.linkedin.com/in/example
https://ieeexplore.ieee.org/document/10910637
"""


def sections(text=THIRD):
    return _split_sections([l.strip() for l in text.split("\n") if l.strip()])


class TestAHeadingIsRecognisedByItsWords(unittest.TestCase):

    def test_research_projects_is_a_projects_section(self):
        self.assertIn("projects", sections())

    def test_the_projects_do_not_end_up_under_experience(self):
        joined = " ".join(sections().get("experiences", []))
        self.assertNotIn("TrailSpecies", joined)
        self.assertIn("TrailSpecies", " ".join(sections()["projects"]))

    def test_a_plural_heading_still_matches(self):
        """
        `Skills` against the term `skill`. Matching whole words instead of
        prefixes broke this and took a whole section with it.
        """
        self.assertIn("skills", sections())

    def test_a_qualified_heading_still_matches(self):
        self.assertIn("skills", sections("Technical Skills\nPython, Go\n"))
        self.assertIn("experiences",
                      sections("Professional Experience\nDid a thing\n"))


class TestALineThatMerelyContainsAHeadingWordIsNot(unittest.TestCase):
    """
    The guard on the rule above. Matching a term anywhere in a short line is
    what makes an employer into a section break.
    """

    def test_an_employer_named_technologies_is_not_a_skills_heading(self):
        found = sections(
            "Experience\nML Intern Jan 2025 - April 2025\n"
            "Halden Technologies Bristol, United Kingdom\n"
            "- Built the pipeline.\n")
        self.assertNotIn("skills", found)
        self.assertEqual(len(found["experiences"]), 3)

    def test_a_short_job_title_line_is_not_a_heading(self):
        """
        `ML Intern Jan 2025 - April 2025` is 30 characters and
        `Halden Systems Bristol, United Kingdom` is 37. Any rule of the form
        "a short line is a heading" deletes the experience section.
        """
        self.assertGreaterEqual(len(sections()["experiences"]), 3)


class TestAnUnknownHeadingEndsTheSectionAboveIt(unittest.TestCase):

    def test_publications_are_not_filed_as_projects(self):
        self.assertNotIn("ICDDS", " ".join(sections()["projects"]))

    def test_publications_are_not_filed_as_anything(self):
        for lines in sections().values():
            self.assertNotIn("ICDDS", " ".join(lines))


class TestTheLinkAppendixIsNotResumeContent(unittest.TestCase):

    def test_no_category_is_named_after_a_url_scheme(self):
        self.assertNotIn("https", heuristic_schema(THIRD)["skills"])

    def test_the_marker_does_not_end_up_in_a_skills_list(self):
        for values in heuristic_schema(THIRD)["skills"].values():
            self.assertNotIn("LINKS FOUND", values)

    def test_the_real_categories_survive_intact(self):
        skills = heuristic_schema(THIRD)["skills"]
        self.assertEqual(list(skills), ["Languages", "Frameworks"])
        self.assertEqual(skills["Frameworks"], "React, Node.js, Flask, FastAPI")


class TestTwoDegreesAreTwoEntries(unittest.TestCase):

    def entries(self):
        return _heuristic_education(sections()["education"])

    def test_both_qualifications_are_kept(self):
        self.assertEqual(len(self.entries()), 2)

    def test_neither_degree_is_filed_under_the_others_dates(self):
        masters, bachelors = self.entries()
        self.assertIn("Masters", masters["degree"])
        self.assertIn("2027", masters["dates"])
        self.assertIn("Bachelor", bachelors["degree"])
        self.assertIn("2025", bachelors["dates"])

    def test_the_two_schools_do_not_merge_into_one_name(self):
        masters, bachelors = self.entries()
        self.assertNotIn("Eastbourne", masters["school"])
        self.assertIn("Riverside", masters["school"])
        self.assertIn("Eastbourne", bachelors["school"])

    def test_a_single_degree_is_still_a_single_entry(self):
        """Priya's shape, which must not become two."""
        one = _heuristic_education([
            "Northeastern University - Boston, MA Sep 2014 - May 2018",
            "Bachelor of Science in Computer Engineering",
        ])
        self.assertEqual(len(one), 1)
        self.assertEqual(one[0]["degree"],
                         "Bachelor of Science in Computer Engineering")

    def test_no_education_section_is_still_no_entries(self):
        self.assertEqual(_heuristic_education([]), [])


class TestTheDegreeWordsCoverHowPeopleWriteThem(unittest.TestCase):
    """
    `\bmaster\b` against "Masters of Science" is the whole finding: the line
    was not a degree, so it fell through to the school name and took the
    entry's structure with it.
    """

    def test_plural_qualifications_are_degrees(self):
        for degree in ("Masters of Science in Computer Science",
                       "Bachelors of Engineering",
                       "Associates in Applied Science"):
            with self.subTest(degree=degree):
                entry = _heuristic_education(["Some University", degree])[0]
                self.assertEqual(entry["degree"], degree)

    def test_a_city_and_state_is_not_read_as_a_masters(self):
        """
        Why bare "MA" and "BA" are absent from the pattern: "Boston, MA" is a
        state. Held here because adding the plurals is exactly the kind of
        edit that would reintroduce them — `m\\.a\\.?` is in the pattern and
        one careless `s?` away from matching a state code.
        """
        entry = _heuristic_education(["Northeastern University Boston, MA"])[0]
        self.assertEqual(entry["degree"], "")

    def test_a_school_name_can_still_leak_into_the_location(self):
        """
        Observed, not desired. `_CITY_STATE` anchors on the state code and
        grows leftwards through up to three capitalised words, so a school
        line with no separator gives up its name to the location field:

            Northeastern University Boston, MA  ->  the whole line

        Priya's resume writes " - " between them and is unaffected, which is
        why this has never been seen. Recorded rather than fixed because
        every tighter rule also splits a legitimate multi-word city, and the
        confirmation screen shows the field for correction (R33).
        """
        entry = _heuristic_education(["Northeastern University Boston, MA"])[0]
        self.assertEqual(entry["location"], "Northeastern University Boston, MA")
        entry = _heuristic_education(["Northeastern University - Boston, MA"])[0]
        self.assertEqual(entry["location"], "Boston, MA")


if __name__ == "__main__":
    unittest.main()

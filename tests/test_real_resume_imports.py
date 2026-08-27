r"""
Two real resumes, from outside this project, held as permanent fixtures.

Yash's is a `.tex` he wrote. Priya's is a PDF invented to test the importer —
and **a fixture you write is a fixture that agrees with you**: it can only
contain the problems somebody already thought of. These two were written by
other people for their own job searches, and between them they have found
eight defects that no synthetic fixture in this repo expressed.

    tests/fixtures/resume_two_degrees_non_us.txt
        A masters in progress and a bachelors, one of them in Bangalore.
        Sections named `Research/Projects` and `Publications`.
    tests/fixtures/resume_glued_runs_six_roles.txt
        Six roles, an expected graduation with no date range, coursework as
        a bullet under Education, and bold runs extracted with no spaces
        between them: `Lakeside UniversityFairview, IL`.

**They are anonymized and they are text, not PDFs.** Names, contact details,
employers, schools and links are replaced; every structural artifact is kept
byte for byte — the glue, the `•` glyphs, the en dashes, the margin wraps, the
`|` separators. What makes them valuable is the shape, and the shape is not
personal data. Storing the PDFs would have meant committing two strangers'
contact details to a public repository.

The eight, in the order they were found:

1. `Research/Projects` matched no heading, so the projects section did not
   exist and thirty-six lines were filed under Experience
2. `Publications` did not end the section above it, so conference papers
   became project bullets
3. two degrees merged into one record that was **wrong rather than missing**
4. `\bmaster\b` never matched "Masters", which is why 3 scrambled the way it did
5. the PDF link appendix — appended for the *model* to read — became a skills
   category named `https`
6. a coursework bullet under Education became the school name
7. its margin-wrapped continuation became a second school called "Learning"
8. `Lakeside UniversityFairview, IL` matched whole as a location, so the
   location field held the university and the school field held nothing
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.resume.resume_import import (  # noqa: E402
    _heuristic_education, _split_sections, heuristic_schema,
)

FIXTURES = ROOT / "tests" / "fixtures"
TWO_DEGREES = FIXTURES / "resume_two_degrees_non_us.txt"
GLUED_RUNS = FIXTURES / "resume_glued_runs_six_roles.txt"


def text(path):
    return path.read_text(encoding="utf-8")


def sections(source):
    body = source if isinstance(source, str) else text(source)
    return _split_sections([l.strip() for l in body.split("\n") if l.strip()])


class TestTheFixturesAreWhatTheyClaim(unittest.TestCase):
    """
    Guards against a fixture being tidied into uselessness. Every assertion
    below is about a defect these artifacts carry; if the artifacts stop
    carrying them, the tests pass while testing nothing.
    """

    def test_both_fixtures_exist_and_are_text(self):
        for path in (TWO_DEGREES, GLUED_RUNS):
            self.assertTrue(path.exists(), f"{path.name} is missing")
            self.assertGreater(len(text(path)), 2000)

    def test_no_real_contact_details_survive_anonymisation(self):
        """
        These came from real job searches. A committed fixture may carry the
        shape and must not carry the person.
        """
        for path in (TWO_DEGREES, GLUED_RUNS):
            body = text(path).lower()
            with self.subTest(path.name):
                self.assertNotIn("@gmail.com", body)
                self.assertNotIn("@u.northwestern", body)
                for real in ("tanishka", "pasarad", "suhaib", "aden",
                             "northwestern", "provedentia", "isteer"):
                    self.assertNotIn(real, body)

    def test_the_extraction_artifacts_are_preserved(self):
        glued = text(GLUED_RUNS)
        self.assertIn("UniversityFairview", glued)   # no space between runs
        self.assertIn("Expected: June 2027", glued)  # a date with no range
        self.assertIn("• Relevant Coursework", glued)  # a real bullet glyph

        wrapped = [l for l in glued.split("\n") if len(l) >= 90]
        self.assertTrue(wrapped, "the margin wraps are gone")

    def test_the_characters_are_unicode_and_not_damaged(self):
        """
        Recorded because R77 claimed the opposite. These arrive as correct
        code points — an en dash is U+2013, not a replacement character. What
        looked like mojibake was a console that could not print them.
        """
        body = text(TWO_DEGREES)
        self.assertIn("–", body)              # en dash
        self.assertIn("²", body)              # superscript two
        self.assertNotIn("�", body)           # the replacement character


class TestAHeadingIsRecognisedByItsWords(unittest.TestCase):

    def test_research_projects_is_a_projects_section(self):
        self.assertIn("projects", sections(TWO_DEGREES))

    def test_the_projects_do_not_end_up_under_experience(self):
        # "T railSpecies", spelled the way the PDF extracts it. The kerning
        # split is in the *project name*, which the extraction prompt asks the
        # model to repair and the pattern reader cannot — so on the free tier
        # it reaches the page. Written out here rather than tidied away,
        # because the spelling is the finding.
        found = sections(TWO_DEGREES)
        self.assertIn("T railSpecies", " ".join(found["projects"]))
        self.assertNotIn("railSpecies", " ".join(found["experiences"]))

    def test_a_plural_heading_still_matches(self):
        """`Skills` against the term `skill`. Matching whole words broke it."""
        self.assertIn("skills", sections(TWO_DEGREES))
        self.assertIn("skills", sections(GLUED_RUNS))

    def test_the_rule_holds_on_a_resume_it_has_not_seen(self):
        """
        The fourth resume was run to find out whether the heading rule
        generalised or had been fitted to the third. Four sections, none
        merged.
        """
        self.assertEqual(set(sections(GLUED_RUNS)),
                         {"education", "experiences", "projects", "skills"})

    def test_six_roles_all_land_in_experience(self):
        joined = " ".join(sections(GLUED_RUNS)["experiences"])
        for employer in ("Meridian Exchange", "SIGNAL Lab", "Ardent Capital",
                         "Cedar Home Healthcare", "GreenPlate"):
            self.assertIn(employer, joined)


class TestALineThatMerelyContainsAHeadingWordIsNot(unittest.TestCase):
    """The guard on the rule above — what makes an employer a section break."""

    def test_an_employer_named_technologies_is_not_a_skills_heading(self):
        found = sections("Experience\nML Intern Jan 2025 - April 2025\n"
                         "Halden Technologies Bristol, United Kingdom\n"
                         "- Built the pipeline.\n")
        self.assertNotIn("skills", found)
        self.assertEqual(len(found["experiences"]), 3)

    def test_a_skills_category_called_languages_is_not_a_section_break(self):
        """
        `Programming Languages:` heads a real skills row on the fourth
        resume. "language" was briefly in the list of headings that end a
        section, which would have dropped everything under it.
        """
        skills = heuristic_schema(text(GLUED_RUNS))["skills"]
        self.assertIn("Programming Languages", skills)
        self.assertEqual(len(skills), 3)

    def test_a_short_job_title_line_is_not_a_heading(self):
        """
        `AMP Intern Jun 2024 - Aug 2024` is 30 characters. Any rule of the
        form "a short line is a heading" deletes the experience section.
        """
        self.assertGreaterEqual(len(sections(GLUED_RUNS)["experiences"]), 25)


class TestAnUnknownHeadingEndsTheSectionAboveIt(unittest.TestCase):

    def test_publications_are_filed_as_nothing(self):
        for name, lines in sections(TWO_DEGREES).items():
            with self.subTest(section=name):
                self.assertNotIn("ICDDS", " ".join(lines))


class TestTheLinkAppendixIsNotResumeContent(unittest.TestCase):

    def test_no_category_is_named_after_a_url_scheme(self):
        for path in (TWO_DEGREES, GLUED_RUNS):
            self.assertNotIn("https", heuristic_schema(text(path))["skills"])

    def test_the_marker_does_not_end_up_in_a_skills_list(self):
        for values in heuristic_schema(text(GLUED_RUNS))["skills"].values():
            self.assertNotIn("LINKS FOUND", values)

    def test_the_links_are_still_read_for_contact_details(self):
        """
        Excluding the appendix from the *sections* must not stop the contact
        patterns finding a URL in it. That is the only place a PDF's link
        targets exist — the visible text says "GitHub".
        """
        contact = heuristic_schema(text(GLUED_RUNS))["contact"]
        self.assertIn("github.com/example-user", contact["github"])
        self.assertIn("linkedin.com/in/malikosei", contact["linkedin"])


class TestTwoDegreesAreTwoEntries(unittest.TestCase):

    def entries(self):
        return _heuristic_education(sections(TWO_DEGREES)["education"])

    def test_both_qualifications_are_kept(self):
        self.assertEqual(len(self.entries()), 2)

    def test_neither_degree_is_filed_under_the_others_dates(self):
        masters, bachelors = self.entries()
        self.assertIn("Masters", masters["degree"])
        self.assertIn("2027", masters["dates"])
        self.assertIn("Bachelor", bachelors["degree"])
        self.assertIn("2021", bachelors["dates"])

    def test_the_two_schools_do_not_merge_into_one_name(self):
        masters, bachelors = self.entries()
        self.assertNotIn("Deccan", masters["school"])
        self.assertIn("Riverside", masters["school"])
        self.assertIn("Deccan", bachelors["school"])

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

    def test_plural_qualifications_are_degrees(self):
        for degree in ("Masters of Science in Computer Science",
                       "Bachelors of Engineering",
                       "Associates in Applied Science"):
            with self.subTest(degree=degree):
                entry = _heuristic_education(["Some University", degree])[0]
                self.assertEqual(entry["degree"], degree)

    def test_a_state_code_is_not_a_master_of_arts(self):
        """
        Why bare `MA` and `BA` stay out of the pattern. Adding the plurals is
        exactly the edit that would put them back.
        """
        entry = _heuristic_education(["Northeastern University Boston, MA"])[0]
        self.assertEqual(entry["degree"], "")


class TestEducationHoldsFieldsAndNotContent(unittest.TestCase):
    """The fourth resume's contribution: three ways a school stopped being one."""

    def entry(self):
        return _heuristic_education(sections(GLUED_RUNS)["education"])[0]

    def test_a_coursework_bullet_is_not_the_school_name(self):
        school = self.entry()["school"]
        self.assertNotIn("Coursework", school)
        self.assertIn("Lakeside", school)

    def test_the_wrapped_half_of_that_bullet_is_not_a_second_school(self):
        """
        `...Operating Systems, Machine` / `Learning` is one line of the
        resume. Dropping only the first half left a school called "Learning".
        """
        entries = _heuristic_education(sections(GLUED_RUNS)["education"])
        self.assertEqual(len(entries), 1)
        self.assertNotIn("Learning", [e["school"] for e in entries])

    def test_a_short_bullet_does_not_swallow_the_line_after_it(self):
        """
        The guard on that rule: only a line that reached the margin wraps, so
        a second school following a short bullet must survive.
        """
        entries = _heuristic_education([
            "First University Boston, MA",
            "Bachelor of Science in Physics Sep 2014 - May 2018",
            "• Coursework: Optics",
            "Second University Austin, TX",
            "Masters of Science in Physics Sep 2018 - May 2020",
        ])
        self.assertEqual(len(entries), 2)
        self.assertIn("Second University", entries[1]["school"])

    def test_an_expected_graduation_is_a_date(self):
        entry = self.entry()
        self.assertEqual(entry["dates"], "June 2027")
        self.assertNotIn("Expected", entry["degree"])
        self.assertNotIn("2027", entry["degree"])

    def test_a_real_range_still_wins_over_a_lone_month(self):
        entry = _heuristic_education([
            "Some University", "B.S. in Physics Sep 2014 - May 2018"])[0]
        self.assertEqual(entry["dates"], "Sep 2014 - May 2018")

    def test_a_glued_run_is_not_read_as_a_location(self):
        """
        `Lakeside UniversityFairview, IL` matched the city/state pattern
        whole, so the location field held the university and the school field
        was empty. A glued candidate is two things touching, not a place —
        rejected, never repaired, because splitting on the same boundary
        splits PostgreSQL and LinkedIn too.
        """
        entry = self.entry()
        self.assertEqual(entry["location"], "")
        self.assertIn("UniversityFairview", entry["school"])

    def test_an_unglued_location_is_still_read(self):
        entry = _heuristic_education(["Lakeside University - Fairview, IL"])[0]
        self.assertEqual(entry["location"], "Fairview, IL")

    def test_without_a_separator_the_school_name_still_leaks(self):
        """
        Observed, not desired, and now seen on two of the three real resumes.
        `_CITY_STATE` anchors on the state code and grows leftwards through up
        to three capitalised words, so with no separator the school gives up
        its name to the location field.

        Not fixed here, because the shortest match is not the right answer
        either: it would turn "San Francisco, CA" into "Francisco, CA" and
        "Salt Lake City, UT" into "City, UT". Telling a city from a university
        needs a place vocabulary — the same thing "Bristol, United Kingdom"
        needs, and the reason those two are one deferred piece of work rather
        than two regex tweaks.
        """
        entry = _heuristic_education(["Lakeside University Fairview, IL"])[0]
        self.assertEqual(entry["location"], "Lakeside University Fairview, IL")


if __name__ == "__main__":
    unittest.main()

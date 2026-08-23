"""
Rendering a structured resume into LaTeX (R38).

Phase 2 item 10 imports PDF and DOCX by extracting a schema and rendering it
into the known template — the model never emits markup. This covers the
rendering half, which is the half that can be tested without an API.

The strongest test here is the round trip: render a schema, parse the result
with the pipeline's own parser, and check nothing was lost. Two real bugs
surfaced that way, one of them in the parser rather than the renderer.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.resume import tex_renderer as renderer  # noqa: E402
from tools.resume.latex_parser import parse_latex_resume  # noqa: E402

SCHEMA = {
    "contact": {
        "name": "Jane Doe", "email": "jane@example.com", "phone": "555-0100",
        "github": "https://github.com/janedoe",
        "linkedin": "https://www.linkedin.com/in/janedoe",
    },
    "education": [{
        "school": "State University", "location": "Austin, TX",
        "degree": "B.S. in Computer Science", "dates": "Aug 2021 - May 2025",
    }],
    "experiences": [{
        "company": "Acme Corp", "title": "Software Engineer Intern",
        "dates": "Jun 2024 - Aug 2024", "location": "Remote",
        "bullets": ["Built a REST API in Python handling 10k requests/day",
                    "Reduced p95 latency by 40% using caching & connection pooling",
                    "Wrote tests covering 90% of the payment module"],
    }, {
        "company": "Beta Labs", "title": "Research Assistant",
        "dates": "2023", "location": "Austin, TX",
        "bullets": ["Analysed ~500 samples with C++ tooling",
                    "Published results in a lab report"],
    }],
    "projects": [{
        "name": "Trip Planner", "tech": "React, Node.js, PostgreSQL",
        "dates": "2024",
        "bullets": ["Built a full-stack planner with 100% test coverage",
                    "Deployed on AWS with CI/CD"],
    }],
    "skills": {"Languages": "Python, C++, JavaScript", "Tools": "Docker, Git, AWS"},
}


class TestRoundTrip(unittest.TestCase):
    """Render, then parse with the pipeline's own parser."""

    @classmethod
    def setUpClass(cls):
        path = Path(tempfile.mkdtemp()) / "imported.tex"
        renderer.write(SCHEMA, path)
        cls.parsed = parse_latex_resume(str(path))

    def test_contact_survives(self):
        self.assertEqual(self.parsed.name, "Jane Doe")
        self.assertEqual(self.parsed.email, "jane@example.com")
        self.assertIn("janedoe", self.parsed.github_url)
        self.assertIn("janedoe", self.parsed.linkedin_url)

    def test_education_survives_without_a_coursework_line(self):
        # Most resumes have no "Relevant Coursework" bullet. The parser used
        # to require one and silently returned no education at all.
        self.assertEqual(self.parsed.education_school, "State University")
        self.assertIn("Computer Science", self.parsed.education_degree)

    def test_experience_fields_are_not_transposed(self):
        """Experience is {title}{dates}{company}{location}; education is not."""
        first = self.parsed.experiences[0]
        self.assertEqual(first.company, "Acme Corp")
        self.assertEqual(first.title, "Software Engineer Intern")

    def test_every_bullet_survives(self):
        # A consuming group in the parser used to eat every second bullet.
        self.assertEqual([len(e.bullets) for e in self.parsed.experiences], [3, 2])
        self.assertEqual(len(self.parsed.projects[0].bullets), 2)

    def test_project_tech_stack_survives(self):
        self.assertIn("React", self.parsed.projects[0].tech)
        self.assertIn("PostgreSQL", self.parsed.projects[0].tech)

    def test_skills_survive_with_their_labels(self):
        self.assertEqual(set(self.parsed.skills.categories), {"Languages", "Tools"})

    def test_special_characters_survive_a_round_trip(self):
        text = " ".join(self.parsed.experiences[0].bullets)
        self.assertIn("40%", text)
        self.assertIn("&", text)
        self.assertIn("~500", " ".join(self.parsed.experiences[1].bullets))


class TestEscaping(unittest.TestCase):

    def test_latex_metacharacters_are_escaped(self):
        out = renderer.escape("100% & $5 #1 _x {y} ^ ~")
        # Each metacharacter is present only in its escaped form.
        self.assertNotIn("100% ", out)
        self.assertEqual(out.count("%"), 1)
        self.assertIn(r"\%", out)

    def test_a_backslash_does_not_escape_the_escapes(self):
        # Replacing the backslash last would mangle every replacement made
        # before it.
        self.assertEqual(renderer.escape("a" + chr(92) + "b"),
                         "a" + chr(92) + "textbackslash{}b")

    def test_none_and_empty_are_safe(self):
        self.assertEqual(renderer.escape(None), "")
        self.assertEqual(renderer.escape(""), "")


class TestRenderShape(unittest.TestCase):

    def test_empty_sections_are_omitted_not_left_hanging(self):
        minimal = renderer.render({"contact": {"name": "A"}})
        self.assertNotIn("section{Projects}", minimal)
        self.assertIn("end{document}", minimal)

    def test_a_resume_with_no_contact_still_renders(self):
        self.assertIn("Your Name", renderer.render({}))

    def test_existing_latex_is_recognised_as_such(self):
        self.assertTrue(renderer.looks_like_latex(r"\documentclass{article}"))
        self.assertFalse(renderer.looks_like_latex("Jane Doe\nSoftware Engineer"))


if __name__ == "__main__":
    unittest.main()

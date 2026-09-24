r"""
`# _ % & $` survive every section the parser reads, and what it cannot read
it says (R112).

The defect: a skills category holding an escaped character (`C\#`,
`scikit\_learn`, `50\%`, `R\&D`) failed the parser's pattern, and **the whole
category vanished** from every tailored resume with no message. A resume
listing C# lost its Languages line. Nothing caught it because the property
tests in `test_latex_round_trip` run over the masters on disk, and none of
them has one of these characters in a skills value. A test over what exists
cannot see what does not.

The same measurement found a second one: two dollar signs in one bullet
(`$5M and $3M`) came back as `5M and3M`, because the parser un-escaped `\$`
before reading math spans and took the pair for one.

So this renders a resume **constructed** to hold each character in every
field the parser reads, parses it back, and requires every field equal. It
also compiles it where an engine exists, and checks that a line the parser
cannot read produces a warning a person sees, never a silent drop.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.resume import tex_renderer  # noqa: E402
from tools.resume.latex_parser import parse_latex_resume  # noqa: E402

CHARACTERS = ("#", "_", "%", "&", "$")


def resume_with(s: str) -> dict:
    """`s` in every field the parser reads back."""
    return {
        "contact": {"name": f"Jane {s} Doe", "phone": "555-0100",
                    "email": "jane@example.com", "github": "", "linkedin": ""},
        "education": [{"school": f"School {s}", "location": f"Town {s}",
                       "degree": f"Degree {s}", "dates": "2019 -- 2023"}],
        "experiences": [{"company": f"Co {s}", "title": f"Title {s}",
                         "dates": "Jan 2023 -- Present", "location": f"Town {s}",
                         "bullets": [f"First {s} bullet", f"Second {s} and {s} again"]}],
        "projects": [{"name": f"Proj {s}", "url": "", "tech": f"Tech {s}",
                      "dates": "2022", "bullets": [f"Project {s} bullet"]}],
        "skills": {f"Label {s}": f"One {s}, Two {s}", "Plain": "Python, Go"},
    }


def parse_text(tex: str):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "r.tex"
        path.write_text(tex, encoding="utf-8")
        return parse_latex_resume(str(path))


def fields(parsed) -> dict:
    """What the parser returned, in the shape `resume_with` wrote it."""
    e, p = parsed.experiences[0], parsed.projects[0]
    return {
        "name": parsed.name,
        "school": parsed.education_school, "town": parsed.education_location,
        "degree": parsed.education_degree,
        "company": e.company, "title": e.title, "exp town": e.location,
        "exp bullets": e.bullets,
        "project": p.name, "tech": p.tech, "project bullets": p.bullets,
        "skills": dict(parsed.skills.categories),
    }


def expected(s: str) -> dict:
    r = resume_with(s)
    e, p = r["experiences"][0], r["projects"][0]
    return {
        "name": r["contact"]["name"],
        "school": r["education"][0]["school"], "town": r["education"][0]["location"],
        "degree": r["education"][0]["degree"],
        "company": e["company"], "title": e["title"], "exp town": e["location"],
        "exp bullets": e["bullets"],
        "project": p["name"], "tech": p["tech"], "project bullets": p["bullets"],
        "skills": r["skills"],
    }


class TestEveryCharacterInEveryField(unittest.TestCase):

    def test_each_character_alone(self):
        for s in CHARACTERS:
            parsed = parse_text(tex_renderer.render(resume_with(s)))
            got, want = fields(parsed), expected(s)
            for field in want:
                with self.subTest(character=s, field=field):
                    self.assertEqual(got[field], want[field])
            with self.subTest(character=s, field="warnings"):
                self.assertEqual(parsed.warnings, [])

    def test_all_of_them_together(self):
        s = "C# node_js 50% R&D $5M"
        parsed = parse_text(tex_renderer.render(resume_with(s)))
        self.assertEqual(fields(parsed), expected(s))
        self.assertEqual(parsed.warnings, [])

    def test_two_dollars_are_not_a_math_span(self):
        """`\\$5M and \\$3M` came back as "5M and3M"."""
        from tools.resume.latex_parser import _clean_latex
        self.assertEqual(_clean_latex(r"Cut \$5M and \$3M"), "Cut $5M and $3M")
        # And a real math span still reads as before.
        self.assertEqual(_clean_latex(r"$\sim$10\% faster"), "~10% faster")

    @unittest.skipIf(shutil.which("pdflatex") is None, "needs a LaTeX engine")
    def test_the_rendered_resume_compiles(self):
        from tools.generation import pdf_builder
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.tex"
            path.write_text(tex_renderer.render(resume_with("C# node_js 50% R&D $5M")),
                            encoding="utf-8")
            result = pdf_builder.compile_pdf(str(path))
        self.assertEqual(result.status, "ok", result.log_excerpt)


class TestTheSkillsBuilderEscapes(unittest.TestCase):
    """The parser now keeps `C#`; the builder must write it back as `C\\#`."""

    def test_a_language_with_a_hash_reaches_the_page_escaped(self):
        from tests.fixture_home import fixture_home, generation_agent_for

        with fixture_home("rohan_deshmukh") as home:
            master = home / "data" / "master_resumes" / "rohan_deshmukh.tex"
            source = master.read_text(encoding="utf-8")
            self.assertIn("HTML/CSS, R}", source)
            source = source.replace("HTML/CSS, R}",
                                    r"HTML/CSS, R, C\#, scikit\_learn, R\&D, 50\% SIMD}")
            master.write_text(source, encoding="utf-8")
            agent, _ = generation_agent_for("rohan_deshmukh")
            section = agent._build_skills_section(source, jd_text="")
        languages = next((line for line in section.splitlines()
                          if "Languages" in line), None)
        self.assertIsNotNone(languages, "the Languages category was dropped")
        for escaped in (r"C\#", r"scikit\_learn", r"R\&D", r"50\% SIMD"):
            self.assertIn(escaped, languages)


# A minimal Jake's-template body around whatever a test needs to break.
BODY = r"""\documentclass{article}
\begin{document}
\section{Experience}
  \resumeSubHeadingListStart
%s
  \resumeSubHeadingListEnd
\section{Projects}
  \resumeSubHeadingListStart
%s
  \resumeSubHeadingListEnd
\section{Technical Skills}
 \begin{itemize}[leftmargin=0.15in, label={}]
    \small{\item{
%s
    }}
 \end{itemize}
%s
\end{document}
"""
GOOD_EXP = (r"\resumeSubheading{Engineer}{2023}{Acme}{Town}"
            r"\resumeItemListStart \resumeItem{Did a thing} \resumeItemListEnd")
GOOD_PROJ = (r"\resumeProjectHeading{\textbf{Tool} $|$ \emph{Go}}{2022}"
             r"\resumeItemListStart \resumeItem{Built it} \resumeItemListEnd")
GOOD_SKILLS = r"\textbf{Languages}{: Python, Go}"


class TestWhatCannotBeReadIsSaid(unittest.TestCase):

    def parse(self, exp=GOOD_EXP, proj=GOOD_PROJ, skills=GOOD_SKILLS, tail=""):
        return parse_text(BODY % (exp, proj, skills, tail))

    def test_a_clean_resume_has_no_warnings(self):
        parsed = self.parse()
        self.assertEqual(parsed.warnings, [])
        self.assertEqual(parsed.skills.categories, {"Languages": "Python, Go"})

    def test_an_unreadable_skills_category_is_reported(self):
        # Written without the braced value the template expects: the list
        # follows the label as bare text, so there is no `{...}` to read.
        parsed = self.parse(skills=GOOD_SKILLS + r" \\ \textbf{Broken}: a, b")
        self.assertEqual(parsed.skills.categories, {"Languages": "Python, Go"})
        self.assertTrue(any("Broken" in w for w in parsed.warnings), parsed.warnings)

    def test_an_unreadable_experience_heading_is_reported(self):
        parsed = self.parse(exp=GOOD_EXP + "\n" + r"\resumeSubheading{Only one}")
        self.assertEqual(len(parsed.experiences), 1)
        self.assertTrue(any(w.startswith("Experience") and "Only one" in w
                            for w in parsed.warnings), parsed.warnings)

    def test_an_unreadable_project_heading_is_reported(self):
        parsed = self.parse(proj=GOOD_PROJ + "\n" + r"\resumeProjectHeading{\textbf{Half}")
        self.assertEqual(len(parsed.projects), 1)
        self.assertTrue(any(w.startswith("Projects") for w in parsed.warnings),
                        parsed.warnings)

    def test_bullets_that_were_not_read_are_counted(self):
        exp = (r"\resumeSubheading{Engineer}{2023}{Acme}{Town}"
               r"\resumeItemListStart \resumeItem{Read} \resumeItem {Spaced} "
               r"\resumeItemListEnd")
        parsed = self.parse(exp=exp)
        self.assertTrue(any("1 of 2 bullets" in w and "Engineer" in w
                            for w in parsed.warnings), parsed.warnings)

    def test_a_section_nothing_reads_is_reported(self):
        parsed = self.parse(tail=r"\section{Publications} A paper.")
        self.assertTrue(any("Publications" in w for w in parsed.warnings),
                        parsed.warnings)


class TestSomebodyIsTold(unittest.TestCase):
    """The consumer, in the same change as the field."""

    def test_import_and_the_rules_screen_both_return_them(self):
        from tests.fixture_home import fixture_home
        from scripts import init_profile

        with fixture_home() as home:
            master = home / "data" / "master_resumes" / "resume.tex"
            master.write_text(BODY % (GOOD_EXP, GOOD_PROJ, GOOD_SKILLS,
                                      r"\section{Publications} A paper."),
                              encoding="utf-8")
            summary = init_profile.create_profile(None, master, "jane")
            rules = init_profile.read_component_rules(None, "jane")
        for returned in (summary, rules):
            self.assertTrue(any("Publications" in w
                                for w in returned["parse_warnings"]))

    def test_both_uis_render_them_at_both_places(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertEqual(app.count("_show_parse_warnings(summary.get("), 1)
        self.assertEqual(app.count("_show_parse_warnings(rules.get("), 1)
        for screen, prop in (("Wizard.tsx", "summary.parse_warnings"),
                             ("steps/TuningStep.tsx", "rules.parse_warnings")):
            source = (ROOT / "web/src/components" / screen).read_text(encoding="utf-8")
            self.assertIn(f"<ParseWarnings warnings={{{prop}}} />", source)


if __name__ == "__main__":
    unittest.main()

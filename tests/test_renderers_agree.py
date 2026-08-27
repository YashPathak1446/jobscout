"""
Two renderers write this template. They must agree about what it means.

`tools/resume/tex_renderer.py` renders an imported PDF or DOCX. `agents/
generation_agent.py` renders a tailored resume. Both emit Jake's
`\\resumeSubheading{#1}{#2}{#3}{#4}`, and the template gives no hint that
education means {school}{location}{degree}{dates} while experience means
{title}{dates}{company}{location}.

The transposition was found once, in the import renderer, and fixed there. The
generation renderer kept it for four more months: it wrote {company}{dates}
{title}{location}, which renders a perfectly plausible PDF — bold company,
italic title — and parses back with every job title filed as the employer. On
a resume with two internships that share a title, both collapsed onto one id,
so saving a tailored resume as a new master silently lost an experience.

That is the fifth time a fix has landed on one of two paths and not the other
(`rarely_include`, `scraped_successfully`, the selection breakdown, the escape
table, this). The pattern is not that the fixes are wrong; it is that the
author only ever walks one path, so nothing exercises the other. These tests
walk both and compare, which is the only thing that would have caught it.
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from agents.generation_agent import GenerationAgent  # noqa: E402
from tools.profile.profile_loader import load_profile  # noqa: E402
from tools.resume import tex_renderer as renderer  # noqa: E402
from tools.resume.latex_parser import parse_latex_resume  # noqa: E402
from tools.resume.resume_parser import ResumeParser  # noqa: E402

# Two experiences that share a job title. This is the shape that turns a
# transposition into data loss rather than a cosmetic swap: filed under the
# title, both become the same component.
#
# Listed newest first, which is the order both renderers now put them in.
# These tests are about which field lands in which slot, so the fixture is
# written in rendered order to keep the assertions positional and readable;
# `test_experiences_are_reverse_chronological` is where the ordering itself
# is held.
TWO_INTERNSHIPS = [
    {
        "id": "exp_globex", "company": "Globex",
        "title": "Software Engineer Intern",
        "dates": "Jun 2025 - Aug 2025", "location": "Austin, TX",
        "bullets": ["Cut p95 latency by 40% with caching and pooling"],
    },
    {
        "id": "exp_acme", "company": "Acme Corp",
        "title": "Software Engineer Intern",
        "dates": "Jun 2024 - Aug 2024", "location": "Remote",
        "bullets": ["Built a REST API in Python handling 10k requests/day"],
    },
]


def _master():
    masters = sorted(ROOT.glob("data/master_resumes/*.tex"))
    return masters[0] if masters else None


class TestBothRenderersMeanTheSameThing(unittest.TestCase):

    def _generated(self, experiences):
        """Render through the generation path and parse the result back."""
        master = _master()
        if master is None:
            self.skipTest("needs a master resume")

        agent = GenerationAgent.__new__(GenerationAgent)
        agent.resume_parser = ResumeParser(str(master), skip_embeddings=True)
        agent.profile = load_profile("yash_pathak", str(ROOT / "user_profiles"))

        tailored = {"experiences": experiences, "projects": []}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "generated.tex"
            agent._generate_latex_file(tailored, out, {"full_jd": ""})
            return parse_latex_resume(str(out))

    def _imported(self, experiences):
        """Render through the import path and parse the result back."""
        schema = {
            "contact": {"name": "Jane Doe", "email": "jane@example.com"},
            "education": [{"school": "State University", "location": "Austin, TX",
                           "degree": "B.S. in Computer Science",
                           "dates": "Aug 2021 - May 2025"}],
            "experiences": experiences,
            "projects": [],
            "skills": {"Languages": "Python, Go"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "imported.tex"
            out.write_text(renderer.render(schema), encoding="utf-8")
            return parse_latex_resume(str(out))

    def test_the_generation_renderer_does_not_transpose(self):
        """The bug itself: company must come back as the company."""
        parsed = self._generated(TWO_INTERNSHIPS)
        companies = [e.company for e in parsed.experiences]
        titles = [e.title for e in parsed.experiences]
        self.assertEqual(companies, ["Globex", "Acme Corp"])
        self.assertEqual(titles, ["Software Engineer Intern"] * 2)

    def test_the_import_renderer_does_not_transpose(self):
        """The path where this was already fixed, held in place."""
        parsed = self._imported(TWO_INTERNSHIPS)
        self.assertEqual([e.company for e in parsed.experiences],
                         ["Globex", "Acme Corp"])

    def test_both_renderers_round_trip_to_the_same_fields(self):
        """
        The comparison neither renderer's own tests could make. Either one
        alone looks correct against itself; only holding them side by side
        shows that they disagree.
        """
        generated = self._generated(TWO_INTERNSHIPS)
        imported = self._imported(TWO_INTERNSHIPS)
        self.assertEqual(
            [(e.company, e.title) for e in generated.experiences],
            [(e.company, e.title) for e in imported.experiences])

    def test_two_jobs_sharing_a_title_keep_distinct_ids(self):
        """
        The data loss. Ids are derived from the employer, so a transposition
        merges every job that shares a title — and a resume with two
        internships is the common case, not the corner case.
        """
        parsed = self._generated(TWO_INTERNSHIPS)
        ids = [e.id for e in parsed.experiences]
        self.assertEqual(len(set(ids)), len(ids),
                         f"two experiences collapsed onto one id: {ids}")

    def test_a_generated_resume_survives_becoming_a_master(self):
        """
        The user-facing flow: generate a tailored resume, save it as the new
        master, generate again. Nothing may be lost on the way through.
        """
        parsed = self._generated(TWO_INTERNSHIPS)
        self.assertEqual(len(parsed.experiences), len(TWO_INTERNSHIPS))
        for source, landed in zip(TWO_INTERNSHIPS, parsed.experiences):
            self.assertEqual(landed.company, source["company"])
            self.assertEqual(len(landed.bullets), len(source["bullets"]))


class TestNoThirdRendererAppearsUnnoticed(unittest.TestCase):
    """
    The structural half. Two renderers diverged because nothing knew there
    were two; a third would diverge the same way. This fails if one appears.
    """

    # Every module that encodes the argument order. There is now **one**
    # writer and one reader, which is the outcome this class was arguing for:
    # `agents/generation_agent.py` used to assemble its own sections and has
    # been merged into `tex_renderer` after the pair produced four bugs — the
    # transposition R70 fixed on one side, the escape tables that
    # desynchronised twice (R69, R73), an orphan Projects heading, and a
    # project link one builder dropped.
    #
    # If a second writer reappears here, the merge has been undone.
    KNOWN = {
        "tools/resume/tex_renderer.py",      # writes: the only builder
        "tools/resume/latex_parser.py",      # reads: what it writes
    }

    def test_every_module_writing_a_subheading_is_covered_here(self):
        """
        Asks git for the file list rather than walking the directory.

        `rglob` finds whatever happens to be under the repo, and the README
        instructs `python -m venv venv` right there — so a contributor
        following the install steps could fail this on vendored code they
        never wrote. It was found failing on a nested clone of this repo
        inside itself, and the exclusion list had grown to `tests/`, `build/`
        and `site-packages` one discovery at a time, which is the tell.

        A test that walks a directory tests whatever is in the directory.
        `git ls-files` answers the question actually being asked: which
        modules does this project ship?
        """
        import subprocess

        listed = subprocess.run(
            ["git", "ls-files", "*.py"],
            cwd=ROOT, capture_output=True, text=True, check=False)
        if listed.returncode != 0:
            self.skipTest("not a git checkout, so the file list is unknowable")
        tracked = [line for line in listed.stdout.splitlines() if line.strip()]
        self.assertTrue(tracked, "git listed no Python files at all")

        writers = set()
        for rel in tracked:
            path = ROOT / rel
            if rel.startswith("tests/") or not path.exists():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            # Comments mention the command when explaining the rule; only an
            # f-string or literal that emits it counts as a writer. Strip
            # comment bodies first, or every note about this bug looks like a
            # renderer (the false positive `test_doc_claims_hold.py` hit).
            code = re.sub(r"^\s*#.*$", "", text, flags=re.M)
            if re.search(r"\\\\resumeSubheading", code):
                writers.add(rel)

        self.assertEqual(
            writers, self.KNOWN,
            "a module writes \\resumeSubheading and is not held to the "
            "argument order:\n  new: " + str(sorted(writers - self.KNOWN)) +
            "\n  gone: " + str(sorted(self.KNOWN - writers)))


if __name__ == "__main__":
    unittest.main()

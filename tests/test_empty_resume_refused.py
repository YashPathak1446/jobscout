r"""
A resume with nothing on it is refused, loudly, before the run.

The end of the stranger pass. Priya Raghunathan's three jobs were extracted
correctly, displayed on the confirmation screen, and dropped — the only way to
keep them was to type them into fields that did not exist. Five screens and a
full pipeline later she received this, in full:

    %-----------EXPERIENCE-----------
        \section{Experience}
        \resumeSubHeadingListStart
          \resumeSubHeadingListEnd
    ...
    \end{document}

574 bytes. No `\documentclass`, no `\begin{document}`, no name, no education.
It cannot compile, which is why there was no PDF. The screen said **"Wrote 1
resume"** with four green stage ticks.

Every component behaved as designed. Import produced what a regex could.
`tex_renderer` omits empty sections — its own test asserts that. Generation
filled the two sections it owns. `_generate_latex_file` looked for
`\section{Experience}`, got `-1`, and treated it as "this master has no
header".

Two guards, because the hole needed two conditions:

* the orchestrator refuses a master with no experiences and no projects, before
  any API call, with a message naming the cause
* the generator refuses a master whose Experience heading it cannot find,
  rather than slicing on `-1`

The second is the seventh instance of a not-found sentinel read as a value,
after `years_required: None`, `location_score == 0`, "Not scored",
`int(current or 0)`, dividing by the cap, and "Finished" on an empty run.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from agents.orchestrator import JobScoutOrchestrator  # noqa: E402
from tools.resume import tex_renderer  # noqa: E402

CONTACT = {"name": "Priya Raghunathan", "email": "priya@example.com"}
EDUCATION = [{"school": "Northeastern University", "location": "Boston, MA",
              "degree": "B.S. in Computer Engineering",
              "dates": "Sep 2014 - May 2018"}]
SKILLS = {"Languages": "Java, Kotlin, Python"}
ONE_JOB = [{"title": "Staff Software Engineer", "company": "Wayfair",
            "dates": "Mar 2023 - Present", "location": "Boston, MA",
            "bullets": ["Sharded the checkout ledger across 12 shards."]}]


def render(**parts):
    schema = {"contact": CONTACT, "education": EDUCATION, "skills": SKILLS,
              "experiences": [], "projects": [], **parts}
    handle = tempfile.NamedTemporaryFile(suffix=".tex", delete=False, mode="w",
                                         encoding="utf-8")
    handle.write(tex_renderer.render(schema))
    handle.close()
    return Path(handle.name)


class TestTheRendererStillOmitsEmptySections(unittest.TestCase):
    """
    The premise. If this ever changes the guards below can relax, and whoever
    changes it should find out here rather than from a 574-byte resume.
    """

    def test_no_experiences_means_no_experience_heading(self):
        text = render().read_text(encoding="utf-8")
        self.assertNotIn("\\section{Experience}", text)

    def test_one_experience_brings_the_heading_back(self):
        text = render(experiences=ONE_JOB).read_text(encoding="utf-8")
        self.assertIn("\\section{Experience}", text)


class TestAnEmptyMasterIsRefusedBeforeTheRun(unittest.TestCase):

    def test_no_experiences_and_no_projects_raises(self):
        with self.assertRaises(ValueError) as caught:
            JobScoutOrchestrator._refuse_an_empty_resume(str(render()))
        message = str(caught.exception)
        self.assertIn("nothing to tailor", message)
        # It has to say what to do, not only what is wrong. The person who
        # hits this imported a PDF ten minutes ago.
        self.assertIn("resume step", message)

    def test_one_experience_is_enough_to_proceed(self):
        JobScoutOrchestrator._refuse_an_empty_resume(str(render(experiences=ONE_JOB)))

    def test_projects_alone_are_enough_to_proceed(self):
        projects = [{"name": "JobScout", "tech": "Python", "dates": "2026",
                     "bullets": ["Built a resume tailoring pipeline."]}]
        JobScoutOrchestrator._refuse_an_empty_resume(str(render(projects=projects)))

    def test_an_unreadable_master_is_left_to_the_parser(self):
        """
        This guard answers one question. A file it cannot parse is a different
        failure, reported properly further down, and must not be swallowed
        into "you have no experience".
        """
        broken = Path(tempfile.mkstemp(suffix=".tex")[1])
        broken.write_text("not latex at all", encoding="utf-8")
        JobScoutOrchestrator._refuse_an_empty_resume(str(broken))


class TestTheGeneratorRefusesAHeaderlessMaster(unittest.TestCase):
    """
    The second line of defence, for a hand-written master that names its
    section something the template does not expect.
    """

    def test_a_missing_experience_heading_raises_rather_than_slicing(self):
        from tools.profile import load_profile
        from tools.resume.resume_parser import ResumeParser

        master = render()          # no Experience heading at all
        profiles = sorted(ROOT.glob("user_profiles/*.json"))
        if not profiles:
            self.skipTest("needs a profile to construct the agent")

        from agents.generation_agent import GenerationAgent
        agent = GenerationAgent.__new__(GenerationAgent)
        agent.resume_parser = ResumeParser(str(master), skip_embeddings=True)
        agent.profile = load_profile("yash_pathak", str(ROOT / "user_profiles"))

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as caught:
                agent._generate_latex_file(
                    {"experiences": [], "projects": []},
                    Path(tmp) / "out.tex",
                    {"full_jd": ""})
        self.assertIn("Experience section", str(caught.exception))

    def test_the_slice_bug_is_expressible(self):
        r"""
        Why -1 was dangerous rather than merely wrong: it is a valid index.
        `text[:-1]` is not an error, it is everything but the last character —
        and the guard that followed then discarded the header entirely.
        """
        text = "abcdef"
        self.assertEqual(text[:text.find("nope")], "abcde")


if __name__ == "__main__":
    unittest.main()

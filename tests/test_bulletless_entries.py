"""
An entry with no bullets is its own entry, and never takes another's (R102).

Both entry patterns in `latex_parser` ran heading-then-list as one expression.
An entry with no bullet list (a scholarship, an award, a volunteer role)
could not match on its own:

* a bullet-less **project** listed first ran on into the next project's list,
  so "Merit Scholarship" came out carrying the paper's bullet and the paper
  vanished. That is wrong content on a resume someone sends to an employer;
* one listed last was dropped;
* a bullet-less **experience** was dropped in either position.

Each ordering is tested for each section, because the defect depended on
the order. Downstream, an entry with no source bullets gets a budget of 0,
and anything a model writes under it is removed: it had no source.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.resume import tex_renderer  # noqa: E402
from tools.resume.latex_parser import parse_latex_resume  # noqa: E402

PAPER = {"name": "Paper: Fast Indexing", "tech": "", "dates": "2019",
         "bullets": ["Published at a workshop on indexing structures"]}
SCHOLARSHIP = {"name": "Merit Scholarship", "tech": "", "dates": "2017", "bullets": []}
TOOL = {"name": "Log Shipper", "tech": "Go", "dates": "2021",
        "bullets": ["Shipped logs at scale", "Cut costs by a third"]}
JOB = {"company": "Acme", "title": "Engineer", "location": "Boston", "dates": "2020",
       "bullets": ["Built the billing service", "Ran the on-call rotation"]}
# `tex_renderer` writes experiences newest first, so a position on the page
# is set by the dates. Each ordering below is real on the rendered page.
def volunteer(dates):
    return {"company": "Code Club", "title": "Mentor", "location": "Boston",
            "dates": dates, "bullets": []}
LATER_JOB = {"company": "Beta", "title": "Senior Engineer", "location": "NYC",
             "dates": "2023", "bullets": ["Led the platform migration"]}


def parse(experiences=(), projects=()):
    schema = {"contact": {"name": "Test Person"},
              "experiences": list(experiences) or [JOB],
              "projects": list(projects),
              "skills": {"Languages": "Python"}}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "master.tex"
        tex_renderer.write(schema, path)
        return parse_latex_resume(str(path))


def projects_of(resume):
    return [(p.name, p.bullets) for p in resume.projects]


def jobs_of(resume):
    return [(e.company, e.bullets) for e in resume.experiences]


class TestProjects(unittest.TestCase):

    def test_bulletless_first_does_not_take_the_next_ones_bullets(self):
        """The misattribution: the case this entry exists for."""
        self.assertEqual(projects_of(parse(projects=[SCHOLARSHIP, PAPER])), [
            ("Merit Scholarship", []),
            ("Paper: Fast Indexing", PAPER["bullets"]),
        ])

    def test_bulletless_last_is_kept(self):
        self.assertEqual(projects_of(parse(projects=[PAPER, SCHOLARSHIP])), [
            ("Paper: Fast Indexing", PAPER["bullets"]),
            ("Merit Scholarship", []),
        ])

    def test_bulletless_in_the_middle(self):
        self.assertEqual(projects_of(parse(projects=[TOOL, SCHOLARSHIP, PAPER])), [
            ("Log Shipper", TOOL["bullets"]),
            ("Merit Scholarship", []),
            ("Paper: Fast Indexing", PAPER["bullets"]),
        ])

    def test_no_bullet_is_ever_credited_to_the_wrong_project(self):
        for order in ([SCHOLARSHIP, PAPER, TOOL], [TOOL, PAPER, SCHOLARSHIP],
                      [PAPER, SCHOLARSHIP, TOOL]):
            with self.subTest(order=[p["name"] for p in order]):
                parsed = dict(projects_of(parse(projects=order)))
                for source in order:
                    self.assertEqual(parsed[source["name"]], source["bullets"])


class TestExperiences(unittest.TestCase):

    def test_bulletless_first_is_kept_and_takes_nothing(self):
        self.assertEqual(jobs_of(parse(experiences=[volunteer("2024"), JOB])), [
            ("Code Club", []), ("Acme", JOB["bullets"])])

    def test_bulletless_last_is_kept(self):
        self.assertEqual(jobs_of(parse(experiences=[JOB, volunteer("2016")])), [
            ("Acme", JOB["bullets"]), ("Code Club", [])])

    def test_bulletless_between_two_jobs(self):
        self.assertEqual(
            jobs_of(parse(experiences=[LATER_JOB, volunteer("2021"), JOB])), [
                ("Beta", LATER_JOB["bullets"]), ("Code Club", []),
                ("Acme", JOB["bullets"])])


class TestTheMastersThatExistParseAsBefore(unittest.TestCase):
    """The committed masters, pinned to what they parsed to before R102."""

    def test_priya(self):
        r = parse_latex_resume(str(ROOT / "data/master_resumes/priya_raghunathan.tex"))
        self.assertEqual([len(e.bullets) for e in r.experiences], [3, 3, 2])
        self.assertEqual(r.projects, [])

    def test_rohan(self):
        r = parse_latex_resume(str(ROOT / "data/master_resumes/rohan_deshmukh.tex"))
        self.assertEqual([len(e.bullets) for e in r.experiences], [3, 3, 2])
        self.assertEqual([len(p.bullets) for p in r.projects], [1, 2, 1, 1])

    def test_a_hand_written_heading_with_a_link_and_tech_still_parses(self):
        tex = r"""
\section{Projects}
  \resumeSubHeadingListStart
    \resumeProjectHeading
      {\textbf{\href{https://example.com}{\underline{Linked Tool}}} $|$ \emph{Rust, Go}}{2022}
      \resumeItemListStart
        \resumeItem{Did the linked thing}
      \resumeItemListEnd
    \resumeProjectHeading
      {\textbf{Plain Tool} $|$ \emph{Python}}{2021}
      \resumeItemListStart
        \resumeItem{Did the plain thing}
      \resumeItemListEnd
  \resumeSubHeadingListEnd
\section{Technical Skills}
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.tex"
            path.write_text(r"\section{Experience}" + "\n" + tex, encoding="utf-8")
            r = parse_latex_resume(str(path))
        self.assertEqual([(p.name, p.tech, p.bullets) for p in r.projects], [
            ("Linked Tool", "Rust, Go", ["Did the linked thing"]),
            ("Plain Tool", "Python", ["Did the plain thing"])])


class TestNothingIsWrittenUnderAnEntryWithNoSource(unittest.TestCase):

    def _agent(self, resume):
        from agents.generation_agent import GenerationAgent
        agent = GenerationAgent.__new__(GenerationAgent)
        agent.resume_parser = mock.Mock(parsed_resume=resume)
        by_id = {c.id: c for c in list(resume.experiences) + list(resume.projects)}
        agent.resume_parser.get_experience_by_id = lambda cid: (
            by_id.get(cid) if cid in {e.id for e in resume.experiences} else None)
        agent.resume_parser.get_project_by_id = lambda cid: (
            by_id.get(cid) if cid in {p.id for p in resume.projects} else None)
        return agent

    def test_an_entry_with_no_master_bullets_is_budgeted_zero(self):
        resume = parse(projects=[SCHOLARSHIP, PAPER, TOOL])
        agent = self._agent(resume)
        ids = [p.id for p in resume.projects]
        budget = agent._allocate_with_importance(
            component_ids=ids, scores={}, importance={}, total_budget=6, global_max=3)
        self.assertEqual(budget[ids[0]], 0, "a budget of 1 asks for a bullet from nothing")
        self.assertEqual(sum(budget.values()), 6,
                         "the scholarship's share goes to entries that can use it")
        # Capping the others by *their* master counts is the budget change's
        # job (Q59), not this one's.

    def test_a_model_bullet_under_it_is_removed(self):
        resume = parse(projects=[SCHOLARSHIP, PAPER])
        agent = self._agent(resume)
        scholarship, paper = resume.projects
        tailored = {"projects": [
            {"id": scholarship.id, "name": scholarship.name,
             "bullets": ["Awarded for outstanding research in distributed systems"]},
            {"id": paper.id, "name": paper.name, "bullets": ["Rewritten paper bullet"]},
        ]}
        agent._restore_factual_fields(tailored)
        self.assertEqual(tailored["projects"][0]["bullets"], [])
        self.assertEqual(tailored["projects"][1]["bullets"], ["Rewritten paper bullet"])


if __name__ == "__main__":
    unittest.main()

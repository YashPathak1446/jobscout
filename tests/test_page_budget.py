"""
The page is budgeted first, and every component is capped by its own master (R104).

The budget tables were measured on resumes with both sections full, so each
describes half a page. R74 let jobs take the page only when there were *no*
projects. With one project the jobs kept their half, so a one-line project
cost every job a bullet: 3,3,3 became 2,2,2. A sparse resume (3 jobs,
1 project, the shape most friends have) got 9 bullets of the page's 12.

Now the page is budgeted before the sections share it, and every component is
capped by the smaller of its master's bullet count and validation's
per-component maximum. A 2-bullet role is never asked for 3, since the third
would be invented, and a many-bullet role cannot fill the page on its own.

These run on parsed masters, the committed fixtures and synthetic shapes,
not on `yash_pathak`, which a clean clone does not have (A11b).
"""

import logging
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from agents.generation_agent import PAGE_BULLETS, GenerationAgent  # noqa: E402
from tools.generation.validation import (EXPERIENCE_MAX_BULLETS,  # noqa: E402
                                         PROJECT_MAX_BULLETS)
from tools.profile.profile_loader import load_profile  # noqa: E402
from tools.resume import tex_renderer  # noqa: E402
from tools.resume.resume_parser import ResumeParser  # noqa: E402


def _agent(resume_path):
    agent = GenerationAgent.__new__(GenerationAgent)
    agent.profile = load_profile("priya_raghunathan", user_id=None)
    agent.resume_parser = ResumeParser(str(resume_path), skip_embeddings=True, user_id=None)
    return agent


def fixture(name):
    return _agent(ROOT / f"data/master_resumes/{name}.tex")


def synthetic(job_bullets, project_bullets, tmp):
    """A master with jobs and projects holding the given bullet counts."""
    schema = {
        "contact": {"name": "Test Person"},
        "experiences": [{"company": f"Co{i}", "title": "Engineer", "dates": f"{2024 - i}",
                         "bullets": [f"Built system {i}.{j} with Python and Kafka"
                                     for j in range(n)]}
                        for i, n in enumerate(job_bullets)],
        "projects": [{"name": f"Project {i}", "tech": "Go", "dates": "2020",
                      "bullets": [f"Shipped feature {i}.{j} in Go" for j in range(n)]}
                     for i, n in enumerate(project_bullets)],
        "skills": {"Languages": "Python, Go"},
    }
    path = Path(tmp) / "master.tex"
    tex_renderer.write(schema, path)
    return _agent(path)


def budget(agent, n_jobs=None, n_projects=None):
    r = agent.resume_parser.parsed_resume
    exps = [e.id for e in r.experiences][:n_jobs]
    projs = [p.id for p in r.projects][:n_projects]
    b = agent._compute_bullet_budgets(
        {"selected_components": {"experiences": exps, "projects": projs}, "score": {}})
    return [b["experiences"][e] for e in exps], [b["projects"][p] for p in projs]


class _Quiet(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name


class TestAProjectNeverCostsAJobABullet(_Quiet):

    def test_rohans_jobs_are_the_same_with_one_project_as_with_none(self):
        agent = fixture("rohan_deshmukh")
        with_one, _ = budget(agent, 3, 1)
        with_none, _ = budget(agent, 3, 0)
        self.assertEqual(with_one, with_none)

    def test_a_senior_with_one_project_uses_the_page(self):
        """Long masters: the page binds, not the master."""
        agent = synthetic([5, 4, 4], [2], self.tmp)
        jobs, projects = budget(agent)
        self.assertEqual(sum(jobs) + sum(projects), PAGE_BULLETS,
                         "9 of 12 was the defect; the page is there to be used")
        self.assertEqual(projects, [2])


class TestEveryComponentIsCappedByItsOwnMaster(_Quiet):

    def test_no_budget_exceeds_what_the_master_holds(self):
        for label, agent in (("priya", fixture("priya_raghunathan")),
                             ("rohan", fixture("rohan_deshmukh")),
                             ("sparse", synthetic([2, 1, 3], [1], self.tmp))):
            r = agent.resume_parser.parsed_resume
            jobs, projects = budget(agent)
            with self.subTest(resume=label):
                for count, component in zip(jobs, r.experiences):
                    self.assertLessEqual(count, len(component.bullets), component.company)
                for count, component in zip(projects, r.projects):
                    self.assertLessEqual(count, len(component.bullets), component.name)

    def test_a_many_bullet_role_cannot_fill_the_page_on_its_own(self):
        agent = synthetic([12], [], self.tmp)
        jobs, _ = budget(agent)
        self.assertEqual(jobs, [EXPERIENCE_MAX_BULLETS])

    def test_project_ceiling_holds(self):
        agent = synthetic([1], [8], self.tmp)
        _, projects = budget(agent)
        self.assertLessEqual(projects[0], PROJECT_MAX_BULLETS)


class TestAFullResumeIsBudgetedAsBefore(_Quiet):
    """Both halves full: the tables' shares, unchanged."""

    def test_three_and_three(self):
        agent = synthetic([6, 6, 6], [6, 6, 6], self.tmp)
        self.assertEqual(budget(agent), ([2, 2, 2], [2, 2, 2]))

    def test_three_and_four(self):
        agent = synthetic([6, 6, 6], [6, 6, 6, 6], self.tmp)
        jobs, projects = budget(agent)
        self.assertEqual(sum(jobs), 6)
        self.assertEqual(sum(projects), 7)
        self.assertLessEqual(max(projects), 2, "four projects keep the 2-bullet cap")


if __name__ == "__main__":
    unittest.main()

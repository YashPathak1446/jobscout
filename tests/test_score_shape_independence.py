"""
A resume is not scored on how closely its shape matches the author's.

Priya Raghunathan — Staff Software Engineer, six years, three jobs, no
projects — ran through the whole product and got nothing. Five senior backend
roles she is plainly qualified for scored **1.8%, 1.8%, 1.8%, 4.7% and 15.2%**
against a threshold of 40. The run reported "finished", the board stayed
empty, and nothing anywhere said why.

The arithmetic:

    top_exp_avg  = sum(top 5 experience scores) / max_experiences   # / 5
    top_proj_avg = sum(top 5 project scores)    / max_projects      # / 5
    overall      = top_exp_avg * .4 + top_proj_avg * .3 + skills * .3

Both averages divide by the **cap** rather than by how many components exist.
Three jobs are scored at three-fifths of what they earned; no projects makes
the entire 30% projects term a zero — not "excluded", *zero*. Her ceiling was
about 0.4 x (3/5) x similarity and she could not reach the threshold whatever
she applied to.

Two rules of this codebase meet here.

**Absence is not a value.** A section a resume does not have is unknown
evidence, not evidence of a bad match. Sixth instance, and the first one that
made the product silently return nothing.

**Two paths, one walked.** `score_job_mock` next door has divided by
`min(len(sorted), cap)` since it was written. The fix already existed on the
twin, as with the escape table (R69) and the experience field order (R70), and
production had the defect because the author's resume — five experiences,
thirteen projects — saturates both caps and is therefore the one shape for
which the old arithmetic was correct.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.resume.embedding_scorer import _section_average, _weighted  # noqa: E402

CAP_E, CAP_P = 5, 5


def components(count, base=0.5):
    return [(f"c{i}", base + i * 0.01) for i in range(count)]


def old_formula(exp, proj, skills):
    """The arithmetic that shipped, kept so the regression is expressible."""
    e = sum(s for _, s in exp[:CAP_E]) / CAP_E if exp else 0
    p = sum(s for _, s in proj[:CAP_P]) / CAP_P if proj else 0
    return e * 0.4 + p * 0.3 + skills * 0.3


def new_formula(exp, proj, skills, has_skills=True):
    e, has_e = _section_average(exp, CAP_E)
    p, has_p = _section_average(proj, CAP_P)
    return _weighted([(e, 0.4, has_e), (p, 0.3, has_p), (skills, 0.3, has_skills)])


class TestAnAbsentSectionIsNotAZero(unittest.TestCase):

    def test_no_projects_does_not_collapse_the_score(self):
        with_projects = new_formula(components(3), components(4, 0.4), 0.45)
        without = new_formula(components(3), [], 0.45)
        # Not equal — projects carry real evidence when they exist — but the
        # same order of magnitude, rather than a third of the score vanishing.
        self.assertGreater(without, with_projects * 0.8)

    def test_the_old_arithmetic_would_have_collapsed_it(self):
        """The regression, stated so it cannot come back quietly."""
        self.assertLess(old_formula(components(3), [], 0.45), 0.30)
        self.assertGreater(new_formula(components(3), [], 0.45), 0.45)

    def test_three_jobs_are_not_scored_as_three_fifths(self):
        three = new_formula(components(3), components(5, 0.4), 0.45)
        five = new_formula(components(5), components(5, 0.4), 0.45)
        self.assertAlmostEqual(three, five, delta=0.05)

    def test_a_resume_with_nothing_but_skills_still_scores(self):
        self.assertAlmostEqual(new_formula([], [], 0.45), 0.45, places=6)

    def test_a_resume_with_no_sections_at_all_scores_zero_not_nan(self):
        self.assertEqual(new_formula([], [], 0.0, has_skills=False), 0.0)


class TestTheAuthorsScoresDoNotMove(unittest.TestCase):
    """
    The fix has to be a no-op wherever both sections reach their caps, which
    is every resume the frozen baselines were measured against. Otherwise this
    is a rescoring dressed as a bug fix.
    """

    SATURATED = [(5, 13), (5, 5), (5, 6), (6, 13), (8, 20), (13, 5)]

    def test_identical_when_both_sections_reach_their_caps(self):
        for exp_count, proj_count in self.SATURATED:
            exp, proj = components(exp_count), components(proj_count, 0.4)
            self.assertAlmostEqual(
                old_formula(exp, proj, 0.45),
                new_formula(exp, proj, 0.45),
                places=12,
                msg=f"{exp_count} experiences / {proj_count} projects moved")

    def test_the_authors_own_resume_is_in_that_set(self):
        """5 experiences, 13 projects. If this stops being true, re-measure."""
        from tools.resume.resume_parser import ResumeParser
        master = ROOT / "data" / "master_resumes" / "yash_pathak.tex"
        if not master.is_file():
            self.skipTest("needs the author's master resume")
        parsed = ResumeParser(str(master), skip_embeddings=True).parsed_resume
        self.assertGreaterEqual(len(parsed.experiences), CAP_E)
        self.assertGreaterEqual(len(parsed.projects), CAP_P)


class TestBothScorersAgree(unittest.TestCase):
    """
    The mock had the right divisor and production did not, for months. They
    now share the arithmetic rather than each carrying a copy — which is the
    only thing that stops them drifting again.
    """

    def test_neither_scorer_divides_by_the_cap(self):
        source = (ROOT / "tools" / "resume" / "embedding_scorer.py").read_text(
            encoding="utf-8")
        self.assertNotIn("/ max_experiences", source)
        self.assertNotIn("/ max_projects", source)

    def test_both_scorers_use_the_shared_helpers(self):
        source = (ROOT / "tools" / "resume" / "embedding_scorer.py").read_text(
            encoding="utf-8")
        self.assertEqual(source.count("_section_average(sorted_exp"), 2)
        self.assertEqual(source.count("_section_average(sorted_proj"), 2)
        self.assertEqual(source.count("_weighted(["), 2)


if __name__ == "__main__":
    unittest.main()

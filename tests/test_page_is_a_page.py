"""
A page holds what a page holds, whoever's resume is on it.

Two constants decided how much of Priya Raghunathan's resume got written, and
both of them were the author's own file wearing a number.

**The budget tables.** `exp_budget_table` and `proj_budget_table` were
measured against resumes that have both sections — Q3's trial compiles, three
experiences and three projects, twelve bullets with two spare — so each table
describes *half* a page. Priya has no projects, so the projects half was spent
on nothing: three jobs shared six bullets and the bottom third of the page was
blank. Eighth instance of absence read as a value, after `years_required:
None`, the country parse, `location_score == 0`, "Not scored", and the scoring
cap that divided her three jobs by five.

**The verbatim scale.** The no-model rung took `count // 2` bullets because a
master bullet "occupies roughly twice the space" of a rewritten one. True of
the author's: his run 250-440 characters and render three lines each. Priya's
run 59-192 and render one. Halving spent half her page on nothing and printed
**one bullet per job**, which is not a thin resume, it is a resume that looks
like the person had nothing to say. Her whole master is eight bullets; she was
sent three of them.

The replacement is the quantity that was always meant: **a budget of N bullets
is a claim on 2N lines**, because `line_2` is the zone the prompt and the
validator both aim the model at, and every bullet of the last Gemini run
landed in it. A rung that cannot shorten a bullet keeps the claim and changes
the count.

Measured after the fact, on the real fixtures: Priya 3 bullets → 8, one page.
The author 6 → 11, one page.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from agents.generation_agent import (  # noqa: E402
    GenerationAgent, MODEL_PATH_LINES_PER_BULLET,
)
from tools.profile.profile_loader import load_profile  # noqa: E402


class Component:
    """What the budget code and the verbatim tailor read off a component."""

    def __init__(self, cid, bullets):
        self.id = cid
        self.bullets = list(bullets)
        self.title = self.name = "Software Engineer"
        self.company = "Wayfair"
        self.dates = "Mar 2023 - Present"
        self.location = "Boston, MA"
        self.tech = "Python"
        self.url = ""


class Parser:
    def __init__(self, experiences=(), projects=()):
        self._exp = {c.id: c for c in experiences}
        self._proj = {c.id: c for c in projects}
        self.derived_importance = {}

    def get_experience_by_id(self, cid):
        return self._exp.get(cid)

    def get_project_by_id(self, cid):
        return self._proj.get(cid)


# One line, two lines, three lines — measured against the same zone table
# `bullet_fit` uses, so these are the lengths the page actually renders.
ONE_LINE = "Introduced contract testing across nine services with Pact."
TWO_LINES = (
    "Led the migration of the checkout ledger from a single Postgres instance "
    "to a sharded topology, cutting p99 write latency from 340ms to 48ms "
    "across 12 shards with no customer-visible downtime.")
THREE_LINES = TWO_LINES + (" The rollout ran shard by shard behind a dual-write "
                           "window, with a read-repair job reconciling drift "
                           "and a documented rollback at every step of it.")


def agent(experiences=(), projects=()):
    made = GenerationAgent.__new__(GenerationAgent)
    made.resume_parser = Parser(experiences, projects)
    made.profile = load_profile("yash_pathak", str(ROOT / "user_profiles"))
    return made


def analysis(exp_ids=(), proj_ids=()):
    """The minimum an analysis payload has to carry to be budgeted."""
    ids = list(exp_ids) + list(proj_ids)
    return {
        "selected_components": {
            "experiences": list(exp_ids),
            "projects": list(proj_ids),
            "score_breakdown": {
                cid: {"embedding": 0.5, "keyword": 0.0, "conditional": 0.0,
                      "importance": 0.1, "always": 0.0, "final": 0.6}
                for cid in ids
            },
        },
        "score": {"experience_scores": {}, "project_scores": {}},
    }


class TestAnAbsentSectionDoesNotShrinkThePage(unittest.TestCase):

    def test_three_jobs_and_no_projects_get_more_than_half_a_page(self):
        """
        The regression, stated so it cannot come back quietly. Six bullets
        across three jobs is what the half-page table gave her.
        """
        exps = [Component(f"exp_{i}", [TWO_LINES] * 3) for i in range(3)]
        budgets = agent(exps)._compute_bullet_budgets(
            analysis([e.id for e in exps]))
        self.assertEqual(budgets["totals"]["experiences"], 9)

    def test_a_resume_with_both_sections_is_budgeted_as_before(self):
        """
        The other half of the claim: this changes the shape it was wrong for
        and leaves the shape it was measured on alone. Q3's trial compiles
        found zero headroom at 3 exp + 4 proj, so moving that number would be
        moving a resume onto a second page.
        """
        exps = [Component(f"exp_{i}", [TWO_LINES] * 3) for i in range(3)]
        projs = [Component(f"proj_{i}", [TWO_LINES] * 3) for i in range(4)]
        budgets = agent(exps, projs)._compute_bullet_budgets(
            analysis([e.id for e in exps], [p.id for p in projs]))
        self.assertEqual(budgets["totals"]["experiences"], 6)
        self.assertEqual(budgets["totals"]["projects"], 7)

    def test_projects_alone_get_the_page_too(self):
        """The symmetric case: a student with projects and no jobs yet."""
        projs = [Component(f"proj_{i}", [TWO_LINES] * 3) for i in range(3)]
        budgets = agent((), projs)._compute_bullet_budgets(
            analysis((), [p.id for p in projs]))
        self.assertEqual(budgets["totals"]["projects"], 9)


class TestTheVerbatimRungSpendsLinesNotBullets(unittest.TestCase):

    def budgeted(self, component, count):
        made = agent([component])
        fitted = made._fit_budgets_to_lines(
            {"experiences": {component.id: count}, "projects": {}})
        return fitted["experiences"][component.id]

    def test_short_bullets_are_not_halved(self):
        """
        Priya's shape. Three one-line bullets against a budget of three cost
        three lines of a six-line claim, so all three belong on the page. The
        old constant sent one.
        """
        self.assertEqual(self.budgeted(Component("exp_toast", [ONE_LINE] * 3), 3), 3)

    def test_long_bullets_still_are(self):
        """
        The author's shape, which the constant was right about. Three-line
        bullets against a six-line claim: two fit, and the third would put the
        resume on a second page.
        """
        self.assertEqual(self.budgeted(Component("exp_a", [THREE_LINES] * 3), 3), 2)

    def test_a_bullet_too_tall_is_skipped_and_not_a_full_stop(self):
        """
        101gen's five bullets measure 3, 4, 2, 1, 2 lines against a budget of
        six. Stopping at the four-line one shipped a single bullet; three of
        them fit the claim exactly.
        """
        component = Component("exp_101gen", [THREE_LINES, THREE_LINES + THREE_LINES,
                                             TWO_LINES, ONE_LINE])
        self.assertEqual(self.budgeted(component, 3), 3)

    def test_a_component_always_keeps_one_bullet(self):
        """A heading with nothing under it is worse than a line of overflow."""
        self.assertEqual(self.budgeted(Component("exp_a", [THREE_LINES * 3]), 1), 1)

    def test_the_count_and_the_page_cannot_disagree(self):
        """
        The budget is the contract between tailoring and validation, and the
        two used to be a count computed in one place and a slice taken in
        another. They are now one function called twice — this is what says
        so, because the failure it prevents is every component reported as
        short and every resume routed to needs_review.
        """
        made = agent([Component("exp_101gen", [THREE_LINES, THREE_LINES * 2,
                                               TWO_LINES, ONE_LINE])])
        budgets = {"experiences": {"exp_101gen": 3}, "projects": {}}
        expected = made._fit_budgets_to_lines(budgets)["experiences"]["exp_101gen"]

        tailored = made._verbatim_tailor(
            {"full_jd": ""}, {"experiences": ["exp_101gen"], "projects": []},
            budgets)
        self.assertEqual(len(tailored["experiences"][0]["bullets"]), expected)

    def test_the_claim_is_the_model_paths_lines(self):
        """
        Stated rather than assumed: N budgeted bullets is 2N lines. If the
        model path is ever re-aimed at a different zone, this is the number
        that has to move with it.
        """
        self.assertEqual(MODEL_PATH_LINES_PER_BULLET, 2)
        one_liners = Component("exp_a", [ONE_LINE] * 10)
        self.assertEqual(self.budgeted(one_liners, 3),
                         3 * MODEL_PATH_LINES_PER_BULLET)


if __name__ == "__main__":
    unittest.main()

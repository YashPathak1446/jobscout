"""
The skills line advertised work the page did not show (R59 / Q21).

`AI / ML & Data` holds thirteen entries in the master and about seven fit on a
line. On the run of 2026-08-25 the last slot went to `OpenAI Gym` on three
resumes — and the selection was exactly inverted:

    Scale AI    RL project NOT on the page    OpenAI Gym listed
    Experian    RL project NOT on the page    OpenAI Gym listed
    Elastic     RL project ON the page        OpenAI Gym absent

`OpenAI Gym` comes from one reinforcement-learning project. A recruiter reading
Scale AI's skills line finds nothing about RL anywhere else on the page.

Two mechanisms produced that. Everything not matching the JD filled in the
order the master happens to list it, and that order clusters
`stable-baselines3, OpenAI Gym, MineRL` ahead of `Pandas, NumPy`. Then the
character cap *skipped* rather than stopped, so `stable-baselines3` (17 chars)
missed the line and `OpenAI Gym` (10) took the slot — the tail of the line was
selected by length.

The fix orders by what backs a skill: the JD asked for it, a bullet on this
page shows it, nothing in particular owns it, or its only evidence is a
component left off this resume.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from agents.generation_agent import GenerationAgent  # noqa: E402


class _Component:
    def __init__(self, comp_id, keywords=(), tech=""):
        self.id = comp_id
        self.keywords = list(keywords)
        self.tech = tech


class _Parsed:
    def __init__(self, experiences=(), projects=()):
        self.experiences = list(experiences)
        self.projects = list(projects)


class _Parser:
    def __init__(self, parsed):
        self.parsed_resume = parsed


def agent_with(experiences=(), projects=()):
    agent = GenerationAgent.__new__(GenerationAgent)
    agent.resume_parser = _Parser(_Parsed(experiences, projects))
    return agent


# The real components, reduced to what this check reads.
MINECRAFT = _Component("proj_autonomous_minecraft_agent",
                       keywords=["openai gym", "stable-baselines3", "minerl",
                                 "pytorch", "python"],
                       tech="Python, PyTorch, stable-baselines3, OpenAI Gym, MineRL")
ANTIBIOTIC = _Component("proj_ml_based_antibiotic",
                        keywords=["xgboost", "scikit-learn", "biopython", "python"],
                        tech="Python, scikit-learn, XGBoost, TF-IDF")
JOBSCOUT = _Component("proj_jobscout", keywords=["python", "gemini"],
                      tech="Python, Google ADK, Gemini, React")

AI_SKILLS = ["PyTorch", "TensorFlow", "Hugging Face Transformers", "scikit-learn",
             "XGBoost", "stable-baselines3", "OpenAI Gym", "MineRL", "Pandas",
             "NumPy", "OpenCV", "matplotlib", "Biopython"]


def page(*ids):
    return {"experiences": [], "projects": [{"id": i} for i in ids]}


class TestTheInversion(unittest.TestCase):
    """The case Q21 was opened for, both directions."""

    def setUp(self):
        self.agent = agent_with(projects=[MINECRAFT, ANTIBIOTIC, JOBSCOUT])

    def _line(self, on_page, jd=""):
        shown, elsewhere = self.agent._skill_evidence(on_page)
        return self.agent._select_skills_for_jd(
            label="AI / ML & Data", skills=AI_SKILLS, jd_lower=jd.lower(),
            max_line_chars=100, shown=shown, elsewhere=elsewhere,
            breadth=self.agent._skill_breadth())

    def test_an_rl_library_is_not_listed_when_its_project_is_absent(self):
        line = self._line(page("proj_jobscout", "proj_ml_based_antibiotic"))
        for orphan in ("OpenAI Gym", "MineRL", "stable-baselines3"):
            self.assertNotIn(orphan, line)

    def test_the_general_libraries_take_those_slots_instead(self):
        line = self._line(page("proj_jobscout", "proj_ml_based_antibiotic"))
        self.assertIn("Pandas", line)

    def test_the_general_libraries_outrank_the_orphans(self):
        """
        Ranking rather than presence: the line is capped at 100 characters and
        the tail of any real category falls off it. What must hold is the
        order, so that what falls off is the least-supported claim.
        """
        shown, elsewhere = self.agent._skill_evidence(
            page("proj_jobscout", "proj_ml_based_antibiotic"))
        order = self.agent._select_skills_for_jd(
            label="AI / ML & Data", skills=AI_SKILLS, jd_lower="",
            max_line_chars=500, shown=shown, elsewhere=elsewhere,
            breadth=self.agent._skill_breadth())

        for general in ("Pandas", "NumPy"):
            for orphan in ("OpenAI Gym", "MineRL", "stable-baselines3"):
                self.assertLess(order.index(general), order.index(orphan),
                                f"{orphan} ranked above {general}")

    def test_the_same_library_ranks_above_them_when_its_project_is_present(self):
        """
        The other direction, and the one that proves this is evidence rather
        than a denylist: with the project on the page, the library outranks the
        general ones.
        """
        shown, elsewhere = self.agent._skill_evidence(
            page("proj_autonomous_minecraft_agent"))
        line = self.agent._select_skills_for_jd(
            label="AI", skills=["Pandas", "NumPy", "OpenAI Gym"], jd_lower="",
            max_line_chars=100, shown=shown, elsewhere=elsewhere,
            breadth=self.agent._skill_breadth())
        self.assertEqual(line[0], "OpenAI Gym")

    def test_biopython_follows_its_project_onto_and_off_the_page(self):
        with_it = self._line(page("proj_ml_based_antibiotic"))
        without = self._line(page("proj_jobscout"))
        self.assertIn("Biopython", with_it)
        self.assertNotIn("Biopython", without)


class TestTheOrdering(unittest.TestCase):
    """Four tiers, in order."""

    def setUp(self):
        self.agent = agent_with(projects=[MINECRAFT, ANTIBIOTIC, JOBSCOUT])
        self.shown, self.elsewhere = self.agent._skill_evidence(
            page("proj_ml_based_antibiotic"))

    def _order(self, skills, jd=""):
        return self.agent._select_skills_for_jd(
            label="X", skills=skills, jd_lower=jd, max_line_chars=500,
            shown=self.shown, elsewhere=self.elsewhere,
            breadth=self.agent._skill_breadth())

    def test_the_job_description_outranks_everything(self):
        order = self._order(["MineRL", "Biopython", "Pandas"], jd="minerl experience")
        self.assertEqual(order[0], "MineRL")

    def test_a_skill_on_the_page_outranks_a_general_one(self):
        order = self._order(["Pandas", "Biopython"])
        self.assertEqual(order, ["Biopython", "Pandas"])

    def test_a_general_skill_outranks_one_whose_project_is_absent(self):
        order = self._order(["MineRL", "Pandas"])
        self.assertEqual(order, ["Pandas", "MineRL"])

    def test_master_order_survives_inside_a_tier(self):
        """
        The order an author lists their own skills in is a real signal about
        what they consider central, and nothing overrides it but evidence.
        """
        self.assertEqual(self._order(["Pandas", "NumPy", "OpenCV"]),
                         ["Pandas", "NumPy", "OpenCV"])


class TestBreadthInsideTheLastTier(unittest.TestCase):
    """
    Without this the last tier is ordered by the master's listing, which
    clusters a whole stack together and hands it the final slot.

    Measured before it existed: `MineRL` displaced `NumPy` on the Databricks
    resume, trading one absent project's library for one used across four.
    """

    def test_a_widely_used_term_outranks_a_single_projects(self):
        common = _Component("proj_a", keywords=["numpy"])
        also = _Component("proj_b", keywords=["numpy"])
        niche = _Component("proj_c", keywords=["minerl"])
        agent = agent_with(projects=[common, also, niche])

        shown, elsewhere = agent._skill_evidence(page("proj_other"))
        order = agent._select_skills_for_jd(
            label="X", skills=["MineRL", "NumPy"], jd_lower="",
            max_line_chars=500, shown=shown, elsewhere=elsewhere,
            breadth=agent._skill_breadth())
        self.assertEqual(order, ["NumPy", "MineRL"])


class TestSkillTerms(unittest.TestCase):
    """A skill has to match a component that knows it by a shorter name."""

    def test_a_parenthetical_expands_to_its_parts(self):
        terms = GenerationAgent._skill_terms("SQL (MySQL, PostgreSQL)")
        self.assertIn("sql", terms)
        self.assertIn("mysql", terms)
        self.assertIn("postgresql", terms)

    def test_the_plain_form_is_kept(self):
        self.assertIn("docker", GenerationAgent._skill_terms("Docker"))

    def test_a_multi_part_cloud_entry(self):
        terms = GenerationAgent._skill_terms("AWS (EC2, S3, Lambda)")
        self.assertIn("aws", terms)
        self.assertIn("s3", terms)


class TestEvidenceSets(unittest.TestCase):
    def setUp(self):
        self.agent = agent_with(projects=[MINECRAFT, ANTIBIOTIC, JOBSCOUT])

    def test_shown_and_elsewhere_do_not_overlap(self):
        shown, elsewhere = self.agent._skill_evidence(
            page("proj_autonomous_minecraft_agent"))
        self.assertEqual(shown & elsewhere, set())

    def test_a_term_shared_by_both_counts_as_shown(self):
        """`python` is in every project; being on the page wins."""
        shown, elsewhere = self.agent._skill_evidence(page("proj_jobscout"))
        self.assertIn("python", shown)
        self.assertNotIn("python", elsewhere)

    def test_tech_strings_are_read_as_well_as_keywords(self):
        shown, _ = self.agent._skill_evidence(page("proj_jobscout"))
        self.assertIn("google adk", shown)

    def test_an_empty_page_evidences_nothing(self):
        shown, elsewhere = self.agent._skill_evidence(None)
        self.assertEqual(shown, set())
        self.assertTrue(elsewhere)


class TestNothingRegressed(unittest.TestCase):
    """The behaviours that were already right."""

    def setUp(self):
        self.agent = agent_with(projects=[MINECRAFT, ANTIBIOTIC, JOBSCOUT])

    def test_the_line_still_respects_the_character_cap(self):
        line = self.agent._select_skills_for_jd(
            label="AI / ML & Data", skills=AI_SKILLS, jd_lower="",
            max_line_chars=100, shown=set(), elsewhere=set(), breadth={})
        rendered = "AI / ML & Data: " + ", ".join(line)
        self.assertLessEqual(len(rendered), 100)

    def test_a_short_skill_still_fills_a_gap_a_long_one_could_not(self):
        """
        The skip is deliberate. Stopping at the first miss would waste the rest
        of the line; what R59 changes is that priority decides the order the
        skips happen in, not that skipping stops.
        """
        line = self.agent._select_skills_for_jd(
            label="X", skills=["A" * 40, "bb"], jd_lower="",
            max_line_chars=20, shown=set(), elsewhere=set(), breadth={})
        self.assertEqual(line, ["bb"])

    def test_no_evidence_supplied_falls_back_to_master_order(self):
        line = self.agent._select_skills_for_jd(
            label="X", skills=["Pandas", "MineRL"], jd_lower="",
            max_line_chars=500)
        self.assertEqual(line, ["Pandas", "MineRL"])

    def test_an_empty_category_stays_empty(self):
        self.assertEqual(
            self.agent._select_skills_for_jd(
                label="X", skills=[], jd_lower="", max_line_chars=100), [])


class TestAgainstTheRealRun(unittest.TestCase):
    """Skipped on a clean clone."""

    def setUp(self):
        import json

        # The frozen copy, not `outputs/` — a live output directory is
        # overwritten by the next run, and these assert facts about one
        # specific run. Verified by `scripts/baseline.py verify --all`.
        self.analysis = ROOT / "baselines" / "2026-08-25-pre-r53" / "analysis_results.json"
        master = ROOT / "data" / "master_resumes" / "yash_pathak.tex"
        if not self.analysis.exists() or not master.exists():
            self.skipTest("needs a real run and master resume")

        from tools.profile import load_profile
        from tools.resume.resume_parser import ResumeParser

        self.results = json.loads(self.analysis.read_text(encoding="utf-8"))
        self.master_text = master.read_text(encoding="utf-8")
        self.agent = GenerationAgent.__new__(GenerationAgent)
        self.agent.resume_parser = ResumeParser(str(master))
        self.agent.profile = load_profile("yash_pathak")

    def test_no_resume_advertises_a_library_whose_only_project_is_absent(self):
        orphans = ("openai gym", "minerl", "stable-baselines3")

        for result in self.results[:8]:
            selected = result["selected_components"]
            on_page = {
                "experiences": [{"id": i} for i in selected["experiences"]],
                "projects": [{"id": i} for i in selected["projects"]],
            }
            if any("minecraft" in p for p in selected["projects"]):
                continue

            section = self.agent._build_skills_section(
                self.master_text, jd_text="", on_page=on_page)
            for orphan in orphans:
                self.assertNotIn(orphan, section.lower(),
                                 f"{result['job'].get('company')} lists {orphan} "
                                 f"with no RL project on the page")


if __name__ == "__main__":
    unittest.main()

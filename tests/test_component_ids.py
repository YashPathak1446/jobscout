r"""
Two roles at one company are two components (Q34).

A component ID was `exp_{slug(company)}`, so two stints at one employer — a
promotion — produced **one ID for two components**. Seven separate consumers
key a dict by that ID (`derivation` for trigger rules, `embedding_scorer` for
vectors, `analysis_agent` for the selection breakdown, and four more), so the
second role did not raise anything; it *replaced* the first. The component
editor showed two rows with the same key, and marking one never-include marked
both.

`test_latex_round_trip` is what caught it, the moment a resume with a repeated
employer entered `data/master_resumes/` — and it had asserted the right thing
the whole time, for six weeks, against masters that happened not to have one.
The fixture found it, not the care.

The fix has a hard constraint on one side and a design choice on the other, and
both need holding down:

* **Byte-identical for anything that already exists.** Every profile's
  `conditional_inclusion` keys, `component_importance`, the recorded baselines
  and the embedding cache are keyed on the old spelling, and every one of them
  is single-occurrence. A scheme that renamed those would orphan live rules to
  fix a bug none of them has.
* **Every occurrence of a repeated base is suffixed, the first included.**
  Leaving the bare ID to whichever component the parser reached first makes the
  mapping depend on document order, so reordering a resume would move one
  role's rules onto another. That is the same silent misattribution, one step
  sideways, and it is the reason the tests below check that *no* bare ID
  survives rather than just that the two differ.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.resume.latex_parser import _assign_ids, parse_latex_resume  # noqa: E402

# The stranger fixture that found this. Two roles at Vertex Technologies.
ROHAN = ROOT / "data" / "master_resumes" / "rohan_deshmukh.tex"

# Priya's master is committed, so these three are a fixed point rather than a
# snapshot of whatever this machine happens to hold. Spelled out rather than
# recomputed: a test that compares the parser to itself would pass under any
# renaming at all, which is exactly what must not happen here.
PRIYA = ROOT / "data" / "master_resumes" / "priya_raghunathan.tex"
PRIYA_IDS = ["exp_wayfair", "exp_toast", "exp_vistaprint"]


class TestASingleOccurrenceIdNeverMoves(unittest.TestCase):
    """The constraint. Everything already on disk is keyed this way."""

    def test_one_company_keeps_the_bare_slug(self):
        self.assertEqual(
            _assign_ids("exp", ["Arcline Engineering"], ["Developer"]),
            ["exp_arcline_engineering"])

    def test_distinct_companies_are_all_bare(self):
        self.assertEqual(
            _assign_ids("exp", ["Toast", "Vistaprint"], ["SWE", "SWE"]),
            ["exp_toast", "exp_vistaprint"])

    def test_the_committed_master_parses_to_the_ids_it_is_keyed_on(self):
        """
        `user_profiles/priya_raghunathan.json` names `exp_toast` and
        `exp_vistaprint`. If this fails, those two rules stopped firing.
        """
        if not PRIYA.is_file():
            self.skipTest("needs the committed master resume")
        parsed = parse_latex_resume(str(PRIYA))
        self.assertEqual([e.id for e in parsed.experiences], PRIYA_IDS)

    def test_a_repeat_elsewhere_does_not_disturb_a_single_occurrence(self):
        """
        Disambiguation is per base, not a mode the whole pool enters.
        """
        ids = _assign_ids("exp",
                          ["Vertex", "Arcline", "Vertex"],
                          ["ML Intern", "Developer", "Analyst"])
        self.assertEqual(ids[1], "exp_arcline")


class TestEveryOccurrenceOfARepeatIsDisambiguated(unittest.TestCase):
    """The design choice, and the reason it is not `_2` on the second."""

    def test_neither_role_keeps_the_bare_company_id(self):
        ids = _assign_ids("exp", ["Vertex", "Vertex"], ["ML Intern", "Analyst"])
        self.assertNotIn("exp_vertex", ids,
                         "one of the two roles silently owns the old ID, so "
                         "which one a rule means depends on document order")

    def test_the_two_ids_differ(self):
        ids = _assign_ids("exp", ["Vertex", "Vertex"], ["ML Intern", "Analyst"])
        self.assertEqual(len(set(ids)), 2)

    def test_the_suffix_is_the_title_not_the_position(self):
        self.assertEqual(
            _assign_ids("exp", ["Vertex", "Vertex"], ["ML Intern", "Analyst"]),
            ["exp_vertex_ml_intern", "exp_vertex_analyst"])

    def test_reordering_the_resume_does_not_move_an_id(self):
        """
        What a positional suffix would fail. The pair is the same set read in
        either direction, so a rule keyed to either survives a reshuffle.
        """
        forward = _assign_ids("exp", ["Vertex", "Vertex"], ["ML Intern", "Analyst"])
        backward = _assign_ids("exp", ["Vertex", "Vertex"], ["Analyst", "ML Intern"])
        self.assertEqual(set(forward), set(backward))

    def test_the_real_fixture_produces_three_distinct_experiences(self):
        if not ROHAN.is_file():
            self.skipTest("needs the second fixture user's master resume")
        parsed = parse_latex_resume(str(ROHAN))
        ids = [e.id for e in parsed.experiences]
        self.assertEqual(len(set(ids)), 3, f"collided: {ids}")
        self.assertIn("exp_arcline_engineering", ids,
                      "the company that appears once was renamed")


class TestThePositionalFallback(unittest.TestCase):
    """
    The three ways a title suffix cannot separate two components. Each is a
    real input, not a hypothetical: `_slugify` truncates at 40 characters, a
    suffixed ID can land on a real single-occurrence ID, and two projects can
    share a name with no second field to tell them apart.
    """

    def test_titles_that_truncate_to_the_same_slug_still_separate(self):
        long_a = "Senior Staff Software Engineer, Platform Infrastructure North"
        long_b = "Senior Staff Software Engineer, Platform Infrastructure South"
        ids = _assign_ids("exp", ["Globex", "Globex"], [long_a, long_b])
        self.assertEqual(len(set(ids)), 2, f"truncation collided: {ids}")

    def test_a_suffix_never_takes_a_real_single_occurrence_id(self):
        """
        Company "Vertex" twice, one role titled "Data"; separately a company
        literally named "Vertex Data". The single occurrence must keep its ID
        because something is already keyed to it.
        """
        ids = _assign_ids("exp",
                          ["Vertex", "Vertex", "Vertex Data"],
                          ["Data", "Analyst", "Engineer"])
        self.assertEqual(ids[2], "exp_vertex_data")
        self.assertEqual(len(set(ids)), 3, f"collided: {ids}")

    def test_two_projects_of_one_name_are_numbered_from_one(self):
        """
        A project has no second field to be told apart by, so this case is
        positional and says so — but no occurrence keeps the bare ID.
        """
        ids = _assign_ids("proj", ["Search Engine", "Search Engine"], ["", ""])
        self.assertNotIn("proj_search_engine", ids)
        self.assertEqual(ids, ["proj_search_engine_1", "proj_search_engine_2"])

    def test_a_company_that_is_its_own_title_falls_back_to_numbering(self):
        """
        `exp_{slug(company or title)}` falls back to the title when there is no
        company, so the suffix would be the base repeated. Number instead.
        """
        ids = _assign_ids("exp", ["Freelance", "Freelance"],
                          ["Freelance", "Freelance"])
        self.assertEqual(len(set(ids)), 2, f"collided: {ids}")
        self.assertNotIn("exp_freelance", ids)


class TestAnIdThatNamesTheWrongNumberOfComponentsIsReported(unittest.TestCase):
    """
    A profile rule keyed to nothing has always been silent (the check for it
    existed); a rule keyed to an ID that two components now *share* is worse,
    because it fires — on whichever was parsed first. The fuzzy resolver hides
    exactly that case: `exp_vertex_technologies` prefix-matches the first
    suffixed role, so `find_unresolvable_ids` reports nothing for the one key
    this fix orphans.
    """

    @classmethod
    def setUpClass(cls):
        if not ROHAN.is_file():
            raise unittest.SkipTest("needs the second fixture user")
        from tools.resume.resume_parser import ResumeParser
        cls.parser = ResumeParser(str(ROHAN), skip_embeddings=True)

    def _profile(self):
        from tools.profile import load_profile
        return load_profile("rohan_deshmukh")

    def test_the_fixture_as_imported_has_no_problems(self):
        from tools.profile.validation import find_id_problems
        self.assertEqual(find_id_problems(self._profile(), self.parser), [])

    def test_a_stale_pre_q34_bare_key_is_reported_as_ambiguous(self):
        from tools.profile.validation import find_ambiguous_ids

        profile = self._profile()
        rules = profile.resume_preferences.experiences.conditional_inclusion
        rules["exp_vertex_technologies"] = list(rules.values())[0]

        problems = find_ambiguous_ids(profile, self.parser)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("matches 2 components", problems[0])

    def test_a_key_naming_nothing_is_still_reported(self):
        from tools.profile.validation import find_unresolvable_ids

        profile = self._profile()
        profile.resume_preferences.experiences.never_include.append("exp_gone")

        problems = find_unresolvable_ids(profile, self.parser)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("can never fire", problems[0])

    def test_the_combined_check_reports_both_kinds(self):
        from tools.profile.validation import find_id_problems

        profile = self._profile()
        rules = profile.resume_preferences.experiences.conditional_inclusion
        rules["exp_vertex_technologies"] = list(rules.values())[0]
        profile.resume_preferences.experiences.never_include.append("exp_gone")

        self.assertEqual(len(find_id_problems(profile, self.parser)), 2)


class TestTheImportPathReportsIdProblems(unittest.TestCase):
    """
    `create_profile` is the path both UIs use, and it ran no check at all: the
    validator's only callers were the `init_profile` CLI's `main()` and the
    orchestrator at generation, so a profile imported through either front end
    went unchecked until somebody started a run.

    A failed check reports a problem rather than `[]`, because `[]` is read
    everywhere as "every rule names one component" — which is the one thing a
    check that did not run does not know.
    """

    def test_create_profile_returns_the_check_as_data(self):
        from scripts import init_profile

        if not PRIYA.is_file():
            self.skipTest("needs the committed master resume")

        name = "_id_check_probe"
        try:
            result = init_profile.create_profile(PRIYA, name, force=True)
            self.assertIn("id_problems", result)
            self.assertEqual(result["id_problems"], [],
                             "a freshly imported profile keys every rule to a "
                             "component the same import just parsed")
        finally:
            # Including the timestamped backup `create_profile` takes when it
            # overwrites, so a re-run does not leave one per run behind.
            for leftover in init_profile.PROFILES.glob(f"{name}*.json"):
                leftover.unlink()

    def test_a_check_that_cannot_run_says_so_rather_than_returning_nothing(self):
        from scripts import init_profile

        problems = init_profile._id_problems("no_such_profile_anywhere",
                                             ROOT / "no_such_resume.tex")
        self.assertTrue(problems, "a check that could not run reported no "
                                  "problems, which reads as 'all rules fine'")
        self.assertIn("could not be checked", problems[0])


class TestTheRoundTripThatCaughtIt(unittest.TestCase):
    """
    The regression guard, stated directly rather than left implicit in
    `test_latex_round_trip`'s sweep over whatever masters a machine holds.
    """

    def test_a_resume_with_a_repeated_employer_survives_a_reparse(self):
        if not ROHAN.is_file():
            self.skipTest("needs the second fixture user's master resume")

        from tools.resume import tex_renderer

        parsed = parse_latex_resume(str(ROHAN))
        schema = {
            "experiences": [
                {"company": e.company, "title": e.title, "location": e.location,
                 "dates": e.dates, "bullets": list(e.bullets)}
                for e in parsed.experiences
            ],
            "projects": [
                {"name": p.name, "tech": p.tech, "dates": p.dates,
                 "bullets": list(p.bullets)}
                for p in parsed.projects
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "again.tex"
            tex_renderer.write(schema, out)
            again = parse_latex_resume(str(out))

        before = {e.id: e.bullets for e in parsed.experiences}
        after = {e.id: e.bullets for e in again.experiences}
        self.assertEqual(len(before), 3,
                         "the parse collapsed two roles into one key")
        self.assertEqual(sorted(before), sorted(after),
                         f"IDs changed across a render: {sorted(before)} -> "
                         f"{sorted(after)}")
        for comp_id, bullets in before.items():
            self.assertEqual(bullets, after[comp_id],
                             f"{comp_id} changed on the way through")


if __name__ == "__main__":
    unittest.main()

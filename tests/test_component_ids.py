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

import json
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


class TestTheEditorReportsWithoutRepairing(unittest.TestCase):
    """
    The tuning screen already parses the resume to draw itself, so the check
    costs it nothing — and it is the one screen that lists the rules, which
    makes it the only place a warning about them is actionable.

    R17's behaviour is unchanged and deliberately so: a rule keyed to a
    component the resume no longer has is **kept**, on the grounds that a rule
    somebody wrote is worth more than a tidy file. What changes is that the
    save says so. A rule kept and never mentioned is indistinguishable from a
    rule that works, which is the silence R17 set out to remove and could not
    finish on its own.
    """

    NAME = "_editor_id_probe"

    def setUp(self):
        from scripts import init_profile

        source = init_profile.PROFILES / "rohan_deshmukh.json"
        if not source.is_file():
            self.skipTest("needs the second fixture user")

        self.path = init_profile.PROFILES / f"{self.NAME}.json"
        raw = json.loads(source.read_text(encoding="utf-8"))
        raw["user_id"] = self.NAME
        rules = raw["resume_preferences"]["experiences"]["conditional_inclusion"]
        # One of each kind: a key naming nothing, and a pre-Q34 bare key that
        # now names two components.
        rules["exp_a_company_that_left"] = {
            "include_if_jd_contains": ["kafka"], "description": "hand written"}
        rules["exp_vertex_technologies"] = {
            "include_if_jd_contains": ["fraud"], "description": "pre-Q34"}
        self.path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

    def tearDown(self):
        from scripts import init_profile
        for leftover in init_profile.PROFILES.glob(f"{self.NAME}*.json"):
            leftover.unlink()

    def _saved(self):
        from scripts import init_profile
        return init_profile.write_component_rules(self.NAME, {}, {})

    def test_saving_reports_both_kinds(self):
        problems = self._saved()["id_problems"]
        self.assertEqual(len(problems), 2, problems)
        self.assertTrue(any("can never fire" in p for p in problems), problems)
        self.assertTrue(any("matches 2 components" in p for p in problems),
                        problems)

    def test_saving_still_keeps_the_rules_it_warns_about(self):
        """R17. The warning is a report, not a repair."""
        self._saved()

        kept = json.loads(self.path.read_text(encoding="utf-8"))
        rules = kept["resume_preferences"]["experiences"]["conditional_inclusion"]
        self.assertIn("exp_a_company_that_left", rules,
                      "the save deleted a rule it was only meant to mention")
        self.assertIn("exp_vertex_technologies", rules)

    def test_the_screen_is_told_before_the_save_not_only_after(self):
        """
        A warning a person meets only on pressing Save is attached to the wrong
        moment — the rules are on the screen they are already looking at.
        """
        from scripts import init_profile

        rules = init_profile.read_component_rules(self.NAME)
        self.assertEqual(len(rules["id_problems"]), 2, rules["id_problems"])

    def test_the_editors_own_view_is_unchanged_otherwise(self):
        """The added key must not disturb what the screen already draws."""
        from scripts import init_profile

        rules = init_profile.read_component_rules(self.NAME)
        self.assertEqual(len(rules["experiences"]), 3)
        self.assertEqual(len(rules["projects"]), 4)


class TestBothFrontEndsActuallyReadIt(unittest.TestCase):
    """
    The closing move, and the reason this class exists at all.

    `id_problems` was added to `create_profile`'s return and **nothing read
    it** — `app.py` rendered `summary["counts"]`, `Wizard.tsx` rendered
    `summary.counts`, and `api.ts` did not even name the field in its type. It
    crossed the wire from `POST /api/profile` and went on the floor.

    That is this codebase's most-repeated bug, committed by the change that
    was quoting the rule against it: `rarely_include` (R31),
    `scraped_successfully` (R61), the selection breakdown (R57),
    `graduation_eligibility` (R66), `LLM_BACKEND` (R80) — and CLAUDE.md's
    instruction is flat: *wire the consumer in the same change, or do not add
    the field.*

    So the consumer gets an assertion rather than a promise. A producer with
    no reader now fails the build on the side where the reader should be.
    """

    WEB = ROOT / "web" / "src"

    # Files that must name the field itself: the two Python views, the two
    # React screens that pass it on, and the type the response is read
    # through. `IdProblems.tsx` is deliberately absent — it is the renderer
    # and takes a prop, so it never spells the field, and listing it here
    # would only assert that a comment mentions it.
    NAMES_THE_FIELD = {
        "app.py": ROOT / "app.py",
        "api/main.py": ROOT / "api" / "main.py",
        "Wizard.tsx": WEB / "components" / "Wizard.tsx",
        "TuningStep.tsx": WEB / "components" / "steps" / "TuningStep.tsx",
        "api.ts": WEB / "lib" / "api.ts",
    }

    def test_every_front_end_file_that_should_name_the_field_does(self):
        for label, path in self.NAMES_THE_FIELD.items():
            with self.subTest(file=label):
                if not path.is_file():
                    self.skipTest(f"{label} is not in this checkout")
                self.assertIn(
                    "id_problems", path.read_text(encoding="utf-8"),
                    f"{label} does not read `id_problems`, so a profile rule "
                    f"that cannot fire is computed and shown to nobody")

    def test_the_react_warning_has_one_renderer_and_two_call_sites(self):
        """The same rule as the Streamlit one below, on the other front end."""
        renderer = self.WEB / "components" / "IdProblems.tsx"
        if not renderer.is_file():
            self.skipTest("the React app is not in this checkout")

        callers = [self.WEB / "components" / "Wizard.tsx",
                   self.WEB / "components" / "steps" / "TuningStep.tsx"]
        for path in callers:
            with self.subTest(file=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertIn("IdProblems", source,
                              f"{path.name} renders the warning some other "
                              f"way, so there are now two of it to improve")

    def test_the_streamlit_warning_has_one_renderer_and_two_call_sites(self):
        """
        Both screens through `_show_id_problems`, not a block of Streamlit
        copied twice. A warning written twice is a warning improved once,
        which is R69 and R70's shape wearing a view layer.
        """
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("def _show_id_problems"), 1)
        self.assertEqual(source.count("_show_id_problems("), 3,
                         "expected one definition and two call sites")


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

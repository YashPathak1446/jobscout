"""
The About-you screen asks three questions and records what was said (A4).

It used to ask one dropdown and derive two booleans from it, so "Other /
prefer not to say" was saved as "not a US person". Now each question has a
"Prefer not to say" that is stored as `unknown`, nothing is pre-selected from
a stored `unknown`, and Continue waits until all three are answered.

The wording is load-bearing and was reviewed line by line, so it lives in one
place (`init_profile.WORK_AUTHORIZATION_QUESTIONS`) and the React copy is held
to it verbatim.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.init_profile import (  # noqa: E402
    NEEDS_HUMAN,
    WORK_AUTHORIZATION_QUESTIONS,
    update_profile_fields,
)

REACT = ROOT / "web" / "src" / "components" / "steps" / "AboutYouStep.tsx"
LEGACY = ("us_citizen", "permanent_resident", "holds_security_clearance")


class TestTheWording(unittest.TestCase):

    def test_the_reviewed_phrases(self):
        """Each of these was a decision, not a draft."""
        by_field = {q["field"]: q for q in WORK_AUTHORIZATION_QUESTIONS}
        self.assertEqual([q["field"] for q in WORK_AUTHORIZATION_QUESTIONS],
                         ["us_person", "needs_sponsorship", "holds_clearance"])
        # A wrong "No" from an asylee hides ITAR jobs they may hold.
        self.assertIn("refugee or asylee", by_field["us_person"]["question"])
        # Readers answer about the present unless told otherwise.
        self.assertIn("now or in future", by_field["needs_sponsorship"]["question"])
        self.assertEqual(dict(by_field["needs_sponsorship"]["options"])["yes"],
                         "Yes, now or later")
        self.assertTrue(by_field["needs_sponsorship"]["help"].startswith(
            "If you're on a work visa today, the answer is yes."))
        self.assertIn("active", by_field["holds_clearance"]["question"])

    def test_every_question_can_be_declined_and_declining_is_unknown(self):
        for spec in WORK_AUTHORIZATION_QUESTIONS:
            self.assertEqual(dict(spec["options"])["unknown"], "Prefer not to say")
            self.assertEqual([v for v, _ in spec["options"]],
                             ["yes", "no", "unknown"])

    def test_the_react_copy_is_verbatim(self):
        if not REACT.is_file():
            self.skipTest("the React app is not in this checkout")
        source = REACT.read_text(encoding="utf-8")
        for spec in WORK_AUTHORIZATION_QUESTIONS:
            strings = [spec["field"], spec["question"], spec["help"]]
            strings += [label for _, label in spec["options"]]
            for text in strings:
                with self.subTest(text=text):
                    self.assertIn(text, source,
                                  "the React wording has drifted from "
                                  "init_profile.WORK_AUTHORIZATION_QUESTIONS")


class TestNothingDerivesTheOldBooleans(unittest.TestCase):
    """Both screens, counted: the old derivation lived in two files (R80)."""

    def test_neither_screen_writes_a_legacy_key_or_the_visa_dropdown(self):
        for path in (ROOT / "app.py", REACT):
            if not path.is_file():
                continue
            source = path.read_text(encoding="utf-8")
            for token in LEGACY + ("VISA_OPTIONS",):
                with self.subTest(file=path.name, token=token):
                    self.assertNotIn(token, source)

    def test_the_three_answers_are_what_a_human_must_give(self):
        self.assertEqual(NEEDS_HUMAN["personal_info"], [
            "location", "work_authorization.us_person",
            "work_authorization.needs_sponsorship",
            "work_authorization.holds_clearance"])


class _Home(unittest.TestCase):
    """A JOBSCOUT_HOME holding a copy of one committed profile."""

    PROFILE = "rohan_deshmukh"

    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        home = Path(self._home.name)
        self._env = mock.patch.dict(os.environ, {"JOBSCOUT_HOME": str(home)})
        self._env.start()
        self.profiles = home / "user_profiles"
        self.profiles.mkdir()
        shutil.copy(ROOT / "user_profiles" / f"{self.PROFILE}.json", self.profiles)

    def tearDown(self):
        self._env.stop()
        self._home.cleanup()

    def stored(self):
        path = self.profiles / f"{self.PROFILE}.json"
        return json.loads(path.read_text(encoding="utf-8"))["personal_info"]


class TestSavingDropsTheLegacyKeys(_Home):

    def test_an_answer_written_removes_the_booleans_it_replaces(self):
        self.assertIn("us_citizen", self.stored())
        update_profile_fields(None, self.PROFILE, {"personal_info": {
            "work_authorization": {"us_person": "no", "needs_sponsorship": "yes",
                                   "holds_clearance": "no"}}})
        personal = self.stored()
        for key in LEGACY:
            self.assertNotIn(key, personal)
        self.assertEqual(personal["work_authorization"]["us_person"], "no")

    def test_an_unrelated_save_leaves_them_alone(self):
        update_profile_fields(None, self.PROFILE,
                              {"personal_info": {"location": "Austin, TX"}})
        self.assertIn("us_citizen", self.stored())


try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    AppTest = None


def _always_offered() -> list:
    """`app.EXCLUDE_ALWAYS`, read from the source without running the page."""
    import ast
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", None) == "EXCLUDE_ALWAYS"
                        for t in node.targets)):
            return ast.literal_eval(node.value)
    raise AssertionError("app.py no longer defines EXCLUDE_ALWAYS")


@unittest.skipIf(AppTest is None, "streamlit not installed")
class TestTheStreamlitScreen(_Home):
    """Rohan never answered: every question must render unanswered."""

    def _screen(self):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
        app.session_state["profile_name"] = self.PROFILE
        app.session_state["step"] = 1
        app.session_state["max_step"] = 1
        app.run()
        self.assertFalse(app.exception, app.exception)
        return app

    def _radio(self, app, field):
        return next(r for r in app.radio if r.key == f"work-{field}")

    def _continue(self, app):
        return next(b for b in app.button if b.label == "Continue")

    def test_each_question_and_its_help_is_on_screen(self):
        app = self._screen()
        captions = [c.value for c in app.caption]
        for spec in WORK_AUTHORIZATION_QUESTIONS:
            radio = self._radio(app, spec["field"])
            self.assertEqual(radio.label, spec["question"])
            self.assertIn(spec["help"], captions)

    def test_a_stored_unknown_is_shown_unanswered(self):
        app = self._screen()
        for spec in WORK_AUTHORIZATION_QUESTIONS:
            self.assertIsNone(self._radio(app, spec["field"]).value, spec["field"])

    def test_continue_waits_for_all_three(self):
        app = self._screen()
        app.text_input[0].input("Austin, TX").run()
        self.assertTrue(self._continue(app).disabled)
        self._radio(app, "us_person").set_value("yes").run()
        self._radio(app, "needs_sponsorship").set_value("unknown").run()
        self.assertTrue(self._continue(app).disabled)
        self._radio(app, "holds_clearance").set_value("no").run()
        self.assertFalse(self._continue(app).disabled)

    def test_declining_is_saved_as_unknown(self):
        app = self._screen()
        app.text_input[0].input("Austin, TX").run()
        for field, value in (("us_person", "unknown"),
                             ("needs_sponsorship", "unknown"),
                             ("holds_clearance", "no")):
            self._radio(app, field).set_value(value).run()
        self._continue(app).click().run()

        personal = self.stored()
        self.assertEqual(personal["work_authorization"], {
            "us_person": "unknown", "needs_sponsorship": "unknown",
            "holds_clearance": "no"})
        for key in LEGACY:
            self.assertNotIn(key, personal)

    def test_continuing_reaches_a_preferences_screen_that_renders(self):
        """
        Q43. Continue from here lands on Preferences, and for a profile whose
        years are unanswered — Rohan, and every profile the wizard builds —
        that screen raised on `int(None)` while building its options. The
        test above clicked Continue and never looked at what it reached.
        """
        app = self._screen()
        app.text_input[0].input("Austin, TX").run()
        for field in ("us_person", "needs_sponsorship", "holds_clearance"):
            self._radio(app, field).set_value("unknown").run()
        self._continue(app).click().run()

        self.assertFalse(app.exception, app.exception)
        self.assertEqual(app.session_state["step"], 2)
        skip = next(m for m in app.multiselect
                    if m.label == "Skip postings mentioning")
        # Only the level-independent options: unanswered is not zero years,
        # so nothing is offered that assumes where this person sits. Read
        # from source rather than imported — importing app.py runs the page.
        self.assertEqual(skip.options, _always_offered())

    def test_both_screens_offer_the_same_when_years_are_unanswered(self):
        """
        The twin (R70). React's `excludeOptions(null)` already returned
        `EXCLUDE_ALWAYS`; Streamlit now does too, and the two lists are one
        claim kept in two files.
        """
        import re
        tsx = (ROOT / "web" / "src" / "components" / "steps"
               / "PreferencesStep.tsx").read_text(encoding="utf-8")
        self.assertIn("if (years === null) return EXCLUDE_ALWAYS", tsx)
        react = re.search(r"const EXCLUDE_ALWAYS = \[([^\]]*)\]", tsx).group(1)
        self.assertEqual(re.findall(r"'([^']*)'", react), _always_offered())


@unittest.skipIf(AppTest is None, "streamlit not installed")
class TestAStoredAnswerIsShownAsAnswered(_Home):
    """Priya is an H-1B holder: migrated to no / yes, clearance unknown."""

    PROFILE = "priya_raghunathan"

    def test_it_is_preselected_and_the_unknown_one_is_not(self):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
        app.session_state["profile_name"] = self.PROFILE
        app.session_state["step"] = 1
        app.session_state["max_step"] = 1
        app.run()
        values = {r.key: r.value for r in app.radio}
        self.assertEqual(values, {"work-us_person": "no",
                                  "work-needs_sponsorship": "yes",
                                  "work-holds_clearance": None})


if __name__ == "__main__":
    unittest.main()

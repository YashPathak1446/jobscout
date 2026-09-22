"""
A years value the input allows, the API refuses — and the save wrote it (Q44).

Three defects, one field:

- **The save** merged without validating, so `years_experience: 2.5` wrote a
  profile the loader refuses — R30's outcome by a different route. Now
  `update_profile_fields` validates the merged profile and refuses a save that
  *introduces* a schema error, writing nothing.
- **The bound** was 40 on both inputs and 60 on `/api/levels`, and the schema
  had none. One constant now, `YEARS_EXPERIENCE_MAX`, and every consumer reads
  it. Counted: the schema, the levels endpoint, the Streamlit input and the
  React input. The React copy is held equal here.
- **The screen** swallowed a failed levels lookup and kept the previous
  answer's levels beside a number they were not derived from. Now it clears
  them and says why.

Built against Priya (six years). Streamlit is rendered for real; React has no
runner, so its half is source-level and `tsc` checks the rest.
"""

import ast
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.init_profile import ProfileInvalid, update_profile_fields  # noqa: E402
from tools.profile.profile_loader import validate_profile_file  # noqa: E402
from tools.profile.profile_schema import YEARS_EXPERIENCE_MAX  # noqa: E402

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    AppTest = None

WEB = ROOT / "web" / "src"
REFUSED = (2.5, -1, YEARS_EXPERIENCE_MAX + 1)
ACCEPTED = (0, 6, YEARS_EXPERIENCE_MAX, None)


class _Home(unittest.TestCase):
    """A JOBSCOUT_HOME holding a copy of Priya."""

    PROFILE = "priya_raghunathan"

    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        home = Path(self._home.name)
        self._env = mock.patch.dict(os.environ, {"JOBSCOUT_HOME": str(home)})
        self._env.start()
        self.path = home / "user_profiles" / f"{self.PROFILE}.json"
        self.path.parent.mkdir()
        shutil.copy(ROOT / "user_profiles" / f"{self.PROFILE}.json", self.path)

    def tearDown(self):
        self._env.stop()
        self._home.cleanup()

    def years(self, value):
        return {"job_preferences": {"years_experience": value}}

    def write_years(self, value):
        """Put a value on disk the way an unvalidated save once did."""
        profile = json.loads(self.path.read_text(encoding="utf-8"))
        profile["job_preferences"]["years_experience"] = value
        self.path.write_text(json.dumps(profile, indent=2), encoding="utf-8")

    def loads(self):
        return validate_profile_file(str(self.path))[0]


class TestTheSaveRefusesWhatWouldNotLoad(_Home):

    def test_a_refused_value_writes_nothing_and_says_which_field(self):
        before = self.path.read_bytes()
        for value in REFUSED:
            with self.subTest(years=value):
                with self.assertRaises(ProfileInvalid) as caught:
                    update_profile_fields(None, self.PROFILE, self.years(value))
                self.assertIn("job_preferences.years_experience", str(caught.exception))
                self.assertEqual(self.path.read_bytes(), before)
                self.assertTrue(self.loads())

    def test_every_answer_in_range_and_no_answer_are_saved(self):
        for value in ACCEPTED:
            with self.subTest(years=value):
                update_profile_fields(None, self.PROFILE, self.years(value))
                stored = json.loads(self.path.read_text(encoding="utf-8"))
                self.assertEqual(stored["job_preferences"]["years_experience"], value)
                self.assertTrue(self.loads())


class TestABrokenProfileCanStillBeFixedThroughTheForm(_Home):
    """
    Only errors a save *introduces* refuse it. Refusing every save to a
    profile that is already invalid would put a second wall in front of the
    one screen that can fix it — the bad 2.5 written before this change is
    exactly such a profile.
    """

    def setUp(self):
        super().setUp()
        self.write_years(2.5)
        self.assertFalse(self.loads())

    def test_an_unrelated_field_still_saves(self):
        update_profile_fields(None, self.PROFILE, {
            "job_preferences": {"target_roles": ["Staff Engineer"]}})
        stored = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(stored["job_preferences"]["target_roles"], ["Staff Engineer"])

    def test_answering_the_field_again_fixes_it(self):
        update_profile_fields(None, self.PROFILE, self.years(6))
        self.assertTrue(self.loads())

    def test_a_new_error_is_still_refused_alongside_the_old_one(self):
        with self.assertRaises(ProfileInvalid):
            update_profile_fields(None, self.PROFILE, {
                "job_preferences": {"target_roles": "not a list"}})


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestTheApi(_Home):

    def setUp(self):
        super().setUp()
        from api.main import app
        self.client = TestClient(app)

    def test_a_refused_save_is_a_422_with_the_reason_in_words(self):
        before = self.path.read_bytes()
        response = self.client.patch(f"/api/profile/{self.PROFILE}",
                                     json={"updates": self.years(2.5)})
        self.assertEqual(response.status_code, 422)
        # A string, not FastAPI's error list: `api.ts` shows it as it is.
        self.assertIsInstance(response.json()["detail"], str)
        self.assertIn("years_experience", response.json()["detail"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_levels_takes_exactly_the_range_the_save_does(self):
        for value in (0, YEARS_EXPERIENCE_MAX):
            with self.subTest(years=value):
                self.assertEqual(
                    self.client.get(f"/api/levels?years={value}").status_code, 200)
        for value in REFUSED:
            with self.subTest(years=value):
                self.assertEqual(
                    self.client.get(f"/api/levels?years={value}").status_code, 422)


@unittest.skipIf(AppTest is None, "streamlit not installed")
class TestTheStreamlitScreen(_Home):

    def _screen(self):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
        app.session_state["profile_name"] = self.PROFILE
        app.session_state["step"] = 2
        app.session_state["max_step"] = 2
        app.run()
        self.assertFalse(app.exception, app.exception)
        return app

    def _years(self, app):
        return next(n for n in app.number_input
                    if n.label == "Years of professional experience")

    def test_the_input_takes_what_the_schema_takes(self):
        """45 was a save React allowed and a value Streamlit crashed on."""
        self.write_years(45)
        app = self._screen()
        self.assertEqual(self._years(app).value, 45)
        self.assertEqual(self._years(app).max, YEARS_EXPERIENCE_MAX)

    def test_a_stored_value_the_schema_refuses_is_shown_empty_and_explained(self):
        """Not `int(2.5)`: that would show 2 and write 2 back unasked."""
        for value in (2.5, YEARS_EXPERIENCE_MAX + 10):
            with self.subTest(years=value):
                self.write_years(value)
                app = self._screen()
                self.assertIsNone(self._years(app).value)
                self.assertTrue(any(repr(value) in w.value for w in app.warning))

    def test_every_save_goes_through_the_one_that_reports_a_refusal(self):
        """A second bare call would move on as though a refused save saved."""
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        callers = [fn.name for fn in ast.walk(tree)
                   if isinstance(fn, ast.FunctionDef)
                   for call in ast.walk(fn)
                   if isinstance(call, ast.Call)
                   and getattr(call.func, "id", None) == "update_profile_fields"]
        self.assertEqual(callers, ["_save_profile"])


class TestTheReactScreen(unittest.TestCase):
    """Source-level: no runner. `tsc` in `npm run build` checks the types."""

    def _source(self, rel):
        path = WEB / rel
        if not path.is_file():
            self.skipTest(f"{rel} is not in this checkout")
        return path.read_text(encoding="utf-8")

    def test_the_input_bound_is_the_schema_bound(self):
        step = self._source("components/steps/PreferencesStep.tsx")
        copy = re.search(r"const YEARS_MAX = (\d+)", step)
        self.assertIsNotNone(copy, "PreferencesStep no longer defines YEARS_MAX")
        self.assertEqual(int(copy.group(1)), YEARS_EXPERIENCE_MAX)
        self.assertIn("max={YEARS_MAX}", step)
        self.assertNotRegex(step, r"max=\{\d+\}")

    def test_a_failed_lookup_clears_the_levels_rather_than_keeping_them(self):
        step = self._source("components/steps/PreferencesStep.tsx")
        self.assertNotIn(".catch(() => undefined)", step)
        self.assertIn("setLookup({ years, derived: null })", step)
        # And what is shown is keyed to the years on screen, so neither a
        # failed lookup nor a late one stands in for this one.
        self.assertIn("lookup.years === years", step)
        self.assertIn("current = false", step)

    def test_a_refused_save_shows_the_servers_reason(self):
        api = self._source("lib/api.ts")
        self.assertIn("typeof payload.detail === 'string'", api)


if __name__ == "__main__":
    unittest.main()

"""
`PATCH /api/profile/{name}` writes only what the wizard's screens save.

The route merged any dict it was sent. The two screens that call it save
Preferences and About you, and nothing else, but a hand-built request could
also set run caps (A10), the scoring threshold (Q63), or the master resume's
path. Set to a relative `../<other user>/...`, that path made the pipeline
read another partition's resume.

Both directions are checked here. A field outside the list is a 400 and
writes nothing. And every field the two screens send is on the list: a screen
that starts saving a field the list lacks would 400 on every real user. That
would be R72's dead button again, with a server behind it.
"""

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

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None

WEB = ROOT / "web" / "src" / "components" / "steps"
PROFILE = "priya_raghunathan"

# What the two screens send, shape for shape (PreferencesStep.save and
# AboutYouStep.save).
PREFERENCES = {"job_preferences": {
    "target_roles": ["Staff Engineer"],
    "years_experience": 6,
    "seniority": [],
    "exclude_keywords": ["intern"],
    "locations": {
        "cities": ["Boston"], "remote_ok": True, "countries": ["US"],
        "states_priority": ["MA"], "states_acceptable": [],
        "willing_to_relocate": False,
    },
}}
ABOUT_YOU = {"personal_info": {
    "location": "Boston, MA",
    "work_authorization": {"us_person": "yes", "needs_sponsorship": "no",
                           "holds_clearance": "unknown"},
}}

# (what the 400 names, the request). An unlisted section is named as a whole:
# nothing under it is writable, so listing its children would add nothing.
REFUSED = [
    ("agent_preferences", {"agent_preferences": {"max_jobs_to_generate": 500}}),
    ("agent_preferences", {"agent_preferences": {"scoring_threshold": 0}}),
    ("resume_preferences",
     {"resume_preferences": {"master_resume_path": "../bob/data/r.tex"}}),
    ("job_preferences.locations.exclude_countries",
     {"job_preferences": {"locations": {"exclude_countries": ["CA"]}}}),
    ("personal_info.email", {"personal_info": {"email": "someone@example.com"}}),
    ("job_preferences", {"job_preferences": "not a section"}),
]


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestThePatchRoute(unittest.TestCase):

    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        home = Path(self._home.name)
        self._env = mock.patch.dict(os.environ, {"JOBSCOUT_HOME": str(home)})
        self._env.start()
        self.path = home / "user_profiles" / f"{PROFILE}.json"
        self.path.parent.mkdir()
        shutil.copy(ROOT / "user_profiles" / f"{PROFILE}.json", self.path)
        from api.main import app
        self.client = TestClient(app)

    def tearDown(self):
        self._env.stop()
        self._home.cleanup()

    def patch(self, updates):
        return self.client.patch(f"/api/profile/{PROFILE}", json={"updates": updates})

    def test_what_the_two_screens_send_is_saved(self):
        for name, updates in (("preferences", PREFERENCES), ("about you", ABOUT_YOU)):
            with self.subTest(screen=name):
                response = self.patch(updates)
                self.assertEqual(response.status_code, 200, response.text)

    def test_anything_else_is_a_400_that_names_it_and_writes_nothing(self):
        before = self.path.read_bytes()
        for field, updates in REFUSED:
            with self.subTest(request=updates):
                response = self.patch(updates)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertIn(field, response.json()["detail"])
                self.assertEqual(self.path.read_bytes(), before)

    def test_one_refused_field_refuses_the_whole_save(self):
        """No partial writes: the allowed half of a mixed request is not saved."""
        before = self.path.read_bytes()
        mixed = {**PREFERENCES, "agent_preferences": {"scoring_threshold": 0}}
        self.assertEqual(self.patch(mixed).status_code, 400)
        self.assertEqual(self.path.read_bytes(), before)


class TestTheScreensStayInsideTheList(unittest.TestCase):
    """
    Source-level, because the web app has no test runner. It reads the object
    literal each screen passes to `api.updateProfile` and requires every key
    to be on the list at the depth it is sent.
    """

    @staticmethod
    def _sent_keys(source: str) -> list:
        call = source[source.index("api.updateProfile(profile, {"):]
        body, depth = [], 0
        for ch in call[call.index("{"):]:
            depth += ch == "{"
            depth -= ch == "}"
            body.append(ch)
            if depth == 0:
                break
        text = re.sub(r"//[^\n]*", "", "".join(body))[1:-1]  # comments, outer braces
        keys, path = [], []
        for match in re.finditer(r"([A-Za-z_]+)\s*:\s*(\{)?|\}", text):
            if match.group(0) == "}":
                path.pop()
                continue
            keys.append(".".join(path + [match.group(1)]))
            if match.group(2):  # the value is a nested section
                path.append(match.group(1))
        return keys

    def test_every_key_a_screen_sends_is_patchable(self):
        from api.main import PROFILE_PATCHABLE
        for screen in ("PreferencesStep.tsx", "AboutYouStep.tsx"):
            source = (WEB / screen).read_text(encoding="utf-8")
            sent = self._sent_keys(source)
            self.assertTrue(sent, f"{screen}: found no update payload to check")
            for dotted in sent:
                with self.subTest(screen=screen, field=dotted):
                    rule = PROFILE_PATCHABLE
                    for part in dotted.split("."):
                        self.assertIsInstance(rule, dict, dotted)
                        self.assertIn(part, rule, f"{screen} sends {dotted}")
                        rule = rule[part]


if __name__ == "__main__":
    unittest.main()

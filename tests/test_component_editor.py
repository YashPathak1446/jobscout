"""
Reading and writing component rules from the UI (R32).

Derivation reaches a component's tech stack but not the domain words a job
posting uses (R21) — that gap is not closable from the resume, because the
resume never contains those words. The tuning screen closes it by hand, and
these tests cover the two functions behind it, because they write to the one
artefact in this project that is hand-tuned and unbacked.
"""

import json
import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.init_profile import read_component_rules, write_component_rules  # noqa: E402

SOURCE = ROOT / "user_profiles" / "yash_pathak.json"
TEMP = ROOT / "user_profiles" / "_editor_test.json"


@unittest.skipUnless(SOURCE.exists(), "needs a real profile; skipped on a clean clone")
class TestComponentEditor(unittest.TestCase):

    def setUp(self):
        shutil.copy2(SOURCE, TEMP)

    def tearDown(self):
        TEMP.unlink(missing_ok=True)

    def _rules(self):
        return read_component_rules("_editor_test")

    def _first_project(self):
        return self._rules()["projects"][0]["id"]

    def test_reads_both_sections_with_labels_and_tiers(self):
        rules = self._rules()
        self.assertTrue(rules["experiences"] and rules["projects"])
        for section in rules.values():
            for entry in section:
                self.assertTrue(entry["label"], "an editor row needs a human label")
                self.assertIn(entry["tier"], ("high", "medium", "low"))
                self.assertIsInstance(entry["triggers"], list)

    def test_writes_a_trigger_list(self):
        target = self._first_project()
        write_component_rules("_editor_test", {}, {target: ["android", "mobile app"]})
        after = {c["id"]: c for c in self._rules()["projects"]}[target]
        self.assertEqual(after["triggers"], ["android", "mobile app"])

    def test_normalises_case_and_whitespace_and_deduplicates(self):
        target = self._first_project()
        write_component_rules(
            "_editor_test", {},
            {target: ["Android", "  ANDROID  ", "mobile app", "", "   "]},
        )
        after = {c["id"]: c for c in self._rules()["projects"]}[target]
        self.assertEqual(after["triggers"], ["android", "mobile app"])

    def test_clearing_removes_the_rule_rather_than_storing_an_empty_one(self):
        # An empty rule cannot fire and looks identical to one that never
        # matched — the silence R17 set out to remove.
        target = self._first_project()
        write_component_rules("_editor_test", {}, {target: ["android"]})
        write_component_rules("_editor_test", {}, {target: []})

        raw = json.loads(TEMP.read_text(encoding="utf-8"))
        rules = raw["resume_preferences"]["projects"]["conditional_inclusion"]
        self.assertNotIn(target, rules)

    def test_writes_an_importance_tier(self):
        target = self._first_project()
        write_component_rules("_editor_test", {target: "low"}, {})
        after = {c["id"]: c for c in self._rules()["projects"]}[target]
        self.assertEqual(after["tier"], "low")

    def test_an_existing_description_survives_an_edit(self):
        raw = json.loads(TEMP.read_text(encoding="utf-8"))
        rules = raw["resume_preferences"]["projects"]["conditional_inclusion"]
        if not rules:
            self.skipTest("profile has no authored project rules")
        target, original = next(iter(rules.items()))
        note = original.get("description")

        write_component_rules("_editor_test", {}, {target: ["something"]})
        after = json.loads(TEMP.read_text(encoding="utf-8"))
        self.assertEqual(
            after["resume_preferences"]["projects"]["conditional_inclusion"][target]["description"],
            note,
        )

    def test_unknown_component_ids_are_ignored(self):
        before = TEMP.read_text(encoding="utf-8")
        write_component_rules("_editor_test", {"proj_nope": "high"}, {"proj_nope": ["x"]})
        after = json.loads(TEMP.read_text(encoding="utf-8"))
        self.assertNotIn("proj_nope",
                         after["resume_preferences"]["projects"]["conditional_inclusion"])
        self.assertNotIn("proj_nope",
                         after["resume_preferences"]["component_importance"]["projects"])
        self.assertNotEqual(before, "")   # sanity: the file is still readable

    def test_editing_one_component_leaves_the_rest_of_the_profile_alone(self):
        """The screen edits two maps; it must not rewrite the profile."""
        before = json.loads(TEMP.read_text(encoding="utf-8"))
        write_component_rules("_editor_test", {}, {self._first_project(): ["android"]})
        after = json.loads(TEMP.read_text(encoding="utf-8"))

        for key in ("personal_info", "job_preferences", "agent_preferences"):
            self.assertEqual(before[key], after[key], f"{key} should be untouched")
        self.assertEqual(
            before["resume_preferences"]["experiences"]["always_include"],
            after["resume_preferences"]["experiences"]["always_include"],
        )

    def test_a_missing_profile_raises_rather_than_creating_one(self):
        with self.assertRaises(FileNotFoundError):
            read_component_rules("_no_such_profile_")
        with self.assertRaises(FileNotFoundError):
            write_component_rules("_no_such_profile_", {}, {})


if __name__ == "__main__":
    unittest.main()


class TestAlwaysAndNeverInclude(unittest.TestCase):
    """
    R52: the last two USER-INPUT fields that were hand-edited JSON.

    Both have been read by the parser since it was written — `always_include`
    boosts a component, `never_include` excludes it outright — so the rules
    worked and there was simply no way to set them without opening the file.
    """

    def setUp(self):
        if not SOURCE.exists():
            self.skipTest("needs a real profile; skipped on a clean clone")
        shutil.copy2(SOURCE, TEMP)

    def tearDown(self):
        TEMP.unlink(missing_ok=True)

    def _first_project_id(self):
        return read_component_rules("_editor_test")["projects"][0]["id"]

    def _stored(self, section, field):
        data = json.loads(TEMP.read_text(encoding="utf-8"))
        return data["resume_preferences"][section].get(field, [])

    def test_marking_always_include_persists(self):
        component = self._first_project_id()
        write_component_rules("_editor_test", {}, {}, {component: True}, {})
        self.assertIn(component, self._stored("projects", "always_include"))

    def test_unmarking_removes_it_again(self):
        component = self._first_project_id()
        write_component_rules("_editor_test", {}, {}, {component: True}, {})
        write_component_rules("_editor_test", {}, {}, {component: False}, {})
        self.assertNotIn(component, self._stored("projects", "always_include"))

    def test_never_include_persists_separately(self):
        component = self._first_project_id()
        write_component_rules("_editor_test", {}, {}, {}, {component: True})
        self.assertIn(component, self._stored("projects", "never_include"))

    def test_the_reader_reports_what_the_writer_stored(self):
        """A form that cannot read what it wrote reverts it on the next save."""
        component = self._first_project_id()
        write_component_rules("_editor_test", {}, {}, {component: True}, {})
        entry = next(c for c in read_component_rules("_editor_test")["projects"]
                     if c["id"] == component)
        self.assertTrue(entry["always"])
        self.assertFalse(entry["never"])

    def test_omitting_the_decisions_changes_nothing(self):
        """
        The tuning screen can save tiers alone. Passing None must not be read
        as "the user unticked everything".
        """
        component = self._first_project_id()
        write_component_rules("_editor_test", {}, {}, {component: True}, {})
        write_component_rules("_editor_test", {}, {})
        self.assertIn(component, self._stored("projects", "always_include"))

    def test_a_rule_for_an_unknown_component_is_left_alone(self):
        """R17: rules referencing components the resume no longer has."""
        data = json.loads(TEMP.read_text(encoding="utf-8"))
        data["resume_preferences"]["projects"]["always_include"] = ["proj_ghost"]
        TEMP.write_text(json.dumps(data, indent=2), encoding="utf-8")

        write_component_rules("_editor_test", {}, {},
                              {self._first_project_id(): True}, {})
        self.assertIn("proj_ghost", self._stored("projects", "always_include"))

    def test_the_profile_still_loads_afterwards(self):
        from tools.profile import load_profile

        write_component_rules("_editor_test", {}, {},
                              {self._first_project_id(): True}, {})
        self.assertTrue(load_profile("_editor_test"))

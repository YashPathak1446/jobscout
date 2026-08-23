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

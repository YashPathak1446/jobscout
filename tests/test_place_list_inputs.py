"""
Places with spaces can be entered in Preferences, one entry each (R127).

The city, country and state inputs showed the saved list joined with ", "
and re-split and trimmed it on every keystroke. So a space vanished before
the next letter and a comma became a separator as it was typed:
"San Francisco", "New York" and "North Carolina" could not be entered. They
are now chips added with Enter, from a draft typed freely.

The matcher needed no change: `job_filter._score_us_location` compares a
whole entry, case-insensitively, with the full state name the location
parser returns, so "North Carolina" matches "Raleigh, NC" and the split
"North" + "Carolina" never did. Checked here.

The React half is source-level (no web runner). It was also driven once in
Chromium against a hosted build (see R127).
"""

import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

STEP = (ROOT / "web/src/components/steps/PreferencesStep.tsx").read_text(encoding="utf-8")


class TestTheInputs(unittest.TestCase):

    def test_nothing_re_splits_on_commas_while_typing(self):
        self.assertNotIn(".split(',')", STEP)
        self.assertNotIn("value={value.join(', ')}", STEP)
        self.assertNotIn("prefs.cities.join(', ')", STEP)

    def test_enter_adds_one_entry_and_a_draft_is_kept_on_blur(self):
        field = STEP[STEP.index("function Field({"):]
        self.assertRegex(field, r"e\.key === 'Enter'[\s\S]*add\(\)")
        self.assertIn("onBlur={add}", field)
        self.assertIn("onChange([...value, entry])", field)

    def test_every_place_list_uses_it_and_says_enter(self):
        for field_id in ("cities", "countries", "states-priority", "states-acceptable"):
            with self.subTest(field=field_id):
                self.assertRegex(STEP, rf'<Field\s+id="{field_id}"')
        self.assertEqual(len(re.findall(r"then press Enter", STEP)), 4)


class TestAWholeEntryMatches(unittest.TestCase):

    def test_multi_word_states_match_and_their_halves_do_not(self):
        from tools.jobs.job_filter import _score_us_location
        from tools.jobs.location_matcher import parse_location

        whole = SimpleNamespace(states_priority=["North Carolina", "New York"],
                                states_acceptable=[])
        halves = SimpleNamespace(states_priority=["North", "Carolina"],
                                 states_acceptable=[])
        self.assertEqual(_score_us_location(parse_location("Raleigh, NC"), whole), 3)
        self.assertEqual(_score_us_location(parse_location("New York, NY"), whole), 3)
        self.assertEqual(_score_us_location(parse_location("Raleigh, NC"), halves), 0)


if __name__ == "__main__":
    unittest.main()

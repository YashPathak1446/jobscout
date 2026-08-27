"""
Front-end controls that can silently stop being controlled.

`web/` has no test runner yet, and the first bug it produced is one no
contract-level test could see: a Radix `Select` given `value={x || undefined}`
becomes **uncontrolled**. It manages its own selection, `onValueChange` sets
React state, the component flips back to controlled — and the displayed value
never catches up with what the app thinks was chosen.

The instance was the work-authorisation control on step two, which writes
`personal_info.visa_status`. That field feeds `_is_us_person`, which decides
whether ITAR-restricted postings are shown at all. A display that disagrees
with state is usually an annoyance; on this one control it means telling
somebody they are eligible for work they are legally barred from.

Source-level, in the same shape as `test_ui_contract.py`. A real browser test
is the right answer eventually; this costs nothing and holds the specific
footgun that already cost a session.
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

WEB = ROOT / "web" / "src"


def _sources():
    if not WEB.is_dir():
        return []
    return [p for p in sorted(WEB.rglob("*.tsx"))
            if "components/ui/" not in p.as_posix()]


@unittest.skipIf(not WEB.is_dir(), "no web frontend in this checkout")
class TestNoControlDrifts(unittest.TestCase):

    # `value={anything || undefined}` and `value={undefined}`. Both hand a
    # controlled component the one value that turns it uncontrolled.
    UNDEFINED_VALUE = re.compile(
        r"value=\{[^}]*\|\|\s*undefined\s*\}|value=\{\s*undefined\s*\}")

    def test_no_select_is_handed_an_undefined_value(self):
        offenders = []
        for path in _sources():
            text = path.read_text(encoding="utf-8")
            for match in self.UNDEFINED_VALUE.finditer(text):
                line = text[:match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{line}")
        self.assertEqual(
            offenders, [],
            "a controlled component is handed `undefined`, which makes it "
            f"uncontrolled and its display stop tracking state: {offenders}. "
            "Give 'not answered' a named sentinel instead.")

    def test_a_sentinel_is_used_where_empty_is_not_allowed(self):
        """
        The positive half: the two places that need one have one. Radix
        forbids a `SelectItem` with an empty value, so "unset" has to be
        spelled out rather than left as `''` or `undefined`.
        """
        found = {}
        for path in _sources():
            text = path.read_text(encoding="utf-8")
            for name in re.findall(r"const (\w+) = '__\w+__'", text):
                found.setdefault(path.name, []).append(name)
        self.assertIn("AboutYouStep.tsx", found,
                      "the work-authorisation select lost its unset sentinel")
        self.assertIn("Board.tsx", found,
                      "the board filters lost their 'any' sentinel")

    def test_work_authorisation_gates_continue(self):
        """
        Not a rendering detail. The Streamlit form defaulted this select to
        its first option, "US Citizen", so anyone who did not touch it
        asserted citizenship by omission. An unanswered question has to stay
        unanswered, and the button has to know that.
        """
        step = (WEB / "components" / "steps" / "AboutYouStep.tsx")
        if not step.is_file():
            self.skipTest("step two not built")
        text = step.read_text(encoding="utf-8")
        gate = re.search(r"disabled=\{([^}]*saving[^}]*)\}", text)
        self.assertIsNotNone(gate, "Continue has no disabled condition")
        self.assertIn("visa_status", gate.group(1),
                      "Continue does not wait for work authorisation, so "
                      "skipping the question writes whatever the template "
                      "happened to hold")


if __name__ == "__main__":
    unittest.main()

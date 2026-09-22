"""
Front-end controls that can silently stop being controlled.

`web/` has no test runner yet, and the first bug it produced is one no
contract-level test could see: a Radix `Select` given `value={x || undefined}`
becomes **uncontrolled**. It manages its own selection, `onValueChange` sets
React state, the component flips back to controlled — and the displayed value
never catches up with what the app thinks was chosen.

The instance was the work-authorisation control on step two, which wrote
`personal_info.visa_status` and, through it, the booleans that decided
whether ITAR-restricted postings were shown at all. A display that disagrees
with state is usually an annoyance; on that control it meant telling
somebody they were eligible for work they are legally barred from. (A4
replaced the select with three answer buttons, `work_authorization`; the
rule below still holds for every other Select.)

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
        The positive half: the places where "unset" is a real state spell it
        as a named sentinel. Radix forbids a `SelectItem` with an empty value,
        so it cannot be left as `''` or `undefined`.

        The board's filters have "any". About-you had one for its work-
        authorisation select until A4 replaced the select with three answer
        buttons, whose unset state is `null` in plain state; should a Select
        come back to that screen, so must the sentinel.
        """
        found, selects = {}, set()
        for path in _sources():
            text = path.read_text(encoding="utf-8")
            if "<Select" in text:
                selects.add(path.name)
            for name in re.findall(r"const (\w+) = '__\w+__'", text):
                found.setdefault(path.name, []).append(name)
        self.assertIn("Board.tsx", found,
                      "the board filters lost their 'any' sentinel")
        if "AboutYouStep.tsx" in selects:
            self.assertIn("AboutYouStep.tsx", found,
                          "About-you has a Select again and no unset sentinel")

    def test_work_authorisation_gates_continue(self):
        """
        Not a rendering detail. The Streamlit form defaulted its select to
        "US Citizen", so anyone who did not touch it asserted citizenship by
        omission. Since A4 there are three questions; each unanswered one is
        `null`, and Continue waits until none is.
        """
        step = (WEB / "components" / "steps" / "AboutYouStep.tsx")
        if not step.is_file():
            self.skipTest("step two not built")
        text = step.read_text(encoding="utf-8")
        gate = re.search(r"disabled=\{([^}]*saving[^}]*)\}", text)
        self.assertIsNotNone(gate, "Continue has no disabled condition")
        self.assertIn("answered", gate.group(1),
                      "Continue does not wait for work authorisation, so "
                      "skipping the questions writes whatever the template "
                      "happened to hold")
        self.assertRegex(
            text, r"const answered = QUESTIONS\.every\(\s*\(q\) => "
                  r"stored\.answers\[q\.field\] !== null")

if __name__ == "__main__":
    unittest.main()

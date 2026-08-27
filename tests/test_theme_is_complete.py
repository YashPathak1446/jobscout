"""
Every colour token the components reference is defined by the theme.

The visible symptom was a transparent dropdown: `SelectContent` uses
`bg-popover`, the theme never defined `--popover`, so the options rendered
over the page text with nothing behind them. Grepping the vendored components
rather than fixing the one that showed found three more families — the theme
defined nine tokens and the components use thirteen. Error alerts had no
colour either, and nobody had looked at one yet.

The same shape as the recurring bug in reverse: not a value computed and never
read, but a value read and never defined. CSS answers a missing custom
property with silence, so it fails soundlessly and only in the eye.
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

WEB = ROOT / "web" / "src"
CSS = WEB / "index.css"

# Utilities Tailwind resolves from a theme token rather than from its own
# palette. `bg-popover` needs `--color-popover`; `bg-red-500` needs nothing.
USES_TOKEN = re.compile(
    r"\b(?:bg|text|border|ring|fill|stroke|from|to|via|outline|divide|shadow)-"
    r"(popover|destructive|secondary|primary|accent|muted|card|background|"
    r"foreground|border|input|ring|strong|typical|weak)"
    r"(-foreground|-bg)?\b")


@unittest.skipIf(not CSS.is_file(), "no web frontend in this checkout")
class TestNoComponentReferencesAnUndefinedColour(unittest.TestCase):

    def setUp(self):
        css = CSS.read_text(encoding="utf-8")
        self.defined = set(re.findall(r"--color-([a-z-]+):", css))
        self.css = css

    def _referenced(self):
        used = set()
        for path in sorted(WEB.rglob("*.tsx")):
            for base, suffix in USES_TOKEN.findall(path.read_text(encoding="utf-8")):
                used.add(base + (suffix or ""))
        return used

    def test_every_referenced_token_exists(self):
        missing = sorted(self._referenced() - self.defined)
        self.assertEqual(
            missing, [],
            f"components reference colour tokens the theme never defines: "
            f"{missing}. CSS answers a missing custom property with silence, "
            "so these render as transparent or unstyled rather than failing.")

    def test_a_popover_has_something_behind_it(self):
        """
        The specific one. A dropdown with no background is not a style nit —
        the options sit unreadably over whatever is under them.
        """
        self.assertIn("popover", self.defined)
        self.assertIn("popover-foreground", self.defined)

    def test_every_token_is_defined_for_both_themes(self):
        """
        A token defined only in `:root` looks right in light mode and wrong in
        dark, which is the half of this that a single screenshot misses.
        """
        light = self.css[self.css.index(":root {"):self.css.index(".dark {")]
        dark = self.css[self.css.index(".dark {"):self.css.index("@theme inline")]
        light_vars = set(re.findall(r"^\s+--([a-z-]+):", light, re.M))
        dark_vars = set(re.findall(r"^\s+--([a-z-]+):", dark, re.M))
        # `--radius` and its derivatives are deliberately theme-independent.
        only_light = sorted(v for v in light_vars - dark_vars
                            if not v.startswith("radius"))
        self.assertEqual(only_light, [],
                         f"defined for light mode only: {only_light}")


if __name__ == "__main__":
    unittest.main()

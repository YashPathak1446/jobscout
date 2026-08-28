"""
The half of the glyph problem escaping could not fix (R69).

R53 found that `<` renders as an inverted exclamation mark in this template's
OT1 font encoding and escaped it to `\\textless{}`. Two things were left.

**The twin renderer.** R53 fixed `generation_agent._escape_latex_impl` and not
`tex_renderer.escape`, which is the path an imported PDF or DOCX resume takes.
So the identical bug survived in the module only a *new* user reaches — the
author's resume is a `.tex` that never passes through it. Same shape as the
state-code collision in R68: a defect unreachable by the person maintaining it.

**The tilde, which no escape could fix.** `\\textasciitilde` is the correct
escape and renders as a raised diacritic under OT1 — "˜2 min" — and extracts
from the PDF as an unmappable character, so an ATS reading the text loses the
qualifier entirely.

**T1 was tried and rejected on measurement.** Loading `fontenc` fixes all three
glyphs, and breaks the ToUnicode mapping for the en-dash, so every date range
extracts as a control character rather than "2021 - 2025". Trading every date
for three glyphs is the wrong way round for a document ATS software reads as
text. `$\\sim$` fixes the tilde without that cost, and is what a resume means by
a tilde anyway: roughly.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from agents.generation_agent import GenerationAgent  # noqa: E402
from tools.resume.tex_renderer import escape  # noqa: E402


def generated(text: str) -> str:
    return GenerationAgent._escape_latex_impl(GenerationAgent, text)


class TestTheTwoRenderersAgree(unittest.TestCase):
    """
    The divergence is the bug. One table was fixed and the other was not, and
    nothing compared them.
    """

    SAMPLES = (
        "p99 latency <5ms",
        "throughput >1000 rps",
        "about ~2 minutes",
        "94.2% accuracy & 0.71 F1",
        "cost_per_run #3 {edge} case",
        "a\\backslash and a ^caret",
    )

    def test_identical_output_for_every_sample(self):
        for sample in self.SAMPLES:
            self.assertEqual(generated(sample), escape(sample), sample)

    def test_both_tables_cover_the_same_characters(self):
        from agents.generation_agent import GenerationAgent as G
        from tools.resume.tex_renderer import _ESCAPES

        # The generation table is built inline, so probe it character by
        # character rather than reaching for a private constant.
        for char in _ESCAPES:
            self.assertNotEqual(
                generated(char), char,
                f"generation path leaves {char!r} unescaped")


class TestTheCharactersThatRenderWrong(unittest.TestCase):
    def test_less_than_is_escaped_in_the_import_path(self):
        """The one R53 fixed in only one of the two renderers."""
        self.assertIn(r"\textless", escape("p99 <5ms"))

    def test_greater_than_is_escaped_in_the_import_path(self):
        self.assertIn(r"\textgreater", escape("throughput >1000"))

    def test_a_tilde_becomes_math_sim_not_a_raised_diacritic(self):
        """
        `\\textasciitilde` is the *correct* escape and the thing that renders
        wrong, which is why R53 could not reach this one.
        """
        for rendered in (generated("about ~2 min"), escape("about ~2 min")):
            self.assertIn(r"$\sim$", rendered)
            self.assertNotIn("textasciitilde", rendered)

    def test_the_other_escapes_are_untouched(self):
        self.assertIn(r"\%", generated("94.2%"))
        self.assertIn(r"\&", generated("R&D"))
        self.assertIn(r"\_", generated("snake_case"))


class TestTheTemplateStillAvoidsT1(unittest.TestCase):
    """
    Pins a decision that looks like an omission.

    Someone will eventually notice there is no font encoding and add one. The
    reason not to is measurable and is written in the template; this fails if
    the line is added without revisiting it.
    """

    def test_no_fontenc_in_the_base_preamble(self):
        preamble = ROOT / "tools" / "assets" / "base_preamble.tex"
        if not preamble.exists():
            self.skipTest("no base preamble")
        text = preamble.read_text(encoding="utf-8")
        active = [line for line in text.splitlines()
                  if "fontenc" in line and not line.lstrip().startswith("%")]
        self.assertEqual(active, [],
                         "T1 fixes three glyphs and breaks en-dash extraction "
                         "for every date range — see R69 before adding it")

    def test_the_reason_is_recorded_where_someone_would_look(self):
        preamble = ROOT / "tools" / "assets" / "base_preamble.tex"
        if not preamble.exists():
            self.skipTest("no base preamble")
        self.assertIn("fontenc", preamble.read_text(encoding="utf-8"))


class TestMetricChecksSurviveTheChange(unittest.TestCase):
    """
    `$\\sim$` introduces math delimiters into bullet text, and R45's fabrication
    check normalises markup away before comparing figures. If that stopped
    working, a real metric would read as invented.
    """

    def test_a_qualified_figure_still_matches_its_source(self):
        from tools.generation.validation import find_invented_metrics

        master = r"reduced runtime to $\sim$503ms across the fleet"
        data = {"experiences": [{"id": "e", "bullets": [generated("cut runtime to ~503ms")]}],
                "projects": []}
        self.assertEqual(find_invented_metrics(data, master), [])


if __name__ == "__main__":
    unittest.main()

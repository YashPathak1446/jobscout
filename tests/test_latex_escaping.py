"""
Characters that fail silently in the render (R53).

Every other LaTeX special fails loudly: `%` eats the rest of the line, `&`
breaks alignment, `#` is a macro parameter. `<` and `>` fail *quietly* — the
file compiles, the PDF is one page, validation passes, and the default OT1
font encoding renders them as `¡` and `¿`.

Three shipped resumes read "p99 query latency of ¡5ms" before a human opened
one. No test that checks compilation, page count or validation could have
seen it, which is why the last test here goes all the way to reading text back
out of a rendered PDF.
"""

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.generation.pdf_builder import find_pdflatex  # noqa: E402


def _escape(text):
    """The generator's escaper, without standing up a whole agent."""
    from agents.generation_agent import GenerationAgent
    return GenerationAgent._escape_latex_impl(None, text)


class TestTheSilentPair(unittest.TestCase):
    """`<` and `>`, which have no backslash escape and no warning."""

    def test_less_than_is_escaped(self):
        self.assertEqual(_escape("latency of <5ms"),
                         r"latency of \textless{}5ms")

    def test_greater_than_is_escaped(self):
        self.assertEqual(_escape("throughput of >5K QPS"),
                         r"throughput of \textgreater{}5K QPS")

    def test_the_real_bullet_that_shipped_wrong(self):
        """From the Elastic, Baseten and Modal resumes of 2026-08-25."""
        escaped = _escape("p99 query latency of <5ms at million-scale")
        self.assertNotIn("<", escaped)
        self.assertIn(r"\textless{}", escaped)


class TestTheLoudOnesStillWork(unittest.TestCase):
    """Adding two entries to the map must not disturb the other nine."""

    def test_percent_would_otherwise_comment_out_the_line(self):
        self.assertEqual(_escape("95% positive"), r"95\% positive")

    def test_ampersand(self):
        self.assertEqual(_escape("R&D"), r"R\&D")

    def test_underscore(self):
        self.assertEqual(_escape("snake_case"), r"snake\_case")

    def test_dollar(self):
        self.assertEqual(_escape("$5M ARR"), r"\$5M ARR")

    def test_hash(self):
        self.assertEqual(_escape("C# and F#"), r"C\# and F\#")

    def test_tilde(self):
        """
        `$\\sim$` since R69, not `\\textasciitilde`. The old escape was correct
        LaTeX that rendered as a raised diacritic under this template's OT1
        encoding — "˜2 minutes" — and extracted from the PDF as an unmappable
        character, so an ATS reading the text lost the qualifier.
        """
        self.assertEqual(_escape("~2 minutes"), r"$\sim$2 minutes")

    def test_backslash(self):
        self.assertEqual(_escape("a\\b"), r"a\textbackslash{}b")

    def test_nothing_is_escaped_twice(self):
        """
        A single-pass regex, so the backslash introduced by escaping `%` is
        not itself escaped afterwards. Two passes would give `\\textbackslash{}%`.
        """
        self.assertEqual(_escape("100%"), r"100\%")

    def test_ordinary_text_is_untouched(self):
        plain = "Architected an asynchronous serverless REST API in Python"
        self.assertEqual(_escape(plain), plain)

    def test_empty_and_none_are_safe(self):
        self.assertEqual(_escape(""), "")
        self.assertEqual(_escape(None), "")


class TestTheUsersOwnLatexIsLeftAlone(unittest.TestCase):
    """
    The no-model rung passes the master resume's bullets straight through, and
    those are already valid LaTeX — escaping them would print the markup.
    """

    def test_already_latex_text_is_not_escaped(self):
        from agents.generation_agent import GenerationAgent

        source = r"returning HTTP 201 in $\sim 503$ms"
        kept = GenerationAgent._escape_latex(None, source, already_latex=True)
        self.assertEqual(kept, source)


@unittest.skipUnless(find_pdflatex(), "needs a LaTeX engine")
class TestTheRenderedGlyph(unittest.TestCase):
    """
    The only check that could have caught this.

    `<` compiles cleanly and produces a one-page PDF, so compilation and page
    count both pass on the broken version. The defect exists solely in the
    glyph, which means the test has to read the PDF back.
    """

    DOC = (r"\documentclass{article}" "\n" r"\pagestyle{empty}" "\n"
           r"\begin{document}" "\n%s\n" r"\end{document}" "\n")

    def _rendered_text(self, body):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            tex = folder / "probe.tex"
            tex.write_text(self.DOC % body, encoding="utf-8")

            # Run *inside* the folder with a relative filename rather than
            # passing an absolute path. On Windows the temp directory sits
            # under a short 8.3 name — `C:\Users\YASHPA~1\...` — and pdflatex
            # treats `~` as special in a filename, truncating the path at it
            # and dying with "Emergency stop" before it reads a byte.
            subprocess.run(
                [find_pdflatex(), "-interaction=nonstopmode", "probe.tex"],
                cwd=str(folder), capture_output=True, timeout=120)

            pdf = folder / "probe.pdf"
            self.assertTrue(pdf.exists(), "the probe should always compile")

            from pypdf import PdfReader
            return PdfReader(str(pdf)).pages[0].extract_text()

    def test_an_unescaped_less_than_renders_as_an_inverted_bang(self):
        """The bug itself, demonstrated rather than asserted from memory."""
        self.assertIn("¡", self._rendered_text("latency of <5ms"))

    def test_the_escaped_form_renders_as_a_less_than(self):
        rendered = self._rendered_text(_escape("latency of <5ms"))
        self.assertIn("<", rendered)
        self.assertNotIn("¡", rendered)


class TestNoShippedResumeStillHasOne(unittest.TestCase):
    """A regression guard over real output, not a fixture."""

    ITEM = re.compile(r"\\resumeItem\{(.+?)\}\s*\n", re.S)

    def test_resumes_generated_from_now_on_are_clean(self):
        """
        Only checks runs from 2026-08-26 onward — everything before that was
        generated by the broken escaper and is evidence, not a failure.
        """
        offenders = []
        for path in sorted(ROOT.glob("outputs/*/*.tex")):
            if path.parent.name <= "2026-08-25":
                continue
            bodies = " ".join(self.ITEM.findall(path.read_text(encoding="utf-8")))
            if "<" in bodies or ">" in bodies:
                offenders.append(path.name)

        self.assertEqual(offenders, [], f"unescaped angle brackets: {offenders}")


if __name__ == "__main__":
    unittest.main()

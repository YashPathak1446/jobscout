"""
PDF compilation (R8, R9).

Runs with or without a real LaTeX install by standing in a stub "pdflatex"
that fakes each outcome. That matters twice over: contributors without TeX
can still run the suite, and the failure paths (timeout, error, missing
engine) are otherwise almost impossible to trigger deliberately.

This suite already earned its keep once — it caught the wrapped-log page
count bug that had silently disabled the one-page gate for most resumes.
"""

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.generation.pdf_builder import (  # noqa: E402
    _read_page_count,
    compile_pdf,
    find_pdflatex,
)

WINDOWS = os.name == "nt"

MINIMAL_TEX = r"""\documentclass{article}
\begin{document}
Hello.
\end{document}
"""

# Stub bodies, per platform. Each fakes one pdflatex outcome by writing the
# files a real run would leave behind.
STUBS = {
    "ok": {
        "cmd": "@echo off\n"
               "echo %%PDF-1.4 fake > resume.pdf\n"
               "echo This is a fake log > resume.log\n"
               "echo fake aux > resume.aux\n"
               "echo fake out > resume.out\n"
               "exit /b 0\n",
        "sh": "#!/bin/sh\n"
              "echo '%PDF-1.4 fake' > resume.pdf\n"
              "echo 'This is a fake log' > resume.log\n"
              "echo 'fake aux' > resume.aux\n"
              "echo 'fake out' > resume.out\n"
              "exit 0\n",
    },
    "fail": {
        "cmd": "@echo off\n"
               "echo ./resume.tex:42: Undefined control sequence. > resume.log\n"
               "echo fake aux > resume.aux\n"
               "exit /b 1\n",
        "sh": "#!/bin/sh\n"
              "echo './resume.tex:42: Undefined control sequence.' > resume.log\n"
              "echo 'fake aux' > resume.aux\n"
              "exit 1\n",
    },
    "nonzero_but_pdf": {
        "cmd": "@echo off\n"
               "echo %%PDF-1.4 fake > resume.pdf\n"
               "echo recovered warning > resume.log\n"
               "exit /b 1\n",
        "sh": "#!/bin/sh\n"
              "echo '%PDF-1.4 fake' > resume.pdf\n"
              "echo 'recovered warning' > resume.log\n"
              "exit 1\n",
    },
    "slow": {
        "cmd": "@echo off\nping -n 8 127.0.0.1 > nul\nexit /b 0\n",
        "sh": "#!/bin/sh\nsleep 8\nexit 0\n",
    },
    # pdflatex hard-wraps its log at ~79 columns, and where the break lands
    # depends on the filename length. A long name pushes it to just after the
    # "(", so the flattened text reads "( 1 page". A page-count regex that
    # demands the digit adjacent to the paren silently returns 0 here, which
    # switches off the one-page gate for exactly the longest-named resumes.
    "wrapped_log": {
        "cmd": "@echo off\n"
               "echo %%PDF-1.4 fake > resume.pdf\n"
               "echo Output written on Yash_Pathak_Palantir_Technologies_Software_Engineer_New.pdf ( > resume.log\n"
               "echo 1 page, 113911 bytes). >> resume.log\n"
               "exit /b 0\n",
        "sh": "#!/bin/sh\n"
              "echo '%PDF-1.4 fake' > resume.pdf\n"
              "printf 'Output written on Yash_Pathak_Palantir_Technologies_Software_Engineer_New.pdf (\\n1 page, 113911 bytes).\\n' > resume.log\n"
              "exit 0\n",
    },
}


def make_case(tmp: Path, kind: str):
    """Write a resume.tex plus a stub pdflatex; return (tex_path, stub_path)."""
    case = tmp / kind
    case.mkdir()
    tex = case / "resume.tex"
    tex.write_text(MINIMAL_TEX, encoding="utf-8")

    if WINDOWS:
        stub = case / "fake_pdflatex.cmd"
        stub.write_text(STUBS[kind]["cmd"], encoding="utf-8")
    else:
        stub = case / "fake_pdflatex.sh"
        stub.write_text(STUBS[kind]["sh"], encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    return tex, stub


class TestCompilePdf(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_tex_file_fails_without_raising(self):
        result = compile_pdf(self.tmp / "nope.tex", binary="anything")
        self.assertEqual(result.status, "failed")

    def test_no_engine_is_a_skip_not_a_failure(self):
        if find_pdflatex() is not None:
            self.skipTest("a real pdflatex is installed on this machine")
        tex, _ = make_case(self.tmp, "ok")
        result = compile_pdf(tex, binary=None)
        self.assertEqual(result.status, "skipped")
        self.assertFalse(result.success)

    def test_successful_compile(self):
        tex, stub = make_case(self.tmp, "ok")
        result = compile_pdf(tex, binary=str(stub), flavor="texlive")
        self.assertEqual(result.status, "ok")
        self.assertTrue(result.pdf_path.exists())

    def test_aux_files_are_cleaned_up(self):
        tex, stub = make_case(self.tmp, "ok")
        compile_pdf(tex, binary=str(stub), flavor="texlive")
        for suffix in (".aux", ".log", ".out"):
            self.assertFalse(tex.with_suffix(suffix).exists(), suffix)

    def test_keep_aux_preserves_them(self):
        tex, stub = make_case(self.tmp, "ok")
        compile_pdf(tex, binary=str(stub), flavor="texlive", keep_aux=True)
        self.assertTrue(tex.with_suffix(".log").exists())

    def test_latex_error_is_reported_with_the_log_excerpt(self):
        tex, stub = make_case(self.tmp, "fail")
        result = compile_pdf(tex, binary=str(stub), flavor="texlive")
        self.assertEqual(result.status, "failed")
        self.assertIn("Undefined control sequence", result.log_excerpt or "")

    def test_aux_cleaned_even_when_the_compile_fails(self):
        tex, stub = make_case(self.tmp, "fail")
        compile_pdf(tex, binary=str(stub), flavor="texlive")
        self.assertFalse(tex.with_suffix(".aux").exists())

    def test_nonzero_exit_with_a_pdf_on_disk_is_trusted(self):
        # MiKTeX sometimes exits nonzero for warnings it recovered from.
        tex, stub = make_case(self.tmp, "nonzero_but_pdf")
        result = compile_pdf(tex, binary=str(stub), flavor="texlive")
        self.assertEqual(result.status, "ok")

    def test_a_hung_compile_times_out_rather_than_blocking(self):
        tex, stub = make_case(self.tmp, "slow")
        result = compile_pdf(tex, binary=str(stub), flavor="texlive", timeout=1)
        self.assertEqual(result.status, "timeout")

    def test_page_count_survives_a_wrapped_log_line(self):
        # Regression guard for the bug that disabled the one-page gate.
        tex, stub = make_case(self.tmp, "wrapped_log")
        result = compile_pdf(tex, binary=str(stub), flavor="texlive")
        self.assertEqual(result.pages, 1)


if __name__ == "__main__":
    unittest.main()


class TestThePageCountComesFromThePdf(unittest.TestCase):
    r"""
    Ask the PDF, not the log about the PDF.

    Caught by the first run of `scripts/acceptance.py`: a resume reported as
    **0 pages** that was a perfectly good one-page PDF sitting on disk.
    pdflatex hard-wraps its log at ~79 columns and the break had landed inside
    the word itself —

        Output written on Malik_Osei_Nuro_..._2379aef0.pdf (1 pa
        ge, 111668 bytes).

    — so flattening whitespace produced `(1 pa ge,` and nothing looking for
    `page` could match. An earlier fix had already taught the pattern to
    tolerate wraps *between* tokens; this one splits a token, and the next
    filename length would have produced a third variant. The log is a
    rendering of the fact and the PDF is the fact.

    It mattered because `page_count` feeds the one-page gate, and that gate
    asks `> 1` — so an uncountable resume passed as fine. A two-page resume
    with an unlucky filename length would have shipped.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _log(self, body):
        path = self.tmp / "resume.log"
        path.write_text(body, encoding="utf-8")
        return path

    def _pdf(self, pages):
        """A real PDF, because the point is that the artifact is consulted."""
        from pypdf import PdfWriter

        path = self.tmp / "resume.pdf"
        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=612, height=792)
        with open(path, "wb") as handle:
            writer.write(handle)
        return path

    def test_a_wrap_inside_the_word_page_no_longer_hides_the_count(self):
        """The exact log that shipped a 0."""
        log = self._log(
            "Output written on Malik_Osei_Nuro_Software_Engineer_Autonomy"
            "_2379aef0.pdf (1 pa\nge, 111668 bytes).\nPDF statistics:\n")
        self.assertEqual(_read_page_count(log, self._pdf(1)), 1)

    def test_the_log_is_not_consulted_when_the_pdf_can_be_read(self):
        """A log claiming three pages loses to a PDF that has two."""
        log = self._log("Output written on resume.pdf (3 pages, 9 bytes).\n")
        self.assertEqual(_read_page_count(log, self._pdf(2)), 2)

    def test_a_two_page_resume_is_still_reported_as_two(self):
        """The gate this feeds exists to catch exactly this."""
        self.assertEqual(_read_page_count(self._log(""), self._pdf(2)), 2)

    def test_the_log_still_answers_when_there_is_no_pdf(self):
        """The fallback, for a compile that produced a log and nothing else."""
        log = self._log("Output written on resume.pdf (1 page, 5 bytes).\n")
        self.assertEqual(_read_page_count(log, self.tmp / "missing.pdf"), 1)

    def test_an_unreadable_pdf_falls_back_rather_than_raising(self):
        broken = self.tmp / "broken.pdf"
        broken.write_bytes(b"not a pdf at all")
        log = self._log("Output written on resume.pdf (1 page, 5 bytes).\n")
        self.assertEqual(_read_page_count(log, broken), 1)

    def test_nothing_to_read_is_zero_which_means_unknown(self):
        """
        Zero is the *unknown* answer, not a page count. The caller in
        `generation_agent` now demotes on it rather than reading it as "fits".
        """
        self.assertEqual(
            _read_page_count(self.tmp / "missing.log", self.tmp / "missing.pdf"),
            0)


class TestVerbatimLatexIsNotDoubleEscaped(unittest.TestCase):
    """
    The no-model rung emits the user's own bullets, which are already LaTeX.

    Escaping them turns a math span into visible backslash-and-dollar markup
    in the rendered PDF. Both paths compiled and both produced one page — the
    difference was only visible by reading the output, which is why this test
    exists (V3).
    """

    def setUp(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from agents.generation_agent import GenerationAgent

        self.agent = GenerationAgent.__new__(GenerationAgent)

    def test_model_prose_is_escaped(self):
        escaped = self.agent._escape_latex("100% & rising")
        self.assertNotIn("100% ", escaped)
        self.assertIn(r"\%", escaped)

    def test_the_users_own_math_arrives_as_a_tilde_and_leaves_as_a_span(self):
        r"""
        `already_latex=True` used to protect `$\sim 503$ms` from the escaper.
        The parser now hands over `~503ms` instead, so there is nothing to
        protect and the escaper produces the span itself.
        """
        from tools.resume.latex_parser import _clean_latex

        plain = _clean_latex(r"reduced latency to $\sim 503$ms")
        self.assertEqual(plain, "reduced latency to ~503ms")
        self.assertEqual(self.agent._escape_latex(plain),
                         r"reduced latency to $\sim$503ms")

    def test_escaping_a_math_span_would_have_mangled_it(self):
        """Pins the bug itself, so it cannot come back quietly."""
        mangled = self.agent._escape_latex(r"$\sim 503$ms")
        self.assertIn("textbackslash", mangled)

    def test_empty_input_is_safe(self):
        self.assertEqual(self.agent._escape_latex(""), "")
        self.assertEqual(self.agent._escape_latex(None), "")

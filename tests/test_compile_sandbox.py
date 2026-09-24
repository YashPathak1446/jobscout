"""
Every compile runs with fixed engine settings in a fresh directory, and a
compile that produces no PDF is reported, never counted valid (R116).

Engine-independent where it can be: the subprocess is mocked to check what it
is handed, so these pass on TeX Live, MiKTeX and a machine with no LaTeX. The
real compiles of Priya and Rohan run wherever a TeX Live or MiKTeX engine is
installed, and say why they skip elsewhere.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.generation import pdf_builder  # noqa: E402
from tools.generation.pdf_builder import PdfResult  # noqa: E402

TEX = r"\documentclass{article}\begin{document}Hello\end{document}"


class _Scratch(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.tex = self.dir / "resume.tex"
        self.tex.write_text(TEX, encoding="utf-8")
        # Something else in the run's folder, which the compile must not see.
        (self.dir / "other_resume.tex").write_text(TEX, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def compile_with(self, fake_run, flavor="texlive", **kwargs):
        with mock.patch.object(pdf_builder.subprocess, "run", side_effect=fake_run):
            return pdf_builder.compile_pdf(self.tex, binary="pdflatex",
                                           flavor=flavor, **kwargs)


def _writes_a_pdf(calls):
    """A stand-in for pdflatex: records its call and writes a PDF in its cwd."""
    def run(cmd, **kwargs):
        cwd = Path(kwargs["cwd"])
        calls.append({"cmd": cmd, "cwd": cwd, "env": kwargs.get("env"),
                      "files": sorted(p.name for p in cwd.iterdir())})
        (cwd / Path(cmd[-1]).with_suffix(".pdf")).write_bytes(b"%PDF-1.4 stub")
        (cwd / Path(cmd[-1]).with_suffix(".log")).write_text("", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return run


class TestWhatTheEngineIsHanded(_Scratch):

    def test_the_environment_carries_the_settings(self):
        calls = []
        with mock.patch.dict(os.environ, {"TEXMFOUTPUT": "/somewhere", "KEEP": "1"}):
            result = self.compile_with(_writes_a_pdf(calls))
        self.assertEqual(result.status, "ok")
        env = calls[0]["env"]
        self.assertIsNotNone(env, "the engine inherited the environment implicitly")
        for name, value in (("openin_any", "p"), ("openout_any", "p"),
                            ("shell_escape", "f")):
            self.assertEqual(env.get(name), value)
        self.assertNotIn("TEXMFOUTPUT", env)
        self.assertEqual(env.get("KEEP"), "1", "the rest of the environment is kept")

    def test_the_shell_escape_flag_in_each_engines_spelling(self):
        for flavor, flag, absent in (("texlive", "-no-shell-escape", "--disable-write18"),
                                     ("miktex", "--disable-write18", "-no-shell-escape"),
                                     ("unknown", "-no-shell-escape", "--disable-write18")):
            with self.subTest(flavor=flavor):
                calls = []
                self.compile_with(_writes_a_pdf(calls), flavor=flavor)
                self.assertIn(flag, calls[0]["cmd"])
                self.assertNotIn(absent, calls[0]["cmd"])
                self.assertEqual("--enable-installer" in calls[0]["cmd"],
                                 flavor == "miktex")

    def test_each_compile_gets_a_fresh_directory_holding_only_its_tex(self):
        calls = []
        self.compile_with(_writes_a_pdf(calls))
        self.compile_with(_writes_a_pdf(calls))
        first, second = calls[0]["cwd"], calls[1]["cwd"]
        self.assertNotEqual(first, second)
        for call in calls:
            self.assertNotEqual(call["cwd"], self.dir)
            self.assertEqual(call["files"], ["resume.tex"])
            self.assertFalse(call["cwd"].exists(), "the scratch directory was left behind")

    def test_the_pdf_comes_back_beside_the_tex(self):
        result = self.compile_with(_writes_a_pdf([]))
        self.assertEqual(result.pdf_path, self.tex.with_suffix(".pdf"))
        self.assertTrue(result.pdf_path.exists())
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()),
                         ["other_resume.tex", "resume.pdf", "resume.tex"])


class TestNoPdfIsSaidSo(_Scratch):

    def test_a_timeout_is_reported_and_leaves_no_stale_pdf(self):
        self.tex.with_suffix(".pdf").write_bytes(b"%PDF-1.4 from an earlier run")

        def hangs(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

        result = self.compile_with(hangs, timeout=1)
        self.assertEqual(result.status, "timeout")
        self.assertFalse(self.tex.with_suffix(".pdf").exists(),
                         "a PDF from an earlier compile survived beside a new .tex")

    def test_generation_words_each_outcome(self):
        from agents.generation_agent import GenerationAgent
        problem = GenerationAgent._pdf_problem
        self.assertIsNone(problem(None))
        self.assertIsNone(problem(PdfResult(status="ok")))
        self.assertIsNone(problem(PdfResult(status="skipped")))
        self.assertIn("too long", problem(PdfResult(status="timeout")))
        self.assertIn("Undefined control sequence", problem(PdfResult(
            status="failed", log_excerpt="! Undefined control sequence.\nl.3")))

    def test_a_run_whose_compiles_time_out_has_no_valid_resume(self):
        """End to end, mock mode, Rohan: the reason reaches the summary."""
        from agents import orchestrator
        from agents.generation_agent import GenerationAgent
        from tests.fixture_home import fixture_home

        timed_out = PdfResult(status="timeout", error="stub")
        with fixture_home("rohan_deshmukh") as home, \
                mock.patch.object(GenerationAgent, "_compile_to_pdf",
                                  lambda self, path: timed_out):
            run = orchestrator.JobScoutOrchestrator(
                profile_name="rohan_deshmukh", user_id=None, mock_mode=True,
                backend="none", generate_pdf=True, max_resumes=2,
                output_dir=str(home / "outputs"))
            with mock.patch.object(run, "_print_final_report"):
                state = run.run(max_jobs=5)
            summary = (run.output_path / "summary.md").read_text(encoding="utf-8")

        results = state["generation_results"]
        self.assertTrue(results, "the mock run generated nothing; test is blind")
        for result in results:
            self.assertNotEqual(result["status"], "valid")
            self.assertIn("too long", result["pdf_problem"])
            self.assertIsNone(result["pdf_path"])
        self.assertIn("No PDF for", summary)

    def test_the_reason_reaches_the_run_record_and_the_run_screen(self):
        from agents import orchestrator
        from tests.fixture_home import fixture_home

        class StubPipeline:
            profile = None

            def __init__(self, **kwargs):
                pass

            def run(self, **kwargs):
                return {"generation_results": [
                    {"status": "needs_review", "pdf_problem": "the PDF compile ran "
                     "too long and was stopped"}]}

        with fixture_home("priya_raghunathan"), \
                mock.patch.object(orchestrator, "JobScoutOrchestrator", StubPipeline):
            run_id = orchestrator.start_run(None, "priya_raghunathan")
            import time
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                status = orchestrator.run_status(None, run_id)
                if status and not status["active"]:
                    break
                time.sleep(0.02)
            for thread in __import__("threading").enumerate():
                if thread.name == f"jobscout-run-{run_id}":
                    thread.join(20)
        self.assertEqual(status["result"]["pdf_problems"],
                         ["the PDF compile ran too long and was stopped"])
        run_step = (ROOT / "web/src/components/steps/RunStep.tsx").read_text(
            encoding="utf-8")
        self.assertIn("status.result.pdf_problems", run_step)


class TestUploadsAreClassifiedByFileType(unittest.TestCase):

    def setUp(self):
        from tools.resume import resume_import
        self.classify = resume_import.classify_upload
        self.refused = resume_import.UploadRefused

    def test_the_extension_decides_and_the_bytes_must_agree(self):
        self.assertEqual(self.classify(b"%PDF-1.7\n...", "cv.pdf"), "pdf")
        self.assertEqual(self.classify(b"\n\n%PDF-1.4\n", "cv.pdf"), "pdf")
        self.assertEqual(self.classify(b"PK\x03\x04...", "cv.docx"), "docx")
        self.assertEqual(self.classify(TEX.encode(), "cv.tex"), "tex")
        for data, name in ((b"hello", "cv.pdf"), (b"%PDF-1.7", "cv.docx"),
                           (b"%PDF-1.7", "cv.tex"), (b"PK\x03\x04", "cv.txt"),
                           (b"x", "cv.exe"), (b"x", "cv")):
            with self.subTest(name=name, data=data[:8]):
                with self.assertRaises(self.refused):
                    self.classify(data, name)

    def test_a_pdf_whose_text_looks_like_latex_is_imported_as_a_pdf(self):
        """
        What the text says never decides the kind. This was the one path by
        which a PDF's content could be kept and compiled as LaTeX.
        """
        from scripts import init_profile
        from tests.fixture_home import fixture_home
        from tools.resume import resume_import

        latexish = "\\documentclass{article}\\begin{document}Jane Doe\\end{document}"
        readable = {"contact": {"email": "jane@example.com"}}
        with fixture_home(), \
                mock.patch.object(resume_import, "extract_text", return_value=latexish), \
                mock.patch.object(resume_import, "to_schema",
                                  return_value=readable) as to_schema:
            result = init_profile.extract_resume(
                None, b"%PDF-1.7\nstub", "cv.pdf", backend="none")
        self.assertEqual(result["kind"], "extracted")
        self.assertEqual(to_schema.call_args.args[0], latexish,
                         "the PDF's text was not sent through the PDF import path")


@unittest.skipIf(pdf_builder.find_pdflatex() is None,
                 "needs a LaTeX engine (TeX Live or MiKTeX) to compile for real")
class TestTheFixturesStillCompile(unittest.TestCase):

    def test_priya_and_rohan(self):
        for name in ("priya_raghunathan", "rohan_deshmukh"):
            with self.subTest(fixture=name), tempfile.TemporaryDirectory() as tmp:
                tex = Path(shutil.copy(ROOT / "data" / "master_resumes" / f"{name}.tex",
                                       tmp))
                result = pdf_builder.compile_pdf(tex)
                self.assertEqual(result.status, "ok", result.log_excerpt or result.error)
                self.assertEqual(result.pages, 1)
                self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()),
                                 [f"{name}.pdf", f"{name}.tex"])


if __name__ == "__main__":
    unittest.main()

"""
The doctor, and the two rules that make it worth running (R50).

Roadmap item 8 argued a doctor outlives an install script: an installer has to
know how to put LaTeX on six platforms, a doctor only has to notice it is
missing and name it. These tests hold the two rules that decide whether anyone
keeps reading its output.

**Say what to do, not just what is wrong.** A report of diagnoses is a
to-do list you still have to research.

**Distinguish broken from absent.** Most of this pipeline is optional — no
Gemini key, no LaTeX and no local embeddings are all supported configurations.
Reporting them as failures would train someone to skim past the report, which
is R47's lesson applied to a diagnostic tool: a warning that fires when
nothing is wrong is worse than no warning.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts import doctor  # noqa: E402


class TestOptionalThingsAreNotFailures(unittest.TestCase):
    """Every one of these is a run that still works."""

    def test_no_latex_engine_is_a_warning(self):
        import tools.generation.pdf_builder as pdf_builder

        real = pdf_builder.find_pdflatex
        pdf_builder.find_pdflatex = lambda: None
        try:
            report = doctor.Report()
            doctor.check_pdflatex(report)
        finally:
            pdf_builder.find_pdflatex = real

        self.assertEqual(report.checks[0]["status"], doctor.WARN)
        self.assertEqual(report.failures, [])

    def test_no_model_is_a_warning_not_a_failure(self):
        """R37's floor is a supported configuration, not a fault."""
        import agents.orchestrator as orchestrator

        real = orchestrator.backend_status
        orchestrator.backend_status = lambda key="": {
            "backend": "none", "description": "", "forced": False, "available": {}}
        try:
            report = doctor.Report()
            doctor.check_rewriting_backend(report)
        finally:
            orchestrator.backend_status = real

        self.assertEqual(report.checks[0]["status"], doctor.WARN)

    def test_no_local_embeddings_is_a_warning(self):
        import tools.resume.local_embeddings as local_embeddings

        real = local_embeddings.is_available
        local_embeddings.is_available = lambda: False
        try:
            report = doctor.Report()
            doctor.check_scoring_backend(report)
        finally:
            local_embeddings.is_available = real

        self.assertEqual(report.checks[0]["status"], doctor.WARN)


class TestEveryProblemComesWithAFix(unittest.TestCase):

    def _warned(self, check, module, attribute, replacement):
        real = getattr(module, attribute)
        setattr(module, attribute, replacement)
        try:
            report = doctor.Report()
            check(report)
        finally:
            setattr(module, attribute, real)
        return report.checks[0]

    def test_a_missing_latex_engine_names_what_to_install(self):
        import tools.generation.pdf_builder as pdf_builder

        found = self._warned(doctor.check_pdflatex, pdf_builder,
                             "find_pdflatex", lambda: None)
        self.assertIn("MiKTeX", found["fix"])
        self.assertIn("TeX Live", found["fix"])

    def test_a_missing_model_names_where_to_get_a_key(self):
        import agents.orchestrator as orchestrator

        found = self._warned(
            doctor.check_rewriting_backend, orchestrator, "backend_status",
            lambda key="": {"backend": "none", "description": "",
                            "forced": False, "available": {}})
        self.assertIn("aistudio.google.com", found["fix"])

    def test_a_missing_dependency_names_the_command(self):
        report = doctor.Report()
        real = doctor.__builtins__["__import__"] if isinstance(
            doctor.__builtins__, dict) else __import__

        def refuse(name, *args, **kwargs):
            if name == "pypdf":
                raise ImportError("no pypdf")
            return real(name, *args, **kwargs)

        import builtins
        builtins.__import__ = refuse
        try:
            doctor.check_dependencies(report)
        finally:
            builtins.__import__ = real

        self.assertEqual(report.checks[0]["status"], doctor.FAIL)
        self.assertIn("pip install", report.checks[0]["fix"])
        self.assertIn("pypdf", report.checks[0]["detail"])


class TestABrokenProfileIsAFailure(unittest.TestCase):
    """
    The one class of problem that does stop a run, so it must not be a
    warning lost among the optional ones.
    """

    def test_an_unloadable_profile_fails(self):
        import tools.profile as profile_module

        real_list = profile_module.list_available_profiles
        real_load = profile_module.load_profile

        def explode(name):
            raise ValueError("countries: field required")

        profile_module.list_available_profiles = lambda: ["broken"]
        profile_module.load_profile = explode
        try:
            report = doctor.Report()
            doctor.check_profiles(report)
        finally:
            profile_module.list_available_profiles = real_list
            profile_module.load_profile = real_load

        self.assertEqual(report.checks[0]["status"], doctor.FAIL)
        self.assertIn("countries", report.checks[0]["detail"])

    def test_no_profiles_at_all_is_only_a_warning(self):
        """A fresh clone has none, and that is where everybody starts."""
        import tools.profile as profile_module

        real = profile_module.list_available_profiles
        profile_module.list_available_profiles = lambda: []
        try:
            report = doctor.Report()
            doctor.check_profiles(report)
        finally:
            profile_module.list_available_profiles = real

        self.assertEqual(report.checks[0]["status"], doctor.WARN)
        self.assertIn("init_profile", report.checks[0]["fix"])


class TestTheReportItself(unittest.TestCase):

    def test_a_check_that_explodes_is_reported_rather_than_lost(self):
        """
        A doctor that dies on its own diagnostic is worse than useless — you
        get a traceback instead of the eight things that were fine.
        """
        def broken(report):
            raise RuntimeError("boom")

        real = doctor.CHECKS
        doctor.CHECKS = (broken,)
        try:
            report = doctor.run()
        finally:
            doctor.CHECKS = real

        self.assertTrue(any("boom" in c["detail"] for c in report.checks))
        self.assertTrue(report.failures)

    def test_the_exit_code_is_zero_when_only_warnings(self):
        report = doctor.Report()
        report.add(doctor.WARN, "PDF", "no engine", "install MiKTeX")
        self.assertEqual(report.failures, [])

    def test_the_render_names_every_check(self):
        report = doctor.Report()
        report.add(doctor.OK, "Python", "3.12")
        report.add(doctor.FAIL, "Profiles", "broken", "rebuild it")
        text = report.render()

        self.assertIn("Python", text)
        self.assertIn("Profiles", text)
        self.assertIn("rebuild it", text)

    def test_a_clean_run_says_so(self):
        report = doctor.Report()
        report.add(doctor.OK, "Python", "3.12")
        self.assertIn("Everything checks out", report.render())

    def test_the_real_report_runs_end_to_end(self):
        """Against this machine, whatever state it is in."""
        report = doctor.run()
        self.assertTrue(report.checks)
        self.assertTrue(all(c["status"] in (doctor.OK, doctor.WARN, doctor.FAIL)
                            for c in report.checks))


class TestBackupsAreNotProfiles(unittest.TestCase):
    """
    Found by the doctor reporting three profiles where there is one.

    Rebuilding keeps a timestamped backup beside the profile (R30), and the
    listing offered those as choices — so the app's profile dropdown showed
    yesterday's copy of your own profile as a separate option.
    """

    def test_a_bak_file_is_not_offered(self):
        import json
        import tempfile
        from tools.profile import list_available_profiles

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for name in ("jane.json", "jane.20260823T141736.bak.json",
                         "template.json"):
                (folder / name).write_text(json.dumps({}), encoding="utf-8")

            self.assertEqual(list_available_profiles(str(folder)), ["jane"])


if __name__ == "__main__":
    unittest.main()

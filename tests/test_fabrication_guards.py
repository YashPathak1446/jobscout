"""
Two guards against a model inventing your resume (R45).

R44 watched llama3.1:8b return a job that did not exist: a date of "Summer
2022" against real work in June–Oct 2025, a "30% reduction in development
time" that appears nowhere, and Flask/MySQL/EC2 in place of the actual
Terraform and dual-Lambda work. Only a parse failure kept it off a resume.

The two guards work at different levels and neither replaces the other:

    restore   fields whose correct value is already known are taken back from
              the master, so the model cannot get them wrong at all
    detect    figures inside rewritten bullets are checked against the master,
              because those the model genuinely has to write

The detector's calibration is the delicate part and has its own tests below.
Its first version flagged 13 of 16 real Gemini resumes, every one a false
positive from LaTeX math mode — and a check that cries wolf is worse than no
check, because it teaches you to click past the error that matters.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.generation.validation import (  # noqa: E402
    find_invented_metrics,
    validate_resume_output,
)

# How the master resume actually writes its figures: LaTeX math mode.
MASTER = r"""
\resumeItem{Architected an asynchronous serverless REST API in Python using a
dual-Lambda fan-out pattern that eliminated a 25-second downstream-service read
timeout by spawning background-thread invocations and returning HTTP 201 in
$\sim 503$ms - collapsing client-perceived end-to-end runtime from
$\sim 10$ minutes (synchronous polling) to under a second, while sidestepping
API Gateway's 30-second idle-connection limit.}
\resumeItem{Engineered an embedding cache and persistent job-deduplication layer
that delivered a $\sim 3.6$x speedup on warm runs (137s $\to$ 38s).}
\resumeItem{Designed a multi-tier pipeline over PubMed's 36M-article corpus.}
\resumeItem{Crawled and indexed 30K+ web documents per assignment specification.}
\resumeItem{Maintained a 95\%+ positive feedback rating across sessions.}
"""


def _output(*bullets):
    return {"experiences": [{"id": "exp_sorenson", "bullets": list(bullets)}],
            "projects": []}


class TestRealMetricsAreNotFlagged(unittest.TestCase):
    """
    Calibration. Every case here is a figure that IS in the master, written
    differently — and every one was a false positive at some point today.
    """

    def _flagged(self, *bullets):
        return [m for _, m, _ in find_invented_metrics(_output(*bullets), MASTER)]

    def test_a_math_mode_figure_is_recognised(self):
        """`$\\sim 503$ms` in the master, `503ms` in the bullet."""
        self.assertEqual(self._flagged("Returned HTTP 201 in ~503ms"), [])

    def test_a_math_mode_multiplier_is_recognised(self):
        """`$\\sim 3.6$x` — the first false positive found."""
        self.assertEqual(self._flagged("Delivered a 3.6x speedup on warm runs"), [])

    def test_an_abbreviated_unit_is_recognised(self):
        """Master says `10 minutes`, the bullet says `10 min`."""
        self.assertEqual(self._flagged("Cut runtime from 10 min to under a second"), [])

    def test_prose_in_the_master_matches_a_numeral_in_the_bullet(self):
        """
        Master: "to under a second". Bullet: "to <1 sec". Same claim, and the
        numeral is the better line — this appeared in four real resumes.
        """
        self.assertEqual(self._flagged("Cut client-perceived runtime to <1 sec"), [])

    def test_a_trailing_plus_does_not_make_a_figure_new(self):
        """Master `36M-article`, bullet `36M+ articles`."""
        self.assertEqual(self._flagged("Ingested 36M+ articles into the index"), [])

    def test_an_intervening_word_does_not_either(self):
        """Master `30K+ web documents`, bullet `30K+ documents`."""
        self.assertEqual(self._flagged("Indexed 30K+ documents with TF-IDF ranking"), [])

    def test_an_escaped_percentage_is_recognised(self):
        """Master writes `95\\%+`."""
        self.assertEqual(self._flagged("Held a 95% positive feedback rating"), [])


class TestInventedMetricsAreCaught(unittest.TestCase):
    """The figures llama3.1:8b actually produced in R44."""

    def _flagged(self, *bullets):
        return [m for _, m, _ in find_invented_metrics(_output(*bullets), MASTER)]

    def test_an_invented_percentage_is_caught(self):
        self.assertIn("30%", self._flagged(
            "Designed a scalable web application using Python, Flask and MySQL, "
            "resulting in a 30% reduction in development time."))

    def test_a_second_invented_percentage_is_caught(self):
        self.assertIn("25%", self._flagged(
            "Implemented cloud infrastructure using AWS EC2, S3 and Lambda, "
            "achieving a 25% increase in application performance."))

    def test_an_invented_figure_makes_the_resume_invalid(self):
        """
        Not a warning. A resume is a factual claim about a person, so an
        invented number is a correctness failure, and generation must route it
        to needs_review rather than write it out.
        """
        result = validate_resume_output(
            _output("Cut costs by 40% across the platform."),
            master_resume_text=MASTER)
        self.assertFalse(result.valid)
        self.assertTrue(any("does not appear" in e for e in result.errors))

    def test_nothing_is_checked_without_a_master_to_check_against(self):
        """
        The old behaviour, kept deliberately: no master text, no metric checks.
        What changed is that the callers now pass one — for as long as they
        did not, this whole guard was dead code.
        """
        result = validate_resume_output(_output("Cut costs by 40%."))
        self.assertFalse(any("does not appear" in e for e in result.errors))


class TestFactualFieldsAreRestored(unittest.TestCase):
    """
    Dates, company and title are records, not writing.

    The LaTeX builder reads them straight out of the model's reply, so a
    hallucinated date reaches the page. Taking them back from the master
    removes the class instead of detecting it.
    """

    def setUp(self):
        from agents.generation_agent import GenerationAgent
        from tools.profile import load_profile
        from tools.resume import ResumeParser

        source = ROOT / "user_profiles" / "yash_pathak.json"
        if not source.exists():
            self.skipTest("needs a real profile; skipped on a clean clone")

        profile = load_profile("yash_pathak")
        parser = ResumeParser(profile.resume_preferences.master_resume_path,
                              skip_embeddings=True)
        self.agent = GenerationAgent(profile, parser, generate_pdf=False)
        self.real = parser.get_experience_by_id("exp_sorenson_communications")
        if self.real is None:
            self.skipTest("this profile does not have the expected component")

    def _restore(self, **overrides):
        entry = {"id": "exp_sorenson_communications", "bullets": ["A bullet."]}
        entry.update(overrides)
        tailored = {"experiences": [entry], "projects": []}
        self.agent._restore_factual_fields(tailored)
        return tailored["experiences"][0]

    def test_a_hallucinated_date_is_replaced(self):
        """R44's actual output: "Summer 2022" for work done in 2025."""
        self.assertEqual(self._restore(dates="Summer 2022")["dates"], self.real.dates)

    def test_a_changed_company_is_replaced(self):
        self.assertEqual(self._restore(company="Acme Corp")["company"],
                         self.real.company)

    def test_a_changed_title_is_replaced(self):
        self.assertEqual(self._restore(title="Senior Architect")["title"],
                         self.real.title)

    def test_bullets_are_left_to_the_model(self):
        """Restoring facts must not undo the rewriting that is the whole point."""
        entry = self._restore(dates="Summer 2022", bullets=["A tailored bullet."])
        self.assertEqual(entry["bullets"], ["A tailored bullet."])

    def test_an_unknown_id_is_left_alone(self):
        """
        A component the resume does not have is a different failure, already
        reported by _validate_selected_ids. Silently inventing fields for it
        would hide that.
        """
        tailored = {"experiences": [{"id": "exp_does_not_exist",
                                     "dates": "Summer 2022", "bullets": []}],
                    "projects": []}
        self.agent._restore_factual_fields(tailored)
        self.assertEqual(tailored["experiences"][0]["dates"], "Summer 2022")


if __name__ == "__main__":
    unittest.main()

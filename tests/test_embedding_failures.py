"""
An embedding call that fails says why, and a rate limit is waited out (R97).

A 40-job comparison on a free Gemini key came back with 34 jobs unscored and
34 identical log lines. `_get_embedding` caught every exception, logged it and
returned `[]`: no retry, and no classification, so nobody could say whether it
was a rate limit, a retired model or a bad key. These tests hold the three
things that replaced that:

* every call that failed or needed a retry leaves one entry in a caller-owned
  report, classified by `config.classify_api_error`;
* quota and transient errors are retried with backoff, anything else is not;
* two vectors of different widths are refused rather than truncated, and the
  resume cache is labelled with the model that actually wrote it — because a
  potion vector filed under Gemini's name was the other way a "Gemini" column
  could be quietly wrong.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import tools.resume.embedding_scorer as scorer  # noqa: E402
from tools import paths  # noqa: E402
from tools.cache.rate_limiter import backoff_delay  # noqa: E402

try:
    from google import genai
except ImportError:  # pragma: no cover - google-genai is a runtime dependency
    genai = None

PRIYA_TEX = ROOT / "data" / "master_resumes" / "priya_raghunathan.tex"


def _fake_client(outcomes, calls):
    """
    A genai.Client whose embed_content plays `outcomes` in order: an exception
    instance is raised, a list is returned as the vector.
    """
    class FakeClient:
        def __init__(self, api_key=None):
            self.models = self

        def embed_content(self, **kwargs):
            calls.append(kwargs["contents"])
            outcome = outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
            if isinstance(outcome, Exception):
                raise outcome

            class R:
                embeddings = [type("V", (), {"values": outcome})()]
            return R()

    return FakeClient


@unittest.skipIf(genai is None, "google-genai not installed")
class _GeminiCase(unittest.TestCase):
    """A Gemini backend with a stub client, a fresh cache and no real sleeping."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.calls, self.slept = [], []
        for patcher in (
            mock.patch.dict(os.environ, {paths.HOME_ENV: self._dir.name}),
            mock.patch.object(scorer, "active_backend",
                              lambda: ("gemini", "test-model", 2)),
            mock.patch.object(scorer, "_EMBEDDING_CACHES", {}),
            mock.patch.object(scorer, "_sleep", self.slept.append),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def play(self, *outcomes):
        patcher = mock.patch.object(genai, "Client",
                                    _fake_client(list(outcomes), self.calls))
        patcher.start()
        self.addCleanup(patcher.stop)


class TestEveryFailureIsClassified(_GeminiCase):

    def test_a_rate_limit_that_never_clears_is_reported_as_quota(self):
        self.play(Exception("429 RESOURCE_EXHAUSTED: quota exceeded"))
        report = []

        self.assertEqual(scorer._get_embedding("jd", user_id=None, report=report), [])

        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]["kind"], "quota")
        self.assertFalse(report[0]["recovered"])
        self.assertEqual(report[0]["attempts"], scorer.EMBED_RETRIES + 1)
        self.assertEqual(len(self.slept), scorer.EMBED_RETRIES,
                         "a rate limit must be waited out before giving up")

    def test_a_retired_model_fails_at_once_and_says_so(self):
        self.play(Exception("404 NOT_FOUND: models/x is not found"))
        report = []
        scorer._get_embedding("jd", user_id=None, report=report)

        self.assertEqual([e["kind"] for e in report], ["retired"])
        self.assertEqual(report[0]["attempts"], 1)
        self.assertEqual(self.slept, [], "a retired model will not come back")

    def test_a_bad_key_is_fatal_and_not_retried(self):
        self.play(Exception("400 INVALID_ARGUMENT: API key not valid"))
        report = []
        scorer._get_embedding("jd", user_id=None, report=report)

        self.assertEqual([e["kind"] for e in report], ["fatal"])
        self.assertEqual(len(self.calls), 1)

    def test_a_server_hiccup_is_retried(self):
        self.play(Exception("503 UNAVAILABLE"), [0.6, 0.8])
        report = []

        self.assertEqual(scorer._get_embedding("jd", user_id=None, report=report),
                         [0.6, 0.8])
        self.assertEqual(report, [{"kind": "transient", "attempts": 2,
                                   "recovered": True}])

    def test_a_clean_call_leaves_no_entry(self):
        self.play([0.6, 0.8])
        report = []
        scorer._get_embedding("jd", user_id=None, report=report)
        self.assertEqual(report, [])

    def test_the_report_is_optional(self):
        """Every caller before R97 passes none, and must keep working."""
        self.play(Exception("429 RESOURCE_EXHAUSTED"))
        self.assertEqual(scorer._get_embedding("jd", user_id=None), [])


class TestARateLimitIsWaitedOut(_GeminiCase):

    def test_two_rate_limits_then_success_scores_the_job(self):
        self.play(Exception("429 RESOURCE_EXHAUSTED"),
                  Exception("429 RESOURCE_EXHAUSTED"),
                  [0.6, 0.8])
        report = []

        vector = scorer._get_embedding("jd", user_id=None, report=report)

        self.assertEqual(vector, [0.6, 0.8])
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(report, [{"kind": "quota", "attempts": 3, "recovered": True}],
                         "a retry that succeeded must still be visible, or the "
                         "fix erases the diagnosis")

    def test_the_wait_honours_the_delay_the_api_asks_for(self):
        self.play(Exception("429 RESOURCE_EXHAUSTED. Please retry in 26.8s"),
                  [0.6, 0.8])
        scorer._get_embedding("jd", user_id=None)
        self.assertGreaterEqual(self.slept[0], 26.8)

    def test_a_recovered_vector_is_cached_and_a_failure_is_not(self):
        self.play(Exception("429 RESOURCE_EXHAUSTED"))
        scorer._get_embedding("jd", user_id=None)
        failed_calls = len(self.calls)

        self.play([0.6, 0.8])
        scorer._get_embedding("jd", user_id=None)
        scorer._get_embedding("jd", user_id=None)
        self.assertEqual(len(self.calls), failed_calls + 1,
                         "the success was not cached, or the failure was")


class TestASpentDailyCapFailsFast(_GeminiCase):
    """Backoff rescues a per-minute limit; it cannot rescue a spent daily cap."""

    def test_after_two_exhausted_calls_the_run_stops_waiting(self):
        self.play(Exception("429 RESOURCE_EXHAUSTED"))
        report = []
        for text in ("a", "b"):
            scorer._get_embedding(text, user_id=None, report=report)
        waits_so_far = len(self.slept)

        scorer._get_embedding("c", user_id=None, report=report)

        self.assertEqual(len(self.slept), waits_so_far,
                         "a third job waited out the full backoff to fail anyway")
        self.assertEqual(report[-1], {"kind": "quota", "attempts": 1, "recovered": False,
                                      "error": "429 RESOURCE_EXHAUSTED"})

    def test_the_breaker_is_per_report_not_per_process(self):
        """One user's spent key must not stop another's run from retrying."""
        self.play(Exception("429 RESOURCE_EXHAUSTED"))
        spent = []
        for text in ("a", "b"):
            scorer._get_embedding(text, user_id=None, report=spent)

        self.play(Exception("429 RESOURCE_EXHAUSTED"), [0.6, 0.8])
        fresh = []
        self.assertEqual(scorer._get_embedding("z", user_id=None, report=fresh),
                         [0.6, 0.8])

    def test_recovered_rate_limits_do_not_trip_it(self):
        report = [{"kind": "quota", "attempts": 3, "recovered": True}] * 5
        self.assertFalse(scorer._quota_spent(report))


class TestTheSummary(unittest.TestCase):

    def test_failures_are_counted_by_kind_and_recoveries_apart(self):
        report = [
            {"kind": "quota", "attempts": 5, "recovered": False},
            {"kind": "quota", "attempts": 5, "recovered": False},
            {"kind": "fatal", "attempts": 1, "recovered": False},
            {"kind": "quota", "attempts": 2, "recovered": True},
        ]
        summary = scorer.summarise_report(report)

        self.assertEqual(summary, {"failed": {"fatal": 1, "quota": 2}, "recovered": 1})
        self.assertEqual(scorer.describe_report(summary),
                         "3 failed (1 fatal, 2 quota); 1 recovered after retrying")

    def test_nothing_to_report_says_so(self):
        self.assertEqual(scorer.describe_report(scorer.summarise_report([])),
                         "no embedding failures")


class TestBackoffDelay(unittest.TestCase):
    """Split out of `retry_with_backoff`; generation must wait exactly as before."""

    def test_it_grows_exponentially_and_is_capped(self):
        self.assertEqual(backoff_delay(0, "", 2.0, 60.0, jitter=False), 2.0)
        self.assertEqual(backoff_delay(3, "", 2.0, 60.0, jitter=False), 16.0)
        self.assertEqual(backoff_delay(10, "", 2.0, 60.0, jitter=False), 60.0)

    def test_an_asked_for_delay_is_a_floor(self):
        self.assertEqual(backoff_delay(0, "Please retry in 26.5s", 2.0, 60.0,
                                       jitter=False), 26.5)


class TestTwoVectorSpacesAreRefused(unittest.TestCase):

    def test_vectors_of_different_widths_are_not_compared(self):
        """They were `zip`ped, which truncated and returned a plausible number."""
        with self.assertRaises(scorer.DimensionMismatch):
            scorer._cosine_similarity([1.0] * 256, [1.0] * 768)

    def test_equal_widths_still_compare(self):
        self.assertAlmostEqual(scorer._cosine_similarity([1.0, 0.0], [1.0, 0.0]), 1.0)

    def test_a_mismatch_is_not_scored_and_is_reported_as_dimension(self):
        from tools.resume.resume_parser import ResumeParser

        parser = ResumeParser(str(PRIYA_TEX), skip_embeddings=True, user_id=None)
        exp = parser.parsed_resume.experiences[0]
        report = []
        with mock.patch.object(scorer, "_get_embedding", return_value=[1.0] * 768):
            score = scorer.score_job_with_embeddings(
                "a job", {exp.id: [1.0] * 256}, parser.parsed_resume,
                user_id=None, report=report)

        self.assertIsNone(score)
        self.assertEqual([e["kind"] for e in report], ["dimension"])


class TestTheScoreCarriesItsRawSimilarity(unittest.TestCase):
    """What `scripts/calibration_probe.py` reads to find the ceiling (Q51)."""

    def test_the_raw_blend_survives_the_clip(self):
        from tools.resume.resume_parser import ResumeParser

        parser = ResumeParser(str(PRIYA_TEX), skip_embeddings=True, user_id=None)
        vectors = {e.id: [1.0, 0.0] for e in parser.parsed_resume.experiences}
        with mock.patch.object(scorer, "_get_embedding", return_value=[1.0, 0.0]), \
                mock.patch.object(scorer, "active_backend",
                                  lambda: ("local", "m", 2)):
            score = scorer.score_job_with_embeddings(
                "a job", vectors, parser.parsed_resume, user_id=None)

        # cosine 1.0 against a local ceiling of 0.10: clipped to 100, raw kept.
        self.assertEqual(score.embedding_score, 100.0)
        self.assertEqual(score.raw_similarity, 1.0)


@unittest.skipIf(genai is None, "google-genai not installed")
class TestTheResumeCacheNamesTheModelThatWroteIt(unittest.TestCase):
    """
    It was labelled `config.EMBEDDING_MODEL` — Gemini — whichever backend ran,
    so the next Gemini run was served potion's vectors as its own.
    """

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        for patcher in (
            mock.patch.dict(os.environ, {paths.HOME_ENV: self._dir.name}),
            mock.patch.object(scorer, "_EMBEDDING_CACHES", {}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _parse(self, backend, model):
        from tools.resume.resume_parser import ResumeParser

        with mock.patch.object(scorer, "active_backend",
                               lambda: (backend, model, 2)):
            return ResumeParser(str(PRIYA_TEX), user_id=None)

    def test_a_local_run_does_not_hand_its_vectors_to_a_gemini_run(self):
        from tools.cache.embedding_cache import EmbeddingCache, cache_dir
        from tools.resume import local_embeddings

        with mock.patch.object(local_embeddings, "embed", return_value=[1.0, 0.0]):
            self._parse("local", "potion-test")

        saved = EmbeddingCache(cache_dir(None), model="potion-test").get(PRIYA_TEX)
        self.assertIsNotNone(saved, "the local run's vectors were filed under "
                                    "another model's name")

        calls = []
        with mock.patch.object(genai, "Client", _fake_client([[0.0, 1.0]], calls)):
            parser = self._parse("gemini", "gemini-test")

        self.assertGreater(len(calls), 0,
                           "the Gemini run was served the local run's vectors")
        self.assertTrue(all(v == [0.0, 1.0]
                            for v in parser.component_embeddings.values()))


class TestTheRunSaysWhatWentUnscored(unittest.TestCase):
    """The consumer, wired in the same change (the recurring bug in this repo)."""

    def _agent(self, report, mock_used, mock_requested):
        from agents.analysis_agent import AnalysisAgent

        agent = AnalysisAgent.__new__(AnalysisAgent)
        agent.resume_parser = mock.Mock(embedding_report=report,
                                        using_mock_embeddings=mock_used)
        agent.mock_requested = mock_requested
        return agent

    def test_the_summary_counts_and_classifies(self):
        report = [{"kind": "quota", "attempts": 5, "recovered": False}] * 3
        summary = self._agent(report, False, False).scoring_summary(3)

        self.assertEqual(summary["unscored"], 3)
        self.assertEqual(summary["embeddings"]["failed"], {"quota": 3})
        self.assertFalse(summary["mock"])

    def test_asked_for_mock_is_not_reported_as_a_fallback(self):
        self.assertFalse(self._agent([], True, True).scoring_summary(0)["mock"])
        self.assertTrue(self._agent([], True, False).scoring_summary(0)["mock"])

    def test_the_final_report_prints_the_reason(self):
        from agents.orchestrator import JobScoutOrchestrator

        orch = JobScoutOrchestrator.__new__(JobScoutOrchestrator)
        orch.state = {"scoring": self._agent(
            [{"kind": "quota", "attempts": 5, "recovered": False}] * 34, False, False,
        ).scoring_summary(34)}

        self.assertEqual(orch._scoring_lines(),
                         ["Jobs not scored: 34 (34 failed (34 quota))"])

    def test_a_clean_run_prints_nothing(self):
        from agents.orchestrator import JobScoutOrchestrator

        orch = JobScoutOrchestrator.__new__(JobScoutOrchestrator)
        orch.state = {"scoring": self._agent([], False, False).scoring_summary(0)}
        self.assertEqual(orch._scoring_lines(), [])
        orch.state = {}
        self.assertEqual(orch._scoring_lines(), [], "a run that never analysed")


class TestTheCalibrationProbe(unittest.TestCase):
    """`scripts/calibration_probe.py` reads the ceiling as a number (Q51)."""

    def setUp(self):
        from scripts import calibration_probe
        self.probe = calibration_probe

    def _row(self, raw, overall=50.0):
        return {"label": "x", "raw": raw, "embedding": 0.0, "overall": overall, "hits": 0}

    def test_it_counts_what_the_clip_hides(self):
        rows = [self._row(r, o) for r, o in
                [(0.02, 40), (0.06, 60), (0.11, 77.5), (0.14, 77.5), (0.20, 85)]]
        s = self.probe.summarise(rows, 0.00, 0.10)

        self.assertEqual(s["at_ceiling"], 3)
        self.assertAlmostEqual(s["share_at_ceiling"], 0.6)
        self.assertEqual((s["min"], s["max"]), (0.02, 0.20))
        self.assertAlmostEqual(s["median"], 0.11)
        self.assertEqual(s["top10_distinct_scores"], 4)

    def test_an_unscored_job_is_counted_not_averaged_in(self):
        s = self.probe.summarise([self._row(0.05), self._row(None)], 0.0, 0.10)
        self.assertEqual((s["scored"], s["unscored"]), (1, 1))
        self.assertEqual(s["min"], 0.05)

    def test_nothing_scored_reports_no_distribution(self):
        s = self.probe.summarise([self._row(None)], 0.0, 0.10)
        self.assertNotIn("min", s)
        self.assertEqual(s["unscored"], 1)

    def test_it_measures_the_production_window(self):
        """Its ceiling is the scorer's, not a copy that can drift."""
        floor, span = scorer.CALIBRATION["local"]
        s = self.probe.summarise([self._row(0.05)], floor, span)
        self.assertEqual(s["ceiling"], floor + span)

    def test_the_script_runs_end_to_end_on_a_stubbed_embedder(self):
        """Smoke: profile to printed distribution, in a data home of its own."""
        import contextlib
        import io
        import shutil

        from tools.resume import local_embeddings

        with tempfile.TemporaryDirectory() as home:
            for rel in ("user_profiles/priya_raghunathan.json",
                        "data/master_resumes/priya_raghunathan.tex"):
                (Path(home) / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(ROOT / rel, Path(home) / rel)

            out = io.StringIO()
            with mock.patch.dict(os.environ, {paths.HOME_ENV: home}), \
                    mock.patch.object(scorer, "EMBEDDING_BACKEND", "auto"), \
                    mock.patch.object(scorer, "_BACKEND", None), \
                    mock.patch.object(scorer, "_EMBEDDING_CACHES", {}), \
                    mock.patch.object(local_embeddings, "is_available", lambda: True), \
                    mock.patch.object(local_embeddings, "dimensions", lambda m: 2), \
                    mock.patch.object(local_embeddings, "embed",
                                      lambda text, m: [1.0, len(text) % 7 / 10]), \
                    contextlib.redirect_stdout(out):
                self.probe.main(["--input",
                                 str(ROOT / "tests/fixtures/acceptance_jobs.json")])

        text = out.getvalue()
        self.assertIn("at or above the ceiling", text)
        self.assertIn("fit on    raw 0.00 - 0.08", text)
        self.assertIn("7 in the input, 7 scored", text)


if __name__ == "__main__":
    unittest.main()

"""
A job scored under the bar is stored and labelled as that, never "Not scored" (R106).

Analysis scored every job it was given, then dropped the ones under
`scoring_threshold` before anything was written. The board then read
`score NULL` and said **"Not scored"** ("analysis has not scored it yet")
about a job analysis had scored 39.9 and set aside. That is a known value
shown as unknown: the codebase's invariant, pointed the other way from usual.

Now every score is stored with the bar it was judged against. Both UIs label
a job under its bar with its score and the reason no resume was written.
Discovery counts it as processed, so it no longer takes a slot in every run.
Match bands are computed over the jobs that met their bar, as before.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import tools.resume.embedding_scorer as scorer  # noqa: E402
from tools.jobs.job_store import JobStore  # noqa: E402
from tools.search.job_listing import JobListing  # noqa: E402


def listing(url):
    return JobListing(id=f"id_{url}", title="Engineer", company="ACME", location="Remote",
                      description="", apply_url=url, salary_min=None, salary_max=None,
                      created="", source="ats_greenhouse", full_jd="jd")


class _Store(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = JobStore(Path(self._tmp.name) / "jobs.db")
        self.addCleanup(self.store.close)


class TestTheStore(_Store):

    def test_a_score_under_its_bar_is_stored_with_the_bar(self):
        self.store.record([listing("u1")])
        self.store.set_score("u1", 39.9, bar=40)
        row = self.store.get("u1") if hasattr(self.store, "get") else None
        row = row or next(r for r in self.store.query(limit=10) if r["url"] == "u1")
        self.assertEqual((row["score"], row["bar"]), (39.9, 40.0))
        self.assertIsNotNone(row["scored_at"])

    def test_a_scored_job_under_its_bar_is_not_unprocessed(self):
        """It is not re-analysed in every run's slice any more."""
        self.store.record([listing("u1"), listing("u2")])
        self.store.set_score("u1", 12.0, bar=40)
        self.assertEqual(self.store.unprocessed_urls(), {"u2"})

    def test_bands_are_over_jobs_that_met_their_bar(self):
        urls = [f"u{i}" for i in range(12)]
        self.store.record([listing(u) for u in urls])
        for i, u in enumerate(urls[:10]):
            self.store.set_score(u, 50.0 + i, bar=40)          # met the bar
        self.store.set_score("u10", 5.0, bar=40)               # under it
        self.store.set_score("u11", 6.0, bar=40)
        bands_with = self.store.score_bands()

        self.assertGreaterEqual(bands_with["typical"], 50.0,
                                "a job set aside under its bar moved everyone's labels")
        self.assertEqual(bands_with["n"], 10)

    def test_a_row_scored_before_bars_is_still_banded(self):
        urls = [f"u{i}" for i in range(9)]
        self.store.record([listing(u) for u in urls])
        for i, u in enumerate(urls):
            self.store.set_score(u, 30.0 + i)                  # bar unknown
        self.assertTrue(self.store.score_bands())

    def test_selection_and_bar_together(self):
        self.store.record([listing("u1")])
        self.store.set_score("u1", 70.0, selection={"experiences": ["a"]}, bar=40)
        row = next(r for r in self.store.query(limit=10) if r["url"] == "u1")
        self.assertEqual(row["bar"], 40.0)
        self.assertIn("experiences", row["selection"])


class TestAnalysisKeepsWhatItSetsAside(unittest.TestCase):

    def test_a_job_under_the_threshold_is_kept_with_its_score(self):
        from agents.analysis_agent import AnalysisAgent

        agent = AnalysisAgent.__new__(AnalysisAgent)
        agent.mock_requested = False
        agent.profile = mock.Mock()
        agent.profile.agent_preferences.scoring_threshold = 40
        parser = mock.Mock(embedding_report=[], using_mock_embeddings=True)
        parser.score_job.return_value = scorer.EmbeddingScore(
            job_id="", title="", company="", overall_score=39.9,
            best_experience_ids=[], best_project_ids=[], experience_scores={},
            project_scores={})
        agent.resume_parser = parser

        job = {"title": "SWE", "company": "Samsara", "full_jd": "x", "apply_url": "u"}
        results = agent.analyze_jobs([job])

        self.assertEqual(results, [])
        self.assertEqual(agent.below_bar, [{"job": job, "score": 39.9}])


class TestTheRunStoresItAndSaysSo(_Store):

    def _orch(self):
        from agents.orchestrator import JobScoutOrchestrator
        orch = JobScoutOrchestrator.__new__(JobScoutOrchestrator)
        orch.profile = mock.Mock()
        orch.profile.agent_preferences.scoring_threshold = 40
        orch._update_store = lambda write, what: write(self.store)
        return orch

    def test_both_passing_and_set_aside_scores_are_written_with_the_bar(self):
        self.store.record([listing("pass"), listing("under")])
        self._orch()._store_scores(
            [{"job": {"apply_url": "pass"}, "score": {"overall": 71.0}}],
            [{"job": {"apply_url": "under"}, "score": 39.9}])
        rows = {r["url"]: r for r in self.store.query(limit=10)}
        self.assertEqual((rows["pass"]["score"], rows["pass"]["bar"]), (71.0, 40.0))
        self.assertEqual((rows["under"]["score"], rows["under"]["bar"]), (39.9, 40.0))

    def test_the_summary_counts_them(self):
        orch = self._orch()
        orch.state = {"below_bar": [{"url": "u", "score": 39.9}]}
        lines = orch._scoring_lines()
        self.assertEqual(len(lines), 1)
        self.assertIn("Below your bar of 40: 1 job(s)", lines[0])


class TestBothUIsLabelIt(unittest.TestCase):
    """Twin paths: the React badge and Streamlit's board row."""

    def test_the_react_badge_has_a_below_bar_state_before_banding(self):
        src = (ROOT / "web/src/components/MatchBadge.tsx").read_text(encoding="utf-8")
        self.assertIn("Below your bar", src)
        self.assertLess(src.index("Below your bar"), src.index("const tier = band("),
                        "the bar must decide before the quartile does")
        board = (ROOT / "web/src/components/Board.tsx").read_text(encoding="utf-8")
        self.assertIn("bar={job.bar}", board)

    def test_streamlit_labels_it(self):
        import ast
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        strings = " ".join(n.value for n in ast.walk(tree)
                           if isinstance(n, ast.Constant) and isinstance(n.value, str))
        self.assertIn("below your bar of", strings)


if __name__ == "__main__":
    unittest.main()

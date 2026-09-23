"""
The local window is refit with its script, its record and a guard (R99).

R36's window `(0.00, 0.10)` had no artifact, so when it turned out to be fit
on noise (R98) nobody could say how it had been made. Its replacement is held
to three things:

* the fit is reproducible from a committed rule, and refuses to be recorded
  from fewer than four profiles or when a held-out profile would not fit;
* the blind comparison shows no scores, since today's ties at 77.5 would say
  which list is which;
* every run counts the jobs the window clips, and the run summary says so —
  the event that tells the author the window has gone stale for a new kind of
  resume (Q53).
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import tools.resume.embedding_scorer as scorer  # noqa: E402
from scripts import calibration_probe as probe  # noqa: E402


def dump(profile, raws, hits=None, model="potion", sha="abc"):
    hits = hits or [2] * len(raws)
    return {"profile": profile, "backend": "local", "model": model, "dims": 256,
            "input_sha256": sha,
            "rows": [{"label": f"{profile}-{i}", "raw": r, "hits": h}
                     for i, (r, h) in enumerate(zip(raws, hits))]}


def spread(lo, hi, n=40):
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


class TestTheFit(unittest.TestCase):

    def test_the_window_is_the_pooled_range_plus_the_margin(self):
        self.assertEqual(probe.fit_window([0.10, 0.50]), (0.06, 0.54))

    def test_four_similar_profiles_fit_and_hold_out(self):
        dumps = [dump(n, spread(lo, hi)) for n, lo, hi in (
            ("yash", 0.2550, 0.5908), ("priya", 0.1994, 0.4864),
            ("rohan", 0.1213, 0.4436), ("real", 0.18, 0.52))]
        record = probe.fit(dumps)

        self.assertTrue(record["enough_profiles"])
        self.assertTrue(record["loo_pass"], record["profiles"])
        floor, ceiling = record["window"]
        self.assertLess(floor, 0.1213)
        self.assertGreater(ceiling, 0.5908)

    def test_a_profile_outside_the_others_fails_leave_one_out(self):
        """The event the guard reports in production, caught at fit time."""
        dumps = [dump(n, spread(0.20, 0.50)) for n in ("a", "b", "c")]
        dumps.append(dump("short", spread(0.02, 0.15)))
        record = probe.fit(dumps)

        held = {p["profile"]: p for p in record["profiles"]}
        self.assertFalse(held["short"]["loo_pass"])
        self.assertFalse(record["loo_pass"])

    def test_three_profiles_are_printed_but_never_recorded(self):
        dumps = [dump(n, spread(0.2, 0.5)) for n in ("a", "b", "c")]
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for d in dumps:
                paths.append(Path(tmp) / f"{d['profile']}.json")
                paths[-1].write_text(json.dumps(d), encoding="utf-8")
            target = Path(tmp) / "record.json"
            with mock.patch.object(probe, "_print"):
                probe.main(["fit", *map(str, paths), "--write", str(target)])
            self.assertFalse(target.exists(), "a three-profile fit was recorded")

    def test_dumps_from_different_models_or_jobs_are_refused(self):
        for a, b in ((dump("a", [0.2], model="m1"), dump("b", [0.2], model="m2")),
                     (dump("a", [0.2], sha="x"), dump("b", [0.2], sha="y"))):
            with tempfile.TemporaryDirectory() as tmp:
                paths = []
                for d in (a, b):
                    paths.append(Path(tmp) / f"{d['profile']}.json")
                    paths[-1].write_text(json.dumps(d), encoding="utf-8")
                with self.assertRaises(SystemExit):
                    probe.load_dumps(paths)

    def test_a_dump_carries_numbers_and_job_labels_only(self):
        """A private resume's dump must say nothing about the resume."""
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Path(tmp) / "jobs.json"
            jobs.write_text("[]", encoding="utf-8")
            out = Path(tmp) / "d.json"
            probe.write_dump(out, "real", ("local", "m", 256), jobs, [
                {"label": "Co - Role", "raw": 0.3, "embedding": 50.0,
                 "overall": 60.0, "hits": 3}])
            data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(set(data), {"profile", "backend", "model", "dims",
                                     "input_sha256", "rows"})
        self.assertEqual(set(data["rows"][0]), {"label", "raw", "hits"})


class TestTheBlindComparison(unittest.TestCase):

    def setUp(self):
        # Two jobs with equal keywords the old window ties; the fitted window
        # orders them by raw.
        self.dump = dump("p", [0.30, 0.45, 0.20], hits=[2, 2, 4])
        self.record = {"window": [0.10, 0.60], "input_sha256": "abc"}

    def test_the_sheet_shows_no_scores(self):
        sheet, _, _ = probe.blind_sheets([self.dump], self.record, seed=1)
        self.assertNotIn("77.5", sheet)
        self.assertNotRegex(sheet, r"\d+\.\d")

    def test_the_key_says_which_list_is_which(self):
        sheet, key, _ = probe.blind_sheets([self.dump], self.record, seed=1)
        lists = {}
        for line in sheet.splitlines():
            if line.strip() in ("List 1", "List 2"):
                current = line.strip()
                lists[current] = []
            elif line.strip()[:1].isdigit():
                lists[current].append(line.split(". ", 1)[1])
        today = lists[[k for k, v in key["p"].items() if v == "today"][0]]
        self.assertEqual(today[0], "p-2", "today is keyword order: 4 hits first")
        fitted = lists[[k for k, v in key["p"].items() if v == "fitted"][0]]
        # 0.7 x emb + 0.3 x kw: p-1 56.5, p-0 35.5, p-2 29.0
        self.assertEqual(fitted, ["p-1", "p-0", "p-2"])

    def test_today_is_the_void_window_not_whatever_calibration_now_says(self):
        self.assertEqual(probe.TODAY_WINDOW, (0.00, 0.10))

    def test_the_threshold_drops_are_jobs_40_kept_and_the_fit_would_not(self):
        _, _, drops = probe.blind_sheets([self.dump], self.record, seed=1)
        # p-0: raw 0.30 -> 40 emb -> 0.7*40 + 0.3*25 = 35.5, was 77.5
        self.assertIn("p-0", drops["p"])
        self.assertNotIn("p-1", drops["p"])


class TestTheGuard(unittest.TestCase):
    """Every run counts clipped jobs, and the run summary names them."""

    def _agent(self, raws, mock_scores=False):
        from agents.analysis_agent import AnalysisAgent

        agent = AnalysisAgent.__new__(AnalysisAgent)
        agent.mock_requested = False
        agent.profile = mock.Mock()
        agent.profile.agent_preferences.scoring_threshold = 101   # skip selection
        parser = mock.Mock(embedding_report=[], using_mock_embeddings=mock_scores)
        scores = iter(scorer.EmbeddingScore(
            job_id="", title="", company="", overall_score=50.0,
            best_experience_ids=[], best_project_ids=[], experience_scores={},
            project_scores={}, raw_similarity=r) for r in raws)
        parser.score_job.side_effect = lambda **kw: next(scores)
        agent.resume_parser = parser
        return agent

    def _run(self, agent, n):
        with mock.patch.object(scorer, "active_backend",
                               lambda: ("local", "potion-test", 256)), \
                mock.patch.object(scorer, "CALIBRATION",
                                  {"local": (0.10, 0.50), "gemini": (0.3, 0.6)}):
            agent.analyze_jobs([{"title": "t", "company": "c", "full_jd": "x"}] * n)
        return agent.scoring

    def test_clipped_jobs_are_counted_at_each_edge(self):
        window = self._run(self._agent([0.05, 0.30, 0.61, 0.70]), 4)["window"]
        self.assertEqual((window["scored"], window["at_floor"], window["at_ceiling"]),
                         (4, 1, 2))

    def test_the_run_summary_says_so(self):
        from agents.orchestrator import JobScoutOrchestrator

        orch = JobScoutOrchestrator.__new__(JobScoutOrchestrator)
        orch.state = {"scoring": self._run(self._agent([0.70] * 40), 40)}
        lines = orch._scoring_lines()
        self.assertEqual(len(lines), 1)
        self.assertIn("40 of 40 jobs at the ceiling", lines[0])
        self.assertIn("Q53", lines[0])

    def test_a_window_that_fits_says_nothing(self):
        from agents.orchestrator import JobScoutOrchestrator

        orch = JobScoutOrchestrator.__new__(JobScoutOrchestrator)
        orch.state = {"scoring": self._run(self._agent([0.2, 0.3, 0.4]), 3)}
        self.assertEqual(orch._scoring_lines(), [])

    def test_mock_scores_are_not_held_to_the_window(self):
        self.assertIsNone(self._run(self._agent([0.9], mock_scores=True), 1)["window"])

    def test_it_reads_the_window_production_normalises_with(self):
        with mock.patch.object(scorer, "active_backend", lambda: ("local", "m", 256)), \
                mock.patch.object(scorer, "CALIBRATION",
                                  {"local": (0.12, 0.48), "gemini": (0.3, 0.6)}):
            self.assertEqual(scorer.scoring_window(), (0.12, 0.60))
            self.assertEqual(scorer._normalise(0.12), 0.0)
            self.assertEqual(scorer._normalise(0.60), 100.0)


if __name__ == "__main__":
    unittest.main()

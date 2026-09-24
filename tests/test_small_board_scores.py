"""
A scored job on a small board shows its score, not "Not scored" (R121).

Found on the first live deploy: a new account's first run scored 4 jobs and
wrote a valid resume for one, and the React board said "Not scored" for all
of them. It was not the key. `score_bands` needs `MIN_FOR_BANDS` (8) scored
jobs before it will divide them into strong / typical / weak, and returns
nothing below that. `MatchBadge` asked for a band, got none, and fell
through to "Not scored", the label for a job analysis never looked at. The
keyless account on the same deploy had more than 8 scored jobs, so it had
bands.

The server half is checked here, through the hosted API: the rows carry
their scores and the bands are empty. The React half has no test runner, so
it is checked in source: the badge shows a known score before it considers
"Not scored".
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None


class _Listing:
    def __init__(self, url):
        self.id = self.apply_url = url
        self.title, self.company, self.location = "Engineer", "Twilio", "Remote"
        self.description, self.full_jd = "", "A posting."
        self.salary_min = self.salary_max = None
        self.created, self.source = "", "ats_greenhouse"


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestAFirstRunsBoard(unittest.TestCase):

    def setUp(self):
        from tests.signed_in import client, hosted, make_account
        from tools.jobs import job_store

        self._tmp = tempfile.TemporaryDirectory()
        self._env = hosted(self._tmp.name)
        self._env.__enter__()
        import api.main as main

        self.user = make_account("keyed@example.com")
        # What the live run left: four scored under a bar of 40, one of them
        # given a resume. Fewer than MIN_FOR_BANDS.
        store = job_store.JobStore(job_store.db_path(self.user))
        try:
            urls = [f"https://x.test/{i}" for i in range(4)]
            store.record([_Listing(u) for u in urls])
            for url, score in zip(urls, (78.0, 71.0, 66.0, 52.0)):
                store.set_score(url, score, bar=40)
        finally:
            store.close()
        self.assertLess(4, job_store.JobStore.MIN_FOR_BANDS)
        self.api = client(main.app, email="keyed@example.com")

    def tearDown(self):
        self._env.__exit__(None, None, None)
        self._tmp.cleanup()

    def test_the_rows_carry_their_scores_and_there_are_no_bands(self):
        rows = self.api.get("/api/board", params={"sort": "best"}).json()["jobs"]
        self.assertEqual(sorted(r["score"] for r in rows), [52.0, 66.0, 71.0, 78.0])
        self.assertEqual(self.api.get("/api/board/bands").json(), {})


class TestTheBadgeShowsAKnownScore(unittest.TestCase):

    def test_a_score_with_no_band_is_shown_before_not_scored_is_considered(self):
        source = (ROOT / "web/src/components/MatchBadge.tsx").read_text(
            encoding="utf-8")
        scored = source.index("if (!tier && score !== null && score !== undefined)")
        unscored = source.index("Not scored\n")
        self.assertLess(scored, unscored,
                        "a job with a score but no band reaches 'Not scored'")
        branch = source[scored:unscored]
        self.assertRegex(branch, r"Scored\s")
        self.assertIn("score.toFixed(0)", branch)

    def test_not_scored_is_left_only_for_a_missing_score(self):
        source = (ROOT / "web/src/components/MatchBadge.tsx").read_text(
            encoding="utf-8")
        # Every earlier return needs a score; so the one left is for none.
        self.assertTrue(re.search(r"if \(!tier\) \{\s*return \(", source))


if __name__ == "__main__":
    unittest.main()

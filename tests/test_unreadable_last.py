"""
Postings that could not be read sort below readable ones, and are counted (R131).

The GitHub new-grad list links to jobright.ai pages, which the scraper cannot
read. Those jobs reached the board with a snippet for a description, scored
on the snippet's keywords, and sat among the top rows while no resume could
be written for any of them. "best", the default sort, now puts them below
every readable job; `/api/board` says how many it moved. Nothing is deleted.

Built on the store's real gate verdicts, not hand-written ones, so a change
to the reason the gate gives for an unreadable body breaks this file rather
than silently un-sorting the board.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.jobs.job_filter import (  # noqa: E402
    UNDECIDABLE, UNREADABLE_REASON, gate_fingerprint, gate_verdict)
from tools.jobs.job_store import JobStore  # noqa: E402

# Long enough to count as read (`posting_facts.READABLE_MIN_CHARS`).
READABLE = "We build developer tools in Python and Go for small teams. " * 10
CLEARANCE = READABLE + "Must hold an active Top Secret security clearance."
SNIPPET = "Software Engineer, New Grad. Python."


class _Locations:
    countries = ["United States"]
    states_priority = []
    states_acceptable = []
    remote_ok = True


class _Prefs:
    seniority = ["new grad", "entry level", "junior"]
    exclude_keywords = []
    target_roles = []
    locations = _Locations()


class _Personal:
    # Clearance unanswered, so the clearance posting is undecidable for a
    # reason that is not readability.
    work_authorization = {"us_person": "yes", "needs_sponsorship": "no",
                          "holds_clearance": None}


class _Profile:
    job_preferences = _Prefs()
    personal_info = _Personal()


class _Listing:
    def __init__(self, url, jd):
        self.apply_url = url
        self.id = url
        self.title = "Software Engineer"
        self.company = "Example"
        self.location = "San Francisco, CA"
        self.source = "test"
        self.full_jd = jd


# url, description, score. The unreadable one scores highest: a snippet's
# keywords can, which is how these reached the top of the board.
ROWS = (
    ("u-unreadable", SNIPPET, 90.0),
    ("u-readable-high", READABLE, 70.0),
    ("u-unanswered", CLEARANCE, 60.0),
    ("u-readable-low", READABLE + "Entry level.", 40.0),
    ("u-unscored", READABLE + "Junior.", None),
)


def _fill(store):
    store.record([_Listing(url, jd) for url, jd, _ in ROWS])
    for url, _, score in ROWS:
        if score is not None:
            store.set_score(url, score)
    profile = _Profile()
    store.refresh_gate(gate_fingerprint(profile),
                       lambda r: gate_verdict(r, profile))


class TestTheStore(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self._dir.name) / "jobs.db")
        _fill(self.store)

    def tearDown(self):
        self.store.close()
        self._dir.cleanup()

    def test_the_rows_are_what_the_gate_says(self):
        """Preconditions: one unreadable, one undecidable for another reason."""
        unreadable = self.store.get("u-unreadable")
        self.assertEqual(unreadable["gate_verdict"], UNDECIDABLE)
        self.assertEqual(unreadable["gate_reason"], UNREADABLE_REASON)
        unanswered = self.store.get("u-unanswered")
        self.assertEqual(unanswered["gate_verdict"], UNDECIDABLE)
        self.assertNotEqual(unanswered["gate_reason"], UNREADABLE_REASON)

    def test_best_puts_the_unreadable_posting_last(self):
        order = [r["url"] for r in self.store.query(sort="best")]
        self.assertEqual(order, ["u-readable-high", "u-unanswered",
                                 "u-readable-low", "u-unscored",
                                 "u-unreadable"])

    def test_an_unknown_sort_falls_back_to_best_and_keeps_the_rule(self):
        order = [r["url"] for r in self.store.query(sort="nonsense")]
        self.assertEqual(order[-1], "u-unreadable")

    def test_a_page_is_cut_after_the_ordering(self):
        """In SQL, so the first page is the four readable jobs, not three."""
        first = [r["url"] for r in self.store.query(sort="best", limit=4)]
        self.assertNotIn("u-unreadable", first)
        self.assertEqual(len(first), 4)

    def test_an_explicit_ordering_keeps_its_meaning(self):
        """"newest" is newest; only the default moves unreadable jobs."""
        by_company = self.store.query(sort="company")
        self.assertEqual(by_company[0]["url"], "u-unreadable",
                         "company order is score-descending within a company")

    def test_nothing_is_removed(self):
        self.assertEqual(len(self.store.query(sort="best")), len(ROWS))

    def test_the_count_is_a_subset_of_unconfirmed(self):
        self.assertEqual(self.store.count(eligible=True, unreadable=True), 1)
        self.assertEqual(self.store.count(eligible=True, unconfirmed=True), 2)

    def test_an_unjudged_row_is_not_called_unreadable(self):
        """No gate has said so yet, so nothing is claimed (the invariant)."""
        self.store.record([_Listing("u-new", SNIPPET)])
        self.assertIsNone(self.store.get("u-new")["gate_verdict"])
        urls = {r["url"] for r in self.store.query(unreadable=True)}
        self.assertEqual(urls, {"u-unreadable"})


class TestTheRoute(unittest.TestCase):
    """`GET /api/board` carries the count, and its page is in the new order."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        env = mock.patch.dict(os.environ, {"JOBSCOUT_HOME": self._dir.name})
        env.start()
        self.addCleanup(env.stop)

        from tools.jobs.job_store import db_path
        store = JobStore(db_path(None))
        try:
            _fill(store)
        finally:
            store.close()

    def test_the_board_says_how_many_it_could_not_read(self):
        from fastapi.testclient import TestClient
        import api.main as main

        body = TestClient(main.app).get("/api/board").json()

        self.assertEqual(body["unreadable"], 1)
        self.assertEqual(body["unconfirmed"], 2)
        self.assertEqual(body["jobs"][-1]["url"], "u-unreadable")

    def test_the_count_follows_the_filters(self):
        from fastapi.testclient import TestClient
        import api.main as main

        body = TestClient(main.app).get(
            "/api/board", params={"search": "nobody"}).json()
        self.assertEqual(body["unreadable"], 0)


if __name__ == "__main__":
    unittest.main()

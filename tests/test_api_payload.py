"""
What crosses the network, and what must not.

The board's list rows carry every column the store holds, including `full_jd`
— the employer's own posting text. Rendered in-process by Streamlit that costs
nothing; sent to a browser it is **336 KB of a 50-row page, 87% of the
payload**, none of which the list draws.

Size is the cheap half of the argument. The other half is R60: under a hosted
tier, a client that receives job descriptions it never renders is a product
that *transmits* employers' prose rather than one that reads it to score. That
is a different thing to be, and it would have happened by omission — nobody
would have decided it. So it gets an assertion rather than a comment, and the
assertion is written against the field *set* rather than against `full_jd`,
because the way this regresses is somebody adding the next big column.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - fastapi is optional for the CLI
    TestClient = None


# Everything a board row may put on the wire. Adding to this list is a
# decision about what leaves the machine, which is why it is a list and not a
# denylist: a new column is excluded until someone says otherwise here.
ALLOWED_LIST_FIELDS = {
    "url", "job_id", "title", "company", "location", "source",
    "score", "status", "first_seen", "last_seen", "scored_at",
    "resume_tex", "resume_pdf", "run_date", "selection",
    "gate_reason", "gate_checked", "has_jd",
}

# Fields that exist on the row and are deliberately held back from lists.
WITHHELD_FROM_LISTS = {"full_jd"}


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestTheBoardPayload(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from api.main import app
        cls.client = TestClient(app)
        cls.rows = cls.client.get("/api/board?limit=50").json()["jobs"]
        if not cls.rows:
            raise unittest.SkipTest("needs a board with jobs in it")

    def test_no_list_row_carries_the_posting_text(self):
        leaked = sorted({field for row in self.rows
                         for field in row if field in WITHHELD_FROM_LISTS})
        self.assertEqual(
            leaked, [],
            f"the board list is shipping {leaked} to the browser; if that is "
            "intended, move it out of WITHHELD_FROM_LISTS and say why")

    def test_no_field_reaches_the_browser_unreviewed(self):
        """
        The regression path. `full_jd` is not special — it is just the biggest
        column so far. The next one gets caught by this rather than by a
        payload measurement nobody re-runs.
        """
        unexpected = sorted({field for row in self.rows
                             for field in row} - ALLOWED_LIST_FIELDS)
        self.assertEqual(
            unexpected, [],
            f"new field(s) on the wire: {unexpected}. Add them to "
            "ALLOWED_LIST_FIELDS deliberately, or keep them off the list.")

    def test_the_row_still_says_whether_a_description_exists(self):
        """
        Withholding the text may not become withholding the fact. Without
        `has_jd` the UI cannot tell "this posting has no description" from
        "the list does not send descriptions" — absence against unknown, the
        invariant in CLAUDE.md, one layer down.
        """
        for row in self.rows:
            self.assertIn("has_jd", row)
            self.assertIsInstance(row["has_jd"], bool)

    def test_the_detail_endpoint_does_serve_the_description(self):
        """Held back from lists, not unavailable — otherwise this is a feature cut."""
        with_jd = next((r for r in self.rows if r["has_jd"]), None)
        if with_jd is None:
            self.skipTest("no stored job has a description")
        detail = self.client.get("/api/job", params={"url": with_jd["url"]}).json()
        self.assertTrue(detail["job"].get("full_jd"))

    def test_a_page_stays_small_enough_to_be_worth_it(self):
        """
        The measurement, frozen. 50 rows were 336 KB and are now 45; this
        fails long before it drifts back, and names the number so the next
        reader does not have to re-derive it.
        """
        import json
        size = len(json.dumps(self.rows))
        self.assertLess(
            size, 120_000,
            f"a 50-row page is {size // 1024} KB — it was 45 KB when this was "
            "written and 336 KB before `full_jd` came off the list")


if __name__ == "__main__":
    unittest.main()

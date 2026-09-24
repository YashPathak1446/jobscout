"""
The undecidable verdict has a reader on both front ends (A4).

`id_problems` shipped with a producer and no reader: computed, sent over the
wire, rendered by nothing (6f2c27b). A verdict nobody draws is the same bug,
so this asserts the *render*, on each UI, for both halves — the per-row badge
and the count — rather than asserting that the data exists.

Streamlit is rendered for real with `AppTest` against a seeded store. The
React app has no test runner, so its half is source-level — `tsc` in
`npm run build` is what checks the types it declares, in the shape of `test_component_ids.py`; the API it
reads from is exercised for real.

One store, three verdicts, built against Priya — an H-1B holder who has not
said whether she holds a clearance:

    u-clean     a posting that asks nothing                    shown
    u-cleared   demands an active clearance                    undecidable
    u-thin      a one-line snippet                             undecidable
    u-citizens  restricted to US citizens                      hidden
"""

import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

PROFILE = "priya_raghunathan"
BODY = "We build developer tools in Python and Go for small teams. " * 10
POSTINGS = {
    "u-clean": BODY,
    "u-cleared": BODY + "You must hold an active TS/SCI clearance to start.",
    "u-thin": "Backend engineer, Python.",
    "u-citizens": BODY + "Applicants must be U.S. citizens due to ITAR.",
}


class _Listing:
    def __init__(self, url, jd):
        self.apply_url = url
        self.id = url
        self.title = f"Engineer {url}"
        self.company = "Example"
        self.location = "Boston, MA"
        self.source = "test"
        self.full_jd = jd


class _SeededHome(unittest.TestCase):
    """A JOBSCOUT_HOME with Priya's profile and a judged four-row board."""

    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        home = Path(self._home.name)
        self._env = mock.patch.dict(os.environ, {"JOBSCOUT_HOME": str(home)})
        self._env.start()

        profiles = home / "user_profiles"
        profiles.mkdir()
        shutil.copy(ROOT / "user_profiles" / f"{PROFILE}.json", profiles)

        from agents.orchestrator import refresh_board_gate
        from tools.jobs.job_store import JobStore, db_path

        store = JobStore(db_path(None))
        try:
            store.record([_Listing(u, jd) for u, jd in POSTINGS.items()])
            for url in POSTINGS:
                store.set_score(url, 60.0)
        finally:
            store.close()
        refresh_board_gate(None, PROFILE)

    def tearDown(self):
        self._env.stop()
        self._home.cleanup()


class TestTheSeedIsWhatTheseTestsClaim(_SeededHome):
    """Otherwise a render test passing proves nothing about the verdicts."""

    def test_the_verdicts(self):
        from tools.jobs.job_store import JobStore, db_path

        store = JobStore(db_path(None))
        try:
            verdicts = {r["url"]: r["gate_verdict"] for r in store.query()}
        finally:
            store.close()
        self.assertEqual(verdicts, {"u-clean": "shown", "u-cleared": "undecidable",
                                    "u-thin": "undecidable", "u-citizens": "hidden"})


try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover - streamlit is the app's own dependency
    AppTest = None


@unittest.skipIf(AppTest is None, "streamlit not installed")
class TestStreamlitDrawsIt(_SeededHome):

    def _board(self):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
        app.session_state["profile_name"] = PROFILE
        app.session_state["view"] = "board"
        app.run()
        self.assertFalse(app.exception, app.exception)
        return app

    def _text(self, app):
        return "\n".join(
            [e.value for e in app.caption] + [e.value for e in app.info]
            + [e.value for e in app.markdown])

    def test_the_count_renders(self):
        text = self._text(self._board())
        self.assertIn("2 of these job(s) are unconfirmed", text)

    def test_each_undecidable_row_carries_its_badge(self):
        captions = [e.value for e in self._board().caption]
        badges = [c for c in captions if c.startswith("❔ Unconfirmed")]
        self.assertEqual(len(badges), 2, captions)
        self.assertTrue(any("clearance" in b for b in badges), badges)
        self.assertTrue(any("could not be read" in b for b in badges), badges)

    def test_an_undecidable_row_is_not_told_it_is_ruled_out(self):
        """
        The trap this commit fixed: an undecidable row has a `gate_reason`,
        and the old row read any reason as "⛔ Rules you out".
        """
        captions = [e.value for e in self._board().caption]
        self.assertFalse([c for c in captions if c.startswith("⛔")], captions)

    def test_the_hidden_row_still_says_why_when_asked_for(self):
        app = self._board()
        app.checkbox[[c.label for c in app.checkbox].index(
            next(c.label for c in app.checkbox if "rule you out" in c.label))].check()
        app.run()
        captions = [e.value for e in app.caption]
        ruled_out = [c for c in captions if c.startswith("⛔ Rules you out")]
        self.assertEqual(len(ruled_out), 1, captions)
        self.assertIn("US citizens", ruled_out[0])


try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestTheApiCarriesIt(_SeededHome):
    """What the React board reads, exercised rather than read."""

    def setUp(self):
        super().setUp()
        from api.main import app
        self.client = TestClient(app)

    def test_the_count_is_on_the_page(self):
        page = self.client.get("/api/board").json()
        self.assertEqual(page["unconfirmed"], 2)
        self.assertEqual(page["hidden"], 1)
        self.assertEqual(page["total"], 3)

    def test_the_count_follows_the_filters(self):
        page = self.client.get("/api/board?search=u-thin").json()
        self.assertEqual(page["unconfirmed"], 1)

    def test_every_row_carries_its_verdict_and_reason(self):
        rows = {r["url"]: r for r in self.client.get("/api/board").json()["jobs"]}
        self.assertEqual(rows["u-cleared"]["gate_verdict"], "undecidable")
        self.assertIn("clearance", rows["u-cleared"]["gate_reason"])
        self.assertEqual(rows["u-clean"]["gate_verdict"], "shown")


class TestReactDrawsIt(unittest.TestCase):
    """
    Source-level: the React app has no runner. What it holds is the specific failure — a field the server sends
    and no component reads.
    """

    WEB = ROOT / "web" / "src" / "components"

    def _source(self, name):
        path = self.WEB / name
        if not path.is_file():
            self.skipTest(f"{name} is not in this checkout")
        return path.read_text(encoding="utf-8")

    def test_the_board_reads_the_count_and_renders_it(self):
        board = self._source("Board.tsx")
        self.assertIn("result.unconfirmed", board)
        self.assertIn("setUnconfirmed(", board)
        # Rendered, not just stored: the JSX tests and prints it. Less the
        # unreadable postings, which have a line of their own (R131).
        self.assertRegex(board, r"\{unconfirmed !== null &&\s+unreadable !== null &&"
                                r"\s+unconfirmed - unreadable > 0 &&")
        self.assertRegex(board, r"\$\{unconfirmed - unreadable\}")

    def test_the_board_reads_the_unreadable_count_and_renders_it(self):
        """R131: the default sort moves them down, so the screen says how many."""
        board = self._source("Board.tsx")
        self.assertIn("setUnreadable(result.unreadable)", board)
        self.assertRegex(board, r"\{unreadable !== null && unreadable > 0 &&")
        self.assertRegex(board, r"\$\{unreadable\}")

    def test_the_count_starts_unknown_not_zero(self):
        self.assertIn("useState<number | null>(null)", self._source("Board.tsx"))

    def test_every_row_renders_the_badge(self):
        board = self._source("Board.tsx")
        self.assertIn("<GateBadge job={job} />", board)
        self.assertIn("jobs.map(", board)

    def test_the_badge_branches_on_the_verdict_not_the_reason(self):
        badge = self._source("GateBadge.tsx")
        self.assertIn("verdict === 'undecidable'", badge)
        self.assertIn("verdict === 'hidden'", badge)
        self.assertNotRegex(badge, r"if \(\s*(?:job\.)?(?:gate_)?reason\b",
                            "a reason alone is not a verdict: undecidable "
                            "rows carry one too")


class TestTheTypesNameIt(unittest.TestCase):
    """
    The fields are declared, not read around (Q41).

    Until `lib/api.ts` was committed, `GateBadge` took any `object` and
    probed it with `'gate_verdict' in job`, and the board did the same for
    `unconfirmed`. That compiles against anything, so a renamed field would
    have rendered nothing with no error. Declared, `tsc` fails on a rename or
    a misspelt verdict — and this holds the declaration to what the server
    actually sends.
    """

    WEB = ROOT / "web" / "src"

    def _source(self, rel):
        path = self.WEB / rel
        if not path.is_file():
            self.skipTest(f"{rel} is not in this checkout")
        return path.read_text(encoding="utf-8")

    def test_job_declares_every_verdict_the_gate_can_write_and_null(self):
        from tools.jobs.job_filter import VERDICTS
        api = self._source("lib/api.ts")
        declared = re.search(r"^\s*gate_verdict:\s*([^\n]+)$", api, re.M)
        self.assertIsNotNone(declared, "Job does not declare gate_verdict")
        literals = set(re.findall(r"'([a-z]+)'", declared.group(1)))
        self.assertEqual(literals, set(VERDICTS))
        # NULL is a row no gate has judged — the store writes it, so the
        # type has to admit it, or the badge's "renders nothing" branch is
        # a case the compiler believes cannot happen.
        self.assertIn("null", declared.group(1))
        self.assertRegex(api, r"(?m)^\s*gate_reason:\s*string \| null$")

    def test_the_board_response_declares_the_count(self):
        self.assertRegex(self._source("lib/api.ts"),
                         r"(?m)^\s*unconfirmed:\s*number$")

    def test_nothing_reads_around_the_types_any_more(self):
        badge = self._source("components/GateBadge.tsx")
        board = self._source("components/Board.tsx")
        self.assertNotIn("'gate_verdict' in", badge)
        self.assertNotIn("'gate_reason' in", badge)
        self.assertNotIn("job: object", badge)
        self.assertNotIn("'unconfirmed' in", board)


if __name__ == "__main__":
    unittest.main()

"""
The board accumulates; the gates ran once (R62 / Q22).

Every gate this project has built — R54's experience floor, R55's country
check, R56's eligibility — runs between enrichment and analysis. That is right
for a pipeline, which is a pass over new work, and wrong for a board, which
accumulates. A gate shipped on Tuesday never saw a job scored on Monday.

Measured after R61's purge: of 69 scored jobs in the store, **26 (38%) would be
excluded by the gates as they stood** — and they held the entire top of the
board. Samsara's 8+ years role sat at 55.8 because it was scored before R54
existed.

So the verdict is stored per row and recomputed when it goes stale. What makes
it stale is not a date: it is a change to the gate's own code, or to the parts
of the profile the gate reads. Both are folded into one fingerprint, and the
fingerprint is *derived* rather than declared — a `GATE_VERSION` constant
somebody must remember to bump is the same shape as the field nobody read
(R31) and the flag nobody consulted (R61).
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.jobs.job_filter import gate_fingerprint, gate_reason  # noqa: E402
from tools.jobs.job_store import JobStore  # noqa: E402


class _Locations:
    def __init__(self, countries=("United States",)):
        self.countries = list(countries)
        self.states_priority = []
        self.states_acceptable = []
        self.remote_ok = True


class _Prefs:
    def __init__(self, seniority=("new grad", "entry level", "junior"),
                 countries=("United States",)):
        self.seniority = list(seniority)
        self.exclude_keywords = []
        self.target_roles = []
        self.locations = _Locations(countries)


class _Personal:
    def __init__(self, us_citizen=True, holds_security_clearance=False):
        self.us_citizen = us_citizen
        self.permanent_resident = False
        self.holds_security_clearance = holds_security_clearance


class _Profile:
    def __init__(self, seniority=("new grad", "entry level", "junior"),
                 countries=("United States",), **personal):
        self.job_preferences = _Prefs(seniority, countries)
        self.personal_info = _Personal(**personal)


def row(full_jd="", location="San Francisco, CA"):
    return {"url": "u", "full_jd": full_jd, "location": location}


class TestTheVerdict(unittest.TestCase):
    """What a stored row is judged on."""

    def test_a_clean_posting_passes(self):
        self.assertEqual(
            gate_reason(row("Great entry-level role, Python."), _Profile()), "")

    def test_the_experience_floor_still_applies(self):
        reason = gate_reason(row("Requires 8+ years of experience."), _Profile())
        self.assertIn("8+ years", reason)

    def test_the_country_gate_applies_to_a_stored_row(self):
        """
        R55 runs in discovery, against a `JobListing`. The board holds rows, so
        the check has to be reachable from one — otherwise a job scored before
        R55 keeps its place on the board forever.
        """
        reason = gate_reason(row(location="Sao Paulo, BR"), _Profile())
        self.assertIn("Brazil", reason)

    def test_a_clearance_requirement_applies(self):
        reason = gate_reason(
            row("Candidates will not be considered who do not hold an active "
                "TS/SCI clearance."), _Profile())
        self.assertIn("clearance", reason)

    def test_an_empty_row_has_no_opinion(self):
        self.assertEqual(gate_reason(row(), _Profile()), "")

    def test_the_profile_decides(self):
        """The same posting, two profiles, two verdicts."""
        posting = row("Requires 8+ years of experience.")
        self.assertTrue(gate_reason(posting, _Profile()))
        self.assertEqual(gate_reason(posting, _Profile(seniority=("staff",))), "")


class TestTheFingerprint(unittest.TestCase):
    """Stale means the code changed or the profile did."""

    def test_it_is_stable_for_the_same_inputs(self):
        self.assertEqual(gate_fingerprint(_Profile()),
                         gate_fingerprint(_Profile()))

    def test_changing_the_seniority_range_changes_it(self):
        self.assertNotEqual(gate_fingerprint(_Profile()),
                            gate_fingerprint(_Profile(seniority=("senior",))))

    def test_changing_preferred_countries_changes_it(self):
        self.assertNotEqual(gate_fingerprint(_Profile()),
                            gate_fingerprint(_Profile(countries=("Canada",))))

    def test_gaining_a_clearance_changes_it(self):
        self.assertNotEqual(
            gate_fingerprint(_Profile()),
            gate_fingerprint(_Profile(holds_security_clearance=True)))

    def test_changing_citizenship_changes_it(self):
        self.assertNotEqual(gate_fingerprint(_Profile()),
                            gate_fingerprint(_Profile(us_citizen=False)))

    def test_it_covers_the_gate_source_too(self):
        """
        The half a hand-maintained constant would miss. If this ever stops
        being true, editing a gate silently leaves every stored verdict wrong.
        """
        import tools.jobs.job_filter as module

        original = module._gate_source
        try:
            module._gate_source = lambda: "different source"
            changed = gate_fingerprint(_Profile())
        finally:
            module._gate_source = original
        self.assertNotEqual(changed, gate_fingerprint(_Profile()))

    def test_a_profile_missing_fields_does_not_raise(self):
        gate_fingerprint(object())


class TestRefreshingTheStore(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.dir.name) / "jobs.db")

        class _Listing:
            def __init__(self, url, title, jd):
                self.apply_url = url
                self.id = url
                self.title = title
                self.company = "Example"
                self.location = "San Francisco, CA"
                self.source = "test"
                self.full_jd = jd

        self.store.record([
            _Listing("u-ok", "Engineer I", "An entry-level role in Python."),
            _Listing("u-bad", "Engineer", "Requires 8+ years of experience."),
        ])
        for url in ("u-ok", "u-bad"):
            self.store.set_score(url, 55.0)

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def _refresh(self, profile=None):
        profile = profile or _Profile()
        return self.store.refresh_gate(
            gate_fingerprint(profile), lambda r: gate_reason(r, profile))

    def test_the_first_pass_judges_everything(self):
        self.assertEqual(self._refresh(), 2)

    def test_a_second_pass_judges_nothing(self):
        """What makes it cheap enough to call before every render."""
        self._refresh()
        self.assertEqual(self._refresh(), 0)

    def test_a_changed_profile_makes_every_row_stale_again(self):
        self._refresh()
        self.assertEqual(self._refresh(_Profile(seniority=("staff",))), 2)

    def test_the_verdict_is_stored(self):
        self._refresh()
        self.assertEqual(self.store.get("u-ok")["gate_reason"], "")
        self.assertIn("8+ years", self.store.get("u-bad")["gate_reason"])

    def test_a_verdict_can_be_reversed_by_the_profile(self):
        self._refresh()
        self._refresh(_Profile(seniority=("staff",)))
        self.assertEqual(self.store.get("u-bad")["gate_reason"], "")


class TestTheBoardFilter(unittest.TestCase):
    """
    Filtered in SQL, not after the fact.

    Filtering a page the database already sliced turns a page of twenty into a
    page of twelve, and the board is paged.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.dir.name) / "jobs.db")

        class _Listing:
            def __init__(self, url, jd):
                self.apply_url = url
                self.id = url
                self.title = "Engineer"
                self.company = "Example"
                self.location = "San Francisco, CA"
                self.source = "test"
                self.full_jd = jd

        self.store.record([
            _Listing("u-ok", "An entry-level role."),
            _Listing("u-bad", "Requires 8+ years of experience."),
        ])
        for url in ("u-ok", "u-bad"):
            self.store.set_score(url, 55.0)

        profile = _Profile()
        self.store.refresh_gate(gate_fingerprint(profile),
                                lambda r: gate_reason(r, profile))

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def test_eligible_only(self):
        urls = {r["url"] for r in self.store.query(eligible=True)}
        self.assertEqual(urls, {"u-ok"})

    def test_ineligible_only(self):
        urls = {r["url"] for r in self.store.query(eligible=False)}
        self.assertEqual(urls, {"u-bad"})

    def test_no_filter_returns_both(self):
        self.assertEqual(len(self.store.query()), 2)

    def test_the_count_agrees_with_the_rows(self):
        self.assertEqual(self.store.count(eligible=True),
                         len(self.store.query(eligible=True)))

    def test_an_unjudged_row_counts_as_eligible(self):
        """
        An unrun gate must not empty the board. A row with no verdict is shown,
        which is how the board behaved before any of this existed.
        """
        class _New:
            apply_url = "u-new"
            id = "u-new"
            title = "Engineer"
            company = "Example"
            location = "Remote"
            source = "test"
            full_jd = "Requires 8+ years of experience."

        self.store.record([_New()])
        urls = {r["url"] for r in self.store.query(eligible=True)}
        self.assertIn("u-new", urls)


class TestAgainstTheRealStore(unittest.TestCase):
    """Skipped on a clean clone."""

    def test_the_gate_hides_some_of_the_board_but_not_most_of_it(self):
        if not (ROOT / "data" / "jobs.db").exists():
            self.skipTest("needs a real job store")
        if not (ROOT / "user_profiles" / "yash_pathak.json").exists():
            self.skipTest("needs a real profile")

        from agents.orchestrator import board_total, refresh_board_gate

        refresh_board_gate("yash_pathak")
        shown = board_total()
        everything = board_total(include_ineligible=True)

        self.assertLess(shown, everything, "the gate hides nothing at all")
        self.assertGreater(shown, everything / 3,
                           "the gate hides most of the board — too aggressive")


if __name__ == "__main__":
    unittest.main()

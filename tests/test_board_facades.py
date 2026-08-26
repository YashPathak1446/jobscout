"""
What the board screen stands on (R40).

R33 decided the app is a job board you live in rather than a run log, and R35
built the store underneath it. The screen reaches that store through facades
on the orchestrator, because `test_ui_contract` forbids the view layer from
importing `tools/` — so these facades are the whole width of the board's
access to its own data. If one of them changes shape, the board breaks with
no other test noticing.

The nested-merge tests are here for a sharper reason: the preferences screen
saved two of `locations`' seven fields and the merge replaced the section
wholesale, dropping `countries`, which the schema requires. Walking the wizard
left a profile that would not load. That is a form destroying data it never
showed the user (R30's shape), and it is the kind of bug only a test at this
boundary catches.
"""

import json
import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from agents.orchestrator import (  # noqa: E402
    backend_status,
    board_jobs,
    board_stats,
    job_statuses,
    seniority_levels,
    set_job_status,
)
from scripts.init_profile import read_preferences, update_profile_fields  # noqa: E402
from tools.jobs.job_store import JobStore  # noqa: E402

TEMPLATE = ROOT / "user_profiles" / "template.json"
TEMP = ROOT / "user_profiles" / "_board_test.json"


class _Listing:
    """The duck the store records: anything carrying these attributes."""

    def __init__(self, url, title="Engineer", company="Acme"):
        self.apply_url = url
        self.id = url
        self.title = title
        self.company = company
        self.location = "Remote"
        self.source = "test"
        self.full_jd = "a job"


class TestProfileMergeKeepsWhatTheFormNeverShowed(unittest.TestCase):
    """The wizard must not be able to break a profile by being walked."""

    def setUp(self):
        shutil.copy2(TEMPLATE, TEMP)

    def tearDown(self):
        TEMP.unlink(missing_ok=True)

    def _profile(self):
        return json.loads(TEMP.read_text(encoding="utf-8"))

    def test_saving_two_location_fields_keeps_the_other_five(self):
        update_profile_fields("_board_test", {
            "job_preferences": {"locations": {"cities": ["Irvine"], "remote_ok": False}},
        })
        locations = self._profile()["job_preferences"]["locations"]

        self.assertEqual(locations["cities"], ["Irvine"])
        self.assertFalse(locations["remote_ok"])
        # The required field the old merge dropped, plus the one discovery and
        # the filter actually read.
        self.assertEqual(locations["countries"], ["United States"])
        self.assertTrue(locations["states_priority"])

    def test_the_profile_still_loads_after_the_preferences_screen_saves(self):
        """The failure this fixes: a wizard step leaving an unloadable profile."""
        from tools.profile import load_profile

        update_profile_fields("_board_test", {
            "job_preferences": {
                "target_roles": ["Backend Engineer"],
                "seniority": ["mid"],
                "locations": {"cities": ["Austin"], "remote_ok": True},
            },
        })
        profile = load_profile("_board_test")
        self.assertEqual(profile.job_preferences.seniority, ["mid"])
        self.assertEqual(profile.job_preferences.locations.countries, ["United States"])

    def test_a_list_still_replaces_rather_than_merges(self):
        """Lists replace. Merging two lists would be a guess about intent."""
        update_profile_fields("_board_test", {
            "job_preferences": {"target_roles": ["ML Engineer"]},
        })
        self.assertEqual(
            self._profile()["job_preferences"]["target_roles"], ["ML Engineer"])

    def test_read_preferences_returns_what_the_form_needs(self):
        prefs = read_preferences("_board_test")
        self.assertEqual(
            set(prefs),
            {"target_roles", "seniority", "exclude_keywords", "cities",
             "remote_ok",
             # Added by R52, when the form learned to set the rest of
             # `locations` rather than only preserve it.
             "countries", "states_priority", "states_acceptable",
             "willing_to_relocate",
             # Added by R68, when the form started asking how long someone has
             # worked instead of asking them to pick their own seniority band.
             "years_experience"})
        self.assertIsInstance(prefs["remote_ok"], bool)

    def test_read_preferences_round_trips_a_save(self):
        """A form that cannot read what it wrote will revert it on the next save."""
        update_profile_fields("_board_test", {
            "job_preferences": {"seniority": ["senior", "staff"]},
        })
        self.assertEqual(read_preferences("_board_test")["seniority"],
                         ["senior", "staff"])


class TestBoardFacades(unittest.TestCase):
    """The board's read and write paths, against a store of its own."""

    def setUp(self):
        self.db = ROOT / "data" / "_board_test.db"
        self.db.unlink(missing_ok=True)

        store = JobStore(self.db)
        store.record([_Listing("https://x.test/1", "Engineer I"),
                      _Listing("https://x.test/2", "Engineer II")])
        store.set_score("https://x.test/1", 71.0)
        store.attach_resume("https://x.test/1", tex_path="a.tex", pdf_path="a.pdf")
        store.close()

        # The facades open the default store; point that at the test one so
        # running the suite never touches the user's real board.
        import tools.jobs.job_store as job_store
        self._real_default = job_store.DEFAULT_DB
        job_store.DEFAULT_DB = self.db

    def tearDown(self):
        import tools.jobs.job_store as job_store
        job_store.DEFAULT_DB = self._real_default
        self.db.unlink(missing_ok=True)

    def test_board_jobs_returns_rows_the_screen_can_render(self):
        rows = board_jobs()
        self.assertEqual(len(rows), 2)
        for field in ("url", "title", "company", "score", "status", "resume_tex"):
            self.assertIn(field, rows[0], f"the board renders {field}")

    def test_scored_jobs_come_before_unscored(self):
        """An unscored job is unknown, not bad; it must not sort as a zero."""
        rows = board_jobs()
        self.assertEqual(rows[0]["url"], "https://x.test/1")
        self.assertIsNone(rows[-1]["score"])

    def test_filters_reach_the_store(self):
        self.assertEqual(len(board_jobs(min_score=50)), 1)
        self.assertEqual(len(board_jobs(has_resume=True)), 1)
        self.assertEqual(len(board_jobs(status="new")), 2)
        self.assertEqual(len(board_jobs(status=["applied"])), 0)

    def test_setting_a_status_persists(self):
        set_job_status("https://x.test/1", "applied")
        self.assertEqual(board_jobs(status="applied")[0]["url"], "https://x.test/1")

    def test_a_status_the_ui_cannot_produce_is_refused(self):
        with self.assertRaises(ValueError):
            set_job_status("https://x.test/1", "interviewing")

    def test_stats_carry_the_headline_numbers(self):
        stats = board_stats()
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["scored"], 1)
        self.assertEqual(stats["with_resume"], 1)
        self.assertEqual(stats["by_status"]["new"], 2)

    def test_every_status_the_facade_offers_is_one_the_store_accepts(self):
        """The board renders a picker from this list; each must be settable."""
        for status in job_statuses():
            set_job_status("https://x.test/2", status)
        self.assertEqual(board_jobs(status=job_statuses()[-1])[0]["url"],
                         "https://x.test/2")


class TestPersonalRoundTrip(unittest.TestCase):

    def setUp(self):
        shutil.copy2(TEMPLATE, TEMP)

    def tearDown(self):
        TEMP.unlink(missing_ok=True)

    def test_read_personal_round_trips_a_save(self):
        from scripts.init_profile import read_personal

        update_profile_fields("_board_test", {
            "personal_info": {"location": "Austin, TX", "visa_status": "F1 OPT"},
        })
        stored = read_personal("_board_test")
        self.assertEqual(stored["location"], "Austin, TX")
        self.assertEqual(stored["visa_status"], "F1 OPT")

    def test_saving_two_personal_fields_keeps_the_name(self):
        """personal_info carries derived fields no form shows (R16)."""
        before = json.loads(TEMP.read_text(encoding="utf-8"))["personal_info"]
        update_profile_fields("_board_test", {
            "personal_info": {"location": "Austin, TX"},
        })
        after = json.loads(TEMP.read_text(encoding="utf-8"))["personal_info"]
        self.assertEqual(after.get("name"), before.get("name"))
        self.assertEqual(set(before) - set(after), set(), "no field was dropped")


class TestMarkdownSafety(unittest.TestCase):
    """
    A job title is other people's HTML, rendered inside `**...**`.

    One real posting in the store ends in a space, which breaks the closing
    delimiter, so the board printed its own asterisks. Found by looking at the
    running app, which is the only place it could have been found.
    """

    def setUp(self):
        import app
        self.plain = app._plain

    def test_a_trailing_space_cannot_break_bolding(self):
        self.assertEqual(
            self.plain("Software Engineer II, Backend (Furnishing Platform) "),
            "Software Engineer II, Backend (Furnishing Platform)")

    def test_markdown_characters_in_a_title_are_escaped(self):
        self.assertEqual(self.plain("C** Dev_Ops"), r"C\*\* Dev\_Ops")

    def test_missing_text_is_empty_rather_than_none(self):
        self.assertEqual(self.plain(None), "")


class TestChoiceFacades(unittest.TestCase):

    def test_seniority_levels_are_ordered_entry_first(self):
        levels = seniority_levels()
        self.assertEqual(levels[0], "new grad")
        self.assertIn("senior", levels)
        self.assertLess(levels.index("junior"), levels.index("senior"))

    def test_backend_status_reports_a_rung_and_a_line_to_show(self):
        status = backend_status("a-key")
        self.assertEqual(status["backend"], "gemini")
        self.assertTrue(status["description"])
        self.assertTrue(status["available"]["gemini"])

    def test_the_floor_needs_nothing(self):
        """R37's point: no key, no Ollama, still a usable run."""
        import config
        import tools.generation.llm_backends as backends

        saved = (backends.ollama_is_running, backends.env_openai_key,
                 config.resolve_api_key)
        backends.ollama_is_running = lambda url: False
        backends.env_openai_key = lambda: ""
        config.resolve_api_key = lambda explicit=None: explicit or ""
        try:
            status = backend_status("")
        finally:
            (backends.ollama_is_running, backends.env_openai_key,
             config.resolve_api_key) = saved

        self.assertEqual(status["backend"], "none")
        self.assertTrue(status["available"]["none"], "the floor is always reachable")


if __name__ == "__main__":
    unittest.main()


class TestTheRestOfTheLocationFields(unittest.TestCase):
    """
    R52: countries, state priorities and relocation.

    Discovery searches the first priority state by name and the filter scores
    every posting against these, so they were never inert — just unreachable
    without opening the JSON. R40 stopped the form destroying them; this is
    the half that lets someone set them.
    """

    def setUp(self):
        shutil.copy2(TEMPLATE, TEMP)

    def tearDown(self):
        TEMP.unlink(missing_ok=True)

    def test_read_preferences_now_offers_them(self):
        prefs = read_preferences("_board_test")
        for field in ("countries", "states_priority", "states_acceptable",
                      "willing_to_relocate"):
            self.assertIn(field, prefs)

    def test_they_round_trip(self):
        update_profile_fields("_board_test", {"job_preferences": {"locations": {
            "countries": ["United States", "Canada"],
            "states_priority": ["California"],
            "willing_to_relocate": False,
        }}})
        prefs = read_preferences("_board_test")

        self.assertEqual(prefs["countries"], ["United States", "Canada"])
        self.assertEqual(prefs["states_priority"], ["California"])
        self.assertFalse(prefs["willing_to_relocate"])

    def test_the_profile_still_validates(self):
        from tools.profile import load_profile

        update_profile_fields("_board_test", {"job_preferences": {"locations": {
            "countries": ["Canada"], "states_priority": [],
            "states_acceptable": [], "willing_to_relocate": False,
        }}})
        profile = load_profile("_board_test")
        self.assertEqual(profile.job_preferences.locations.countries, ["Canada"])

    def test_relocation_false_is_not_read_as_missing(self):
        """`bool(...)` on a stored False must survive the read."""
        update_profile_fields("_board_test", {"job_preferences": {
            "locations": {"willing_to_relocate": False}}})
        self.assertFalse(read_preferences("_board_test")["willing_to_relocate"])

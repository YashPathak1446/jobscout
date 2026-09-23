"""
A remote posting passes a country whitelist without its country being read (Q55).

A US-only profile was shown "Argentina Remote" and "Remote - Ireland" on its
board. Two defects, stacked:

1. `parse_location` returned early from any remote string with
   `country=None`, so Argentina, Ireland and the United States all parsed to
   the same value.
2. `evaluate` accepted a remote job before either country list was consulted.

And a third under the first: R68's guard struck `AR` from the country codes
because it is Arkansas, and the loop that makes every country recognisable by
name read the filtered map, so "Argentina" stopped being a country by name.

The fix carries three states, not a flipped default. A remote posting that
names a country is judged on it; one that names none is unknown — kept,
ranked as unclear, badged on the board, never silently eligible.

**The strings below are not a live capture.** The sandbox these tests were
written in could not reach the ATS APIs. The first two were seen on a real
board; the rest are common board formats written here, which is the "fixture
you wrote agrees with you" trap. Add real strings as they are seen.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.jobs.job_filter import (  # noqa: E402
    HIDDEN, SHOWN, UNDECIDABLE, UNREADABLE_REASON, REMOTE_UNKNOWN_REASON,
    evaluate, gate_verdict)
from tools.jobs.location_matcher import parse_location  # noqa: E402

US = "United States"


class _Locations:
    def __init__(self, countries=(US,), exclude=(), remote_ok=True):
        self.countries = list(countries)
        self.exclude_countries = list(exclude)
        self.states_priority = []
        self.states_acceptable = []
        self.cities = []
        self.remote_ok = remote_ok
        self.willing_to_relocate = True


class _Prefs:
    def __init__(self, locations):
        self.locations = locations
        self.seniority = ["mid level", "senior"]
        self.years_experience = 6
        self.exclude_keywords = []
        self.target_roles = ["Software Engineer"]


class _Personal:
    work_authorization = {"us_person": "yes", "needs_sponsorship": "no",
                          "holds_clearance": "no"}


class _Profile:
    def __init__(self, **kwargs):
        self.job_preferences = _Prefs(_Locations(**kwargs))
        self.personal_info = _Personal()


class _Job:
    def __init__(self, location):
        self.title = "Software Engineer"
        self.company = "Example"
        self.location = location
        self.description = ""


# Long enough to count as read (`posting_facts.READABLE_MIN_CHARS`).
READABLE = "We build developer tools in Python and Go for small teams. " * 10


def row(location, full_jd=READABLE):
    return {"url": "u", "full_jd": full_jd, "location": location}


class TestTheParseKeepsTheCountry(unittest.TestCase):

    def test_the_two_postings_that_were_seen(self):
        self.assertEqual(parse_location("Argentina Remote").country, "Argentina")
        self.assertEqual(parse_location("Remote - Ireland").country, "Ireland")

    def test_both_are_still_remote(self):
        self.assertTrue(parse_location("Argentina Remote").is_remote)
        self.assertTrue(parse_location("Remote - Ireland").is_remote)

    def test_the_united_states_written_the_ways_boards_write_it(self):
        for raw in ("Remote - US", "Remote (US)", "US Remote", "Remote, US",
                    "Remote-US", "US-Remote", "Remote - USA", "Remote - U.S.",
                    "Remote - US Only", "Remote - United States"):
            with self.subTest(raw=raw):
                self.assertEqual(parse_location(raw).country, US)

    def test_a_bare_remote_names_no_country(self):
        for raw in ("Remote", "Fully Remote", "Anywhere", "Remote - Worldwide"):
            with self.subTest(raw=raw):
                parsed = parse_location(raw)
                self.assertIsNone(parsed.country)
                self.assertEqual(parsed.countries, ())

    def test_several_countries_are_all_kept(self):
        """Taking the first would turn "US or Canada" into Canada."""
        for raw in ("Remote - US or Canada", "Remote (US, Canada)",
                    "US/Canada Remote", "Remote, US; Remote, Canada"):
            with self.subTest(raw=raw):
                parsed = parse_location(raw)
                self.assertIsNone(parsed.country)
                self.assertEqual(set(parsed.countries), {US, "Canada"})

    def test_a_state_keeps_city_and_state_together(self):
        """Dublin is an Irish indicator; "Dublin, Ohio" is one place."""
        parsed = parse_location("Remote - Dublin, Ohio")
        self.assertEqual(parsed.country, US)
        self.assertEqual(parsed.state, "Ohio")
        self.assertEqual(parsed.countries, ())

    def test_us_is_a_token_not_a_substring(self):
        """"us" is inside Austin, Houston, Brussels and Russia."""
        self.assertEqual(parse_location("Remote - Austin, TX").state, "Texas")
        for raw in ("Remote - Brussels", "Remote - Russia"):
            with self.subTest(raw=raw):
                self.assertNotEqual(parse_location(raw).country, US)

    def test_latin_america_is_not_the_united_states(self):
        for raw in ("Remote - Latin America", "Latin America",
                    "Remote - South America", "Remote - Americas"):
            with self.subTest(raw=raw):
                self.assertNotEqual(parse_location(raw).country, US)


class TestTheNamesTheCodeGuardDropped(unittest.TestCase):
    """AR, CO and MA are ambiguous codes. Argentina, Colombia and Morocco are not."""

    def test_the_countries_are_back_by_name(self):
        self.assertEqual(parse_location("Buenos Aires, Argentina").country,
                         "Argentina")
        self.assertEqual(parse_location("Bogota, Colombia").country, "Colombia")
        self.assertEqual(parse_location("Casablanca, Morocco").country, "Morocco")

    def test_the_codes_are_still_states(self):
        self.assertEqual(parse_location("Little Rock, AR").state, "Arkansas")
        self.assertEqual(parse_location("Denver, CO").state, "Colorado")
        self.assertEqual(parse_location("Boston, MA").state, "Massachusetts")


class TestDiscovery(unittest.TestCase):
    """`evaluate`: the per-run gate."""

    def test_a_remote_job_abroad_is_excluded(self):
        for raw in ("Argentina Remote", "Remote - Ireland"):
            with self.subTest(raw=raw):
                decision = evaluate(_Job(raw), _Profile())
                self.assertTrue(decision.exclude)
                self.assertIn("not in preferred countries", decision.reason)

    def test_a_remote_job_at_home_ranks_as_before(self):
        decision = evaluate(_Job("Remote - US"), _Profile())
        self.assertFalse(decision.exclude)
        self.assertEqual(decision.location_score, 3)

    def test_a_bare_remote_is_kept_but_not_ranked_as_a_match(self):
        """Unknown is not no, and it is not yes either."""
        decision = evaluate(_Job("Remote"), _Profile())
        self.assertFalse(decision.exclude)
        self.assertEqual(decision.location_score, -1)
        self.assertIn("Remote, country not stated", decision.reasons)

    def test_one_acceptable_country_of_several_is_enough(self):
        decision = evaluate(_Job("Remote - US or Canada"), _Profile())
        self.assertFalse(decision.exclude)
        self.assertEqual(decision.location_score, 3)

    def test_several_countries_none_acceptable_is_out(self):
        self.assertTrue(
            evaluate(_Job("Remote - UK or Ireland"), _Profile()).exclude)

    def test_the_blacklist_reaches_remote_jobs(self):
        profile = _Profile(countries=[], exclude=["Ireland"])
        self.assertTrue(evaluate(_Job("Remote - Ireland"), profile).exclude)

    def test_no_whitelist_means_no_question(self):
        """A profile naming no countries has not asked where."""
        decision = evaluate(_Job("Remote"), _Profile(countries=[]))
        self.assertFalse(decision.exclude)
        self.assertEqual(decision.location_score, 3)

    def test_remote_not_preferred_is_unchanged(self):
        decision = evaluate(_Job("Remote - US"), _Profile(remote_ok=False))
        self.assertFalse(decision.exclude)
        self.assertEqual(decision.location_score, 0)


class TestTheBoard(unittest.TestCase):
    """`gate_verdict`: the per-row gate, over what the store already holds."""

    def test_a_remote_job_abroad_is_hidden(self):
        for raw in ("Argentina Remote", "Remote - Ireland"):
            with self.subTest(raw=raw):
                self.assertEqual(gate_verdict(row(raw), _Profile()).state, HIDDEN)

    def test_a_bare_remote_is_undecidable_with_a_reason(self):
        verdict = gate_verdict(row("Remote"), _Profile())
        self.assertEqual(verdict.state, UNDECIDABLE)
        self.assertEqual(verdict.reason, REMOTE_UNKNOWN_REASON)

    def test_a_remote_job_at_home_is_shown(self):
        for raw in ("Remote - US", "Remote - US or Canada"):
            with self.subTest(raw=raw):
                self.assertEqual(gate_verdict(row(raw), _Profile()).state, SHOWN)

    def test_no_whitelist_shows_a_bare_remote(self):
        self.assertEqual(
            gate_verdict(row("Remote"), _Profile(countries=[])).state, SHOWN)

    def test_an_unread_body_keeps_its_own_reason(self):
        verdict = gate_verdict(row("Remote", full_jd=""), _Profile())
        self.assertEqual(verdict.state, UNDECIDABLE)
        self.assertEqual(verdict.reason, UNREADABLE_REASON)

    def test_an_absent_location_is_not_newly_badged(self):
        """
        Q55 is remote postings. A missing location is the wider version of
        the same question and is recorded as backlog, not decided here.
        """
        self.assertEqual(gate_verdict(row(""), _Profile()).state, SHOWN)

    def test_the_parser_is_gate_source(self):
        """A parse change has to re-judge every stored row."""
        from tools.jobs.job_filter import _gate_source
        self.assertIn("def _parse_remote", _gate_source())


class TestTheTwoGatesAgree(unittest.TestCase):
    """
    Discovery and the board read the same location through one judgement,
    `country_decision`. Walk both and compare them.
    """

    STRINGS = ("Argentina Remote", "Remote - Ireland", "Remote - US", "Remote",
               "Remote (US, Canada)", "Remote - UK or Ireland",
               "Remote - Dublin, Ohio", "Remote - Latin America", "Remote - UK",
               "Sao Paulo, BR", "Austin, TX", "", "Multiple Locations")

    def test_excluded_there_is_hidden_here(self):
        profile = _Profile()
        for raw in self.STRINGS:
            with self.subTest(raw=raw):
                excluded = evaluate(_Job(raw), profile).exclude
                hidden = gate_verdict(row(raw), profile).state == HIDDEN
                self.assertEqual(excluded, hidden)

    def test_unclear_there_is_undecidable_here_for_remote(self):
        profile = _Profile()
        for raw in self.STRINGS:
            if not parse_location(raw).is_remote:
                continue
            with self.subTest(raw=raw):
                unclear = evaluate(_Job(raw), profile).location_score == -1
                undecidable = gate_verdict(row(raw), profile).state == UNDECIDABLE
                self.assertEqual(unclear, undecidable)


if __name__ == "__main__":
    unittest.main()

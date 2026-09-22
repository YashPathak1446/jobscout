"""
Work authorization: three answers, and unknown is one of them (pilot A4).

The About-you screen derived two booleans from a dropdown:
`us_citizen = visa == "US Citizen"`, `permanent_resident = visa == "Green
Card"`. F-1 OPT, F-1 CPT, H-1B **and "Other / prefer not to say"** all became
`false/false`, and the gate read that as "not a US person, needs
sponsorship". Declining to answer was recorded as an answer.

Now each of `us_person`, `needs_sponsorship` and `holds_clearance` is "yes",
"no" or "unknown", and the gate has a third verdict for a requirement it
cannot settle: shown, badged and counted.

The migration table is walked row by row, **including the absent rows** —
R75: a test that walks a range has not walked the absence.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.jobs.job_filter import (  # noqa: E402
    HIDDEN,
    SHOWN,
    UNDECIDABLE,
    UNREADABLE_REASON,
    gate_verdict,
    judge_body,
    work_answer,
)
from tools.profile import load_profile  # noqa: E402
from tools.profile.profile_schema import (  # noqa: E402
    PersonalInfo,
    migrate_work_authorization,
)

UNKNOWN = {"us_person": "unknown", "needs_sponsorship": "unknown",
           "holds_clearance": "unknown"}


def _answers(us_person, needs_sponsorship, holds_clearance="unknown"):
    return {"us_person": us_person, "needs_sponsorship": needs_sponsorship,
            "holds_clearance": holds_clearance}


# (stored personal_info fragment, expected work_authorization)
MIGRATION_TABLE = [
    # The plan's rows.
    ({"us_citizen": True, "permanent_resident": False, "visa_status": "US Citizen"},
     _answers("yes", "no")),
    ({"us_citizen": False, "permanent_resident": False, "visa_status": "Green Card"},
     _answers("yes", "no")),
    ({"us_citizen": False, "permanent_resident": False, "visa_status": "F1 OPT"},
     _answers("no", "yes")),
    ({"us_citizen": False, "permanent_resident": False, "visa_status": "F1 CPT"},
     _answers("no", "yes")),
    ({"us_citizen": False, "permanent_resident": False, "visa_status": "H1B"},
     _answers("no", "yes")),
    # Row four — the point of the table. The template shipped false/false.
    ({"us_citizen": False, "permanent_resident": False, "visa_status": ""},
     UNKNOWN),
    ({"us_citizen": False, "permanent_resident": False,
      "visa_status": "Other / prefer not to say"},
     UNKNOWN),
    # The absent rows.
    ({}, UNKNOWN),
    ({"visa_status": ""}, UNKNOWN),
    ({"us_citizen": None, "permanent_resident": None, "visa_status": ""},
     UNKNOWN),
    # Found while writing the table.
    ({"us_citizen": False, "permanent_resident": True, "visa_status": ""},
     _answers("yes", "no")),
    ({"us_citizen": True, "visa_status": "H1B"},  # the explicit true wins
     _answers("yes", "no")),
    ({"us_citizen": False, "permanent_resident": False, "visa_status": "TN"},
     UNKNOWN),  # typed by hand: not a value this code recognises
    # Clearance: true is yes; false was an unchecked checkbox's default.
    ({"us_citizen": True, "holds_security_clearance": True},
     _answers("yes", "no", "yes")),
    ({"us_citizen": True, "holds_security_clearance": False},
     _answers("yes", "no", "unknown")),
    ({"visa_status": "", "holds_security_clearance": True},
     _answers("unknown", "unknown", "yes")),
    # An existing answer wins over every legacy key.
    ({"us_citizen": True, "visa_status": "US Citizen",
      "work_authorization": _answers("no", "yes", "no")},
     _answers("no", "yes", "no")),
    ({"work_authorization": {"us_person": "yes"}},
     _answers("yes", "unknown", "unknown")),
    ({"work_authorization": {"us_person": None, "needs_sponsorship": "no"}},
     _answers("unknown", "no", "unknown")),
    ({"work_authorization": {}}, UNKNOWN),
]

HEADER = {"name": "", "email": "", "phone": "", "github_url": "",
          "linkedin_url": "", "graduation_date": "", "graduation_term": "",
          "school": "", "location": "", "degree": ""}


class TestTheMigrationTable(unittest.TestCase):

    def test_every_row_through_the_function(self):
        for stored, expected in MIGRATION_TABLE:
            with self.subTest(stored=stored):
                migrated = migrate_work_authorization(stored)
                self.assertEqual(migrated["work_authorization"], expected)

    def test_every_row_through_the_loader_agrees(self):
        """Two callers of one function; walk both and compare (R70)."""
        for stored, expected in MIGRATION_TABLE:
            with self.subTest(stored=stored):
                info = PersonalInfo(**{**HEADER, **stored})
                self.assertEqual(info.work_authorization.model_dump(), expected)

    def test_the_legacy_keys_do_not_survive(self):
        migrated = migrate_work_authorization(
            {"us_citizen": True, "permanent_resident": False,
             "holds_security_clearance": True})
        for key in ("us_citizen", "permanent_resident",
                    "holds_security_clearance"):
            self.assertNotIn(key, migrated)
        self.assertFalse(hasattr(PersonalInfo(**HEADER), "us_citizen"))

    def test_the_input_is_not_mutated(self):
        stored = {"us_citizen": True}
        migrate_work_authorization(stored)
        self.assertEqual(stored, {"us_citizen": True})

    def test_an_answer_that_is_not_an_answer_is_refused_not_guessed(self):
        with self.assertRaises(Exception):
            PersonalInfo(**HEADER, work_authorization={"us_person": "maybe"})


class TestTheCommittedProfiles(unittest.TestCase):
    """Build against Priya and the second stranger, not the author."""

    def test_priya_is_an_h1b_holder(self):
        auth = load_profile("priya_raghunathan", user_id=None) \
            .personal_info.work_authorization
        self.assertEqual(auth.model_dump(), _answers("no", "yes"))

    def test_rohan_never_answered(self):
        auth = load_profile("rohan_deshmukh", user_id=None) \
            .personal_info.work_authorization
        self.assertEqual(auth.model_dump(), UNKNOWN)


class TestTheScreenReadsTheSameAnswers(unittest.TestCase):
    """
    `read_personal` reads raw JSON for the About-you screen, which skips the
    pydantic model. If it did not run the migration itself, the screen would
    show blanks for answers the gate is already using.
    """

    def test_read_personal_migrates(self):
        from scripts.init_profile import read_personal

        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"JOBSCOUT_HOME": home}):
            profiles = Path(home) / "user_profiles"
            profiles.mkdir()
            (profiles / "someone.json").write_text(json.dumps({
                "personal_info": {"visa_status": "H1B", "us_citizen": False,
                                  "permanent_resident": False}}),
                encoding="utf-8")
            personal = read_personal(None, "someone")

        self.assertEqual(personal["work_authorization"], _answers("no", "yes"))


# --- the judgement ---------------------------------------------------------

READABLE = "We build developer tools in Python and Go for small teams. " * 10
CLEARANCE = READABLE + "You must hold an active TS/SCI clearance to start."
US_PERSON = READABLE + "Applicants must be U.S. citizens due to ITAR."
NO_SPONSOR = READABLE + "We are unable to sponsor visas for this role."


class _Profile:
    def __init__(self, **answers):
        self.personal_info = type("P", (), {"work_authorization": {
            **UNKNOWN, **answers}})()
        self.job_preferences = type("J", (), {"seniority": ["senior"]})()


class TestUnknownIsNeitherAPassNorAFail(unittest.TestCase):

    def test_each_demand_met_by_unknown_is_undecidable(self):
        for text in (CLEARANCE, US_PERSON, NO_SPONSOR):
            with self.subTest(text=text[-50:]):
                verdict = judge_body(text, _Profile())
                self.assertEqual(verdict.state, UNDECIDABLE)
                self.assertIn("you have not said", verdict.reason)

    def test_each_demand_met_by_no_is_hidden(self):
        cases = ((CLEARANCE, {"holds_clearance": "no"}),
                 (US_PERSON, {"us_person": "no"}),
                 (NO_SPONSOR, {"needs_sponsorship": "yes"}))
        for text, answers in cases:
            with self.subTest(answers=answers):
                self.assertEqual(judge_body(text, _Profile(**answers)).state,
                                 HIDDEN)

    def test_each_demand_met_by_yes_is_shown(self):
        cases = ((CLEARANCE, {"holds_clearance": "yes"}),
                 (US_PERSON, {"us_person": "yes"}),
                 (NO_SPONSOR, {"needs_sponsorship": "no"}))
        for text, answers in cases:
            with self.subTest(answers=answers):
                self.assertEqual(judge_body(text, _Profile(**answers)).state,
                                 SHOWN)

    def test_a_posting_that_demands_nothing_is_shown_to_everyone(self):
        self.assertEqual(judge_body(READABLE, _Profile()).state, SHOWN)

    def test_a_ruling_out_beats_an_unanswered_question(self):
        text = READABLE + "Requires 12+ years of experience. " + CLEARANCE
        self.assertEqual(judge_body(text, _Profile()).state, HIDDEN)

    def test_a_missing_section_reads_as_unknown_not_no(self):
        """`_is_us_person` read a missing attribute as a confident False."""
        for profile in (object(), type("X", (), {"personal_info": None})()):
            for field in ("us_person", "needs_sponsorship", "holds_clearance"):
                self.assertEqual(work_answer(profile, field), "unknown")


class TestTheOneEntailment(unittest.TestCase):
    """
    A US person cannot need sponsorship. That follows from an answer, so it
    is applied. Nothing else is, and in particular not the reverse.
    """

    def test_a_us_person_satisfies_a_no_sponsorship_posting(self):
        profile = _Profile(us_person="yes")  # sponsorship left unanswered
        self.assertEqual(judge_body(NO_SPONSOR, profile).state, SHOWN)

    def test_even_when_the_sponsorship_answer_contradicts_it(self):
        profile = _Profile(us_person="yes", needs_sponsorship="yes")
        self.assertEqual(judge_body(NO_SPONSOR, profile).state, SHOWN)

    def test_not_needing_sponsorship_does_not_make_you_a_us_person(self):
        """A TN or H-4 EAD holder needs no sponsorship and is not a US person."""
        profile = _Profile(needs_sponsorship="no")
        self.assertEqual(judge_body(US_PERSON, profile).state, UNDECIDABLE)

    def test_not_a_us_person_and_no_sponsorship_needed_is_shown(self):
        profile = _Profile(us_person="no", needs_sponsorship="no")
        self.assertEqual(judge_body(NO_SPONSOR, profile).state, SHOWN)

    def test_a_us_person_answer_says_nothing_about_a_clearance(self):
        self.assertEqual(judge_body(CLEARANCE, _Profile(us_person="yes")).state,
                         UNDECIDABLE)


class TestAnUnreadPostingIsUndecidable(unittest.TestCase):
    """
    R61's shape: a failed scrape falls back to discovery's snippet, the gate
    found nothing in it, and the job was stored as eligible.
    """

    def test_a_snippet_is_undecidable(self):
        verdict = judge_body("Backend engineer, Python.",
                             _Profile(us_person="yes", needs_sponsorship="no",
                                      holds_clearance="no"))
        self.assertEqual(verdict, verdict.__class__(UNDECIDABLE, UNREADABLE_REASON))

    def test_a_failed_scrape_is_undecidable_however_long(self):
        profile = _Profile(us_person="yes", needs_sponsorship="no",
                           holds_clearance="no")
        self.assertEqual(judge_body(READABLE, profile, readable=False).state,
                         UNDECIDABLE)
        self.assertEqual(judge_body(READABLE, profile, readable=True).state, SHOWN)

    def test_a_snippet_that_rules_you_out_still_does(self):
        self.assertEqual(
            judge_body("Requires 12+ years of experience.", _Profile()).state,
            HIDDEN)


class TestTheTwoGatesAgree(unittest.TestCase):
    """
    Q39: the pipeline gate and the board gate are separate code. They share
    `judge_body`, so for the same text and a location the country gate does
    not touch, they must reach the same verdict.
    """

    def _pipeline(self, jobs, profile):
        from agents.orchestrator import JobScoutOrchestrator

        stub = type("S", (), {"profile": profile})()
        return JobScoutOrchestrator._apply_body_gate(stub, jobs)

    def test_same_text_same_verdict(self):
        texts = ("", "Backend engineer.", READABLE, CLEARANCE, US_PERSON,
                 NO_SPONSOR, READABLE + "Requires 12+ years of experience.")
        profiles = (_Profile(), _Profile(us_person="no", needs_sponsorship="yes",
                                         holds_clearance="no"))
        for profile in profiles:
            for text in texts:
                with self.subTest(text=text[-40:]):
                    board = gate_verdict({"full_jd": text, "location": ""}, profile)
                    kept = self._pipeline([{"full_jd": text}], profile)
                    self.assertEqual(bool(kept), board.state != HIDDEN)

    def test_the_pipeline_keeps_an_unreadable_job(self):
        profile = _Profile(us_person="yes", needs_sponsorship="no",
                           holds_clearance="no")
        job = {"full_jd": READABLE, "scraped_successfully": False}
        self.assertEqual(self._pipeline([job], profile), [job])


if __name__ == "__main__":
    unittest.main()

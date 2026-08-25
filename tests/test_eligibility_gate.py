"""
Eligibility a posting states outright (R56 / Q10).

R54 reads how much experience a JD asks for. This reads who is allowed to hold
the job at all, which R2's bet does not cover: a wrong-*level* job scores low
against a new-grad profile and leaves the funnel on its own, while a
clearance-gated job can be an excellent semantic match and score high on merit.

Q10 asked whether this needed an employer denylist. It did not. Every sentence
below is real, from `outputs/2026-08-25`, and the postings say it themselves:

    will not be considered who do not hold at least a TS/SCI clearance   exclude
    An active TS/SCI clearance, or eligibility to obtain one             KEEP*
    U.S. citizenship is required ... eligible for a security clearance   KEEP*
    military and veteran status ... protected by US federal law          KEEP

    * for a US citizen. Excluded for someone who is not a US person.

The second and third lines are the reason this is not a keyword rule. Scale AI
wrote both clearance sentences, one in each of two postings, and they differ by
one clause: one wants a clearance you *have*, the other one you could *get*. A
rule that reads them the same either hides a job a citizen can apply for or
lets through one that will not consider them.

The fourth is the trap. Equal-opportunity boilerplate sits under a large share
of postings and is made of these exact words while meaning the opposite.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.jobs.job_filter import (  # noqa: E402
    _plain,
    body_disqualifiers,
    eligibility_disqualifiers,
)


class _Personal:
    def __init__(self, us_citizen=True, permanent_resident=False,
                 holds_security_clearance=False):
        self.us_citizen = us_citizen
        self.permanent_resident = permanent_resident
        self.holds_security_clearance = holds_security_clearance


class _Prefs:
    seniority = ["new grad", "entry level", "junior"]


class _Profile:
    def __init__(self, **personal):
        self.personal_info = _Personal(**personal)
        self.job_preferences = _Prefs()


CITIZEN = _Profile()
CLEARED = _Profile(holds_security_clearance=True)
GREEN_CARD = _Profile(us_citizen=False, permanent_resident=True)
F1_OPT = _Profile(us_citizen=False, permanent_resident=False)


# The two Scale AI postings, verbatim apart from surrounding markup.
DEVOPS = ("<li><strong>At least an active TS/SCI clearance and the ability "
          "&amp; willingness to up level to CI Poly. This is a requirement and "
          "candidates will not be considered who do not hold at least a TS/SCI "
          "clearance.</strong></li>")

FDE = ("<li>An active TS/SCI clearance, or eligibility to obtain one.&nbsp;"
       "</li>")

# Collins Aerospace, from the 2026-08-23 baseline. Both sentences at once.
COLLINS = ("The ability to obtain and maintain a U.S. government issued "
           "security clearance is required. U.S. citizenship is required, as "
           "only U.S. citizens are eligible for a security clearance.")

# Stripe's, which contains the vocabulary and none of the meaning.
STRIPE_EEO = ("Stripe does not discriminate on the basis of race, religion, "
              "military and veteran status (including military spouse status), "
              "or any other characteristic protected by US federal, state or "
              "local laws.")


class TestHeldVersusObtainable(unittest.TestCase):
    """
    The distinction the whole gate turns on.

    A clearance takes months and an employer to sponsor the investigation, so
    "must already hold one" excludes everyone who does not. "Able to obtain
    one" excludes nobody who is a US person, because that is all it means.
    """

    def test_a_clearance_you_must_already_hold_excludes_an_uncleared_citizen(self):
        self.assertTrue(eligibility_disqualifiers(DEVOPS, CITIZEN))

    def test_the_same_posting_is_kept_for_someone_who_holds_one(self):
        self.assertEqual(eligibility_disqualifiers(DEVOPS, CLEARED), [])

    def test_a_clearance_you_could_obtain_is_kept_for_a_citizen(self):
        """
        The disjunction: "An active TS/SCI clearance, **or** eligibility to
        obtain one." Reading this as a hard requirement would hide a job the
        candidate may apply for, and a gate's false positives are invisible.
        """
        self.assertEqual(eligibility_disqualifiers(FDE, CITIZEN), [])

    def test_a_clearance_you_could_obtain_still_excludes_a_non_us_person(self):
        self.assertTrue(eligibility_disqualifiers(FDE, F1_OPT))

    def test_the_weaker_reading_wins_within_one_sentence(self):
        """
        Both cues, one sentence — the same rule `required_years` uses when a
        posting lists several experience floors.
        """
        text = "Must possess an active Secret clearance or be able to obtain one."
        self.assertEqual(eligibility_disqualifiers(text, CITIZEN), [])
        self.assertTrue(eligibility_disqualifiers(text, F1_OPT))

    def test_a_bullet_further_down_does_not_soften_a_hard_requirement(self):
        """
        Why `_plain` turns block tags into sentence breaks rather than spaces.
        Without that, an "able to obtain" anywhere in the list would cancel a
        hard requirement three bullets above it.
        """
        text = ("<li>Candidates must hold an active TS/SCI clearance.</li>"
                "<li>Able to obtain a corporate travel card.</li>")
        self.assertTrue(eligibility_disqualifiers(text, CITIZEN))


class TestUsPersonWork(unittest.TestCase):
    """ITAR's term, which includes permanent residents."""

    def test_citizenship_language_excludes_a_visa_holder(self):
        self.assertTrue(eligibility_disqualifiers(COLLINS, F1_OPT))

    def test_a_green_card_holder_is_a_us_person(self):
        self.assertEqual(eligibility_disqualifiers(COLLINS, GREEN_CARD), [])

    def test_a_citizen_is_kept(self):
        self.assertEqual(eligibility_disqualifiers(COLLINS, CITIZEN), [])

    def test_itar_and_export_control_count(self):
        for text in ("This role is subject to ITAR restrictions.",
                     "Position requires access to export-controlled technology.",
                     "Must be able to obtain a Public Trust determination."):
            self.assertTrue(eligibility_disqualifiers(text, F1_OPT), text)
            self.assertEqual(eligibility_disqualifiers(text, CITIZEN), [], text)


class TestSponsorship(unittest.TestCase):
    """The only rule here that fires on candidates rather than on jobs."""

    def test_a_posting_that_will_not_sponsor_excludes_someone_who_needs_it(self):
        text = "We are unable to provide visa sponsorship for this position."
        self.assertTrue(eligibility_disqualifiers(text, F1_OPT))
        self.assertEqual(eligibility_disqualifiers(text, CITIZEN), [])

    def test_the_other_phrasings(self):
        for text in ("No H1B sponsorship available for this role.",
                     "Candidates must not require visa sponsorship now or in "
                     "the future.",
                     "Sponsorship is not available for this opening."):
            self.assertTrue(eligibility_disqualifiers(text, F1_OPT), text)

    def test_a_posting_that_does_sponsor_is_not_read_as_refusing(self):
        text = "We are happy to sponsor visas for exceptional candidates."
        self.assertEqual(eligibility_disqualifiers(text, F1_OPT), [])


class TestEqualOpportunityBoilerplate(unittest.TestCase):
    """
    The failure this gate would otherwise have shipped with.

    Stripe's footer contains "military and veteran status" and "protected by US
    federal law". It is a promise not to restrict, and it is on a large share
    of postings — so reading it as a restriction would have quietly emptied the
    board for every candidate who is not a US citizen.
    """

    def test_stripe_is_kept_for_everyone(self):
        for profile in (CITIZEN, F1_OPT, GREEN_CARD, CLEARED):
            self.assertEqual(eligibility_disqualifiers(STRIPE_EEO, profile), [])

    def test_the_usual_eeo_phrasings_are_skipped(self):
        for text in ("All qualified applicants will receive consideration "
                     "without regard to citizenship status.",
                     "We are an equal opportunity employer and do not "
                     "discriminate on the basis of national origin.",
                     "Employment decisions are made regardless of citizenship "
                     "or veteran status."):
            self.assertEqual(eligibility_disqualifiers(text, F1_OPT), [], text)

    def test_boilerplate_does_not_shield_a_real_restriction_elsewhere(self):
        """
        Skipping is per sentence, not per posting — a footer must not launder
        a requirement stated in the body.
        """
        text = (DEVOPS + " " + STRIPE_EEO)
        self.assertTrue(eligibility_disqualifiers(text, CITIZEN))


class TestNothingToSay(unittest.TestCase):
    """Most postings state no eligibility requirement at all."""

    def test_empty(self):
        self.assertEqual(eligibility_disqualifiers("", CITIZEN), [])
        self.assertEqual(eligibility_disqualifiers(None, CITIZEN), [])

    def test_an_ordinary_posting_is_untouched(self):
        text = ("We are looking for an engineer to build data pipelines in "
                "Python. You will work with Kubernetes and AWS.")
        for profile in (CITIZEN, F1_OPT, GREEN_CARD):
            self.assertEqual(eligibility_disqualifiers(text, profile), [])

    def test_the_word_clearance_alone_proves_nothing(self):
        """
        "Clear" and "clearance" turn up in ordinary prose. Only the held and
        obtainable cues fire.
        """
        text = "You will have clear ownership and a clearance to ship quickly."
        self.assertEqual(eligibility_disqualifiers(text, CITIZEN), [])


class TestPlain(unittest.TestCase):
    """The JD arrives as markup, because every ATS source serves HTML."""

    def test_block_tags_become_sentence_breaks(self):
        self.assertEqual(_plain("<li>one</li><li>two</li>"), " one. two. ")

    def test_the_us_abbreviation_does_not_end_a_sentence(self):
        """
        Collins Aerospace's clearance line is one sentence containing "U.S.",
        and splitting on its periods stranded "ability to obtain" away from the
        requirement it qualifies.
        """
        self.assertEqual(_plain("a U.S. issued clearance"), "a US issued clearance")

    def test_entities_are_decoded(self):
        self.assertIn("&", _plain("Infrastructure &amp; Security"))
        self.assertNotIn("&nbsp;", _plain("obtain one.&nbsp;"))

    def test_inline_tags_do_not_split_a_sentence(self):
        plain = _plain("must <strong>hold</strong> a clearance")
        self.assertNotIn(".", plain)


class TestWiredIntoTheBodyGate(unittest.TestCase):
    """`body_disqualifiers` is the one entry point the orchestrator calls."""

    def test_an_eligibility_reason_reaches_the_caller(self):
        reasons = body_disqualifiers(DEVOPS, CITIZEN)
        self.assertTrue(any("clearance" in reason for reason in reasons))

    def test_it_stacks_with_the_years_floor(self):
        text = DEVOPS + " Requires 9+ years of professional experience."
        self.assertEqual(len(body_disqualifiers(text, CITIZEN)), 2)


class TestAgainstTheRealRun(unittest.TestCase):
    """
    The posting that started this, and the twenty-nine that must survive it.

    Skipped on a clean clone; when the files are there this is the case that
    actually mattered.
    """

    def setUp(self):
        import json

        # The frozen copy, not `outputs/` — a live output directory is
        # overwritten by the next run, and these assert facts about one
        # specific run. Verified by `scripts/baseline.py verify --all`.
        path = ROOT / "baselines" / "2026-08-25-pre-r53" / "enriched_jobs.json"
        if not path.exists():
            self.skipTest("needs a real enriched run")
        self.jobs = json.loads(path.read_text(encoding="utf-8"))

        from tools.profile import load_profile
        if not (ROOT / "user_profiles" / "yash_pathak.json").exists():
            self.skipTest("needs a real profile")
        self.profile = load_profile("yash_pathak")

    def _first(self, company, needle):
        for job in self.jobs:
            if job.get("company") == company and needle in str(job.get("title")):
                return job
        return None

    def test_the_scale_ai_devops_posting_is_finally_dropped(self):
        """
        It cleared R54 (2 years) and R55 (Washington, DC) and was the only
        posting in the run that no existing gate could see.
        """
        job = self._first("Scale AI", "DevOps")
        if job is None:
            self.skipTest("posting not in this run")
        reasons = eligibility_disqualifiers(job.get("full_jd", ""), self.profile)
        self.assertTrue(reasons)
        self.assertIn("clearance", reasons[0])

    def test_the_forward_deployed_posting_is_not_dropped_on_eligibility(self):
        """
        Its clearance line is the obtainable kind, so R54's years floor is what
        removes it — not this gate. Worth pinning: if this ever starts firing,
        the disjunction rule has broken.
        """
        job = self._first("Scale AI", "Forward Deployed")
        if job is None:
            self.skipTest("posting not in this run")
        self.assertEqual(
            eligibility_disqualifiers(job.get("full_jd", ""), self.profile), [])

    def test_the_gate_touches_almost_nothing_else(self):
        dropped = [job for job in self.jobs
                   if eligibility_disqualifiers(job.get("full_jd", ""), self.profile)]
        self.assertLessEqual(len(dropped), 2,
                             f"{len(dropped)}/{len(self.jobs)} dropped on "
                             f"eligibility — too aggressive")


if __name__ == "__main__":
    unittest.main()

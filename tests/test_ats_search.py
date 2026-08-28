"""
Keyless discovery from ATS boards (R34).

Every earlier source was narrow or keyed: `github_newgrad` needs no key but is
new-grad only, Serper and Adzuna reach any level but cost one. Greenhouse,
Lever and Ashby serve public JSON, so this is the first source that is both
free and level-agnostic.

No network here. The readers are exercised against captured response shapes;
the live endpoints were probed once, when the seed list was built.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.search import ats_search  # noqa: E402
from tools.search.ats_search import (  # noqa: E402
    COMPANIES_FILE,
    _strip_html,
    harvest_slugs,
    load_companies,
    search_ats,
    title_matches_roles,
)


class TestTitleMatching(unittest.TestCase):
    """
    A company board is the whole company. Without this, Stripe's 578 roles
    hand you account executives, because they sort first.
    """

    def test_matches_a_role_inside_a_longer_title(self):
        self.assertTrue(title_matches_roles("Senior Software Engineer II",
                                            ["Software Engineer"]))

    def test_hyphenated_titles_still_match(self):
        # A word boundary treats '-' as a separator; lookarounds do not.
        self.assertTrue(title_matches_roles("Full-Stack Engineer II",
                                            ["Full-Stack Engineer"]))

    def test_does_not_match_a_different_job_family(self):
        self.assertFalse(title_matches_roles("Engineering Manager",
                                             ["Software Engineer"]))
        self.assertFalse(title_matches_roles("Account Executive",
                                             ["Software Engineer"]))

    def test_does_not_match_across_a_word_boundary(self):
        # R18's lesson: "ai" must not match inside "Retail".
        self.assertFalse(title_matches_roles("Retail Associate", ["AI Engineer"]))

    def test_software_engineering_manager_is_not_a_software_engineer(self):
        self.assertFalse(title_matches_roles("Software Engineering Manager",
                                             ["Software Engineer"]))

    def test_no_roles_means_everything_matches(self):
        self.assertTrue(title_matches_roles("Anything At All", []))
        self.assertTrue(title_matches_roles("Anything At All", None))

    def test_any_one_role_is_enough(self):
        self.assertTrue(title_matches_roles(
            "ML Engineer, New Grad", ["Backend Engineer", "ML Engineer"]))


class TestSlugHarvest(unittest.TestCase):
    """Any apply URL on a known ATS reveals a company's whole board."""

    def setUp(self):
        self.file = Path(tempfile.mkdtemp()) / "companies.json"
        self.file.write_text(json.dumps({"greenhouse": ["stripe"]}), encoding="utf-8")

    def _read(self):
        return json.loads(self.file.read_text(encoding="utf-8"))

    def test_learns_a_greenhouse_slug(self):
        added = harvest_slugs(["https://boards.greenhouse.io/figma/jobs/123"],
                              path=self.file)
        self.assertEqual(added, {"greenhouse": ["figma"]})
        self.assertIn("figma", self._read()["greenhouse"])

    def test_learns_lever_and_ashby_slugs(self):
        harvest_slugs([
            "https://jobs.lever.co/spotify/abc-def",
            "https://jobs.ashbyhq.com/ramp/xyz",
        ], path=self.file)
        data = self._read()
        self.assertIn("spotify", data["lever"])
        self.assertIn("ramp", data["ashby"])

    def test_learns_workable_and_smartrecruiters_slugs(self):
        harvest_slugs([
            "https://apply.workable.com/blueground/j/ABC123/",
            "https://jobs.smartrecruiters.com/Experian/744000012345",
        ], path=self.file)
        data = self._read()
        self.assertIn("blueground", data["workable"])
        self.assertIn("experian", data["smartrecruiters"])

    def test_a_slug_already_known_is_not_duplicated(self):
        added = harvest_slugs(["https://boards.greenhouse.io/stripe/jobs/1"],
                              path=self.file)
        self.assertEqual(added, {})
        self.assertEqual(self._read()["greenhouse"].count("stripe"), 1)

    def test_unrelated_urls_are_ignored(self):
        added = harvest_slugs(["https://jobright.ai/jobs/info/abc", "", None],
                              path=self.file)
        self.assertEqual(added, {})

    def test_a_missing_file_is_not_an_error_it_is_the_first_run(self):
        """
        A missing learned-slug file is the normal state of a fresh install,
        not a fault.

        This asserted `== {}` — the old implementation bailed out when it
        could not read the file, and learned nothing. That was harmless while
        the file was always seeded from a shipped copy. It is not harmless
        now: the seed stays in the package and is never copied out, so the
        learned file does not exist until something writes it. Bailing would
        mean a fresh install never learns a single slug, forever, with no
        error to notice.

        The test's own name says what it was protecting — *not an error* — and
        that still holds. What changed is that "not an error" now means "learn
        it and create the file" rather than "give up quietly".
        """
        missing = self.file.parent / "nope.json"
        added = harvest_slugs(["https://jobs.lever.co/x/1"], path=missing)

        self.assertEqual(added, {"lever": ["x"]})
        self.assertTrue(missing.exists(), "the first discovery created nothing")
        self.assertEqual(json.loads(missing.read_text(encoding="utf-8")),
                         {"lever": ["x"]})


class TestLoadCompanies(unittest.TestCase):

    def test_unknown_boards_are_dropped(self):
        file = Path(tempfile.mkdtemp()) / "c.json"
        file.write_text(json.dumps({
            "greenhouse": ["stripe"],
            "_comment": ["not a board"],
            "workday": ["someone"],
        }), encoding="utf-8")

        loaded = load_companies(path=file)
        self.assertEqual(set(loaded), {"greenhouse"})

    def test_an_unreadable_file_yields_nothing_rather_than_raising(self):
        self.assertEqual(load_companies(path=Path("/definitely/not/here.json")), {})

    def test_the_shipped_seed_list_is_loadable_and_populated(self):
        loaded = load_companies()
        self.assertTrue(loaded, f"{COMPANIES_FILE} should carry company slugs")
        self.assertTrue(any(loaded.values()))


class TestSearchAts(unittest.TestCase):
    """Filtering must happen before the cap, or the cap picks the wrong jobs."""

    def setUp(self):
        self._real = dict(ats_search.BOARDS)

        def fake(slug):
            titles = ["Account Executive", "Account Manager", "Backend Engineer",
                      "Software Engineer", "Recruiter"]
            return [
                ats_search._listing("greenhouse", slug, i, t, "ACME",
                                    "Remote", f"https://x/{i}", "a job description")
                for i, t in enumerate(titles)
            ]

        ats_search.BOARDS["greenhouse"] = fake

    def tearDown(self):
        ats_search.BOARDS.clear()
        ats_search.BOARDS.update(self._real)

    def test_filters_by_role_before_truncating(self):
        # Cap of 2 against a board whose first two titles are sales roles.
        # Truncating first would return them and no engineers at all.
        found = search_ats(max_results=2, boards=["greenhouse"],
                           companies={"greenhouse": ["acme"]},
                           roles=["Software Engineer", "Backend Engineer"])
        self.assertEqual(len(found), 2)
        for job in found:
            self.assertIn("Engineer", job.title)

    def test_without_roles_everything_comes_back(self):
        found = search_ats(max_results=99, boards=["greenhouse"],
                           companies={"greenhouse": ["acme"]})
        self.assertEqual(len(found), 5)

    def test_listings_carry_the_job_description(self):
        """ATS jobs skip enrichment, so the JD has to arrive with them."""
        found = search_ats(max_results=1, boards=["greenhouse"],
                           companies={"greenhouse": ["acme"]})
        self.assertTrue(found[0].full_jd)
        self.assertTrue(found[0].source.startswith("ats_"))

    def test_no_companies_means_no_listings_and_no_error(self):
        self.assertEqual(search_ats(companies={}, boards=["greenhouse"]), [])


class TestHydration(unittest.TestCase):
    """
    SmartRecruiters does not inline descriptions. Fetching them for every
    posting on an enterprise board — Bosch carries nearly 5,000 — to then
    discard almost all of them would cost more than the source is worth, so
    hydration runs after filtering and after the cap.
    """

    def setUp(self):
        self._real_boards = dict(ats_search.BOARDS)
        self._real_fetch = ats_search._fetch
        self.fetched = []

        def board(slug):
            return [
                ats_search._listing("smartrecruiters", slug, i,
                                    f"Software Engineer {i}", "ACME", "Remote",
                                    "https://x", "")
                for i in range(10)
            ]

        def fake_fetch(url):
            self.fetched.append(url)
            return {"jobAd": {"sections": {
                "jobDescription": {"text": "<p>Build things</p>"},
                "qualifications": {"text": "<p>Know things</p>"},
            }}}

        ats_search.BOARDS["smartrecruiters"] = board
        ats_search._fetch = fake_fetch

    def tearDown(self):
        ats_search.BOARDS.clear()
        ats_search.BOARDS.update(self._real_boards)
        ats_search._fetch = self._real_fetch

    def test_only_the_returned_listings_are_hydrated(self):
        found = search_ats(max_results=3, boards=["smartrecruiters"],
                           companies={"smartrecruiters": ["acme"]})
        self.assertEqual(len(found), 3)
        self.assertEqual(len(self.fetched), 3,
                         "hydration must run after the cap, not before")

    def test_hydrated_listings_carry_the_description(self):
        found = search_ats(max_results=1, boards=["smartrecruiters"],
                           companies={"smartrecruiters": ["acme"]})
        self.assertIn("Build things", found[0].full_jd)
        self.assertIn("Know things", found[0].full_jd)
        self.assertNotIn("<p>", found[0].full_jd)

    def test_boards_that_inline_their_description_are_not_refetched(self):
        ats_search.BOARDS["greenhouse"] = lambda slug: [
            ats_search._listing("greenhouse", slug, 1, "Software Engineer",
                                "ACME", "Remote", "https://x", "already here")
        ]
        search_ats(max_results=1, boards=["greenhouse"],
                   companies={"greenhouse": ["acme"]})
        self.assertEqual(self.fetched, [])


class TestHtmlStripping(unittest.TestCase):

    def test_tags_are_removed_and_entities_decoded(self):
        text = _strip_html("<p>Build &amp; ship</p><li>Python</li>")
        self.assertNotIn("<", text)
        self.assertIn("Build & ship", text)
        self.assertIn("Python", text)

    def test_empty_input_is_safe(self):
        self.assertEqual(_strip_html(""), "")
        self.assertEqual(_strip_html(None), "")


if __name__ == "__main__":
    unittest.main()


class TestTheCapIsSpreadAcrossEmployers(unittest.TestCase):
    """
    R46: the cap used to go to whoever sorted first.

    `search_ats` broke out of the company loop as soon as it had enough
    listings, so a run capped at 20 came back 18 Affirm, 3 Airtable, 2 Airbnb —
    the alphabetical head of the seed file — while 54 Greenhouse companies were
    never contacted and four other boards were never reached at all.

    `title_matches_roles` had already solved this *within* a company, and said
    why in its docstring: truncate first and you get whatever sorts first
    rather than what you asked for. This is the same argument one level up.
    """

    def test_one_prolific_company_cannot_eat_the_whole_cap(self):
        by_company = {
            "gh:affirm": [f"affirm-{i}" for i in range(18)],
            "gh:airtable": ["airtable-1", "airtable-2", "airtable-3"],
            "gh:airbnb": ["airbnb-1", "airbnb-2"],
        }
        spread = ats_search._spread(by_company, 9)

        self.assertEqual(len(spread), 9)
        employers = {job.rsplit("-", 1)[0] for job in spread}
        self.assertEqual(len(employers), 3, f"all three should appear: {spread}")

    def test_order_within_a_company_is_preserved(self):
        """A board listing its newest roles first should still surface them."""
        by_company = {"a": ["a1", "a2", "a3"], "b": ["b1"]}
        spread = ats_search._spread(by_company, 4)
        self.assertEqual([j for j in spread if j.startswith("a")], ["a1", "a2", "a3"])

    def test_a_cap_larger_than_the_pool_returns_everything(self):
        by_company = {"a": ["a1", "a2"], "b": ["b1"]}
        self.assertEqual(len(ats_search._spread(by_company, 100)), 3)

    def test_a_cap_of_zero_returns_nothing(self):
        self.assertEqual(ats_search._spread({"a": ["a1"]}, 0), [])

    def test_no_companies_is_not_an_error(self):
        self.assertEqual(ats_search._spread({}, 10), [])

    def test_a_short_cap_still_takes_from_different_employers_first(self):
        """Two slots, two companies — not two jobs from the first one."""
        by_company = {"a": ["a1", "a2", "a3"], "b": ["b1", "b2"]}
        self.assertEqual(ats_search._spread(by_company, 2), ["a1", "b1"])


class TestEveryCompanyIsAsked(unittest.TestCase):
    """The cap must not decide which companies get contacted."""

    def setUp(self):
        self._real = dict(ats_search.BOARDS)
        self.asked = []

        def fake(slug):
            self.asked.append(slug)
            return [
                ats_search._listing("greenhouse", slug, f"{slug}-{i}",
                                    "Software Engineer", slug.title(),
                                    "Remote", f"https://x.test/{slug}/{i}", "jd")
                for i in range(10)
            ]

        ats_search.BOARDS["greenhouse"] = fake

    def tearDown(self):
        ats_search.BOARDS.clear()
        ats_search.BOARDS.update(self._real)

    def test_a_small_cap_does_not_stop_the_search_early(self):
        slugs = ["affirm", "airbnb", "airtable", "zapier", "zoom"]
        found = ats_search.search_ats(max_results=3, boards=["greenhouse"],
                                      companies={"greenhouse": slugs},
                                      roles=["Software Engineer"])

        self.assertEqual(sorted(self.asked), sorted(slugs),
                         "every seeded company must be contacted")
        self.assertEqual(len(found), 3)
        self.assertEqual(len({job.company for job in found}), 3,
                         "three slots should mean three employers")

    def test_the_last_company_alphabetically_can_still_be_returned(self):
        """
        The old code never reached it. Run enough times that a shuffle
        excluding it every time would be vanishingly unlikely.
        """
        slugs = ["affirm", "airbnb", "airtable", "zapier"]
        seen = set()
        for _ in range(25):
            found = ats_search.search_ats(max_results=1, boards=["greenhouse"],
                                          companies={"greenhouse": slugs},
                                          roles=["Software Engineer"])
            seen.update(job.company for job in found)

        self.assertIn("Zapier", seen)

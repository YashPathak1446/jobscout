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

    def test_a_missing_file_is_not_an_error(self):
        missing = self.file.parent / "nope.json"
        self.assertEqual(harvest_slugs(["https://jobs.lever.co/x/1"], path=missing), {})


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

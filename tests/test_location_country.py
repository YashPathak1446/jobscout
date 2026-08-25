"""
Countries the location matcher could not see (R55).

A São Paulo posting scored 54% and reached the top of the funnel while the
profile lists `countries: ["United States"]` and the same run correctly
excluded jobs in the UK, Ireland, Canada, Poland, India, Israel, China, France
and South Korea.

The exclusion was never the problem: it is a hard gate and it worked. The
country simply never parsed. `"São Paulo, BR"` produced `country=None`, and a
filter comparing None against a list of preferred countries has nothing to
say — so a job that should have been cut sailed through.

Two more bugs surfaced while fixing it, both the same shape as R18: a
substring credited as a term.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.jobs.location_matcher import (  # noqa: E402
    COUNTRY_CODES,
    country_from_code,
    parse_location,
)


class TestTheOriginalMiss(unittest.TestCase):

    def test_sao_paulo_br_is_brazil(self):
        """The posting that started this."""
        self.assertEqual(parse_location("São Paulo, BR").country, "Brazil")

    def test_a_bracketed_code(self):
        self.assertEqual(parse_location("Paris (FR)").country, "France")

    def test_a_country_spelled_out_still_works(self):
        self.assertEqual(parse_location("London, United Kingdom").country,
                         "United Kingdom")


class TestCodesNeverOutrankUSStates(unittest.TestCase):
    """
    The collisions are not exotic. CA is California and Canada, IN is Indiana
    and India, DE is Delaware and Germany. Reading "Los Angeles, CA" as Canada
    would be a far worse bug than the one being fixed, so those codes are not
    treated as countries at all.
    """

    def test_california_is_not_canada(self):
        parsed = parse_location("Los Angeles, CA")
        self.assertEqual(parsed.country, "United States")
        self.assertEqual(parsed.state, "California")

    def test_indiana_is_not_india(self):
        self.assertEqual(parse_location("Indianapolis, IN").state, "Indiana")

    def test_delaware_is_not_germany(self):
        self.assertEqual(parse_location("Wilmington, DE").state, "Delaware")

    def test_no_us_state_abbreviation_is_a_country_code(self):
        from tools.jobs.location_matcher import US_STATE_BY_ABBREV

        overlap = set(COUNTRY_CODES) & set(US_STATE_BY_ABBREV)
        self.assertEqual(overlap, set(), f"ambiguous codes present: {overlap}")

    def test_those_countries_are_still_reachable_by_name(self):
        """Dropping the code must not drop the country."""
        self.assertEqual(parse_location("Toronto, Canada").country, "Canada")
        self.assertEqual(parse_location("Mumbai, India").country, "India")
        self.assertEqual(parse_location("Berlin, Germany").country, "Germany")


class TestACodeIsAToken(unittest.TestCase):
    """`BR` is inside "Brooklyn" and `IT` inside "Detroit"."""

    def test_a_code_must_be_trailing(self):
        self.assertIsNone(country_from_code("Brooklyn, NY"))

    def test_a_code_inside_a_word_is_not_a_country(self):
        self.assertIsNone(country_from_code("Detroit, MI"))

    def test_an_unknown_code_is_none(self):
        self.assertIsNone(country_from_code("Somewhere, ZZ"))

    def test_empty(self):
        self.assertIsNone(country_from_code(""))


class TestCityNamesSharedBetweenCountries(unittest.TestCase):
    """
    R18's finding, in the location matcher: `"india"` matched inside
    "Indianapolis", and `"dublin"` inside "Dublin, Ohio". Both are real US
    cities and both would have been excluded by the country filter.

    A named US state now settles the question before any city name is read.
    """

    def test_dublin_ohio_is_not_ireland(self):
        parsed = parse_location("Dublin, Ohio")
        self.assertEqual(parsed.country, "United States")
        self.assertEqual(parsed.state, "Ohio")

    def test_birmingham_alabama_is_not_the_uk(self):
        self.assertEqual(parse_location("Birmingham, Alabama").country,
                         "United States")

    def test_ontario_california_is_not_canada(self):
        parsed = parse_location("Ontario, California")
        self.assertEqual(parsed.country, "United States")
        self.assertEqual(parsed.state, "California")

    def test_london_ontario_is_still_canada(self):
        """The mirror case: no US state named, so the province wins."""
        self.assertEqual(parse_location("London, Ontario").country, "Canada")

    def test_dublin_ireland_is_still_ireland(self):
        self.assertEqual(parse_location("Dublin, Ireland").country, "Ireland")


class TestTheVocabularyIsWideEnough(unittest.TestCase):
    """
    An unknown country is not neutral — it silently passes a filter meant to
    exclude it. "Reykjavik, Iceland" spelled the country out and was still
    invisible, because the hand-curated list held nineteen countries.
    """

    def test_iceland(self):
        self.assertEqual(parse_location("Reykjavik, Iceland").country, "Iceland")

    def test_spain(self):
        self.assertEqual(parse_location("Madrid, Spain").country, "Spain")

    def test_netherlands(self):
        self.assertEqual(parse_location("Amsterdam, Netherlands").country,
                         "Netherlands")

    def test_every_coded_country_is_also_known_by_name(self):
        for name in set(COUNTRY_CODES.values()):
            with self.subTest(country=name):
                self.assertEqual(parse_location(f"Somewhere, {name}").country,
                                 name)


class TestTheFilterNowExcludesIt(unittest.TestCase):
    """End to end: the decision, not just the parse."""

    def setUp(self):
        if not (ROOT / "user_profiles" / "yash_pathak.json").exists():
            self.skipTest("needs a real profile")
        from tools.profile import load_profile
        self.profile = load_profile("yash_pathak")

    def _decide(self, location):
        from tools.jobs.job_filter import evaluate
        from tools.search.job_listing import JobListing

        job = JobListing(
            id="x", title="Software Engineer", company="Somewhere",
            location=location, description="", apply_url="", salary_min=None,
            salary_max=None, created="", source="test", full_jd="")
        return evaluate(job, self.profile)

    def test_a_brazilian_posting_is_excluded(self):
        decision = self._decide("São Paulo, BR")
        self.assertTrue(decision.exclude)
        self.assertIn("Brazil", decision.reason)

    def test_a_us_posting_is_not(self):
        self.assertFalse(self._decide("San Francisco, CA").exclude)

    def test_an_ohio_posting_is_not_excluded_as_irish(self):
        self.assertFalse(self._decide("Dublin, Ohio").exclude)


if __name__ == "__main__":
    unittest.main()

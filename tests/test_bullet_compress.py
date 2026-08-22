"""
Bullet compression and fitting — the deterministic half of R6.

R6's whole design rests on this being reliable: the LLM writes content and
Python enforces length, so if compression is wrong the length guarantees are
wrong. These are pure functions, which makes them the cheapest useful thing
in the repo to test.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.generation import bullet_compress as bc  # noqa: E402
from tools.generation.bullet_fit import fit_bullet  # noqa: E402
import tools.generation.bullet_fit as bf  # noqa: E402


class TestIndividualTransforms(unittest.TestCase):
    def test_collapse_whitespace(self):
        self.assertEqual(bc.collapse_whitespace("a   b\tc"), "a b c")

    def test_remove_trailing_period(self):
        self.assertEqual(bc.remove_trailing_period("Built a thing."), "Built a thing")

    def test_remove_trailing_period_leaves_inner_punctuation(self):
        self.assertEqual(
            bc.remove_trailing_period("Cut p99 latency by 3.5x"),
            "Cut p99 latency by 3.5x",
        )

    def test_normalize_dashes(self):
        self.assertEqual(bc.normalize_dashes("a — b – c"), "a - b - c")

    def test_drop_articles_is_conservative(self):
        # Drops some articles but must not mangle the sentence.
        out = bc.drop_articles_conservative(
            "Built a pipeline for the team using an API"
        )
        self.assertLess(len(out), len("Built a pipeline for the team using an API"))
        self.assertIn("pipeline", out)
        self.assertIn("API", out)


class TestCompressBullet(unittest.TestCase):
    LONG = (
        "Architected an asynchronous Python serverless REST API using a "
        "dual-Lambda fan-out pattern to eliminate 25-second timeouts, cutting "
        "runtime from 10 minutes to under a second and improving reliability "
        "across the board for everyone"
    )

    def test_short_text_is_returned_untouched(self):
        text = "Built a thing"
        out, applied = bc.compress_bullet(text, target_max=200)
        self.assertEqual(out, text)
        self.assertEqual(applied, [])

    def test_long_text_is_shortened(self):
        out, applied = bc.compress_bullet(self.LONG, target_max=180)
        self.assertLess(len(out), len(self.LONG))
        self.assertTrue(applied, "expected at least one transformation to be recorded")

    def test_reports_which_stages_ran(self):
        _, applied = bc.compress_bullet(self.LONG, target_max=180)
        # Every reported stage must be a real stage name, not a free-form note.
        known = {name for name, _ in bc.COMPRESSION_STAGES}
        for stage in applied:
            self.assertIn(stage, known)

    def test_is_deterministic(self):
        first = bc.compress_bullet(self.LONG, target_max=180)
        second = bc.compress_bullet(self.LONG, target_max=180)
        self.assertEqual(first, second)

    def test_never_returns_empty_for_real_input(self):
        out, _ = bc.compress_bullet(self.LONG, target_max=10)
        self.assertTrue(out.strip(), "compression must not erase the bullet")


class TestZones(unittest.TestCase):
    """Zone boundaries decide what counts as an orphan line."""

    def test_zone_thresholds_are_ordered(self):
        self.assertLess(bf.LINE_1_END, bf.LINE_2_WELL_FILLED_START)
        self.assertLess(bf.LINE_2_WELL_FILLED_START, bf.LINE_2_END)
        self.assertLess(bf.LINE_2_END, bf.LINE_3_WELL_FILLED_START)
        self.assertLess(bf.LINE_3_WELL_FILLED_START, bf.LINE_3_END)

    def test_empty_and_line_1(self):
        self.assertEqual(bf._zone_of(0, "project"), "empty")
        self.assertEqual(bf._zone_of(bf.LINE_1_END, "project"), "line_1")

    def test_orphan_zone_sits_between_line_1_and_a_well_filled_line_2(self):
        midpoint = (bf.LINE_1_END + bf.LINE_2_WELL_FILLED_START) // 2
        self.assertEqual(bf._zone_of(midpoint, "project"), "orphan_2")

    def test_projects_have_no_third_line(self):
        # Experiences may run to three lines; projects overflow instead.
        length = bf.LINE_3_WELL_FILLED_START + 1
        self.assertEqual(bf._zone_of(length, "project"), "overflow")
        self.assertEqual(bf._zone_of(length, "experience"), "line_3")


class TestFitBullet(unittest.TestCase):
    def test_a_well_sized_bullet_is_left_alone(self):
        text = "x" * (bf.LINE_2_WELL_FILLED_START + 5)
        result = fit_bullet(text, "project")
        self.assertEqual(result.text, text)
        self.assertFalse(result.needs_review)

    def test_result_reports_lengths_consistently(self):
        text = "x" * (bf.LINE_2_WELL_FILLED_START + 5)
        result = fit_bullet(text, "project")
        self.assertEqual(result.original_length, len(text))
        self.assertEqual(result.final_length, len(result.text))

    def test_unfittable_content_is_flagged_rather_than_silently_accepted(self):
        # R6's documented caveat: when compression cannot reach a good zone,
        # the bullet goes to needs_review instead of being invented around.
        long = (
            "Architected an asynchronous Python serverless REST API using a "
            "dual-Lambda fan-out pattern to eliminate 25-second timeouts, "
            "cutting runtime from 10 minutes to under a second and improving "
            "reliability across the board for everyone"
        )
        result = fit_bullet(long, "project")
        if result.target_zone == "failed":
            self.assertTrue(result.needs_review)


if __name__ == "__main__":
    unittest.main()

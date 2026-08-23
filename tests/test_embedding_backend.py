"""
Choosing an embedding backend (R36).

Embeddings are the larger of the two API dependencies — about twenty calls a
run against three for generation — so moving them off Gemini is what lets the
pipeline discover, score and select components with no key at all.

The trap these tests guard is calibration. Raw similarity is not comparable
between backends: Gemini's cosines for this text sit around 0.3-0.9 and
model2vec's an order of magnitude lower. The first version of the local
backend inherited Gemini's floor and scored every job 0.0, so the pipeline
found nothing whatsoever.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import tools.resume.embedding_scorer as scorer  # noqa: E402
from tools.resume import local_embeddings  # noqa: E402


class _Backend:
    """Pin the active backend for a test, then restore it."""

    def __init__(self, backend, model="m", dims=256):
        self.value = (backend, model, dims)

    def __enter__(self):
        self.previous = scorer._BACKEND
        scorer._BACKEND = self.value

    def __exit__(self, *exc):
        scorer._BACKEND = self.previous


class TestCalibration(unittest.TestCase):

    def test_every_backend_has_a_calibration(self):
        for name in ("gemini", "local"):
            self.assertIn(name, scorer.CALIBRATION)

    def test_gemini_maps_its_own_range_onto_the_scale(self):
        with _Backend("gemini"):
            self.assertEqual(scorer._normalise(0.30), 0.0)
            self.assertEqual(scorer._normalise(0.90), 100.0)
            self.assertAlmostEqual(scorer._normalise(0.60), 50.0, places=1)

    def test_local_maps_its_much_lower_range_onto_the_same_scale(self):
        with _Backend("local"):
            self.assertEqual(scorer._normalise(0.0), 0.0)
            self.assertEqual(scorer._normalise(0.10), 100.0)
            self.assertAlmostEqual(scorer._normalise(0.05), 50.0, places=1)

    def test_a_local_score_is_not_flattened_by_geminis_floor(self):
        """The bug this exists to prevent: everything scoring zero."""
        with _Backend("local"):
            self.assertGreater(scorer._normalise(0.056), 0.0)

    def test_values_are_clamped_to_the_scale(self):
        with _Backend("gemini"):
            self.assertEqual(scorer._normalise(-1.0), 0.0)
            self.assertEqual(scorer._normalise(5.0), 100.0)

    def test_an_unknown_backend_falls_back_rather_than_raising(self):
        with _Backend("something-else"):
            self.assertIsInstance(scorer._normalise(0.5), float)


class TestBackendResolution(unittest.TestCase):

    def setUp(self):
        self.previous = scorer._BACKEND
        scorer._BACKEND = None

    def tearDown(self):
        scorer._BACKEND = self.previous

    def test_the_choice_is_made_once_and_reused(self):
        """A run that mixed backends would compare incomparable vectors."""
        first = scorer.active_backend()
        self.assertEqual(scorer.active_backend(), first)

    def test_it_reports_a_name_a_model_and_a_width(self):
        name, model, dims = scorer.active_backend()
        self.assertIn(name, ("gemini", "local"))
        self.assertTrue(model)
        self.assertIsInstance(dims, int)


class TestLocalBackend(unittest.TestCase):

    def test_availability_is_answerable_without_loading_a_model(self):
        self.assertIsInstance(local_embeddings.is_available(), bool)

    def test_a_failed_embed_returns_empty_rather_than_raising(self):
        # Matches the Gemini path, so callers need not know which backend
        # produced a miss.
        self.assertEqual(local_embeddings.embed("text", "no/such/model"), [])

    def test_unknown_dimensions_report_zero_rather_than_guessing(self):
        # A guessed width would be silently wrong and the cache's dimension
        # guard would reject every entry written against it.
        self.assertEqual(local_embeddings.dimensions("no/such/model"), 0)


if __name__ == "__main__":
    unittest.main()

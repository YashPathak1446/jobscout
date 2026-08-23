"""
The depth drop must rank on the composite, not the embedding (Q18 / R23).

Generation may drop the weakest project to give the survivors more bullets.
It used to rank candidates by `importance_weight + embedding_similarity` —
a number selection never used and which cannot see *why* a project was
chosen. A project promoted by strong JD-specific trigger evidence is exactly
the one that scores badly on embedding alone, so the stage reliably threw out
the most relevant project on the resume.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.generation_agent import GenerationAgent  # noqa: E402


def _agent():
    """An instance without __init__ — the method only reads a class attribute."""
    return GenerationAgent.__new__(GenerationAgent)


class TestDepthDrop(unittest.TestCase):

    def setUp(self):
        self.agent = _agent()
        self.ids = ["proj_a", "proj_b", "proj_c", "proj_mobile"]
        self.importance = {
            "proj_a": "high", "proj_b": "medium",
            "proj_c": "medium", "proj_mobile": "low",
        }
        # The Ramp shape: the mobile project embeds worst but wins on the
        # composite, because a full 0.20 conditional bonus was earned.
        self.embedding = {
            "proj_a": 0.61, "proj_b": 0.56, "proj_c": 0.54, "proj_mobile": 0.58,
        }
        self.composite = {
            "proj_a": 1.01, "proj_b": 0.86, "proj_c": 0.84, "proj_mobile": 0.91,
        }

    def test_keeps_a_low_tier_project_that_wins_on_the_composite(self):
        kept = self.agent._decide_project_count(
            list(self.ids), self.embedding, self.importance,
            proj_composite=self.composite,
        )
        self.assertIn("proj_mobile", kept)
        self.assertEqual(len(kept), 4)

    def test_the_old_embedding_ranking_would_have_dropped_it(self):
        """Pins the bug itself, so the regression is impossible to reintroduce."""
        kept = self.agent._decide_project_count(
            list(self.ids), self.embedding, self.importance, proj_composite=None,
        )
        self.assertNotIn("proj_mobile", kept)

    def test_still_drops_the_project_that_is_genuinely_weakest(self):
        composite = dict(self.composite, proj_mobile=0.40)
        kept = self.agent._decide_project_count(
            list(self.ids), self.embedding, self.importance,
            proj_composite=composite,
        )
        self.assertNotIn("proj_mobile", kept)
        self.assertEqual(len(kept), 3)

    def test_never_drops_below_four_projects(self):
        three = self.ids[:3]
        kept = self.agent._decide_project_count(
            list(three), self.embedding, self.importance, proj_composite=self.composite,
        )
        self.assertEqual(kept, three)

    def test_does_not_drop_when_the_weakest_is_not_low_importance(self):
        importance = dict(self.importance, proj_mobile="medium")
        composite = dict(self.composite, proj_mobile=0.40)
        kept = self.agent._decide_project_count(
            list(self.ids), self.embedding, importance, proj_composite=composite,
        )
        self.assertEqual(len(kept), 4)

    def test_does_not_drop_when_nothing_would_benefit(self):
        # No high-importance project means the freed bullet has no better home.
        importance = {k: ("medium" if v == "high" else v)
                      for k, v in self.importance.items()}
        composite = dict(self.composite, proj_mobile=0.40)
        kept = self.agent._decide_project_count(
            list(self.ids), self.embedding, importance, proj_composite=composite,
        )
        self.assertEqual(len(kept), 4)

    def test_falls_back_per_component_when_the_composite_is_partial(self):
        partial = {"proj_a": 1.01}
        kept = self.agent._decide_project_count(
            list(self.ids), self.embedding, self.importance, proj_composite=partial,
        )
        self.assertEqual(len(kept), 3)


if __name__ == "__main__":
    unittest.main()


class TestPromoteOnEvidence(unittest.TestCase):
    """A tier is a claim about the user; a trigger is a claim about the job (R27)."""

    def setUp(self):
        self.agent = _agent()
        self.importance = {"p_low": "low", "p_med": "medium", "p_high": "high"}

    def test_strong_evidence_lifts_low_to_medium(self):
        out = self.agent._promote_on_evidence(
            ["p_low"], self.importance, {"p_low": 0.20})
        self.assertEqual(out["p_low"], "medium")

    def test_two_hits_is_the_boundary_and_qualifies(self):
        out = self.agent._promote_on_evidence(
            ["p_low"], self.importance, {"p_low": 0.14})
        self.assertEqual(out["p_low"], "medium")

    def test_a_single_incidental_hit_does_not_qualify(self):
        # R14's whole complaint was one passing mention carrying a component.
        out = self.agent._promote_on_evidence(
            ["p_low"], self.importance, {"p_low": 0.07})
        self.assertEqual(out["p_low"], "low")

    def test_no_evidence_leaves_the_tier_alone(self):
        out = self.agent._promote_on_evidence(
            ["p_low"], self.importance, {})
        self.assertEqual(out["p_low"], "low")

    def test_promotion_stops_at_medium(self):
        """Evidence says 'this matters here', not 'this is your best work'."""
        out = self.agent._promote_on_evidence(
            ["p_low"], self.importance, {"p_low": 0.20})
        self.assertNotEqual(out["p_low"], "high")

    def test_medium_and_high_are_never_altered(self):
        out = self.agent._promote_on_evidence(
            ["p_med", "p_high"], self.importance,
            {"p_med": 0.20, "p_high": 0.20})
        self.assertEqual(out["p_med"], "medium")
        self.assertEqual(out["p_high"], "high")

    def test_the_input_map_is_not_mutated(self):
        original = dict(self.importance)
        self.agent._promote_on_evidence(["p_low"], self.importance, {"p_low": 0.20})
        self.assertEqual(self.importance, original)


class TestAllocationBudgetIsPreserved(unittest.TestCase):
    """Promotion redistributes bullets; it must never create them (page limit)."""

    def test_total_allocated_is_unchanged_by_promotion(self):
        agent = _agent()
        ids = ["a", "b", "c", "d"]
        scores = {"a": 0.9, "b": 0.8, "c": 0.7, "d": 0.85}
        plain = {"a": "high", "b": "medium", "c": "medium", "d": "low"}
        promoted = agent._promote_on_evidence(ids, plain, {"d": 0.20})

        before = agent._allocate_with_importance(
            component_ids=ids, scores=scores, importance=plain,
            total_budget=7, global_max=2)
        after = agent._allocate_with_importance(
            component_ids=ids, scores=scores, importance=promoted,
            total_budget=7, global_max=2)

        self.assertEqual(sum(before.values()), sum(after.values()))
        self.assertGreater(after["d"], before["d"], "promotion should buy depth")

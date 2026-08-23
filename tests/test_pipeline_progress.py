"""
Progress reporting and checkpoint resolution (R25).

The pipeline runs for minutes and used to report only by logging, which a
terminal shows live and a UI cannot consume. Worse, checkpoints were literal
`input()` calls with `checkpoint_after_scoring` defaulting to True — so the
default path for a bootstrapped profile would block a UI on stdin forever.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.orchestrator import (  # noqa: E402
    JobScoutOrchestrator,
    StageProgress,
    _CheckpointStop,
)


def _orch():
    """An instance without __init__ — these methods touch only the callbacks."""
    o = JobScoutOrchestrator.__new__(JobScoutOrchestrator)
    o._on_progress = None
    o._on_checkpoint = None
    return o


class TestStageProgress(unittest.TestCase):

    def test_fraction_is_the_ratio(self):
        self.assertAlmostEqual(StageProgress("analysis", 5, 20).fraction, 0.25)

    def test_unknown_total_is_zero_not_a_crash(self):
        # Discovery cannot know how many jobs exist until it has looked, so it
        # reports total=0. A progress bar must still be able to consume that.
        self.assertEqual(StageProgress("discovery", 0, 0).fraction, 0.0)

    def test_fraction_is_clamped_to_one(self):
        self.assertEqual(StageProgress("generation", 7, 3).fraction, 1.0)

    def test_message_is_optional(self):
        self.assertEqual(StageProgress("analysis", 1, 2).message, "")


class TestEmit(unittest.TestCase):

    def test_no_callback_is_a_no_op(self):
        _orch()._emit("analysis", 1, 2, "x")  # must not raise

    def test_callback_receives_a_stage_progress(self):
        seen = []
        o = _orch()
        o._on_progress = seen.append
        o._emit("analysis", 3, 10, "scoring")

        self.assertEqual(len(seen), 1)
        self.assertIsInstance(seen[0], StageProgress)
        self.assertEqual((seen[0].stage, seen[0].done, seen[0].total), ("analysis", 3, 10))

    def test_a_raising_callback_does_not_take_the_pipeline_down(self):
        """A UI failing to draw a bar must not lose a run that spent quota."""
        def boom(_):
            raise RuntimeError("render failed")

        o = _orch()
        o._on_progress = boom
        o._emit("generation", 1, 3)  # must not propagate


class TestCheckpointResolution(unittest.TestCase):

    def test_callback_decides_and_receives_the_items(self):
        got = {}

        def decide(stage, items):
            got["stage"], got["n"] = stage, len(items)
            return True

        o = _orch()
        o._on_checkpoint = decide

        self.assertTrue(o._request_checkpoint("analysis", [1, 2, 3]))
        self.assertEqual(got, {"stage": "analysis", "n": 3})

    def test_a_falsey_answer_means_stop(self):
        o = _orch()
        o._on_checkpoint = lambda stage, items: False
        self.assertFalse(o._request_checkpoint("discovery", []))

    def test_answer_is_coerced_to_bool(self):
        o = _orch()
        o._on_checkpoint = lambda stage, items: "yes"
        self.assertIs(o._request_checkpoint("discovery", []), True)

    def test_stdin_is_never_touched_when_a_callback_is_supplied(self):
        """The whole point: a UI must never reach the terminal prompt."""
        import builtins

        original, called = builtins.input, []
        builtins.input = lambda *a, **k: called.append(1) or "y"
        try:
            o = _orch()
            o._on_checkpoint = lambda stage, items: True
            o._request_checkpoint("analysis", [])
        finally:
            builtins.input = original

        self.assertEqual(called, [], "terminal prompt was reached despite a callback")


class TestStopSignal(unittest.TestCase):

    def test_checkpoint_stop_is_an_exception_run_can_catch(self):
        self.assertTrue(issubclass(_CheckpointStop, Exception))


if __name__ == "__main__":
    unittest.main()

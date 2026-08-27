"""
The preferences screen's Save button, and who it let through.

R68 replaced "pick your seniority levels" with "how many years have you
worked", because the second is the question a person can answer and the code
translates it back to levels anyway. The override multiselect stayed, and it is
*deliberately empty* when nobody overrides — that is what lets the levels
follow the years, and what lets an override outlive later edits.

The Save button was gated on that empty box:

    disabled=not (roles and seniority)

So for every profile that has never overridden — which is every profile a new
user builds — the button was disabled, permanently, with nothing on screen
saying why. The only way forward was to open a collapsed expander titled
"Choose the levels yourself" and pick by hand: exactly the question R68 had
just removed.

Measured, and it is the two-path shape again. `yash_pathak` still carries
`seniority: ["new grad", "entry level", "junior"]` from before R68 changed the
question, so the author's button was always enabled and the wall was invisible
from his machine. A profile imported today has `seniority: []`.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from agents.orchestrator import derived_levels, seniority_levels  # noqa: E402


def in_force(stored_seniority, years):
    """
    What the screen says is in force: the override if there is one, else what
    the years derive. This mirrors `app.py` rather than importing it, because
    `app.py` is a Streamlit module that cannot be imported without a runtime.
    """
    levels = seniority_levels()
    override = [s for s in stored_seniority or [] if s in levels]
    return override or derived_levels(years)


class TestTheLevelsInForceAreNeverEmpty(unittest.TestCase):
    """
    The gate can only be safe if the thing it gates on always has a value.
    """

    def test_every_plausible_number_of_years_derives_something(self):
        for years in range(0, 41):
            self.assertTrue(
                derived_levels(years),
                f"{years} years derives no levels, so a button gated on them "
                "would be disabled with no way to proceed")

    def test_an_unanswered_number_of_years_derives_nothing_on_purpose(self):
        """
        The hole in the test above: it walks every *answer* and never the
        absence of one. `derived_levels(None)` is `[]` by design — `/api/levels`
        says so in as many words — so a gate on the levels in force is dead for
        anyone who declines to state their years, which is a state the field
        allows and the pipeline handles.

        Stated here rather than fixed, because `[]` is the correct answer. What
        was wrong was the gate reading it as "not ready".
        """
        self.assertEqual(derived_levels(None), [])
        self.assertEqual(in_force([], None), [])

    def test_a_profile_that_never_overrode_still_has_levels_in_force(self):
        """The new-user case, which is the one that was broken."""
        self.assertTrue(in_force([], 0))
        self.assertTrue(in_force([], 6))
        self.assertEqual(in_force([], 6), derived_levels(6))

    def test_an_override_wins_over_the_years(self):
        self.assertEqual(in_force(["staff"], 0), ["staff"])

    def test_an_override_of_junk_falls_back_rather_than_emptying(self):
        """
        A stale profile naming a level that no longer exists must not empty
        the set — that would reintroduce the wall through the back door.
        """
        self.assertEqual(in_force(["archmage"], 6), derived_levels(6))


class TestTheSaveGateLetsANewProfileThrough(unittest.TestCase):

    def gate_disabled(self, roles, stored_seniority, years):
        """
        The button's own condition, as both screens now spell it: target roles
        and nothing else.

        `in_force` was in here, and it is empty whenever the years are
        unanswered and nothing is overridden — so the wall R72 tore down was
        rebuilt one field over, silently, on both UIs at once. The arguments
        are kept in the signature because the tests below are about who gets
        through, and the point is that these two no longer decide it.
        """
        return not roles

    def test_a_freshly_imported_profile_can_continue(self):
        """
        Six years, two target roles, no override — a stranger who answered
        the question the screen actually asks.
        """
        self.assertFalse(
            self.gate_disabled(["Software Engineer", "Backend Engineer"], [], 6),
            "the save button is disabled for a profile that answered "
            "everything the screen asked")

    def test_the_old_gate_would_have_blocked_that_profile(self):
        """
        The regression, stated so it cannot come back quietly. This is the
        condition that shipped.
        """
        roles, stored = ["Software Engineer"], []
        old_gate_disabled = not (roles and stored)
        self.assertTrue(old_gate_disabled,
                        "this test no longer describes the bug it guards")
        self.assertFalse(self.gate_disabled(roles, stored, 6))

    def test_no_target_roles_still_blocks(self):
        """The gate must still gate. An empty search is not a search."""
        self.assertTrue(self.gate_disabled([], [], 6))

    def test_declining_to_state_your_years_does_not_block(self):
        """
        The second wall, and the one this fix is for. Years unanswered, no
        override, two target roles — the caption reads "any level", the filter
        reads it as the widest tolerance rather than as zero, and the run
        works. There was nothing to fix on that screen and no way off it.
        """
        self.assertFalse(self.gate_disabled(["Software Engineer"], [], None))

    def test_the_second_gate_would_have_blocked_that_profile(self):
        """The regression, stated so it cannot come back quietly either."""
        roles, stored, years = ["Software Engineer"], [], None
        second_gate_disabled = not (roles and in_force(stored, years))
        self.assertTrue(second_gate_disabled,
                        "this test no longer describes the bug it guards")
        self.assertFalse(self.gate_disabled(roles, stored, years))

    def test_the_author_profile_was_never_blocked(self):
        """
        Why nobody saw it. Kept as a test because the asymmetry is the
        finding, not the fix.
        """
        self.assertFalse(
            self.gate_disabled(["Software Engineer"],
                               ["new grad", "entry level", "junior"], 0))


if __name__ == "__main__":
    unittest.main()

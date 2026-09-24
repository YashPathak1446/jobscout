"""
A returning hosted user lands on their board, not an empty wizard (R122).

Found on the first live deploy: signing in set the view to the wizard's first
step for every account, and nothing there led to the board, so a returning
friend's jobs, resumes and marks looked gone. The data was on the server.

The routing is React's, and the web app has no test runner, so this checks
the source. It was also driven once in Chromium against a hosted build (the
R122 entry says what was seen): an account with a board opened on the board
with "Edit setup" and every wizard step reachable and prefilled, and an
account with no profile opened on the wizard.
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

APP = (ROOT / "web/src/App.tsx").read_text(encoding="utf-8")
WIZARD = (ROOT / "web/src/components/Wizard.tsx").read_text(encoding="utf-8")


class TestWhereASignedInAccountStarts(unittest.TestCase):

    def test_signing_in_asks_whether_there_is_a_board(self):
        on_signed_in = APP[APP.index("onSignedIn="):APP.index("onSignedIn=") + 300]
        self.assertIn("openHome()", on_signed_in)
        self.assertNotIn("setView('setup')", on_signed_in)

    def test_a_session_already_signed_in_asks_too(self):
        self.assertRegex(APP, r"else if \(s\.mode === 'hosted'\) openHome\(\)")

    def test_a_profile_opens_the_board_and_none_opens_the_wizard(self):
        body = APP[APP.index("function openHome()"):]
        body = body[:body.index("\n  }\n")]
        self.assertRegex(body, r"h\.profiles\.length > 0\)[\s\S]*setView\('board'\)")
        self.assertRegex(body, r"else \{\s*setView\('setup'\)")

    def test_not_yet_known_is_not_rendered_as_either(self):
        """The 'home' beat shows neither the wizard nor a board."""
        self.assertRegex(APP, r"if \(view === 'home'\) \{\s*return \(")

    def test_the_board_offers_edit_setup(self):
        self.assertIn("Edit setup", APP)

    def test_edit_setup_opens_every_step(self):
        self.assertIn("useState(profile ? STEPS.length - 1 : 0)", WIZARD)


if __name__ == "__main__":
    unittest.main()

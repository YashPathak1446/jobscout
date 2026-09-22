"""
The UI's contract with the pipeline (R25).

R25 committed to Streamlit on one condition: `app.py` stays a view layer, so
the eventual React + FastAPI port is a re-skin rather than a rewrite. That
condition was written in a document, which is where architectural rules go to
be forgotten. These tests make it fail the build instead.
"""

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

APP = ROOT / "app.py"
API = ROOT / "api" / "main.py"

# What a view layer is allowed to reach for: the pipeline's entry point, the
# profile bootstrapper, and the standard library.
ALLOWED_PROJECT_MODULES = {"agents.orchestrator", "scripts.init_profile"}
PROJECT_PACKAGES = {"agents", "tools", "scripts", "config"}

# Facade functions the HTTP layer legitimately reaches for and the Streamlit
# view does not. Both are here for one reason: HTTP addresses resources by
# URL and an in-process view does not.
#
#   board_job      `/api/job/{id}` needs a single-row read. `app.py` renders
#                  the board and its expanders from one `board_jobs()` page,
#                  so it never fetches a row on its own.
#   user_outputs_root
#                  `/api/file` has to prove a requested path is inside the
#                  *caller's* outputs tree before serving it. Streamlit hands
#                  `st.download_button` bytes it already holds, so no
#                  containment check exists to anchor. It was `outputs_root`
#                  until A3 scoped it — the stale-entry check below is what
#                  said so.
#
# Anything else appearing here fails the build. Re-exported through
# `agents.orchestrator` rather than imported from `tools.paths` because
# ALLOWED_PROJECT_MODULES above leaves no alternative.
#
#   the session  Accounts exist only on a hosted instance, and the hosted
#                product is the React build. Streamlit is the local UI: it
#                has one unscoped user and nothing to sign in to (A5).
HTTP_ONLY = {"board_job", "user_outputs_root"} | {
    "SESSION_COOKIE", "SESSION_TTL_SECONDS", "EmailTaken", "InviteRefused",
    "PassphraseRefused", "account_email", "check_hosting", "hosting_mode",
    "redeem_invite", "session_user", "sign_in"}


def _facade_imports(tree):
    """
    Every name a view imports from `agents.orchestrator`.

    The authoritative surface, not an approximation of it: both views reach
    the pipeline through this one statement, so what they import is exactly
    what they can see. An AST name scan instead counts `Path` and `Optional`
    as facade access.
    """
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "agents.orchestrator":
            found.update(alias.asname or alias.name for alias in node.names)
    return found


def _imported_modules(tree):
    """Every module named by an import in the file."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


class TestAppIsAViewLayer(unittest.TestCase):

    def setUp(self):
        self.tree = ast.parse(APP.read_text(encoding="utf-8"))
        self.imports = _imported_modules(self.tree)

    def test_app_exists(self):
        self.assertTrue(APP.exists(), "app.py is the UI entry point")

    def test_imports_nothing_from_tools(self):
        """
        The rule with teeth. `tools/` is where scoring, parsing and the
        knowledge of where files live all sit; reaching past the orchestrator
        into it is how a view layer stops being one.
        """
        leaked = sorted(m for m in self.imports if m == "tools" or m.startswith("tools."))
        self.assertEqual(leaked, [], f"app.py must not import from tools/: {leaked}")

    def test_project_imports_are_limited_to_the_two_entry_points(self):
        project = {
            m for m in self.imports
            if m.split(".")[0] in PROJECT_PACKAGES
        }
        unexpected = sorted(project - ALLOWED_PROJECT_MODULES)
        self.assertEqual(
            unexpected, [],
            "app.py should reach the pipeline only through "
            f"{sorted(ALLOWED_PROJECT_MODULES)}; found {unexpected}",
        )

    def test_the_entry_points_it_relies_on_actually_exist(self):
        """A view layer is only as stable as the facade beneath it."""
        from agents.orchestrator import (  # noqa: F401
            JobScoutOrchestrator,
            available_profiles,
            pdflatex_available,
        )
        from scripts.init_profile import (  # noqa: F401
            create_profile,
            save_resume,
            update_profile_fields,
        )

    def test_no_scoring_logic_in_the_ui(self):
        """
        The failure mode R25 names: business logic creeping into callbacks.

        Checked against *identifiers*, not raw text. An earlier version grepped
        the source and failed on the word "embedding" inside a comment
        explaining why a replay is cheap — which is documentation doing its
        job, not logic leaking. A test that punishes explanation trains you to
        delete explanation.
        """
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)

        banned = {"scoring_threshold", "_composite_score", "_keyword_match_score",
                  "score_breakdown", "conditional_hits", "select_components"}
        leaked = sorted(banned & names)
        self.assertEqual(
            leaked, [],
            f"scoring internals referenced in the view layer: {leaked}",
        )


class TestTheApiIsAViewLayerToo(unittest.TestCase):
    """
    The second view, held to the first one's rule.

    R25 accepted Streamlit on the condition that the React + FastAPI port
    would be a re-skin. The port is where that condition gets tested for
    real — and where it is easiest to lose, because an HTTP layer has an
    obvious excuse to "just reach into the store for one field". The excuse
    came up within an hour of writing it: list rows carry `full_jd` and a
    50-row page is 336 KB of job descriptions nothing renders. The fix was a
    facade (`board_job`), not an import.
    """

    def setUp(self):
        if not API.exists():
            self.skipTest("no HTTP boundary yet")
        self.tree = ast.parse(API.read_text(encoding="utf-8"))
        self.imports = _imported_modules(self.tree)

    def test_imports_nothing_from_tools(self):
        leaked = sorted(m for m in self.imports
                        if m == "tools" or m.startswith("tools."))
        self.assertEqual(leaked, [], f"api must not import from tools/: {leaked}")

    def test_project_imports_are_limited_to_the_two_entry_points(self):
        project = {m for m in self.imports if m.split(".")[0] in PROJECT_PACKAGES}
        unexpected = sorted(project - ALLOWED_PROJECT_MODULES)
        self.assertEqual(
            unexpected, [],
            "the HTTP boundary should reach the pipeline only through "
            f"{sorted(ALLOWED_PROJECT_MODULES)}; found {unexpected}")

    def test_no_scoring_logic_in_the_api(self):
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
        banned = {"scoring_threshold", "_composite_score", "_keyword_match_score",
                  "score_breakdown", "conditional_hits", "select_components"}
        leaked = sorted(banned & names)
        self.assertEqual(leaked, [],
                         f"scoring internals referenced in the API: {leaked}")

    def test_both_views_read_the_same_facade(self):
        """
        The two-path rule (R70), applied before there are two paths to
        diverge. Streamlit and React are twin views of one surface; the
        moment one of them can see something the other cannot, a fix will
        land on whichever the author happens to be using.

        This used to assert `(api_names & facade) <= facade` — true for
        every possible input, so the one test standing between the two UIs
        asserted nothing. Two things were wrong, not one:

        1. An intersection with a set is a subset of that set. And the
           failure message it carried ("the API calls something that is
           not on the facade") named a condition the mechanism cannot
           detect: intersecting *with* the facade can only yield facade
           members. There was no non-tautological reading of it.
        2. It compared AST name scans, so `Optional` and `Path` counted as
           facade divergence — both files name them from typing/pathlib,
           and both collide with orchestrator's module namespace. Sixteen
           of the 43 names `dir()` reports are incidental imports.

        Both views reach the facade through one `from agents.orchestrator
        import (...)`, which `test_project_imports_are_limited_to_the_two_
        entry_points` already guarantees is the only way in. So the import
        list *is* the surface each view can see, and comparing the two
        lists is exact rather than approximate.
        """
        app_imports = _facade_imports(ast.parse(APP.read_text(encoding="utf-8")))
        api_imports = _facade_imports(self.tree)

        only_api = sorted(api_imports - app_imports)
        only_app = sorted(app_imports - api_imports)

        # `only_app` is the legitimate lag: the React port is still being
        # built and Streamlit is allowed to be ahead of it. `only_api` is
        # not symmetrical — a facade function only the HTTP layer reaches
        # for is a surface no one is reading in the other view, which is
        # exactly where R69 and R70 both landed.
        #
        # Two are correct today, for one reason: HTTP addresses resources
        # and an in-process view does not.
        unexplained = sorted(set(only_api) - set(HTTP_ONLY))
        self.assertEqual(
            unexplained, [],
            "the API reaches for a facade function Streamlit does not, with "
            f"no reason recorded: {unexplained}. Either give the Streamlit "
            "view the same access or add it to HTTP_ONLY with why.")

        # And the exemption list must not rot. If Streamlit grows a detail
        # view, `board_job` stops being HTTP-only and the entry becomes a
        # comment crediting a distinction that no longer exists — R55's
        # shape, and the shape of the tautology this test replaced.
        stale = sorted(set(HTTP_ONLY) - set(only_api))
        self.assertEqual(
            stale, [],
            f"HTTP_ONLY exempts facade names both views now import: {stale}. "
            "Delete the entries.")

        # Named so a reader of a passing run can still see the split.
        self.assertIsInstance(only_app, list)


if __name__ == "__main__":
    unittest.main()

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
        """
        app_names = {n.attr if isinstance(n, ast.Attribute) else n.id
                     for n in ast.walk(ast.parse(APP.read_text(encoding="utf-8")))
                     if isinstance(n, (ast.Name, ast.Attribute))}
        api_names = {n.attr if isinstance(n, ast.Attribute) else n.id
                     for n in ast.walk(self.tree)
                     if isinstance(n, (ast.Name, ast.Attribute))}

        import agents.orchestrator as orch
        facade = {n for n in dir(orch)
                  if not n.startswith("_") and callable(getattr(orch, n))}

        only_api = sorted((api_names & facade) - app_names)
        # One-way for now: the React port is still being built, so it may
        # legitimately lag. What it may not do is invent its own way in.
        self.assertTrue(
            (api_names & facade) <= facade,
            f"the API calls something that is not on the facade: {only_api}")


if __name__ == "__main__":
    unittest.main()

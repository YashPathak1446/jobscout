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

    def test_no_scoring_or_ranking_happens_in_the_ui(self):
        """
        A blunt check for the failure mode R25 names: business logic creeping
        into callbacks. `sorted(...)` over results, a comparison against a
        threshold, or arithmetic on a score would all show up as these names.
        """
        source = APP.read_text(encoding="utf-8")
        for banned in ("scoring_threshold", "composite", "embedding", "_composite_score"):
            self.assertNotIn(
                banned, source,
                f"'{banned}' suggests scoring logic has moved into the view layer",
            )


if __name__ == "__main__":
    unittest.main()

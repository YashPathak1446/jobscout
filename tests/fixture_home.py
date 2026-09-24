"""
A data home holding one committed fixture user, for a test's duration.

Not a test module (discovery collects `test*.py`). Tests that exercise a
mechanism, not one person's data, used to load `yash_pathak`. His profile is
not committed, so on a clean clone, in CI and in the image they skipped: 36
of them, of which these helpers now carry some (Q65). A fixture is copied into
a temporary `JOBSCOUT_HOME` rather than read in place, so the test reads
through the same path resolution a real user's data does, and never through
the checkout's own `user_profiles/`.

Priya has no projects, so anything about projects wants Rohan.
"""

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent

# The committed fixture users, each with one experience id every test here may
# rely on. A fixture that loses its id should fail, not skip.
FIXTURES = {
    "priya_raghunathan": "exp_wayfair",
    "rohan_deshmukh": "exp_vertex_technologies_ai_ml_intern",
}


@contextmanager
def fixture_home(*names):
    """A temporary data home with the named fixtures' profiles and resumes."""
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / "user_profiles").mkdir()
        (home / "data" / "master_resumes").mkdir(parents=True)
        for name in names:
            shutil.copy(ROOT / "user_profiles" / f"{name}.json",
                        home / "user_profiles")
            shutil.copy(ROOT / "data" / "master_resumes" / f"{name}.tex",
                        home / "data" / "master_resumes")
        with mock.patch.dict(os.environ, {"JOBSCOUT_HOME": str(home)}):
            yield home


def generation_agent_for(name):
    """(agent, parser) for a fixture, in whatever data home is active."""
    from agents.generation_agent import GenerationAgent
    from agents.orchestrator import master_resume_path
    from tools.profile import load_profile
    from tools.resume import ResumeParser

    profile = load_profile(name, user_id=None)
    parser = ResumeParser(
        master_resume_path(None, profile.resume_preferences.master_resume_path),
        skip_embeddings=True, user_id=None)
    return GenerationAgent(profile, parser, generate_pdf=False), parser

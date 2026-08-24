"""
Confirming an extracted resume before anything is saved (R41).

R33 required this screen and R39 shipped the import without it, which left a
misread resume discoverable only by opening the generated `.tex` — the exact
failure R33 predicted. The guarantee is narrow and worth stating plainly:

    between uploading a PDF and a file being written, a person sees every
    field and can change it.

These drive the real app through Streamlit's own harness rather than testing
the screen's helpers in isolation, because the thing worth protecting is the
flow, not the functions. A test that called `save_extracted` directly would
still pass on a version of `app.py` that skipped the screen entirely.
"""

import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(ROOT / "app.py")
RESUMES = ROOT / "data" / "master_resumes"
PROFILES = ROOT / "user_profiles"

STEM = "_confirm_test"


def _schema():
    """An extraction with one of everything, including a wrong field."""
    return {
        # `github` holds visible link text rather than a URL — the exact
        # misread R39 found in a real PDF, and a thing this screen exists to
        # let a person fix.
        "contact": {"name": "Jane Doe", "email": "jane@example.com",
                    "phone": "555-0100", "github": "GitHub", "linkedin": ""},
        "education": [{"school": "UCI", "degree": "BS Computer Science",
                       "location": "Irvine, CA", "dates": "2021 - 2025"}],
        "experiences": [{"company": "Acme", "title": "Engineer",
                         "location": "Remote", "dates": "2024",
                         "bullets": ["Built a thing", "Shipped the thing"]}],
        "projects": [{"name": "Thing Builder", "tech": "Python",
                      "dates": "2024", "bullets": ["Built it"]}],
        "skills": {"Languages": "Python, Go"},
    }


def _pending(schema=None):
    return {
        "schema": schema if schema is not None else _schema(),
        "source": str(RESUMES / f"{STEM}.pdf"),
        "name": STEM,
        "force": True,
    }


def _at(pending=None):
    app = AppTest.from_file(APP, default_timeout=60)
    app.session_state["step"] = 0
    if pending is not None:
        app.session_state["pending_import"] = pending
    return app


class TestNothingIsWrittenBeforeConfirmation(unittest.TestCase):
    """The whole point of the screen, stated as a test."""

    def setUp(self):
        RESUMES.mkdir(parents=True, exist_ok=True)
        self.tex = RESUMES / f"{STEM}.tex"
        self.profile = PROFILES / f"{STEM}.json"
        self._clean()

    def tearDown(self):
        self._clean()

    def _clean(self):
        self.tex.unlink(missing_ok=True)
        self.profile.unlink(missing_ok=True)
        for leftover in PROFILES.glob(f"{STEM}.*.bak.json"):
            leftover.unlink()

    def test_showing_the_screen_writes_no_resume_and_no_profile(self):
        app = _at(_pending())
        app.run()

        self.assertEqual(app.subheader[0].value, "Is this right?")
        self.assertFalse(self.tex.exists(), "no resume until confirmed")
        self.assertFalse(self.profile.exists(), "no profile until confirmed")

    def test_starting_over_discards_the_extraction(self):
        app = _at(_pending())
        app.run()

        [b for b in app.button if b.label == "Start over"][0].click().run()

        self.assertIsNone(app.session_state["pending_import"])
        self.assertFalse(self.tex.exists())


class TestTheScreenShowsEveryField(unittest.TestCase):

    def test_every_extracted_field_is_editable(self):
        app = _at(_pending())
        app.run()

        # 5 contact + 4 education + 4 experience + 3 project + 1 skill.
        self.assertEqual(len(app.text_input), 17)
        # One bullets box per experience and per project.
        self.assertEqual(len(app.text_area), 2)
        # One "include this" per entry.
        self.assertEqual(len(app.checkbox), 2)

    def test_the_counts_are_shown_before_the_detail(self):
        app = _at(_pending())
        app.run()
        metrics = {m.label: m.value for m in app.metric}
        self.assertEqual(metrics["Experiences"], "1")
        self.assertEqual(metrics["Projects"], "1")
        self.assertEqual(metrics["Skill groups"], "1")

    def test_text_that_could_not_be_split_is_surfaced_not_dropped(self):
        """
        The heuristic floor keeps what it could not parse under `_unparsed`.

        Arriving with no model gets you a screen with something on it. Saying
        nothing about the leftover text would be worse than the misparse,
        because the user would believe the short answer was the whole resume.
        """
        schema = _schema()
        schema["_unparsed"] = {"experiences": ["Some Company 2024",
                                               "did a thing nobody could parse"]}
        app = _at(_pending(schema))
        app.run()

        warnings = " ".join(w.value for w in app.warning)
        self.assertIn("could not be split", warnings)

    def test_a_clean_extraction_raises_no_warning(self):
        app = _at(_pending())
        app.run()
        self.assertEqual(len(app.warning), 0)


class TestCorrectionsReachTheSavedResume(unittest.TestCase):
    """A screen that shows the fields but ignores the edits is theatre."""

    def setUp(self):
        RESUMES.mkdir(parents=True, exist_ok=True)
        self.tex = RESUMES / f"{STEM}.tex"
        self.profile = PROFILES / f"{STEM}.json"
        self._clean()

    def tearDown(self):
        self._clean()

    def _clean(self):
        self.tex.unlink(missing_ok=True)
        self.profile.unlink(missing_ok=True)
        for leftover in PROFILES.glob(f"{STEM}.*.bak.json"):
            leftover.unlink()

    def _confirm(self, app):
        [b for b in app.button
         if b.label.startswith("This is right")][0].click().run()

    def test_an_edited_field_is_what_gets_saved(self):
        app = _at(_pending())
        app.run()

        app.text_input(key="contact-github").set_value(
            "https://github.com/janedoe")
        app.text_input(key="contact-name").set_value("Jane Q. Doe")
        self._confirm(app)

        self.assertEqual(len(app.exception), 0, app.exception)
        written = self.tex.read_text(encoding="utf-8")
        self.assertIn("github.com/janedoe", written)
        self.assertIn("Jane Q. Doe", written)
        self.assertNotIn("Jane Doe}", written, "the original name was replaced")

    def test_edited_bullets_are_what_gets_saved(self):
        app = _at(_pending())
        app.run()

        app.text_area(key="experience-0-bullets").set_value(
            "A corrected first bullet\nA corrected second bullet")
        self._confirm(app)

        written = self.tex.read_text(encoding="utf-8")
        self.assertIn("A corrected first bullet", written)
        self.assertNotIn("Shipped the thing", written)

    def test_unticking_an_entry_drops_it(self):
        """
        Extraction can invent an entry out of a heading it misread, so
        correction alone is not enough — there has to be a way to say "this
        is not a job".
        """
        app = _at(_pending())
        app.run()

        app.checkbox(key="keep-project-0").uncheck()
        self._confirm(app)

        written = self.tex.read_text(encoding="utf-8")
        self.assertIn("Acme", written, "the experience survived")
        self.assertNotIn("Thing Builder", written, "the project was dropped")

    def test_confirming_builds_the_profile(self):
        app = _at(_pending())
        app.run()
        self._confirm(app)

        self.assertTrue(self.profile.exists(), "the profile was written")
        self.assertIsNone(app.session_state["pending_import"],
                          "the screen steps aside once it is done")
        self.assertEqual(app.session_state["profile_name"], STEM)

    def test_dropping_everything_blocks_the_build(self):
        """A resume with nothing to tailor is not a resume."""
        app = _at(_pending())
        app.run()

        app.checkbox(key="keep-experience-0").uncheck()
        app.checkbox(key="keep-project-0").uncheck()
        app.run()

        confirm = [b for b in app.button if b.label.startswith("This is right")][0]
        self.assertTrue(confirm.disabled)
        self.assertTrue(any("at least one" in e.value for e in app.error))


class TestLatexSkipsConfirmation(unittest.TestCase):
    """
    A `.tex` upload is the user's own file in the pipeline's own format.

    There is nothing a model guessed at, so a confirmation screen would be
    asking someone to proofread their own document back to them.
    """

    def test_a_tex_upload_needs_no_confirmation(self):
        from scripts.init_profile import extract_resume

        source = ROOT / "data" / "master_resumes" / "yash_pathak.tex"
        if not source.exists():
            self.skipTest("needs a real resume; skipped on a clean clone")

        target = RESUMES / f"{STEM}_latex.tex"
        try:
            result = extract_resume(source.read_bytes(), target.name)
            self.assertEqual(result["kind"], "latex")
            self.assertNotIn("schema", result)
        finally:
            target.unlink(missing_ok=True)


class TestExtractionKeepsWhatItCouldNotParse(unittest.TestCase):

    def test_unparsed_survives_normalisation(self):
        """
        R39 built this hook and `_normalise` threw it away.

        The floor stored leftover text under `_unparsed`, then normalisation
        rebuilt a fixed five-key dict — so the key existed, was populated, and
        could never be read by the screen it was written for.
        """
        from tools.resume import resume_import

        text = ("Jane Doe\njane@example.com\n"
                "EXPERIENCE\nSomething no heuristic can split\n"
                "PROJECTS\nAlso unsplittable\n")
        schema = resume_import.to_schema(text)          # no agent: the floor

        self.assertIn("_unparsed", schema)
        self.assertTrue(schema["_unparsed"])


if __name__ == "__main__":
    unittest.main()

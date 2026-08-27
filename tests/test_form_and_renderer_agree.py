r"""
Every field the form collects is printed, and every field printed was offered.

The schema is a contract with two ends, and this repo has now broken it in
both directions — four times, always the same way and never the same field, so
each one looked like an isolated slip:

* **collected, never printed.** The project link, typed into the confirmation
  screen and dropped by the generation renderer (R74). `contact.portfolio`, a
  labelled box on a screen headed *correct anything that is wrong*, appearing
  nowhere else in the repository at all. `from_parsed` omitting `url`, which
  additionally made the round-trip test blind to the loss it was there to
  catch.
* **printed, never offered.** The skills section: shown on the React screen as
  a count and nothing more, while the Streamlit screen has had an editable
  field the whole time. It reaches the employer verbatim and was the one
  section nobody could correct.

The reverse direction was already asserted somewhere — a field the renderer
ignores is a field somebody fills in for nothing. The forward direction is the
one that keeps catching things, and neither is much use without the other.

**The read-set is measured, not read.** Every field is rendered with a
sentinel value and the output searched for it, so this describes what
`tex_renderer` actually prints rather than what its source appears to say. A
test that greps a renderer for `.get('url')` passes the moment somebody
renames the accessor, which is the failure mode of testing a path against
itself.

The form side is read out of the source, because a `.tsx` cannot be imported
here. That extraction fails loudly if it finds nothing, so this can never
quietly pass by matching an empty set against an empty set.
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.resume import tex_renderer  # noqa: E402

CONFIRM = ROOT / "web" / "src" / "components" / "ImportConfirm.tsx"

SENTINEL = "ZZFIELDMARKZZ"

# Every field either end has ever named, so the probe can ask about fields the
# renderer does *not* read as well as ones it does.
KNOWN = {
    "contact": ["name", "phone", "email", "linkedin", "github", "portfolio",
                "website", "location"],
    "education": ["school", "location", "degree", "dates", "gpa"],
    "experiences": ["title", "company", "dates", "location", "bullets"],
    "projects": ["name", "url", "tech", "dates", "bullets"],
}

# `_projects` reads `link` only when `url` is absent, so a probe that fills
# every field never sees it. It is the alias Gemini sometimes returns for the
# same value rather than a field of its own, and the form is right not to
# offer it twice.
ALIASES = {"projects": {"link"}}


def renders(section, field):
    """Does a value placed in this field reach the rendered document?"""
    def entry(fields):
        out = {}
        for name in fields:
            if name == field:
                out[name] = [SENTINEL] if name == "bullets" else SENTINEL
            else:
                out[name] = [] if name == "bullets" else f"other-{name}"
        return out

    schema = {"contact": {"name": "Someone"}, "education": [],
              "experiences": [], "projects": [], "skills": {}}
    if section == "contact":
        schema["contact"] = entry(KNOWN["contact"])
    else:
        schema[section] = [entry(KNOWN[section])]
    return SENTINEL in tex_renderer.render(schema)


def printed(section):
    """The fields of this section that actually reach the page."""
    return {f for f in KNOWN[section] if renders(section, f)}


def offered(section):
    """
    The fields this section's form puts in front of a person.

    Read out of the array the screen maps over. Raises rather than returning
    an empty set: a silent miss here would make every assertion below vacuous,
    which is worse than a red build.
    """
    source = CONFIRM.read_text(encoding="utf-8")
    # Anchored on a field name each list is guaranteed to contain, so a loose
    # bracket elsewhere in the file cannot be mistaken for the list.
    anchors = {
        "contact": r"\[([^\]]*'email'[^\]]*)\]\.map\(",
        "education": r"\[([^\]]*'school'[^\]]*)\]\.map\(",
        "experiences": r"\?\s*\[([^\]]*'title'[^\]]*)\]",
        "projects": r":\s*\[([^\]]*'tech'[^\]]*)\]",
    }
    found = re.search(anchors[section], source)
    if not found:
        raise AssertionError(
            f"could not find the {section} field list in {CONFIRM.name}. "
            "This test is now asserting nothing — fix the extraction rather "
            "than deleting the check.")
    fields = set(re.findall(r"'([^']+)'", found.group(1)))
    if not fields:
        raise AssertionError(f"the {section} field list read as empty")
    return fields


class TestTheFormOffersWhatThePagePrints(unittest.TestCase):
    """Forward: printed on the resume, so it has to be correctable."""

    def test_every_contact_field_that_prints_is_editable(self):
        self.assertLessEqual(printed("contact"), offered("contact"))

    def test_every_education_field_that_prints_is_editable(self):
        self.assertLessEqual(printed("education"), offered("education"))

    def test_every_experience_field_that_prints_is_editable(self):
        # Bullets get a textarea rather than a row in the field array.
        self.assertLessEqual(printed("experiences") - {"bullets"},
                             offered("experiences"))

    def test_every_project_field_that_prints_is_editable(self):
        self.assertLessEqual(printed("projects") - {"bullets"},
                             offered("projects"))

    def test_skills_are_editable_and_not_merely_counted(self):
        """
        The section that reaches an employer verbatim, and the one the screen
        showed as the number `4`. `A WS` — a kerning artifact of Priya's own
        PDF — printed on her resume with no way to touch it, on the same
        screen that flags her email for exactly this reason.
        """
        source = CONFIRM.read_text(encoding="utf-8")
        self.assertIn("skillRows", source,
                      "the skills section is not editable on this screen")
        self.assertIn("skillsFromRows()", source,
                      "skills are edited but the edits are not what is saved")


class TestThePagePrintsWhatTheFormOffers(unittest.TestCase):
    """Reverse: a field nothing prints is a field somebody fills in for nothing."""

    def test_no_contact_field_is_collected_and_dropped(self):
        self.assertLessEqual(offered("contact"), printed("contact"))

    def test_no_education_field_is_collected_and_dropped(self):
        self.assertLessEqual(offered("education"), printed("education"))

    def test_no_experience_field_is_collected_and_dropped(self):
        self.assertLessEqual(offered("experiences"), printed("experiences"))

    def test_no_project_field_is_collected_and_dropped(self):
        self.assertLessEqual(offered("projects"),
                             printed("projects") | ALIASES["projects"])


class TestThisTestWouldHaveCaughtThem(unittest.TestCase):
    """
    Each direction, demonstrated against the shape that shipped. Without
    these, a later "simplification" of the assertions above could pass while
    checking nothing.
    """

    def test_a_dropped_contact_field_is_caught(self):
        """`portfolio`, offered and printed nowhere."""
        self.assertFalse({"portfolio"} <= printed("contact"))

    def test_a_dropped_project_link_is_caught(self):
        """The link is printed, so the form has to offer it."""
        self.assertIn("url", printed("projects"))
        self.assertIn("url", offered("projects"))

    def test_the_probe_can_tell_a_read_field_from_an_ignored_one(self):
        """If everything looked read, both directions would pass forever."""
        self.assertIn("degree", printed("education"))
        self.assertNotIn("gpa", printed("education"))


if __name__ == "__main__":
    unittest.main()

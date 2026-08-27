r"""
Parse and render are inverses. The whole family, not the five percents.

Three individually reasonable decisions guaranteed a broken output between
them:

* `tex_renderer` escapes on the way into a file
* `parse_latex_resume` unescapes on the way out
* `_escape_latex(bullet, already_latex=True)` trusted what it was handed

The author's master holds five `\%`; the parser returned all five bare; the
no-model rung wrote them straight back. A bare `%` comments out the rest of
the line including the closing brace, so the free tier produced `.tex` files
that would not compile — `page_count: 0` on a machine with LaTeX installed.
Invisible on the author's machine because Gemini rewrites his bullets, and
rewritten prose routes through the escaper.

The invariant, now stated in one place and enforced here: **in memory a bullet
is plain text; LaTeX exists only in a rendered file.** `already_latex` is gone
— it was one flag standing for two different truths depending on which path
built the string, which is the sentinel pattern in its purest form.

These are property tests over every master on disk rather than assertions
about particular characters, because the five percents were never the point.
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.resume import tex_renderer  # noqa: E402
from tools.resume.latex_parser import parse_latex_resume  # noqa: E402

MASTERS = sorted((ROOT / "data" / "master_resumes").glob("*.tex"))

# A `%` outside a comment, and the other characters that are syntax in LaTeX.
# `\` and braces are excluded: a rendered file is full of legitimate commands.
UNESCAPED = re.compile(r"(?<!\\)[%&#_$]")

# What the escaper itself emits. `~` becomes `$\sim$` (R69), so the `$` in a
# rendered bullet is usually the escaper doing its job rather than a leak —
# these are removed before the scan, or the check flags its own output.
EMITTED = re.compile(
    r"\$\\(?:sim|pm|rightarrow|leftrightarrow|leq|geq|times)\$"
    r"|\\(?:textless|textgreater|textasciicircum|textbackslash|ldots)\{\}")


def fields_of(parsed):
    """Every string the parser hands back that will be rendered again."""
    out = []
    for component in list(parsed.experiences) + list(parsed.projects):
        out += [b for b in (component.bullets or []) if b]
        for attr in ("title", "company", "location", "dates", "name", "tech"):
            value = getattr(component, attr, None)
            if isinstance(value, str) and value:
                out.append(value)
    return out


@unittest.skipIf(not MASTERS, "no master resumes on disk")
class TestWhatTheParserReturnsIsPlainText(unittest.TestCase):

    def test_no_latex_command_survives_into_memory(self):
        for master in MASTERS:
            for text in fields_of(parse_latex_resume(str(master))):
                self.assertNotIn("\\", text,
                                 f"{master.name}: a LaTeX command reached memory: {text!r}")

    def test_no_math_span_survives_into_memory(self):
        r"""`$\sim 503$ms` is the one that motivated `already_latex`."""
        for master in MASTERS:
            for text in fields_of(parse_latex_resume(str(master))):
                self.assertNotIn("$", text,
                                 f"{master.name}: a math span reached memory: {text!r}")

    def test_the_characters_a_person_typed_are_the_ones_returned(self):
        parsed = parse_latex_resume(str(MASTERS[0]))
        joined = " ".join(fields_of(parsed))
        # At least one master states a percentage; it must read as one.
        if "%" in joined:
            self.assertNotIn(r"\%", joined)


@unittest.skipIf(not MASTERS, "no master resumes on disk")
class TestTheRoundTripIsClosed(unittest.TestCase):
    """
    Parse a master, render it back, parse that. The second parse must equal
    the first — anything that drifts is a boundary that does not agree with
    its opposite number.
    """

    def _round_trip(self, master):
        first = parse_latex_resume(str(master))
        schema = tex_renderer.from_parsed(first)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "again.tex"
            tex_renderer.write(schema, path)
            rendered = path.read_text(encoding="utf-8")
            second = parse_latex_resume(str(path))
        return first, second, rendered

    def test_bullets_survive_a_render_and_a_reparse_unchanged(self):
        """
        Matched by id rather than by position, because the renderer orders
        experiences newest first and a master is not always written that way.
        Pairing on position would report a reordering as a content change —
        and matching on id is the stronger check anyway: it says every
        component came back, with its own bullets, wherever it now sits.
        """
        for master in MASTERS:
            first, second, _ = self._round_trip(master)
            landed = {c.id: c for c in
                      list(second.experiences) + list(second.projects)}
            for a in list(first.experiences) + list(first.projects):
                self.assertIn(a.id, landed,
                              f"{master.name}: {a.id} did not survive")
                self.assertEqual(
                    list(a.bullets or []), list(landed[a.id].bullets or []),
                    f"{master.name}: {a.id} changed on the way through")

    def test_the_rendered_file_escapes_everything_it_should(self):
        for master in MASTERS:
            _, _, rendered = self._round_trip(master)
            body = rendered[rendered.index(r"\begin{document}"):]
            for line in body.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("%"):
                    continue
                # Only look inside the argument of a resumeItem: the rest of
                # the line is template machinery with legitimate braces.
                for content in re.findall(r"\\resumeItem\{(.*)\}", stripped):
                    leaked = UNESCAPED.findall(EMITTED.sub("", content))
                    self.assertEqual(
                        leaked, [],
                        f"{master.name}: unescaped {leaked} in {content[:70]!r} "
                        "— a bare % comments out the closing brace and the "
                        "file will not compile")

    def test_a_second_render_is_byte_identical_to_the_first(self):
        """
        Idempotence. If rendering twice differs, some boundary is adding or
        removing an escape each time, and the drift compounds per run.
        """
        for master in MASTERS:
            first = parse_latex_resume(str(master))
            once = tex_renderer.render(tex_renderer.from_parsed(first))
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "a.tex"
                path.write_text(once, encoding="utf-8")
                twice = tex_renderer.render(
                    tex_renderer.from_parsed(parse_latex_resume(str(path))))
            self.assertEqual(once, twice, f"{master.name}: rendering is not stable")


class TestTheFlagIsGone(unittest.TestCase):

    def test_nothing_asks_whether_text_is_already_latex(self):
        """
        One flag, two meanings, chosen by which path built the string. If it
        comes back, so does a resume that will not compile.
        """
        for module in ("agents/generation_agent.py", "tools/resume/tex_renderer.py"):
            source = (ROOT / module).read_text(encoding="utf-8")
            code = re.sub(r'"""[\s\S]*?"""', "", source)
            code = re.sub(r"^\s*#.*$", "", code, flags=re.M)
            self.assertNotIn("already_latex", code,
                             f"{module} still branches on already_latex")


if __name__ == "__main__":
    unittest.main()

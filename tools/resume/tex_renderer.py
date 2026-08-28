"""
Turn a structured resume into a LaTeX file the rest of the pipeline can read.

This is the second half of Phase 2 item 10. The first half extracts a schema
from a PDF or DOCX; this renders that schema into the template everything
downstream already expects.

**Why a renderer rather than asking a model for LaTeX.** Generation does not
merely parse the master `.tex`, it *splices* it — the header and education
from the top, the skills section from the bottom, generated content between.
So the master file is the output template as well as the input, and a resume
that never existed as `.tex` has nothing to splice. The obvious fix is to have
the model write LaTeX, and that fails in the worst way available: malformed
markup that compiles to something wrong, or does not compile at all, with the
error thirty lines from the cause.

So the model fills a schema and never emits markup. Structure, escaping and
layout are decided here, in code that can be tested without an API. The model
does what it is good at — reading messy text — and nothing it is bad at.

The output is a real `.tex` the user keeps and can edit, which for someone who
has never used LaTeX is a better gift than a hidden intermediate format.

Location: jobscout_v3/tools/resume/tex_renderer.py
"""

import logging
import re
from pathlib import Path

from tools import paths

logger = logging.getLogger(__name__)

# Ships inside the package. It used to be `ROOT / "data" / "templates"`,
# which is the repo in a checkout and site-packages when installed — where
# it does not exist, so an installed copy could not render anything.
PREAMBLE = paths.asset("base_preamble.tex")

# Sequential replacement cannot work here: the substitution for a backslash
# contains braces, and the brace rules would then escape those, turning a
# stray backslash into \textbackslash\{\}. So this is one pass over the
# source, and nothing a replacement emits is looked at again.
_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}",
    # `$\sim$`, not `\textasciitilde` (R69). In this template's OT1 encoding
    # `\textasciitilde` renders as a raised diacritic — "˜2 min" rather than
    # "~2 min" — and extracts from the PDF as an unmappable character, so ATS
    # software reading the text gets nothing. `$\sim$` renders correctly and
    # extracts as U+223C. It is also what a resume means by a tilde: roughly.
    "~": r"$\sim$", "^": r"\textasciicircum{}",
    # R53 added these two to the *generation* path and not to this one, so an
    # imported resume containing "<5ms" rendered it as an inverted exclamation
    # mark. The same bug, in the module only a new user reaches — the author's
    # resume is a `.tex` that never passes through here, which is why it
    # survived every sweep (R69).
    "<": r"\textless{}", ">": r"\textgreater{}",
    # The other half of the round trip. `latex_parser` turns math spans into
    # these characters so that an in-memory bullet is plain text; without the
    # return journey a re-render would emit a bare `±` or `→`, which is not
    # representable in OT1 and drops out of the PDF silently.
    "±": r"$\pm$", "→": r"$\rightarrow$", "↔": r"$\leftrightarrow$",
    "≤": r"$\leq$", "≥": r"$\geq$", "×": r"$\times$", "…": r"\ldots{}",
}

_ESCAPE_PATTERN = re.compile("|".join(re.escape(c) for c in _ESCAPES))


def escape(text) -> str:
    """
    Make arbitrary text safe to place in a LaTeX document.

    Escaped unconditionally, and this is now the only rule in the project.

    There used to be an exception — the generation agent trusted a bullet that
    came from a master `.tex` and wrote it back unescaped. That rested on the
    premise that `parse_latex_resume` returns valid LaTeX, and it does not: it
    returns plain text. The two together guaranteed that any bullet making the
    round trip came out broken, which is why the no-model rung produced files
    that would not compile.

    The invariant, stated once: **in memory a bullet is plain text; LaTeX
    exists only in a rendered file.** Every boundary honours it — the parser
    converts on the way out, this converts on the way in — so the round trip
    is closed by construction rather than by a flag naming which half of it
    the caller happens to be on.
    """
    if text is None:
        return ""

    return _ESCAPE_PATTERN.sub(lambda m: _ESCAPES[m.group()], str(text))


def _bullets(items) -> str:
    if not items:
        return ""
    lines = ["      \\resumeItemListStart"]
    lines += [f"        \\resumeItem{{{escape(b)}}}" for b in items if b]
    lines.append("      \\resumeItemListEnd")
    return "\n".join(lines)


def _education(entries) -> str:
    if not entries:
        return ""
    blocks = []
    for entry in entries:
        blocks.append(
            "    \\resumeSubheading\n"
            f"      {{{escape(entry.get('school'))}}}{{{escape(entry.get('location'))}}}\n"
            f"      {{{escape(entry.get('degree'))}}}{{{escape(entry.get('dates'))}}}"
        )
    return ("  \\resumeSubHeadingListStart\n"
            + "\n".join(blocks)
            + "\n  \\resumeSubHeadingListEnd")


_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}

_DATE_START = re.compile(
    r"(?:(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+)?"
    r"(\d{4})", re.I)


def _started(dates):
    """
    When a role began, as `(year, month)`, or `None` when it cannot be read.

    Only the first date in the string is looked at: `"Mar 2023 - Present"`
    starts in March 2023 and the end is somebody else's problem. A month is
    optional — a bare `"2023 - 2025"` is a year the code can still order — and
    a missing one sorts as January, which is the only guess available and
    cannot reorder two entries that name different years.
    """
    found = _DATE_START.search(dates or "")
    if not found:
        return None
    month, year = found.groups()
    return (int(year), _MONTHS.get((month or "").lower()[:3], 1))


def reverse_chronological(entries):
    """
    Experiences newest first, or exactly as given when that cannot be decided.

    Selection ranks components by how well they match the job, and that order
    reached the page unchanged: Priya's resume opened with the job she left in
    2020 and buried the one she currently holds. Relevance is the right way to
    choose *which* roles appear and the wrong way to order them once chosen —
    a reader scanning the left edge of a resume reads the dates as a sequence.

    **All of them or none of them.** If a single entry's dates cannot be
    parsed there is no honest place to put it, so nothing is moved and the
    caller's order stands. Sorting the rest around an unknown would state a
    sequence the data does not support — an unread date is not the year zero.
    """
    entries = list(entries or [])
    keyed = [(_started(e.get("dates")) if isinstance(e, dict) else None, e)
             for e in entries]
    if any(key is None for key, _ in keyed):
        logger.debug("Experience dates could not all be read; order preserved")
        return entries
    # Stable, so entries starting in the same month keep the order they came
    # in — which is selection's ranking, the best tie-break available.
    return [e for _, e in sorted(keyed, key=lambda pair: pair[0], reverse=True)]


def _experiences(entries) -> str:
    if not entries:
        return ""
    blocks = []
    for entry in reverse_chronological(entries):
        # needs_review resumes are written to disk too, so this runs on output
        # validation has already rejected. Skip what cannot be rendered rather
        # than losing the whole file.
        if not isinstance(entry, dict):
            continue
        # Argument order differs from Education's and the template gives no
        # hint: experience is {title}{dates}{company}{location} while
        # education is {school}{location}{degree}{dates}. Getting it wrong
        # parses cleanly and files the job title as the employer.
        block = (
            "    \\resumeSubheading\n"
            f"      {{{escape(entry.get('title'))}}}{{{escape(entry.get('dates'))}}}\n"
            f"      {{{escape(entry.get('company'))}}}{{{escape(entry.get('location'))}}}"
        )
        bullets = _bullets(entry.get("bullets"))
        blocks.append(block + ("\n" + bullets if bullets else ""))
    return ("  \\resumeSubHeadingListStart\n"
            + "\n".join(blocks)
            + "\n  \\resumeSubHeadingListEnd")


def _projects(entries) -> str:
    if not entries:
        return ""
    blocks = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = escape(entry.get("name"))
        # The parser reads the tech stack out of the \emph{...} that follows
        # the name, so this separator is load-bearing rather than decorative.
        tech = escape(entry.get("tech"))
        # A project's link. This builder did not render one, so a URL typed
        # into the import confirmation screen was collected and then dropped —
        # the generation agent next door had always written it. Fourth bug
        # from this pair of twins, and the reason they now share this code.
        # Mock tailoring calls it "url" and Gemini sometimes returns "link".
        link = entry.get("url") or entry.get("link") or ""
        shown = (f"\\href{{{link}}}{{\\underline{{{name}}}}}" if link else name)
        heading = f"{{\\textbf{{{shown}}} $|$ \\emph{{{tech}}}}}" if tech else \
                  f"{{\\textbf{{{shown}}}}}"
        block = ("      \\resumeProjectHeading\n"
                 f"        {heading}{{{escape(entry.get('dates'))}}}")
        bullets = _bullets(entry.get("bullets"))
        blocks.append(block + ("\n" + bullets if bullets else ""))
    return ("    \\resumeSubHeadingListStart\n"
            + "\n".join(blocks)
            + "\n    \\resumeSubHeadingListEnd")


def _skills(categories) -> str:
    if not categories:
        return ""
    rows = [f"     \\textbf{{{escape(label)}}}{{: {escape(value)}}}"
            for label, value in categories.items() if value]
    return ("  \\begin{itemize}[leftmargin=0.15in, label={}]\n"
            "    \\small{\\item{\n"
            + " \\\\\n".join(rows)
            + "\n    }}\n  \\end{itemize}")


def _header(contact) -> str:
    """
    Name and contact line.

    Links are emitted as `\\href` because the parser reads GitHub and LinkedIn
    out of the href target, not the visible text (R16).
    """
    name = escape(contact.get("name") or "Your Name")
    pieces = []

    if contact.get("phone"):
        pieces.append(escape(contact["phone"]))
    if contact.get("email"):
        email = escape(contact["email"])
        pieces.append(f"\\href{{mailto:{email}}}{{\\underline{{{email}}}}}")
    for field, label in (("linkedin", "LinkedIn"), ("github", "GitHub")):
        if contact.get(field):
            pieces.append(
                f"\\href{{{escape(contact[field])}}}{{\\underline{{{label}}}}}")

    return ("\\begin{center}\n"
            f"    \\textbf{{\\Huge \\scshape {name}}} \\\\ \\vspace{{1pt}}\n"
            "    \\small "
            + " $|$ ".join(pieces)
            + "\n\\end{center}")


def experience_block(entries) -> str:
    r"""
    A complete Experience section, or `""` when there is nothing to show.

    The seam the two renderers now share. They each used to assemble this,
    and the pair has produced four bugs: the field transposition R70 fixed on
    one side only, the orphan `\section{Projects}` heading this removes, the
    `-1` header lookup that followed from one of them omitting a section the
    other treats as an anchor, and the project link dropped below.

    **A section with nothing in it is not emitted.** An empty heading is a
    visible defect on a resume, and it is also what made a generated file
    unusable as a master — `_generate_latex_file` locates the header by
    finding `\section{Experience}`, so a heading that exists only sometimes is
    a parse anchor that exists only sometimes. Refusing to write an empty one
    at least makes the two ends agree about when it is there.
    """
    body = _experiences(entries)
    return f"\\section{{Experience}}\n{body}\n" if body else ""


def project_block(entries) -> str:
    """A complete Projects section, or `""` when there is nothing to show."""
    body = _projects(entries)
    return f"\\section{{Projects}}\n{body}\n" if body else ""


def render(resume: dict) -> str:
    """
    A complete LaTeX document from a structured resume.

    Sections with no content are omitted rather than emitted empty, so an
    imported resume without projects does not carry an orphan heading.
    """
    preamble = PREAMBLE.read_text(encoding="utf-8").rstrip()

    parts = [preamble, "", _header(resume.get("contact") or {}), ""]

    for title, body in (
        ("Education", _education(resume.get("education"))),
        ("Experience", _experiences(resume.get("experiences"))),
        ("Projects", _projects(resume.get("projects"))),
        ("Technical Skills", _skills(resume.get("skills"))),
    ):
        if body:
            parts += [f"\\section{{{title}}}", body, ""]

    parts.append("\\end{document}")
    return "\n".join(parts) + "\n"


def write(resume: dict, path) -> Path:
    """Render and save. Returns the path written."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(resume), encoding="utf-8")
    logger.info(f"Wrote {target}")
    return target


def from_parsed(parsed) -> dict:
    """
    A parsed resume back into schema shape.

    Only used to round-trip the renderer against a resume the parser already
    understands: render it, parse it again, and check nothing was lost. That
    test is what makes the renderer trustworthy without a PDF in hand.
    """
    return {
        "contact": {
            "name": parsed.name, "phone": parsed.phone, "email": parsed.email,
            "github": parsed.github_url, "linkedin": parsed.linkedin_url,
        },
        "education": [{
            "school": parsed.education_school,
            "location": parsed.education_location,
            "degree": parsed.education_degree,
            "dates": parsed.education_dates,
        }] if parsed.education_school else [],
        "experiences": [{
            "company": e.company, "title": e.title, "dates": e.dates,
            "location": e.location, "bullets": list(e.bullets),
        } for e in parsed.experiences],
        "projects": [{
            # The link, which this omitted. The parser reads it out of the
            # `\href` and `_projects` writes it back, so the only thing
            # standing between the two was this dict — and because the round
            # trip test is what declares the renderer trustworthy, the field
            # it forgot to carry was the field nothing could check. A test
            # blind to a value proves the value is preserved exactly as well
            # as no test at all.
            "name": p.name, "url": p.url, "tech": p.tech, "dates": p.dates,
            "bullets": list(p.bullets),
        } for p in parsed.projects],
        "skills": dict(parsed.skills.categories or {}),
    }


def looks_like_latex(text: str) -> bool:
    """Cheap guard: is this already a .tex rather than something to import?"""
    return bool(re.search(r"\\documentclass|\\begin\{document\}", text or ""))

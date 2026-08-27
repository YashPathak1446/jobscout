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

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent.parent
PREAMBLE = ROOT / "data" / "templates" / "base_preamble.tex"

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


def _experiences(entries) -> str:
    if not entries:
        return ""
    blocks = []
    for entry in entries:
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
        name = escape(entry.get("name"))
        # The parser reads the tech stack out of the \emph{...} that follows
        # the name, so this separator is load-bearing rather than decorative.
        tech = escape(entry.get("tech"))
        heading = f"{{\\textbf{{{name}}} $|$ \\emph{{{tech}}}}}" if tech else \
                  f"{{\\textbf{{{name}}}}}"
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
            "name": p.name, "tech": p.tech, "dates": p.dates,
            "bullets": list(p.bullets),
        } for p in parsed.projects],
        "skills": dict(parsed.skills.categories or {}),
    }


def looks_like_latex(text: str) -> bool:
    """Cheap guard: is this already a .tex rather than something to import?"""
    return bool(re.search(r"\\documentclass|\\begin\{document\}", text or ""))

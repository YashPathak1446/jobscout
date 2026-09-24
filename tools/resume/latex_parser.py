"""
LaTeX Resume Parser — Extracts structured components from main.tex.

Parses Jake's Resume format to get experiences, projects, and skills
with the correct company names, locations, dates, and improved bullets.
This is the authoritative source — always use this over the .txt parser
when a .tex file is available.
"""

import re
import logging
from collections import Counter
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class LatexExperience:
    """A work experience entry from the LaTeX resume."""
    id: str
    title: str
    dates: str
    company: str
    location: str
    bullets: list[str]
    keywords: list[str] = field(default_factory=list)


@dataclass
class LatexProject:
    """A project entry from the LaTeX resume."""
    id: str
    name: str
    url: str
    tech: str
    dates: str
    bullets: list[str]
    keywords: list[str] = field(default_factory=list)


@dataclass
class LatexSkills:
    """Technical skills from the LaTeX resume."""
    categories: dict[str, str]  # label -> value


@dataclass
class LatexResume:
    """Fully parsed LaTeX resume."""
    name: str
    phone: str
    email: str
    github_url: str
    linkedin_url: str
    education_school: str
    education_location: str
    education_degree: str
    education_dates: str
    education_courses: str
    experiences: list[LatexExperience]
    projects: list[LatexProject]
    skills: LatexSkills
    raw_tex: str
    # What the parser saw and could not read, in words (R112). A line it cannot
    # handle is reported here and logged, never dropped in silence. Shown at
    # import and on the rules screen, beside `id_problems`.
    warnings: list[str] = field(default_factory=list)


# Tech keywords to auto-extract for embedding scoring
TECH_KEYWORDS = [
    "python", "java", "javascript", "typescript", "c++", "c#", "go",
    "rust", "ruby", "scala", "kotlin", "swift", "sql", "html", "css",
    "react", "angular", "angularjs", "vue", "next.js", "django", "flask", "fastapi",
    "spring", "express", "node.js", "rails",
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform",
    "lambda", "ec2", "s3", "cloudwatch", "api gateway",
    "mysql", "postgresql", "mongodb", "redis", "elasticsearch",
    "dynamodb", "firebase", "weaviate", "pinecone", "chromadb",
    "kafka", "rabbitmq", "spark", "airflow",
    "pytorch", "tensorflow", "keras", "huggingface", "transformers",
    "bert", "distilbert", "llm", "rag", "langchain", "nlp", "scikit-learn",
    "pandas", "numpy", "matplotlib",
    "git", "ci/cd", "github actions", "jenkins", "linux",
    "rest api", "graphql", "oauth", "jwt",
    "microservices", "serverless", "devops",
    "google adk", "multi-agent", "gemini", "streamlit",
    "ai", "ml", "machine learning", "deep learning",
    "full-stack", "full stack", "backend", "frontend",
    "distributed systems", "data pipelines",
]


def experience_keyword_text(title: str, company: str, bullets: list[str]) -> str:
    """Text an experience's keywords are extracted from."""
    return f"{title} {company} {' '.join(bullets)}"


def _entries(section: str, marker: str) -> list:
    """
    A section cut at each `marker`: one span per entry, heading first (R102).

    An entry's bullets are looked for **inside its own span only.** Both entry
    patterns used to run heading-then-list as one regular expression. So an
    entry with no bullet list (a scholarship, an award, a volunteer role) could
    not match at all, and the project pattern's lazy `.*?` heading ran on to
    the *next* entry's list instead. `Merit Scholarship` followed by a paper
    parsed as one project, named for the scholarship and carrying the paper's
    bullet, and the paper was gone. Every stage after this one saw only that.
    """
    starts = [m.start() for m in re.finditer(re.escape(marker), section)]
    return [section[a:b] for a, b in zip(starts, starts[1:] + [len(section)])]


def _braced(text: str, start: int):
    """
    The `{...}` argument opening at `text[start]`, braces balanced.

    Returns (content, index just past the closing brace), or None. A project
    heading's first argument nests braces (`\\textbf{\\href{url}{\\underline
    {Name}}} $|$ \\emph{tech}`), so no single regular expression reads it: a
    lazy one stops at the first `}{`, which is inside the link.
    """
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    i = start
    while i < len(text):
        # An escaped character is text, not syntax: `\{` and `\}` are braces
        # a person typed, and counting them unbalanced every argument after
        # (R112). Skipping the character after a backslash also steps over
        # `\\`, a line break, whole.
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    return None


def _span_bullets(span: str) -> list:
    """The bullets of one entry's own `\\resumeItemListStart` block, or []."""
    block = re.search(r"\\resumeItemListStart(.*?)\\resumeItemListEnd", span, re.DOTALL)
    if not block:
        return []
    bullets_raw = block.group(1)
    bullets = []
    # Lookahead, not a consuming group. The consuming form ate the next
    # bullet's opening token, so every second bullet vanished: 18 in the
    # master .tex parsed as 10.
    for b in re.findall(r"\\resumeItem\{(.*?)\}(?=\s*\\resumeItem|\s*$)",
                        bullets_raw + "\n\\resumeItem", re.DOTALL):
        cleaned = _clean_latex(b).strip()
        if cleaned:
            bullets.append(cleaned)
    if not bullets:
        for b in re.findall(r"\\resumeItem\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", bullets_raw):
            cleaned = _clean_latex(b).strip()
            if cleaned:
                bullets.append(cleaned)
    return bullets


def _snippet(text: str, width: int = 70) -> str:
    """A short, one-line quote of what could not be read, for a warning."""
    flat = " ".join(text.split())
    return f"\"{flat[:width]}{'…' if len(flat) > width else ''}\""


def _warn_short(warnings: list, section: str, entry: str, body: str,
                bullets: list) -> None:
    """Say so when an entry holds more `\\resumeItem`s than were read (R112)."""
    block = re.search(r"\\resumeItemListStart(.*?)\\resumeItemListEnd", body, re.DOTALL)
    if not block:
        return
    written = len(re.findall(r"\\resumeItem\s*\{\s*[^\s}]", block.group(1)))
    if written > len(bullets):
        warnings.append(
            f"{section}: {written - len(bullets)} of {written} bullets under "
            f"\"{entry}\" could not be read and were left out.")


def _skill_categories(section: str, warnings: list) -> dict:
    """
    `\\textbf{Label}{: a, b, c}` pairs, read by balanced braces (R112).

    The pattern this replaced stopped a value at the first backslash, so any
    category holding an escaped character (`C\\#`, `scikit\\_learn`, `50\\%`,
    `R\\&D`) failed to match and **the whole category vanished**, with no
    message. A resume listing C# lost its Languages line from every tailored
    resume. Now a category is read to its closing brace whatever it holds,
    and one that still cannot be read is reported, not dropped.
    """
    categories = {}
    at = 0
    for m in re.finditer(r"\\textbf\s*\{", section):
        if m.start() < at:
            continue
        label = _braced(section, m.end() - 1)
        if not label:
            warnings.append("Technical Skills: a category heading could not be "
                            f"read: {_snippet(section[m.start():])}")
            continue
        label_raw, after = label
        while after < len(section) and section[after].isspace():
            after += 1
        value = _braced(section, after)
        if not value:
            warnings.append(f"Technical Skills: the skills after "
                            f"\"{_clean_latex(label_raw)}\" could not be read.")
            at = after
            continue
        value_raw, at = value
        name = _clean_latex(label_raw)
        listed = _clean_latex(value_raw.strip().removeprefix(":")).strip()
        listed = listed.rstrip("\\").strip()
        if not name or not listed:
            warnings.append("Technical Skills: a category with no name or no "
                            f"skills was left out: {_snippet(section[m.start():at])}")
            continue
        categories[name] = listed
    return categories


# Sections the parser reads. Anything else *after* Experience is not carried
# into a tailored resume: generation keeps the header verbatim up to
# Experience, then rebuilds Experience, Projects and Technical Skills.
_READ_SECTIONS = {"education", "experience", "projects", "technical skills"}


def _unread_sections(raw: str) -> list:
    """A warning per section after Experience that nothing reads (R112)."""
    experience = re.search(r"\\section\*?\{Experience\}", raw)
    if not experience:
        return []
    found = []
    for m in re.finditer(r"\\section\*?\{([^}]*)\}", raw[experience.end():]):
        name = _clean_latex(m.group(1)).strip()
        if name.lower() not in _READ_SECTIONS:
            found.append(f"\"{name}\" is not a section this reads, so it will "
                         "not appear in tailored resumes.")
    return found


def project_keyword_text(name: str, tech: str, bullets: list[str]) -> str:
    """Text a project's keywords are extracted from."""
    return f"{name} {tech} {' '.join(bullets)}"


# Words every technical posting contains, so matching them says nothing about
# fit. Lives here rather than with the scorers because it is vocabulary, and
# because R67 needed it in `embedding_scorer` too — which cannot import
# `resume_parser`, since that module imports it.
_GENERIC_TERMS = {
    "api", "backend", "frontend", "software", "application", "system",
    "data", "service", "server", "client", "code", "build", "team",
    "work", "experience", "strong", "knowledge", "skills", "ability",
    "development", "engineering", "developer", "engineer", "project",
    "solution", "support", "management", "process", "performance",
    "design", "architecture", "implement", "deploy", "test", "debug",
}


def keyword_source_text(component) -> str:
    """
    Same thing, for an already-constructed component.

    One definition shared by the parser and by any later recompute. These
    drifted apart once: a recompute using only tech+bullets silently dropped
    "ai" from exp_101gen_ai and exp_ai_ensured, where the term appears only
    in the employer name and never in a bullet.
    """
    bullets = getattr(component, "bullets", []) or []

    if hasattr(component, "company"):
        return experience_keyword_text(
            getattr(component, "title", "") or "",
            getattr(component, "company", "") or "",
            bullets,
        )

    return project_keyword_text(
        getattr(component, "name", "") or "",
        getattr(component, "tech", "") or "",
        bullets,
    )


def split_skill_list(value: str) -> list[str]:
    """
    Split one Technical Skills line into individual tokens.

    Naively splitting on commas breaks the parenthesised groups these
    sections are full of — "AWS (EC2, S3, Lambda)" becomes "AWS (EC2" and
    "Lambda)". This splits at depth zero and then expands each group into
    its head plus its members:

        "AWS (EC2, S3, Lambda)"    -> aws, ec2, s3, lambda
        "SQL (MySQL, PostgreSQL)"  -> sql, mysql, postgresql
        "C/C++"                    -> c/c++, c, c++
    """
    items, depth, buf = [], 0, []
    for ch in value:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth = max(0, depth - 1)
        if ch == ',' and depth == 0:
            items.append(''.join(buf))
            buf = []
        else:
            buf.append(ch)
    items.append(''.join(buf))

    tokens = []
    for item in items:
        item = item.strip().rstrip('}').strip()
        if not item:
            continue

        group = re.match(r'^([^(]+)\(([^)]*)\)\s*$', item)
        if group:
            tokens.append(group.group(1).strip())
            tokens.extend(p.strip() for p in group.group(2).split(','))
        else:
            tokens.append(item.replace('(', ' ').replace(')', ' ').strip())

    out = set()
    for t in tokens:
        t = t.strip().lower()
        if len(t) < 2:
            continue
        out.add(t)
        # "C/C++" and "HTML/CSS" are one skill written as two. Require 3+
        # chars on the parts: "ci/cd" would otherwise contribute "ci" and
        # "cd", and the JD matcher tests plain substrings, so "ci" hits
        # "specific" and "efficient".
        if '/' in t:
            out.update(p.strip() for p in t.split('/') if len(p.strip()) >= 3)

    return sorted(out)


def build_tech_vocabulary(skill_categories: dict) -> list[str]:
    """
    TECH_KEYWORDS plus everything in this user's own skills section.

    The curated base carries generic terms JDs use but resumes rarely list
    verbatim ("backend", "distributed systems", "microservices"). The user's
    skills carry the specific tools the base can't know about — for this
    resume that is 45 of 74 skills, including Figma, Ionic, Capacitor,
    Jasypt, EdgeShark and Biopython, none of which could previously produce
    a JD keyword match. This is Q7's fix: the vocabulary becomes per-user
    without losing the shared terms.
    """
    vocab = {k.lower() for k in TECH_KEYWORDS}
    for value in (skill_categories or {}).values():
        vocab.update(split_skill_list(value))
    return sorted(vocab)


def term_matches(term: str, text_lower: str) -> bool:
    """
    Does a vocabulary term appear in text as a term, rather than a substring?

    Word boundaries for everything, with one exception. This used to apply
    boundaries only to terms of three characters or fewer, and plain
    substring matching above that, which credited:

        "scala"  from "scalable"                  (3 of 20 baseline JDs)
        "rust"   from "antitrust lawsuit"
        "bert"   from "Roberts", "Gilbert family foundation"
        "java"   from "javascript"

    The exception is terms containing + or #, where \\b cannot work — the
    boundary after "c++" sits between two non-word characters and never
    matches. Those fall back to substring, which is safe because those
    characters are rare in prose.

    Boundaries also preserve the containments that *should* match: "github"
    inside "github actions" and "html" inside "html/css" both still hit,
    because the next character is a non-word one.

    Note that `UserProfile._trigger_matches` implements the same idea for
    conditional triggers. The two are deliberately not shared — importing
    across the profile and resume packages would couple them in a direction
    nothing else does.
    """
    if any(c in term for c in "+#"):
        return term in text_lower

    return re.search(rf"\b{re.escape(term)}\b", text_lower) is not None


def _extract_keywords(text: str, vocabulary: list[str] | None = None) -> list[str]:
    """Extract tech keywords from text, against TECH_KEYWORDS unless told otherwise."""
    text_lower = text.lower()
    terms = vocabulary if vocabulary is not None else TECH_KEYWORDS
    return sorted({kw for kw in terms if term_matches(kw, text_lower)})


# Math-mode commands, as the plain characters a person would type. The
# invariant this serves: **an in-memory bullet is plain text.** Not "mostly
# plain text with the odd math span left in", which is what it used to be —
# `\%` came back as `%` while `$\sim 503$` came back untouched, so a bullet
# was neither escaped nor unescaped and no single flag could describe it.
#
# That half-and-half string is what `already_latex` existed to paper over, and
# why the no-model rung wrote resumes that would not compile: the flag said
# "this is valid LaTeX, do not escape it", the `%` in it said otherwise, and a
# bare `%` comments out the rest of the line including the closing brace.
MATH_TO_TEXT = {
    r"\sim": "~",
    r"\pm": "±",
    r"\rightarrow": "→",
    r"\leftrightarrow": "↔",
    r"\leq": "≤",
    r"\geq": "≥",
    r"\times": "×",
    r"\ldots": "…",
    r"\%": "%",
}


def _unwrap_math(text: str) -> str:
    r"""
    `$\sim 503$ms` -> `~503ms`, `$CC \leftrightarrow PSTN$` -> `CC ↔ PSTN`.

    Math spans carry real content on a resume — a tilde meaning "about", an
    arrow meaning "improved to" — so they are translated rather than stripped.
    The space LaTeX needs after a control word is dropped with it, because
    `$\sim 503$` means "~503" and not "~ 503".
    """
    def convert(match):
        inner = match.group(1)
        for command, plain in MATH_TO_TEXT.items():
            # The keys are LaTeX, so they have to be escaped before they are
            # used as patterns. `(?![a-zA-Z])` is where a control word ends —
            # without it a shorter command would match inside a longer one.
            inner = re.sub(re.escape(command) + r"(?![a-zA-Z])\s*",
                           lambda _, p=plain: p, inner)
        return inner.strip()

    return re.sub(r"\$([^$]*)\$", convert, text)


# A private-use character: never in a resume, so it cannot collide with one.
_ESCAPED_DOLLAR = "\ue000"


def _clean_latex(text: str) -> str:
    """Remove LaTeX formatting commands, return plain text."""
    # Remove common commands but keep content
    text = re.sub(r"\\textbf\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\textit\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\emph\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\underline\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\textbf\{\\href\{[^}]*\}\{\\underline\{([^}]*)\}\}\}", r"\1", text)
    text = re.sub(r"\\\&", "&", text)
    text = re.sub(r"\\%", "%", text)
    # An escaped dollar is held aside until the math spans are read, then
    # restored (R112). Un-escaped first, `\$5M and \$3M` became one math span
    # from the first dollar to the second, and came back as "5M and3M".
    text = text.replace("\\$", _ESCAPED_DOLLAR)
    text = re.sub(r"\\_", "_", text)
    text = re.sub(r"\\#", "#", text)
    text = re.sub(r"\\texttt\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\textasciitilde\{\}", "~", text)
    text = re.sub(r"\\textless\{\}", "<", text)
    text = re.sub(r"\\textgreater\{\}", ">", text)
    # A lambda, not a template: re.sub reads "\\" in a replacement string as
    # the start of an escape and rejects it.
    text = re.sub(r"\\textbackslash\{\}", lambda _: "\\", text)
    # Every math span, not just the bare `$\sim$` this used to catch. A resume
    # says `$\sim 503$ms` and `0.17$\rightarrow$1.00`, and leaving those in
    # meant the string in memory was still partly LaTeX.
    text = re.sub(r"\$\|?\$", "|", text)
    text = _unwrap_math(text)
    text = text.replace(_ESCAPED_DOLLAR, "$")
    text = re.sub(r"\\small\s*", "", text)
    text = text.replace("--", "–")
    return text.strip()


def _extract_url_from_href(text: str) -> str:
    """Extract URL from \\href{url}{text}."""
    match = re.search(r"\\href\{([^}]+)\}", text)
    return match.group(1) if match else ""


def _slugify(text: str) -> str:
    """Convert text to ID slug."""
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower().strip())
    return slug.strip("_")[:40]


def _assign_ids(prefix: str, bases: list[str], distinguishers: list[str]) -> list[str]:
    r"""
    One ID per component, disambiguating only the bases that repeat (Q34).

    A component ID used to be `prefix_slug(base)` and nothing else — the
    company for an experience, the name for a project. Two roles at one
    employer therefore produced **one ID for two components**, and every
    consumer keys a dict by it: `derivation` builds trigger rules that way,
    `embedding_scorer` stores vectors that way, `analysis_agent` labels the
    selection breakdown that way. Seven such dicts, so the second role did not
    error, it *replaced* the first. A promotion was enough to trigger it.

    Two properties this has to hold at once:

    * **A base that appears once keeps its ID byte-identical.** Every profile's
      `conditional_inclusion` keys, every recorded baseline and every cached
      embedding is keyed on the old spelling, and all of them are
      single-occurrence today. Changing those would orphan live rules to fix a
      bug none of them has.
    * **Every occurrence of a repeated base is suffixed, including the first.**
      Leaving the bare ID to whichever component the parser reached first makes
      the mapping depend on document order, so reordering a resume would swap
      two components' rules — the same silent misattribution this fixes,
      moved one step sideways.

    The suffix is the distinguisher (an experience's title, and for a project
    nothing, because a project's name *is* its identity). It is preferred over
    a positional `_2` because it survives reordering and because the component
    editor shows these IDs: two rows reading `exp_vertex_technologies` are not
    something a person can act on.

    A positional bump is the fallback, for the three ways a suffix can fail to
    separate two components: `_slugify` truncates at 40 characters, so two long
    titles at one employer can slug the same; a suffixed ID can land on a
    *different* component's single-occurrence ID, which must win because it is
    the one something is already keyed to; and a repeated base may have no
    distinguisher at all, which is the two-projects-of-one-name case.

    That last case is numbered from 1 rather than left bare-then-`_2`, so no
    component silently owns the un-suffixed spelling. It is the one case with
    no order-independent answer available -- if two projects share a name,
    position is the only thing telling them apart -- so it is positional and
    says so, rather than looking stable and not being.
    """
    slugs = [_slugify(base) for base in bases]
    counts = Counter(slugs)
    repeated = {slug for slug, n in counts.items() if n > 1}

    # Single-occurrence IDs are fixed points: claimed before anything is
    # disambiguated, so a suffix can never be handed one of them.
    taken = {f"{prefix}_{slug}" for slug in slugs if slug not in repeated}
    seen = Counter()

    ids = []
    for slug, distinguisher in zip(slugs, distinguishers):
        if slug not in repeated:
            ids.append(f"{prefix}_{slug}")
            continue

        seen[slug] += 1
        if distinguisher and _slugify(distinguisher) != slug:
            stem = _slugify(f"{slug} {distinguisher}")
            bump = 2
        else:
            # Nothing to distinguish them by; number every occurrence.
            stem = f"{slug}_{seen[slug]}"
            bump = seen[slug] + 1

        candidate = f"{prefix}_{stem}"
        while candidate in taken:
            candidate = f"{prefix}_{stem}_{bump}"
            bump += 1

        taken.add(candidate)
        ids.append(candidate)

    return ids


def parse_latex_resume(tex_path: str) -> LatexResume:
    """
    Parse a Jake's Resume LaTeX file into structured components.

    Args:
        tex_path: Path to the .tex file (e.g., data/master_resume.tex)

    Returns:
        LatexResume with all components extracted.
    """
    with open(tex_path, "r", encoding="utf-8") as f:
        raw = f.read()

    # Everything below that meets a line it cannot read says so here (R112).
    warnings: list[str] = []

    # ===== HEADING =====
    name = ""
    name_match = re.search(r"\\textbf\{\\Huge \\scshape ([^}]+)\}", raw)
    if name_match:
        name = _clean_latex(name_match.group(1))

    phone = ""
    phone_match = re.search(r"\\small ([0-9\-]+)", raw)
    if phone_match:
        phone = phone_match.group(1)

    email = ""
    # Find email in the heading center block, not the preamble
    heading_block = re.search(r"\\begin\{center\}(.*?)\\end\{center\}", raw, re.DOTALL)
    if heading_block:
        email_match = re.search(r"\\href\{mailto:([^}]+)\}", heading_block.group(1))
        if email_match:
            email = email_match.group(1)

    github_url = ""
    github_match = re.search(r"\\href\{(https://github\.com/[^}]+)\}", raw)
    if github_match:
        github_url = github_match.group(1)

    linkedin_url = ""
    linkedin_match = re.search(r"\\href\{(https://www\.linkedin\.com/[^}]+)\}", raw)
    if linkedin_match:
        linkedin_url = linkedin_match.group(1)

    # ===== EDUCATION =====
    edu_school = edu_location = edu_degree = edu_dates = edu_courses = ""
    # Coursework is optional. It used to be required, which meant a resume
    # without a 'Relevant Coursework' bullet parsed with no education at
    # all - silently, since every other field still populated. Most resumes
    # do not carry that line, so this only ever worked for resumes written
    # against this exact template.
    edu_match = re.search(
        r"\\resumeSubheading\s*\{([^}]*)\}\{([^}]*)\}\s*\{([^}]*)\}\{([^}]*)\}(?:\s*\\resumeItemListStart\s*\\resumeItem\{\\textbf\{[^}]*\} ([^}]*)\})?",
        raw
    )
    if edu_match:
        edu_school = _clean_latex(edu_match.group(1))
        edu_location = _clean_latex(edu_match.group(2))
        edu_degree = _clean_latex(edu_match.group(3))
        edu_dates = _clean_latex(edu_match.group(4))
        # group(5) is None when the resume has no coursework line.
        edu_courses = _clean_latex(edu_match.group(5) or "")

    # ===== EXPERIENCES =====
    experiences = []

    # Find the Experience section
    exp_section_match = re.search(
        r"\\section\{Experience\}(.*?)\\section\{",
        raw, re.DOTALL
    )

    if exp_section_match:
        exp_section = exp_section_match.group(1)

        # One span per entry, so an entry with no bullets is kept as an entry
        # with no bullets, and never borrows the next one's (R102).
        heading_pattern = re.compile(
            r"\\resumeSubheading\s*\{([^}]*)\}\{([^}]*)\}\s*\{([^}]*)\}\{([^}]*)\}"
        )

        for span in _entries(exp_section, "\\resumeSubheading"):
            match = heading_pattern.match(span)
            if not match:
                warnings.append(
                    "Experience: an entry's heading could not be read, so the "
                    f"entry was left out: {_snippet(span)}")
                continue
            title = _clean_latex(match.group(1))
            dates = _clean_latex(match.group(2))
            company = _clean_latex(match.group(3))
            location = _clean_latex(match.group(4))
            bullets = _span_bullets(span[match.end():])
            _warn_short(warnings, "Experience", title or company,
                        span[match.end():], bullets)

            # Assigned in one pass over the whole pool below (Q34) -- whether
            # this company repeats is not knowable from one entry.
            exp_id = ""
            all_text = experience_keyword_text(title, company, bullets)
            keywords = _extract_keywords(all_text)

            experiences.append(LatexExperience(
                id=exp_id,
                title=title,
                dates=dates,
                company=company,
                location=location,
                bullets=bullets,
                keywords=keywords,
            ))

    # ===== PROJECTS =====
    projects = []

    proj_section_match = re.search(
        r"\\section\{Projects\}(.*?)\\section\{",
        raw, re.DOTALL
    )

    if proj_section_match:
        proj_section = proj_section_match.group(1)

        # One span per entry (R102). The heading's arguments are read by
        # balancing braces, not by a lazy pattern: the first one nests
        # (`\\textbf{\\href{url}{\\underline{Name}}} $|$ \\emph{tech}`), and a
        # lazy match stops at the `}{` inside the link.
        for span in _entries(proj_section, "\\resumeProjectHeading"):
            at = len("\\resumeProjectHeading")
            while at < len(span) and span[at].isspace():
                at += 1
            first = _braced(span, at)
            second = _braced(span, first[1]) if first else None
            if not first or not second:
                warnings.append(
                    "Projects: an entry's heading could not be read, so the "
                    f"entry was left out: {_snippet(span)}")
                continue
            heading_raw, at = first
            dates_raw, heading_end = second
            dates = _clean_latex(dates_raw)

            # Extract URL from heading before cleaning
            url = _extract_url_from_href(heading_raw)

            # Extract name: handle \textbf{\href{url}{\underline{Name}}} pattern
            # and simple \textbf{Name} pattern
            name_part = ""
            tech_part = ""

            # Try nested href+underline pattern first
            nested_match = re.search(
                r"\\textbf\{\\href\{[^}]*\}\{\\underline\{([^}]*)\}\}\}",
                heading_raw
            )
            if nested_match:
                name_part = _clean_latex(nested_match.group(1))
            else:
                # Try simple textbf
                simple_match = re.search(r"\\textbf\{([^}]*)\}", heading_raw)
                if simple_match:
                    name_part = _clean_latex(simple_match.group(1))

            # Extract tech after $|$ \emph{...}
            tech_match = re.search(r"\\emph\{([^}]*)\}", heading_raw)
            if tech_match:
                tech_part = _clean_latex(tech_match.group(1))

            bullets = _span_bullets(span[heading_end:])
            _warn_short(warnings, "Projects", name_part, span[heading_end:], bullets)

            proj_id = ""  # likewise, assigned in the pass below
            all_text = project_keyword_text(name_part, tech_part, bullets)
            keywords = _extract_keywords(all_text)

            projects.append(LatexProject(
                id=proj_id,
                name=name_part,
                url=url,
                tech=tech_part,
                dates=dates,
                bullets=bullets,
                keywords=keywords,
            ))

    # ===== SKILLS =====
    skills_categories = {}
    skills_match = re.search(
        r"\\section\{Technical Skills\}(.*?)(?:\\section\{|\\end\{document\})",
        raw, re.DOTALL
    )
    if skills_match:
        skills_section = skills_match.group(1)
        skills_categories = _skill_categories(skills_section, warnings)

    warnings += _unread_sections(raw)

    for warning in warnings:
        logger.warning(f"Resume parse: {warning}")

    # One pass per pool, now that every member is known. An experience is
    # identified by its employer and told apart by its title; a project is
    # identified by its name and has nothing else to be told apart by.
    for component, assigned in zip(experiences, _assign_ids(
            "exp",
            [e.company or e.title for e in experiences],
            [e.title for e in experiences])):
        component.id = assigned

    for component, assigned in zip(projects, _assign_ids(
            "proj",
            [pr.name for pr in projects],
            ["" for _ in projects])):
        component.id = assigned

    return LatexResume(
        name=name,
        phone=phone,
        email=email,
        github_url=github_url,
        linkedin_url=linkedin_url,
        education_school=edu_school,
        education_location=edu_location,
        education_degree=edu_degree,
        education_dates=edu_dates,
        education_courses=edu_courses,
        experiences=experiences,
        projects=projects,
        skills=LatexSkills(categories=skills_categories),
        raw_tex=raw,
        warnings=warnings,
    )


def print_latex_resume(resume: LatexResume) -> None:
    """Pretty-print parsed LaTeX resume for debugging."""
    print(f"Name: {resume.name}")
    print(f"Email: {resume.email} | Phone: {resume.phone}")
    print(f"GitHub: {resume.github_url}")
    print(f"\nEducation: {resume.education_school} | {resume.education_degree} | {resume.education_dates}")
    print(f"\nExperiences ({len(resume.experiences)}):")
    for exp in resume.experiences:
        print(f"  [{exp.id}] {exp.title} @ {exp.company}, {exp.location} ({exp.dates})")
        print(f"    {len(exp.bullets)} bullets | keywords: {', '.join(exp.keywords[:8])}")
    print(f"\nProjects ({len(resume.projects)}):")
    for proj in resume.projects:
        print(f"  [{proj.id}] {proj.name} ({proj.dates})")
        print(f"    Tech: {proj.tech[:60]}")
        print(f"    {len(proj.bullets)} bullets | keywords: {', '.join(proj.keywords[:8])}")
    print(f"\nSkills categories: {list(resume.skills.categories.keys())}")


# === CLI for testing ===
if __name__ == "__main__":
    import sys
    tex_path = sys.argv[1] if len(sys.argv) > 1 else "data/master_resume.tex"
    resume = parse_latex_resume(tex_path)
    print_latex_resume(resume)

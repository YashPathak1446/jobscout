"""
LaTeX Resume Parser — Extracts structured components from main.tex.

Parses Jake's Resume format to get experiences, projects, and skills
with the correct company names, locations, dates, and improved bullets.
This is the authoritative source — always use this over the .txt parser
when a .tex file is available.
"""

import re
import logging
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
    text = re.sub(r"\\\$", "$", text)
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

        # Find all resumeSubheading entries
        subheading_pattern = re.compile(
            r"\\resumeSubheading\s*\{([^}]*)\}\{([^}]*)\}\s*\{([^}]*)\}\{([^}]*)\}\s*"
            r"\\resumeItemListStart(.*?)\\resumeItemListEnd",
            re.DOTALL
        )

        for match in subheading_pattern.finditer(exp_section):
            title = _clean_latex(match.group(1))
            dates = _clean_latex(match.group(2))
            company = _clean_latex(match.group(3))
            location = _clean_latex(match.group(4))
            bullets_raw = match.group(5)

            # Extract bullet items
            bullets = []
            # Lookahead, not a consuming group. The consuming form ate the
            # next bullet's opening token, so every second bullet vanished:
            # 18 in the master .tex parsed as 10. Silent, and it truncated
            # what scoring, keyword extraction and every prompt ever saw.
            # The projects path below always used the lookahead form.
            bullet_matches = re.findall(r"\\resumeItem\{(.*?)\}(?=\s*\\resumeItem|\s*$)", bullets_raw + "\n\\resumeItem", re.DOTALL)
            for b in bullet_matches:
                cleaned = _clean_latex(b).strip()
                if cleaned:
                    bullets.append(cleaned)

            if not bullets:
                # Fallback: simpler extraction
                for b in re.findall(r"\\resumeItem\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", bullets_raw):
                    cleaned = _clean_latex(b).strip()
                    if cleaned:
                        bullets.append(cleaned)

            exp_id = f"exp_{_slugify(company or title)}"
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

        proj_pattern = re.compile(
            r"\\resumeProjectHeading\s*\{(.*?)\}\{([^}]*)\}\s*"
            r"\\resumeItemListStart(.*?)\\resumeItemListEnd",
            re.DOTALL
        )

        for match in proj_pattern.finditer(proj_section):
            heading_raw = match.group(1)
            dates = _clean_latex(match.group(2))
            bullets_raw = match.group(3)

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

            # Extract bullets
            bullets = []
            for b in re.findall(r"\\resumeItem\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", bullets_raw):
                cleaned = _clean_latex(b).strip()
                if cleaned:
                    bullets.append(cleaned)

            if not bullets:
                bullet_matches = re.findall(r"\\resumeItem\{(.*?)\}(?=\s*\\resumeItem|\s*$)", bullets_raw + "\n\\resumeItem", re.DOTALL)
                for b in bullet_matches:
                    cleaned = _clean_latex(b).strip()
                    if cleaned:
                        bullets.append(cleaned)

            proj_id = f"proj_{_slugify(name_part)}"
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
        # The value group stops at a closing brace as well as a backslash.
        # With only [^\\]+ the final category ran past its own "}" and picked
        # up the section's trailing braces, so the last category always ended
        # in LaTeX residue ("Agile/Scrum}\n    }").
        for m in re.finditer(r"\\textbf\{([^}]+)\}\{:\s*([^\\}]+)\}", skills_section):
            label = _clean_latex(m.group(1))
            value = _clean_latex(m.group(2)).strip().rstrip("\\").strip()
            if label and value:
                skills_categories[label] = value

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

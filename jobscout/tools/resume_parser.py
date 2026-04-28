"""
Resume Parser — Extracts structured components from a master resume.

Parses a resume (plain text or extracted from .docx/.pdf) into discrete
components (experiences, projects, skills, education) that can be
independently scored and selected per JD.

No special formatting required from the user — the parser uses heuristics
to detect section boundaries and extract content.
"""

import re
from dataclasses import dataclass, field


@dataclass
class ResumeComponent:
    """A single scorable unit from the resume (one job or one project)."""
    id: str                         # Unique identifier, e.g. "exp_sorenson"
    type: str                       # "experience" or "project"
    title: str                      # Job title or project name
    organization: str               # Company name or empty for projects
    date_range: str                 # "June 2025 – Oct 2025"
    tech_line: str                  # Technologies listed in the header
    bullets: list[str]              # Individual bullet points
    raw_text: str                   # The original unmodified text block
    keywords: list[str] = field(default_factory=list)  # Auto-extracted keywords


@dataclass
class ParsedResume:
    """Fully parsed resume with all components."""
    contact_info: str               # Name, email, phone, links
    education: str                  # Education section text
    skills_text: str                # Full skills section text
    skills_list: list[str]          # Flat list of individual skills
    experiences: list[ResumeComponent]
    projects: list[ResumeComponent]
    raw_text: str                   # Original full text


# Common section header patterns
SECTION_PATTERNS = [
    # Matches lines like "EXPERIENCE", "Work Experience", "PROJECTS", etc.
    r"^(EXPERIENCE|WORK EXPERIENCE|PROFESSIONAL EXPERIENCE|EMPLOYMENT)",
    r"^(PROJECTS|PERSONAL PROJECTS|ACADEMIC PROJECTS|SELECTED PROJECTS)",
    r"^(EDUCATION|ACADEMIC BACKGROUND)",
    r"^(SKILLS|TECHNICAL SKILLS|CORE COMPETENCIES|TECHNOLOGIES)",
    r"^(CONTACT|SUMMARY|OBJECTIVE|PROFILE)",
    r"^(CERTIFICATIONS|AWARDS|PUBLICATIONS|VOLUNTEER)",
]

# Tech keywords to auto-extract from bullet text
TECH_KEYWORDS = [
    # Languages
    "python", "java", "javascript", "typescript", "c++", "c#", "go",
    "golang", "rust", "ruby", "scala", "kotlin", "swift", "php", "sql",
    "r", "matlab", "html", "css",
    # Frameworks
    "react", "angular", "vue", "svelte", "next.js", "nuxt.js", "django",
    "flask", "fastapi", "spring", "express", "node.js", "rails",
    ".net", "bootstrap", "tailwind",
    # Cloud & infra
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform",
    "cloudformation", "lambda", "ec2", "s3", "cloudwatch",
    "api gateway", "cloud run", "ecs", "eks", "fargate",
    # Data
    "mysql", "postgresql", "mongodb", "redis", "elasticsearch",
    "dynamodb", "firebase", "sqlite", "weaviate", "pinecone",
    "chromadb", "kafka", "rabbitmq", "airflow", "spark",
    "snowflake", "bigquery", "dbt",
    # AI/ML
    "pytorch", "tensorflow", "keras", "huggingface", "transformers",
    "bert", "gpt", "llm", "rag", "langchain", "llamaindex",
    "openai", "gemini", "claude", "nlp", "computer vision",
    "scikit-learn", "pandas", "numpy", "matplotlib",
    "embeddings", "vector database", "fine-tuning",
    "ai", "ml", "machine learning", "deep learning",
    "full-stack", "full stack", "backend", "frontend",
    "distributed systems", "data pipelines", "agents",
    # Tools & practices
    "git", "github", "gitlab", "ci/cd", "github actions", "jenkins",
    "jira", "agile", "scrum", "linux", "nginx", "apache",
    "rest api", "graphql", "grpc", "oauth", "jwt",
    "microservices", "serverless", "devops",
    # Testing
    "jest", "pytest", "junit", "selenium", "jmeter", "cypress",
    # Google ADK / agents
    "google adk", "agentic", "multi-agent", "tool use",
    "function calling", "streamlit",
]


def _slugify(text: str) -> str:
    """Convert text to a simple ID slug."""
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower().strip())
    return slug.strip("_")[:40]


def _extract_keywords(text: str) -> list[str]:
    """Extract tech keywords found in the given text."""
    text_lower = text.lower()
    found = []
    for kw in TECH_KEYWORDS:
        if kw in text_lower:
            # Avoid partial matches (e.g., "r" inside "react")
            if len(kw) <= 3:
                # For very short keywords, require word boundaries
                if re.search(rf"\b{re.escape(kw)}\b", text_lower):
                    found.append(kw)
            else:
                found.append(kw)
    return sorted(set(found))


def _is_section_header(line: str) -> str | None:
    """
    Check if a line is a section header. Returns the section type or None.
    """
    stripped = line.strip().upper()
    # Remove common separators
    stripped = re.sub(r"[=\-_]{3,}", "", stripped).strip()
    if not stripped:
        return None

    for pattern in SECTION_PATTERNS:
        if re.match(pattern, stripped):
            if "EXPERIENCE" in stripped or "EMPLOYMENT" in stripped:
                return "experience"
            elif "PROJECT" in stripped:
                return "project"
            elif "EDUCATION" in stripped:
                return "education"
            elif "SKILL" in stripped or "TECHNOLOG" in stripped or "COMPETENC" in stripped:
                return "skills"
            elif "CONTACT" in stripped or "SUMMARY" in stripped or "OBJECTIVE" in stripped:
                return "contact"
            else:
                return "other"
    return None


def _is_entry_header(line: str) -> bool:
    """
    Detect if a line starts a new experience/project entry.
    Heuristics: contains a date pattern, or has a pipe/dash separator
    with capitalized words.
    """
    # Date patterns: "Jun 2025", "2025 – Current", "Jan 2025 - Mar 2025"
    date_pattern = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Spring|Fall|Summer|Winter)\s*\.?\s*\d{4}"
    has_date = bool(re.search(date_pattern, line, re.IGNORECASE))

    # Also match "2024 – 2025", "Current", "Present"
    year_range = bool(re.search(r"\d{4}\s*[–\-]\s*(\d{4}|Current|Present)", line, re.IGNORECASE))

    return has_date or year_range


def _is_bullet(line: str) -> bool:
    """Check if a line is a bullet point."""
    stripped = line.strip()
    return bool(re.match(r"^[•\-\*▪▸◦‣]\s", stripped))


def _extract_date_range(text: str) -> str:
    """Pull date range from an entry header line."""
    # Match patterns like "Jun 2025 – Oct 2025" or "Jan 2025 - Current"
    match = re.search(
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Spring|Fall|Summer|Winter)"
        r"\.?\s*\d{4}\s*[–\-]\s*(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
        r"|Spring|Fall|Summer|Winter)\.?\s*\d{4}|Current|Present))",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()

    # Try year ranges: "2024 – 2025"
    match = re.search(r"(\d{4}\s*[–\-]\s*(?:\d{4}|Current|Present))", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    return ""


def _extract_tech_line(text: str) -> str:
    """
    Extract the technology/tools line from an entry header.
    Usually after a pipe: "Fabflix WebApp | Java, Docker, Kubernetes..."
    """
    # Look for pipe-separated tech list
    pipe_match = re.search(r"\|\s*(.+?)(?:\s{2,}|\t|$)", text)
    if pipe_match:
        return pipe_match.group(1).strip()

    return ""


def _is_tech_line(line: str) -> bool:
    """Check if a line is a 'Tech:' summary line after bullets."""
    stripped = line.strip()
    return bool(re.match(r"^Tech:?\s", stripped, re.IGNORECASE))


def _parse_entries(lines: list[str], entry_type: str) -> list[ResumeComponent]:
    """
    Parse a section's lines into individual entries (experiences or projects).
    """
    entries = []
    current_header = ""
    current_bullets = []
    current_raw_lines = []
    current_extra_tech = ""

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if _is_entry_header(stripped) and not _is_bullet(stripped):
            # Save previous entry if exists
            if current_header:
                raw = "\n".join(current_raw_lines)
                entry = _build_component(
                    current_header, current_bullets, raw, entry_type,
                    extra_tech=current_extra_tech,
                )
                entries.append(entry)

            # Start new entry
            current_header = stripped
            current_bullets = []
            current_raw_lines = [stripped]
            current_extra_tech = ""

        elif _is_bullet(stripped):
            # Clean the bullet marker
            bullet_text = re.sub(r"^[•\-\*▪▸◦‣]\s*", "", stripped)
            current_bullets.append(bullet_text)
            current_raw_lines.append(stripped)

        elif _is_tech_line(stripped):
            # Capture "Tech: Python, AWS, S3..." lines
            current_extra_tech = re.sub(r"^Tech:?\s*", "", stripped, flags=re.IGNORECASE)
            current_raw_lines.append(stripped)

        else:
            # Could be a continuation of the header or a sub-header
            if not current_bullets:
                # Still in header area (e.g., company name on separate line)
                current_header += " " + stripped
            current_raw_lines.append(stripped)

    # Don't forget the last entry
    if current_header:
        raw = "\n".join(current_raw_lines)
        entry = _build_component(
            current_header, current_bullets, raw, entry_type,
            extra_tech=current_extra_tech,
        )
        entries.append(entry)

    return entries


def _build_component(
    header: str, bullets: list[str], raw: str, entry_type: str,
    extra_tech: str = "",
) -> ResumeComponent:
    """Build a ResumeComponent from parsed header and bullets."""
    date_range = _extract_date_range(header)
    tech_line = _extract_tech_line(header)

    # Try to extract title and org from header
    # Common patterns:
    #   "Software Engineer Intern, Sorenson Communications"
    #   "Fabflix WebApp | Java, Docker, Kubernetes"
    #   "Associate Solutions Engineering Intern | Sorenson Communications"
    title = header
    org = ""

    # Remove date range from title
    if date_range:
        title = title.replace(date_range, "").strip()
        title = re.sub(r"[–\-]\s*$", "", title).strip()

    # Remove tech line from title
    if tech_line:
        pipe_idx = title.find("|")
        if pipe_idx > 0:
            title = title[:pipe_idx].strip()

    # Split on comma for "Title, Company" pattern
    comma_parts = title.split(",", 1)
    if len(comma_parts) == 2 and len(comma_parts[1].strip()) > 2:
        title = comma_parts[0].strip()
        org = comma_parts[1].strip()

    # Generate ID
    id_base = f"{entry_type[:3]}_{_slugify(org or title)}"

    # Auto-extract keywords from all text (including Tech: line)
    all_text = f"{header} {tech_line} {extra_tech} {' '.join(bullets)}"
    keywords = _extract_keywords(all_text)

    return ResumeComponent(
        id=id_base,
        type=entry_type,
        title=title,
        organization=org,
        date_range=date_range,
        tech_line=tech_line,
        bullets=bullets,
        raw_text=raw,
        keywords=keywords,
    )


def parse_resume(text: str) -> ParsedResume:
    """
    Parse a full resume text into structured components.

    Works with any standard resume format — no special tags needed.
    Uses heuristics to detect sections, entries, and bullets.

    Args:
        text: The full resume text (from .txt, extracted .docx, etc.)

    Returns:
        ParsedResume with all components extracted and keywords tagged.
    """
    lines = text.split("\n")

    # Identify sections
    sections: dict[str, list[str]] = {}
    current_section = "header"
    sections[current_section] = []

    for line in lines:
        section_type = _is_section_header(line)
        if section_type:
            current_section = section_type
            if current_section not in sections:
                sections[current_section] = []
        else:
            sections.setdefault(current_section, []).append(line)

    # Parse experiences
    exp_lines = sections.get("experience", [])
    experiences = _parse_entries(exp_lines, "experience")

    # Parse projects
    proj_lines = sections.get("project", [])
    projects = _parse_entries(proj_lines, "project")

    # Extract skills
    skills_lines = sections.get("skills", [])
    skills_text = "\n".join(skills_lines).strip()
    skills_list = _extract_keywords(skills_text)

    # Contact / header info
    header_lines = sections.get("header", []) + sections.get("contact", [])
    contact_info = "\n".join(l for l in header_lines if l.strip()).strip()

    # Education
    edu_lines = sections.get("education", [])
    education = "\n".join(l for l in edu_lines if l.strip()).strip()

    return ParsedResume(
        contact_info=contact_info,
        education=education,
        skills_text=skills_text,
        skills_list=skills_list,
        experiences=experiences,
        projects=projects,
        raw_text=text,
    )


def parse_resume_file(filepath: str) -> ParsedResume:
    """
    Parse a resume from a file path. Handles .txt and .docx.

    Args:
        filepath: Path to the resume file.

    Returns:
        ParsedResume with all components extracted.
    """
    import os

    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".txt":
        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read()
    elif ext == ".docx":
        # Use python-docx to extract text
        try:
            from docx import Document

            doc = Document(filepath)
            text = "\n".join(para.text for para in doc.paragraphs)
        except ImportError:
            raise ImportError(
                "python-docx is required to parse .docx files. "
                "Install it: pip install python-docx"
            )
    else:
        # Try reading as plain text
        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read()

    return parse_resume(text)


def print_parsed_resume(parsed: ParsedResume) -> None:
    """Pretty-print a parsed resume for debugging."""
    print("=" * 60)
    print("PARSED RESUME SUMMARY")
    print("=" * 60)

    print(f"\nContact: {parsed.contact_info[:80]}...")
    print(f"Education: {parsed.education[:80]}...")
    print(f"Skills ({len(parsed.skills_list)}): {', '.join(parsed.skills_list[:15])}...")

    print(f"\nExperiences ({len(parsed.experiences)}):")
    for exp in parsed.experiences:
        print(f"  [{exp.id}] {exp.title} @ {exp.organization}")
        print(f"    Date: {exp.date_range}")
        print(f"    Keywords: {', '.join(exp.keywords[:10])}")
        print(f"    Bullets: {len(exp.bullets)}")

    print(f"\nProjects ({len(parsed.projects)}):")
    for proj in parsed.projects:
        print(f"  [{proj.id}] {proj.title}")
        print(f"    Keywords: {', '.join(proj.keywords[:10])}")
        print(f"    Bullets: {len(proj.bullets)}")


# === CLI for testing ===
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m jobscout.tools.resume_parser <resume_file>")
        sys.exit(1)

    parsed = parse_resume_file(sys.argv[1])
    print_parsed_resume(parsed)

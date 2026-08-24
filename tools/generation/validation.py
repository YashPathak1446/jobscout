"""
Resume Output Validation

Validates Gemini's tailored resume output against quality requirements.
Checks structure, bullet counts, max character lengths, and optional metric preservation.

Location: jobscout/tools/generation/validation.py
"""

import re
from typing import Dict, List, Any


# ============================================================================
# Bullet-length validation zones (calibrated to Jake's LaTeX template, 11pt)
# ============================================================================
# Bullets wrap to multiple lines when long. Orphan lines (wrapped lines that
# are mostly empty) look unprofessional. We define explicit "good zones" and
# "bad zones" per line-count target.
#
# Calibration anchors (empirical, from user's rendered PDF samples):
#   LINE_1_END:  fills line 1                  →  110 chars
#   LINE_2_END:  fills line 1 + line 2         →  213 chars
#   LINE_3_END:  fills line 1 + 2 + 3          →  316 chars (estimated)
#
# A wrapped line must use at least ~67% of its budget to count as "well-filled."
LINE_1_END = 110
LINE_2_END = 213
LINE_3_END = 316
LINE_2_WELL_FILLED_START = 180  # 110 + ~67% of (213 - 110)
LINE_3_WELL_FILLED_START = 283  # 213 + ~67% of (316 - 213)

# Hard caps — beyond these, deterministic compression has failed and the
# bullet is flagged for human review.
EXPERIENCE_BULLET_MAX_CHARS = LINE_3_END   # 316 — experiences can use 3 lines
PROJECT_BULLET_MAX_CHARS = LINE_2_END      # 213 — projects max 2 lines

# Soft quality warnings only. Very short bullets can still be strong.
EXPERIENCE_BULLET_SOFT_MIN_CHARS = 60
PROJECT_BULLET_SOFT_MIN_CHARS = 60

# Bullet-count contract expected from the generation prompt.
EXPERIENCE_MIN_BULLETS = 2
EXPERIENCE_MAX_BULLETS = 4
PROJECT_MIN_BULLETS = 2
PROJECT_MAX_BULLETS = 3


class ValidationResult:
    """Result of validating resume output."""

    def __init__(self):
        self.valid = True
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.metrics: Dict[str, Any] = {}

    def add_error(self, message: str):
        """Add an error (makes validation fail)."""
        self.errors.append(message)
        self.valid = False

    def add_warning(self, message: str):
        """Add a warning (validation still passes)."""
        self.warnings.append(message)

    def __str__(self):
        status = "✅ VALID" if self.valid else "❌ INVALID"
        output = [f"\n{status}\n"]

        if self.errors:
            output.append("ERRORS:")
            for err in self.errors:
                output.append(f"  ❌ {err}")

        if self.warnings:
            output.append("\nWARNINGS:")
            for warn in self.warnings:
                output.append(f"  ⚠️  {warn}")

        if self.metrics:
            output.append("\nMETRICS:")
            for key, val in self.metrics.items():
                output.append(f"  • {key}: {val}")

        return "\n".join(output)


def validate_resume_output(data: dict, master_resume_text: str = "", bullet_budgets: dict = None) -> ValidationResult:
    """
    Validate tailored resume output from Gemini.

    Args:
        data: The JSON output from Gemini.
        master_resume_text: Original resume text for optional metric preservation check.
        bullet_budgets: Optional per-component bullet budgets from score-based allocation.
                        If provided, enforces exact bullet counts per component and
                        total budget limits instead of generic min/max rules.

    Returns:
        ValidationResult with errors, warnings, and metrics.
    """
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add_error("Output must be a JSON object/dict")
        return result

    # Validate required top-level structure.
    if "experiences" not in data:
        result.add_error("Missing 'experiences' key in output")
        return result

    if "projects" not in data:
        result.add_error("Missing 'projects' key in output")
        return result

    if not isinstance(data.get("experiences"), list):
        result.add_error("'experiences' must be a list")
        return result

    if not isinstance(data.get("projects"), list):
        result.add_error("'projects' must be a list")
        return result

    # Every entry must be an object, checked here and returned on rather than
    # defended against downstream.
    #
    # llama3.1:8b returned `"experiences": ["exp_sorenson", ...]` — a list of
    # id strings where the schema says objects. Valid JSON, wrong contract, and
    # it only started arriving once R45 asked the server for JSON and stopped
    # the replies failing at the parse. Three separate consumers then crashed
    # on `.get`, each looking like its own bug; they were one missing gate.
    # A structural problem belongs at the structural check.
    for section in ("experiences", "projects"):
        for position, component in enumerate(data.get(section) or [], 1):
            if not isinstance(component, dict):
                result.add_error(
                    f"{section[:-1].title()} {position} must be an object with "
                    f"id and bullets, not {type(component).__name__}")
                return result

    # Use budget-aware or generic validation based on whether budgets are provided
    if bullet_budgets:
        _validate_experiences_with_budget(
            data.get("experiences", []),
            bullet_budgets.get("experiences", {}),
            result,
        )
        _validate_projects_with_budget(
            data.get("projects", []),
            bullet_budgets.get("projects", {}),
            result,
        )
        _validate_total_budget(data, bullet_budgets, result)
    else:
        _validate_experiences(data.get("experiences", []), result)
        _validate_projects(data.get("projects", []), result)

    # Skills are optional here because the current generation prompt returns only
    # experiences/projects and the LaTeX builder preserves skills from the master resume.
    if "skills" in data:
        _validate_skills(data.get("skills", {}), result)

    if master_resume_text:
        _validate_metric_preservation(data, master_resume_text, result)
        _validate_no_invented_metrics(data, master_resume_text, result)

    result.metrics = {
        "total_experiences": len(data.get("experiences", [])),
        "total_projects": len(data.get("projects", [])),
        "total_experience_bullets": sum(len(exp.get("bullets", [])) for exp in data.get("experiences", [])),
        "total_project_bullets": sum(len(proj.get("bullets", [])) for proj in data.get("projects", [])),
    }

    return result


def _validate_experiences(experiences: List[dict], result: ValidationResult):
    """Validate experience entries."""
    if len(experiences) == 0:
        result.add_error("No experiences selected (need at least 1)")
        return

    if len(experiences) > 4:
        result.add_warning(f"Selected {len(experiences)} experiences (typically 2-3 is optimal)")

    for i, exp in enumerate(experiences):
        if not isinstance(exp, dict):
            result.add_error(f"Experience {i + 1}: entry must be an object/dict")
            continue

        company = exp.get("company") or f"Experience {i + 1}"
        bullets = exp.get("bullets", [])

        if not exp.get("id"):
            result.add_error(f"{company}: Missing 'id' field")
        if not exp.get("title"):
            result.add_error(f"{company}: Missing 'title' field")
        if not exp.get("company"):
            result.add_error(f"Experience {i + 1}: Missing 'company' field")
        if not exp.get("dates"):
            result.add_warning(f"{company}: Missing 'dates' field")
        if "location" not in exp:
            result.add_warning(f"{company}: Missing 'location' field")

        if not isinstance(bullets, list):
            result.add_error(f"{company}: 'bullets' must be a list")
            continue

        bullet_count = len(bullets)
        if bullet_count == 0:
            result.add_error(f"{company}: No bullets provided")
        elif bullet_count < EXPERIENCE_MIN_BULLETS:
            result.add_error(
                f"{company}: Only {bullet_count} bullet(s); expected {EXPERIENCE_MIN_BULLETS}-{EXPERIENCE_MAX_BULLETS}"
            )
        elif bullet_count > EXPERIENCE_MAX_BULLETS:
            result.add_error(
                f"{company}: {bullet_count} bullets; expected {EXPERIENCE_MIN_BULLETS}-{EXPERIENCE_MAX_BULLETS}"
            )

        for j, bullet in enumerate(bullets):
            _validate_bullet_length(
                label=f"{company} bullet {j + 1}",
                bullet=bullet,
                max_chars=EXPERIENCE_BULLET_MAX_CHARS,
                soft_min_chars=EXPERIENCE_BULLET_SOFT_MIN_CHARS,
                result=result,
                component_type="experience",
            )


def _validate_projects(projects: List[dict], result: ValidationResult):
    """Validate project entries."""
    if len(projects) == 0:
        result.add_warning("No projects selected (recommend 2-4 projects)")
        return

    if len(projects) > 5:
        result.add_warning(f"Selected {len(projects)} projects (typically 3-4 is optimal)")

    for i, proj in enumerate(projects):
        if not isinstance(proj, dict):
            result.add_error(f"Project {i + 1}: entry must be an object/dict")
            continue

        name = proj.get("name") or f"Project {i + 1}"
        bullets = proj.get("bullets", [])

        if not proj.get("id"):
            result.add_error(f"{name}: Missing 'id' field")
        if not proj.get("name"):
            result.add_error(f"Project {i + 1}: Missing 'name' field")
        if not proj.get("tech"):
            result.add_warning(f"{name}: Missing 'tech' field (technologies used)")
        if "url" not in proj:
            result.add_warning(f"{name}: Missing 'url' field; use empty string if no URL exists")
        if "dates" not in proj:
            result.add_warning(f"{name}: Missing 'dates' field")

        if not isinstance(bullets, list):
            result.add_error(f"{name}: 'bullets' must be a list")
            continue

        bullet_count = len(bullets)
        if bullet_count == 0:
            result.add_error(f"{name}: No bullets provided")
        elif bullet_count < PROJECT_MIN_BULLETS:
            result.add_error(
                f"{name}: Only {bullet_count} bullet(s); expected {PROJECT_MIN_BULLETS}-{PROJECT_MAX_BULLETS}"
            )
        elif bullet_count > PROJECT_MAX_BULLETS:
            result.add_error(
                f"{name}: {bullet_count} bullets; expected {PROJECT_MIN_BULLETS}-{PROJECT_MAX_BULLETS}"
            )

        for j, bullet in enumerate(bullets):
            _validate_bullet_length(
                label=f"{name} bullet {j + 1}",
                bullet=bullet,
                max_chars=PROJECT_BULLET_MAX_CHARS,
                soft_min_chars=PROJECT_BULLET_SOFT_MIN_CHARS,
                result=result,
                component_type="project",
            )


# =========================================================================
# BUDGET-AWARE VALIDATION
# =========================================================================

def _validate_experiences_with_budget(
    experiences: List[dict],
    exp_budgets: dict,
    result: ValidationResult,
):
    """Validate experiences against exact per-component bullet budgets."""
    if len(experiences) == 0:
        result.add_error("No experiences selected (need at least 1)")
        return

    for i, exp in enumerate(experiences):
        if not isinstance(exp, dict):
            result.add_error(f"Experience {i + 1}: entry must be an object/dict")
            continue

        company = exp.get("company") or f"Experience {i + 1}"
        comp_id = exp.get("id", "")
        bullets = exp.get("bullets", [])

        # Metadata checks
        if not exp.get("id"):
            result.add_error(f"{company}: Missing 'id' field")
        if not exp.get("title"):
            result.add_error(f"{company}: Missing 'title' field")
        if not exp.get("company"):
            result.add_error(f"Experience {i + 1}: Missing 'company' field")
        if not exp.get("dates"):
            result.add_warning(f"{company}: Missing 'dates' field")
        if "location" not in exp:
            result.add_warning(f"{company}: Missing 'location' field")

        if not isinstance(bullets, list):
            result.add_error(f"{company}: 'bullets' must be a list")
            continue

        # Check against budget
        expected = exp_budgets.get(comp_id)
        actual = len(bullets)

        if expected is not None and actual != expected:
            result.add_error(
                f"{company}: {actual} bullet(s) but budget requires exactly {expected}"
            )
        elif actual == 0:
            result.add_error(f"{company}: No bullets provided")

        # Length checks still apply
        for j, bullet in enumerate(bullets):
            _validate_bullet_length(
                label=f"{company} bullet {j + 1}",
                bullet=bullet,
                max_chars=EXPERIENCE_BULLET_MAX_CHARS,
                soft_min_chars=EXPERIENCE_BULLET_SOFT_MIN_CHARS,
                result=result,
                component_type="experience",
            )


def _validate_projects_with_budget(
    projects: List[dict],
    proj_budgets: dict,
    result: ValidationResult,
):
    """Validate projects against exact per-component bullet budgets."""
    if len(projects) == 0:
        result.add_warning("No projects selected (recommend 2-4 projects)")
        return

    for i, proj in enumerate(projects):
        if not isinstance(proj, dict):
            result.add_error(f"Project {i + 1}: entry must be an object/dict")
            continue

        name = proj.get("name") or f"Project {i + 1}"
        comp_id = proj.get("id", "")
        bullets = proj.get("bullets", [])

        # Metadata checks
        if not proj.get("id"):
            result.add_error(f"{name}: Missing 'id' field")
        if not proj.get("name"):
            result.add_error(f"Project {i + 1}: Missing 'name' field")
        if not proj.get("tech"):
            result.add_warning(f"{name}: Missing 'tech' field (technologies used)")
        if "url" not in proj:
            result.add_warning(f"{name}: Missing 'url' field; use empty string if no URL exists")
        if "dates" not in proj:
            result.add_warning(f"{name}: Missing 'dates' field")

        if not isinstance(bullets, list):
            result.add_error(f"{name}: 'bullets' must be a list")
            continue

        # Check against budget
        expected = proj_budgets.get(comp_id)
        actual = len(bullets)

        if expected is not None and actual != expected:
            result.add_error(
                f"{name}: {actual} bullet(s) but budget requires exactly {expected}"
            )
        elif actual == 0:
            result.add_error(f"{name}: No bullets provided")

        # Length checks still apply
        for j, bullet in enumerate(bullets):
            _validate_bullet_length(
                label=f"{name} bullet {j + 1}",
                bullet=bullet,
                max_chars=PROJECT_BULLET_MAX_CHARS,
                soft_min_chars=PROJECT_BULLET_SOFT_MIN_CHARS,
                result=result,
                component_type="project",
            )


def _validate_total_budget(
    data: dict,
    bullet_budgets: dict,
    result: ValidationResult,
):
    """Validate total bullet counts against the global budget."""
    totals = bullet_budgets.get("totals", {})

    actual_exp = sum(len(exp.get("bullets", [])) for exp in data.get("experiences", []))
    actual_proj = sum(len(proj.get("bullets", [])) for proj in data.get("projects", []))
    actual_total = actual_exp + actual_proj

    expected_exp = totals.get("experiences")
    expected_proj = totals.get("projects")
    expected_total = totals.get("overall")

    if expected_exp is not None and actual_exp != expected_exp:
        result.add_error(
            f"Total experience bullets: {actual_exp} (budget: {expected_exp})"
        )

    if expected_proj is not None and actual_proj != expected_proj:
        result.add_error(
            f"Total project bullets: {actual_proj} (budget: {expected_proj})"
        )

    if expected_total is not None and actual_total != expected_total:
        result.add_error(
            f"Total bullet count: {actual_total} (budget: {expected_total})"
        )


def _validate_bullet_length(
    label: str,
    bullet: Any,
    max_chars: int,
    soft_min_chars: int,
    result: ValidationResult,
    component_type: str,
):
    """
    Validate one bullet against the zone model.

    Project bullets allow 1 or 2 lines (≤110 or 180-213 chars).
    Experience bullets allow 1, 2, or 3 lines (≤110, 180-213, or 283-316 chars).

    Bullets in orphan zones (wrapped but line not well-filled) generate errors.
    Bullets that overflow the max generate errors. Very short bullets are
    warnings only.

    The repair loop is the recovery path for bullets that miss the zone;
    feedback names exact target ranges so the LLM can correct on retry.
    """
    if not isinstance(bullet, str):
        result.add_error(f"{label}: Bullet must be a string")
        return

    cleaned = bullet.strip()
    char_count = len(cleaned)

    if char_count == 0:
        result.add_error(f"{label}: Empty bullet")
        return

    # Overflow — beyond the max line count for this component type
    if char_count > max_chars:
        max_lines = 3 if component_type == "experience" else 2
        result.add_error(
            f"{label}: {char_count} chars exceeds {max_chars} max "
            f"(would overflow {max_lines} lines).\n"
            f"    → {cleaned[:80]}..."
        )
        return

    # Soft warning for very short bullets
    if char_count < soft_min_chars:
        result.add_warning(
            f"{label}: Only {char_count} chars (short but allowed if high-signal)\n"
            f"    → {cleaned[:80]}..."
        )

    # Line-2 orphan zone (111 to 179 inclusive)
    if LINE_1_END < char_count < LINE_2_WELL_FILLED_START:
        line_2_chars = char_count - LINE_1_END
        result.add_error(
            f"{label}: {char_count} chars falls in the line-2 orphan zone "
            f"(line 2 would have only ~{line_2_chars} chars).\n"
            f"    → Either compress to ≤{LINE_1_END} chars (1 line) "
            f"OR expand to {LINE_2_WELL_FILLED_START}-{LINE_2_END} chars (2 full lines).\n"
            f"    → {cleaned[:80]}..."
        )
        return

    # Line-3 orphan zone — only experiences have a line-3 zone
    if component_type == "experience":
        if LINE_2_END < char_count < LINE_3_WELL_FILLED_START:
            line_3_chars = char_count - LINE_2_END
            result.add_error(
                f"{label}: {char_count} chars falls in the line-3 orphan zone "
                f"(line 3 would have only ~{line_3_chars} chars).\n"
                f"    → Either compress to {LINE_2_WELL_FILLED_START}-{LINE_2_END} chars (2 lines) "
                f"OR expand to {LINE_3_WELL_FILLED_START}-{LINE_3_END} chars (3 full lines).\n"
                f"    → {cleaned[:80]}..."
            )
            return


def _validate_skills(skills: dict, result: ValidationResult):
    """Validate skills section only if Gemini output includes one."""
    if not isinstance(skills, dict):
        result.add_error("'skills' must be an object/dict if provided")
        return

    if not skills:
        result.add_warning("Skills section provided but empty")
        return

    if list(skills.keys())[0] != "Languages":
        result.add_warning("'Languages' should be the first skill category")

    if len(skills) > 5:
        result.add_warning(f"{len(skills)} skill categories (recommend 4 max for readability)")

    for category, value in skills.items():
        if not value or str(value).strip() == "":
            result.add_error(f"Skill category '{category}' is empty")


def _validate_metric_preservation(data: dict, master_text: str, result: ValidationResult):
    """
    Check if key metrics from master resume are preserved in output.

    This is a heuristic check. It extracts numbers/percentages and verifies they appear.
    """
    master_metrics = extract_metrics(master_text)
    output_text = str(data)

    missing_metrics = []
    for metric in master_metrics:
        if is_significant_metric(metric) and metric not in output_text:
            missing_metrics.append(metric)

    if missing_metrics and len(missing_metrics) > 3:
        result.add_warning(
            f"Several metrics from master resume not found in output: {', '.join(missing_metrics[:5])}"
        )


def _normalise_for_metric_search(text: str) -> str:
    """
    Flatten text so a figure matches however it was typeset.

    The master is LaTeX and writes its numbers in math mode: `$\\sim 503$ms`,
    `$\\sim 10$ minutes`, `$\\sim 3.6$x`. A generated bullet writes `503ms`,
    `10 min`, `3.6x`. Comparing those raw finds nothing in common, because a
    `$` sits between the number and its unit.

    That mattered: the first version of this check flagged 13 of 16 past
    Gemini resumes as fabricated, and every one was real — the markup, not
    the model. A fabrication check that cries wolf is worse than none, because
    it teaches you to click past the error that eventually matters.

    So: escapes become their character, LaTeX commands are dropped (they carry
    no digits), math delimiters go, and whitespace goes.
    """
    for escape, plain in (("\\%", "%"), ("\\$", "$"), ("\\&", "&"),
                          ("\\_", "_"), ("\\#", "#")):
        text = text.replace(escape, plain)

    # A resume writes "under a second"; a tailored bullet writes "<1 sec".
    # Same claim, and the numeral is the better line for it — so the words
    # are folded to the numeral rather than counted as an invention. Found by
    # the audit: this was the only remaining false positive across 16 past
    # resumes, and it appeared in four of them.
    for words, numeral in ((r"\ba second\b", "1 second"), (r"\bone second\b", "1 second"),
                           (r"\ba minute\b", "1 minute"), (r"\bone minute\b", "1 minute"),
                           (r"\ban hour\b", "1 hour"), (r"\bone hour\b", "1 hour")):
        text = re.sub(words, numeral, text, flags=re.IGNORECASE)

    text = re.sub(r"\\[a-zA-Z]+", " ", text)      # \sim, \times, \leftrightarrow
    text = text.replace("$", " ")                 # math-mode delimiters
    return re.sub(r"\s+", "", text.lower())


def _metric_variants(metric: str) -> set:
    """
    The forms one figure may legitimately take between resume and bullet.

    `36M+` in a bullet is `36M-article` in the master; `30K+ documents` is
    `30K+ web documents`. The number and its unit are the durable part, so the
    trailing noun and a trailing `+` are both allowed to differ.
    """
    base = _normalise_for_metric_search(metric)
    variants = {base, base.replace("+", "")}

    head = re.match(r"[\d.]+[a-z%]*\+?", base)
    if head:
        variants.add(head.group(0))
        variants.add(head.group(0).replace("+", ""))

    return {v for v in variants if v}


def find_invented_metrics(data: dict, master_text: str) -> List[tuple]:
    """
    Numbers in the output that appear nowhere in the master resume.

    The inverse of `_validate_metric_preservation`, and the direction that
    matters. That function asks whether the master's metrics survived, which a
    resume of pure invention passes trivially — every master metric is equally
    absent whether the model dropped them or replaced them with new ones.

    R44 is why this exists: llama3.1:8b returned "30% reduction in development
    time" and "25% increase in application performance" for work whose real
    bullets contain neither figure. A resume is a factual claim about a person,
    so a number the resume never made is not a style problem.

    Deliberately conservative. Only metrics `is_significant_metric` accepts are
    checked, and a metric counts as invented only when its normalised form
    appears nowhere in the whole master — not merely somewhere else in it.
    Flagging a real achievement would be worse than missing an invented one,
    because it would train someone to ignore this error.

    Returns (component_id, metric, bullet) for each, so the message can point
    at the sentence rather than just the number.
    """
    master = _normalise_for_metric_search(master_text)
    invented = []

    for section in ("experiences", "projects"):
        for component in data.get(section) or []:
            # Malformed shape is the structural validators' to report; this
            # one only has an opinion about numbers.
            if not isinstance(component, dict):
                continue
            component_id = component.get("id") or component.get("name") or "?"
            for bullet in component.get("bullets") or []:
                if not isinstance(bullet, str):
                    continue
                for metric in extract_metrics(bullet):
                    if not is_significant_metric(metric):
                        continue
                    if not any(v in master for v in _metric_variants(metric)):
                        invented.append((component_id, metric, bullet))

    return invented


def _validate_no_invented_metrics(data: dict, master_text: str, result: ValidationResult):
    """An invented figure is an error, not a warning. See `find_invented_metrics`."""
    for component_id, metric, bullet in find_invented_metrics(data, master_text):
        result.add_error(
            f"{component_id}: '{metric}' does not appear anywhere in your resume. "
            f"A tailored bullet may reword your work; it may not invent a number.\n"
            f"    → {bullet[:120]}"
        )


def extract_metrics(text: str) -> List[str]:
    """
    Extract numbers, percentages, and metrics from text.

    Returns list of metric strings like: ["10 min", "30 sec", "99.9%", "36M+"].
    """
    metrics = []

    patterns = [
        r"\d+\.?\d*\s*%",  # Percentages: 99.9%, 40%
        r"\d+\s*(?:min|sec|ms|hours?|days?)",  # Time units
        r"\d+[KMB]\+?",  # Large numbers: 36M+, 500K
        r"\d+\.\d+x",  # Multipliers: 2.5x
        r"p\d+",  # Percentiles: p95, p99
        r"\d+k\+?\s+(?:records|requests|documents|users)",  # Counts with units
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        metrics.extend(matches)

    return list(set(metrics))


def is_significant_metric(metric: str) -> bool:
    """Determine if a metric is significant enough to require preservation."""
    if "%" in metric or "x" in metric or any(c in metric for c in ["K", "M", "B"]):
        return True

    if any(unit in metric.lower() for unit in ["min", "sec", "ms", "hour", "day"]):
        return True

    if any(word in metric.lower() for word in ["records", "requests", "documents"]):
        return True

    if metric.strip().isdigit() and int(metric.strip()) < 10:
        return False

    return True


if __name__ == "__main__":
    test_output = {
        "experiences": [
            {
                "id": "exp_example",
                "title": "Software Engineer Intern",
                "company": "Tech Company",
                "location": "San Francisco, CA",
                "dates": "June 2025 - Oct 2025",
                "bullets": [
                    "Built API reducing latency by 40%",  # Short warning only
                    "Architected dual-Lambda REST API using Python and Terraform IaC, cutting test execution from 10 min to 30 sec",
                ],
            }
        ],
        "projects": [
            {
                "id": "proj_example",
                "name": "JobScout",
                "url": "https://github.com/user/jobscout",
                "tech": "Python, Gemini API, Docker",
                "dates": "Jan 2026 - Present",
                "bullets": [
                    "Built ranking pipeline matching resumes to job descriptions using embeddings and BM25 scoring.",
                    "Added validation gates to prevent malformed resume JSON from reaching LaTeX rendering.",
                ],
            }
        ],
    }

    result = validate_resume_output(test_output)
    print(result)
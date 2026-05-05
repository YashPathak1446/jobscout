"""
Resume Output Validation

Validates Gemini's tailored resume output against quality requirements.
Checks structure, bullet counts, max character lengths, and optional metric preservation.

Location: jobscout/tools/generation/validation.py
"""

import re
from typing import Dict, List, Any


# Hard layout limits used by the LaTeX resume renderer.
EXPERIENCE_BULLET_MAX_CHARS = 280
PROJECT_BULLET_MAX_CHARS = 140

# Soft quality warnings only. Short bullets can still be strong, so these do not fail validation.
EXPERIENCE_BULLET_SOFT_MIN_CHARS = 80
PROJECT_BULLET_SOFT_MIN_CHARS = 70

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
    """Validate one bullet. Empty/non-string/too-long are errors; short is warning only."""
    if not isinstance(bullet, str):
        result.add_error(f"{label}: Bullet must be a string")
        return

    cleaned = bullet.strip()
    char_count = len(cleaned)

    if char_count == 0:
        result.add_error(f"{label}: Empty bullet")
        return

    if char_count > max_chars:
        result.add_error(
            f"{label}: {char_count} chars (max {max_chars} for {component_type}s)\n"
            f"    → {cleaned[:80]}..."
        )
        return

    if char_count < soft_min_chars:
        result.add_warning(
            f"{label}: Only {char_count} chars (short but allowed if high-signal)\n"
            f"    → {cleaned[:80]}..."
        )


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
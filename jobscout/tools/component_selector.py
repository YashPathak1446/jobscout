"""
Component Selector — Ranks resume components against a JD.

Deterministic scoring (no LLM calls). Computes how well each experience
and project matches a given job description, accounting for exact matches
and similar technology partial credit.
"""

from dataclasses import dataclass

from jobscout.tools.resume_parser import ParsedResume, ResumeComponent
from jobscout.tools.research_tools import extract_keywords


@dataclass
class ComponentScore:
    """Score result for a single component against a JD."""
    component_id: str
    component_type: str         # "experience" or "project"
    title: str
    organization: str
    score: float                # 0.0 to 1.0
    exact_matches: list[str]    # Skills matched exactly
    similar_matches: list[str]  # Skills matched via equivalency
    missing: list[str]          # JD skills not covered at all


@dataclass
class SelectionResult:
    """Full selection result for a JD."""
    jd_keywords: dict[str, list[str]]   # Categorized keywords from JD
    all_jd_skills: list[str]            # Flat list of all JD skills
    overall_score: float                # 0-100 weighted score
    selected_experiences: list[ComponentScore]
    selected_projects: list[ComponentScore]
    all_scores: list[ComponentScore]     # Every component scored
    lead_skills: list[str]              # Skills to put first in skills section


def _flatten_keywords(categorized: dict[str, list[str]]) -> list[str]:
    """Flatten categorized keyword dict into a unique sorted list."""
    flat = set()
    for keywords in categorized.values():
        flat.update(keywords)
    return sorted(flat)


def score_component(
    component: ResumeComponent,
    jd_skills: list[str],
    similar_tech_map: dict[str, list[str]],
    similar_weight: float = 0.6,
) -> ComponentScore:
    """
    Score a single resume component against JD skills.

    Uses exact matching first, then partial credit for similar technologies.

    Args:
        component: The resume component to score.
        jd_skills: Flat list of skills required by the JD.
        similar_tech_map: Mapping of tech → list of similar alternatives.
        similar_weight: Weight for similar tech matches (0.0 to 1.0).

    Returns:
        ComponentScore with match details.
    """
    comp_skills = set(component.keywords)
    jd_set = set(jd_skills)

    exact_matches = sorted(comp_skills & jd_set)
    similar_matches = []
    missing = []

    # For each JD skill not exactly matched, check for similar tech
    for jd_skill in sorted(jd_set - comp_skills):
        similar_options = similar_tech_map.get(jd_skill, [])
        found_similar = False
        for alt in similar_options:
            if alt in comp_skills:
                similar_matches.append(f"{alt}≈{jd_skill}")
                found_similar = True
                break
        if not found_similar:
            missing.append(jd_skill)

    # Calculate score
    if not jd_set:
        score = 0.0
    else:
        exact_points = len(exact_matches)
        similar_points = len(similar_matches) * similar_weight
        total_possible = len(jd_set)
        score = (exact_points + similar_points) / total_possible

    return ComponentScore(
        component_id=component.id,
        component_type=component.type,
        title=component.title,
        organization=component.organization,
        score=round(score, 3),
        exact_matches=exact_matches,
        similar_matches=similar_matches,
        missing=missing,
    )


def select_components(
    parsed_resume: ParsedResume,
    jd_text: str,
    similar_tech_map: dict[str, list[str]],
    similar_weight: float = 0.6,
    max_experiences: int = 3,
    max_projects: int = 4,
) -> SelectionResult:
    """
    Score all resume components against a JD and select the best ones.

    This is the main entry point for component selection. It:
    1. Extracts keywords from the JD (deterministic)
    2. Scores every experience and project
    3. Selects the top N of each type
    4. Computes an overall fit score

    Args:
        parsed_resume: The parsed master resume.
        jd_text: Raw job description text.
        similar_tech_map: Technology equivalency map from config.
        similar_weight: Weight for similar tech (default 0.6).
        max_experiences: Max experiences to select.
        max_projects: Max projects to select.

    Returns:
        SelectionResult with scored and selected components.
    """
    # Step 1: Extract JD keywords (deterministic, no LLM)
    jd_keywords = extract_keywords(jd_text)
    jd_keywords_data = jd_keywords.get("keywords_found", {})
    all_jd_skills = _flatten_keywords(jd_keywords_data)

    # Step 2: Score every component
    all_scores = []

    for exp in parsed_resume.experiences:
        score = score_component(exp, all_jd_skills, similar_tech_map, similar_weight)
        all_scores.append(score)

    for proj in parsed_resume.projects:
        score = score_component(proj, all_jd_skills, similar_tech_map, similar_weight)
        all_scores.append(score)

    # Step 3: Select top N experiences and projects
    exp_scores = [s for s in all_scores if s.component_type == "experience"]
    proj_scores = [s for s in all_scores if s.component_type == "project"]

    exp_scores.sort(key=lambda s: s.score, reverse=True)
    proj_scores.sort(key=lambda s: s.score, reverse=True)

    selected_exp = exp_scores[:max_experiences]
    selected_proj = proj_scores[:max_projects]

    # Step 4: Compute overall score
    # Weighted average: experiences count 60%, projects 40%
    if selected_exp or selected_proj:
        exp_avg = (
            sum(s.score for s in selected_exp) / len(selected_exp)
            if selected_exp
            else 0
        )
        proj_avg = (
            sum(s.score for s in selected_proj) / len(selected_proj)
            if selected_proj
            else 0
        )

        # Also factor in skills section match
        resume_skills = set(parsed_resume.skills_list)
        jd_set = set(all_jd_skills)
        skills_match = len(resume_skills & jd_set) / len(jd_set) if jd_set else 0

        # Weighted: 40% experience, 30% projects, 30% skills
        overall = (exp_avg * 0.4 + proj_avg * 0.3 + skills_match * 0.3) * 100
    else:
        overall = 0.0

    # Step 5: Determine lead skills (JD skills that appear in resume)
    resume_all_skills = set(parsed_resume.skills_list)
    for comp in parsed_resume.experiences + parsed_resume.projects:
        resume_all_skills.update(comp.keywords)

    lead_skills = [s for s in all_jd_skills if s in resume_all_skills]

    return SelectionResult(
        jd_keywords=jd_keywords_data,
        all_jd_skills=all_jd_skills,
        overall_score=round(overall, 1),
        selected_experiences=selected_exp,
        selected_projects=selected_proj,
        all_scores=all_scores,
        lead_skills=lead_skills,
    )


def print_selection_result(result: SelectionResult) -> None:
    """Pretty-print selection results for debugging."""
    print("=" * 60)
    print(f"OVERALL FIT SCORE: {result.overall_score}/100")
    print("=" * 60)

    print(f"\nJD requires: {', '.join(result.all_jd_skills)}")
    print(f"Lead skills: {', '.join(result.lead_skills)}")

    print(f"\nSelected Experiences ({len(result.selected_experiences)}):")
    for s in result.selected_experiences:
        org_str = f" @ {s.organization}" if s.organization else ""
        print(f"  [{s.score:.0%}] {s.title}{org_str}")
        print(f"    Exact: {', '.join(s.exact_matches)}")
        if s.similar_matches:
            print(f"    Similar: {', '.join(s.similar_matches)}")
        if s.missing:
            print(f"    Missing: {', '.join(s.missing[:5])}")

    print(f"\nSelected Projects ({len(result.selected_projects)}):")
    for s in result.selected_projects:
        print(f"  [{s.score:.0%}] {s.title}")
        print(f"    Exact: {', '.join(s.exact_matches)}")
        if s.similar_matches:
            print(f"    Similar: {', '.join(s.similar_matches)}")

    print(f"\nAll Scores:")
    for s in sorted(result.all_scores, key=lambda x: x.score, reverse=True):
        org_str = f" @ {s.organization}" if s.organization else ""
        print(f"  {s.score:.0%}  {s.component_type[:3]}  {s.title}{org_str}")


# === CLI for testing ===
if __name__ == "__main__":
    import sys
    from jobscout.tools.resume_parser import parse_resume_file
    import config

    if len(sys.argv) < 3:
        print("Usage: python -m jobscout.tools.component_selector <resume> <jd_file>")
        sys.exit(1)

    parsed = parse_resume_file(sys.argv[1])
    with open(sys.argv[2], "r") as f:
        jd_text = f.read()

    result = select_components(
        parsed, jd_text,
        similar_tech_map=config.SIMILAR_TECH_MAP,
        similar_weight=config.SIMILAR_TECH_WEIGHT,
        max_experiences=config.MAX_EXPERIENCES_TO_SELECT,
        max_projects=config.MAX_PROJECTS_TO_SELECT,
    )
    print_selection_result(result)

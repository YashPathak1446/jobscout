"""
Tools for analyzing resume fit against a job description.
"""

import json


def analyze_skill_match(
    resume_skills: str, job_requirements: str
) -> dict:
    """
    Compare skills from a resume against job requirements and produce
    a structured match analysis.

    Args:
        resume_skills: Comma-separated list of skills from the resume
            (e.g. "python, aws, docker, terraform, mongodb")
        job_requirements: Comma-separated list of required skills from the JD
            (e.g. "python, kubernetes, aws, react, sql")

    Returns:
        dict with matched skills, missing skills, and a match percentage.
    """
    resume_set = {s.strip().lower() for s in resume_skills.split(",") if s.strip()}
    job_set = {s.strip().lower() for s in job_requirements.split(",") if s.strip()}

    matched = resume_set & job_set
    missing = job_set - resume_set
    bonus = resume_set - job_set  # Skills you have that aren't required

    match_pct = (len(matched) / len(job_set) * 100) if job_set else 0

    return {
        "status": "success",
        "match_percentage": round(match_pct, 1),
        "matched_skills": sorted(matched),
        "missing_skills": sorted(missing),
        "bonus_skills": sorted(bonus),
        "total_required": len(job_set),
        "total_matched": len(matched),
    }


def score_experience_level(
    years_experience: int,
    required_years: int,
    has_internship: bool,
    has_projects: bool,
) -> dict:
    """
    Score how well a candidate's experience level matches the job requirements.

    Args:
        years_experience: Candidate's years of professional experience.
        required_years: Years required by the job posting.
        has_internship: Whether the candidate has relevant internship experience.
        has_projects: Whether the candidate has relevant personal/academic projects.

    Returns:
        dict with experience score (0-100), assessment, and recommendations.
    """
    score = 0
    notes = []

    # Base score from years
    if required_years == 0:
        score = 80
        notes.append("Entry-level role — strong fit for new grads")
    elif years_experience >= required_years:
        score = 90
        notes.append("Meets or exceeds experience requirement")
    else:
        gap = required_years - years_experience
        score = max(30, 80 - (gap * 15))
        notes.append(f"Short by {gap} year(s) of professional experience")

    # Boost for internships
    if has_internship:
        score = min(100, score + 10)
        notes.append("Internship experience adds credibility")

    # Boost for projects
    if has_projects:
        score = min(100, score + 5)
        notes.append("Relevant projects demonstrate initiative")

    assessment = "Strong" if score >= 75 else "Moderate" if score >= 50 else "Stretch"

    return {
        "status": "success",
        "score": score,
        "assessment": assessment,
        "notes": notes,
    }


def generate_resume_bullets(
    skill: str, project_context: str
) -> dict:
    """
    Generate a STAR-format resume bullet point suggestion that maps
    a candidate's experience to a specific required skill.

    Args:
        skill: The skill to highlight (e.g. "kubernetes")
        project_context: Brief context about where the candidate used this skill
            (e.g. "Deployed Fabflix movie app using K8s on AWS EC2")

    Returns:
        dict with a suggested bullet point and talking point.
    """
    return {
        "status": "success",
        "skill": skill,
        "context": project_context,
        "instruction": (
            "Using the skill and context provided, generate a strong STAR-format "
            "resume bullet that quantifies impact. Start with a strong action verb. "
            "Include the technology name and a measurable outcome."
        ),
    }

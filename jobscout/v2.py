"""
JobScout V2 — Pipeline Runner
Runs the full Discovery → Fit Scoring → Resume Generation pipeline.

Usage:
    python -m jobscout.v2 --max-jobs 5
    python -m jobscout.v2 --max-jobs 5 --dry-run
    python -m jobscout.v2 --max-jobs 50 --threshold 80
"""

import argparse
import os
import sys
from datetime import datetime

from jobscout.tools.resume_parser import parse_resume_file, print_parsed_resume
from jobscout.tools.component_selector import select_components, SelectionResult
from jobscout.tools.job_search_tools import (
    search_jobs,
    generate_search_queries,
    JobListing,
    print_listings,
)

try:
    import config
except ImportError:
    print("Error: config.py not found. Run from the project root directory.")
    sys.exit(1)


def display_banner():
    """Show the startup banner."""
    print()
    print("=" * 60)
    print("  🔍 JobScout V2 — Automated Job Discovery & Fit Scoring")
    print("=" * 60)
    print()


def discover_jobs(parsed_resume, max_jobs: int) -> list[JobListing]:
    """
    Phase 1: Discover jobs using auto-generated search queries.
    """
    print("📡 Phase 1: Discovering jobs...\n")

    # Generate search queries from resume skills
    all_skills = list(parsed_resume.skills_list)
    for exp in parsed_resume.experiences:
        all_skills.extend(exp.keywords)
    for proj in parsed_resume.projects:
        all_skills.extend(proj.keywords)
    unique_skills = sorted(set(all_skills))

    queries = generate_search_queries(
        skills=unique_skills,
        base_titles=config.BASE_TITLES,
        experience_levels=config.EXPERIENCE_LEVEL,
        max_queries=8,
    )

    print(f"  Search queries generated from your resume:")
    for i, q in enumerate(queries, 1):
        print(f"    {i}. \"{q}\"")
    print()

    # Search across configured APIs
    listings = search_jobs(
        queries=queries,
        country=config.COUNTRY,
        locations=config.LOCATIONS if config.LOCATIONS else None,
        max_results_per_query=max(3, max_jobs // len(queries)),
        max_days_old=config.JOB_RECENCY_HOURS // 24,
        apis=config.JOB_APIS,
    )

    # Trim to max_jobs
    listings = listings[:max_jobs]

    print(f"  ✅ Found {len(listings)} unique jobs\n")
    return listings


def score_jobs(
    listings: list[JobListing],
    parsed_resume,
    threshold: int,
) -> list[tuple[JobListing, SelectionResult]]:
    """
    Phase 2: Score each job against the resume.
    Returns jobs that pass the threshold, sorted by score.
    """
    print(f"📊 Phase 2: Scoring {len(listings)} jobs (threshold: {threshold}%)...\n")

    scored = []
    for listing in listings:
        result = select_components(
            parsed_resume,
            listing.description,
            similar_tech_map=config.SIMILAR_TECH_MAP,
            similar_weight=config.SIMILAR_TECH_WEIGHT,
            max_experiences=config.MAX_EXPERIENCES_TO_SELECT,
            max_projects=config.MAX_PROJECTS_TO_SELECT,
        )
        scored.append((listing, result))

    # Sort by score descending
    scored.sort(key=lambda x: x[1].overall_score, reverse=True)

    # Display all scores
    print(f"  {'#':<4} {'Score':<8} {'Company':<20} {'Title':<35} {'Pass'}")
    print("  " + "-" * 75)
    for i, (listing, result) in enumerate(scored, 1):
        passed = "✅" if result.overall_score >= threshold else "❌"
        print(
            f"  {i:<4} {result.overall_score:>5.1f}%  "
            f"{listing.company:<20} {listing.title:<35} {passed}"
        )

    # Filter to passing jobs
    passing = [(l, r) for l, r in scored if r.overall_score >= threshold]
    print(f"\n  {len(passing)} of {len(scored)} jobs pass the {threshold}% threshold\n")

    return passing


def show_job_details(listing: JobListing, result: SelectionResult, index: int):
    """Show detailed info for a single scored job."""
    print(f"\n  --- Job #{index} ---")
    print(f"  Company:  {listing.company}")
    print(f"  Title:    {listing.title}")
    print(f"  Location: {listing.location}")
    print(f"  Score:    {result.overall_score}%")

    if listing.salary_min and listing.salary_max:
        print(f"  Salary:   ${listing.salary_min:,.0f} - ${listing.salary_max:,.0f}")

    print(f"  Apply:    {listing.apply_url}")

    # Show selected components
    print(f"\n  Selected experiences:")
    for s in result.selected_experiences:
        org = f" @ {s.organization}" if s.organization else ""
        print(f"    [{s.score:.0%}] {s.title}{org}")
        print(f"         Matched: {', '.join(s.exact_matches)}")
        if s.similar_matches:
            print(f"         Similar: {', '.join(s.similar_matches)}")

    print(f"  Selected projects:")
    for s in result.selected_projects:
        print(f"    [{s.score:.0%}] {s.title}")
        print(f"         Matched: {', '.join(s.exact_matches)}")

    print(f"  Lead skills: {', '.join(result.lead_skills)}")


def human_checkpoint_scoring(
    passing: list[tuple[JobListing, SelectionResult]],
) -> list[tuple[JobListing, SelectionResult]]:
    """
    Checkpoint after scoring: let the user choose which jobs to proceed with.
    """
    if not config.CHECKPOINT_AFTER_SCORING:
        return passing

    if not passing:
        print("  No jobs passed the threshold. Try lowering FIT_THRESHOLD in config.py.\n")
        return []

    print("🛑 Checkpoint: Which jobs should we generate resumes for?\n")

    for i, (listing, result) in enumerate(passing, 1):
        show_job_details(listing, result, i)

    print(f"\n  Options:")
    print(f"    'all'     — generate resumes for all {len(passing)} jobs")
    print(f"    '1,3,5'   — generate for specific jobs by number")
    print(f"    'details' — show full JD for a specific job")
    print(f"    'none'    — skip resume generation, just save the summary")
    print()

    while True:
        choice = input("  → Your choice: ").strip().lower()

        if choice == "all":
            return passing
        elif choice == "none":
            return []
        elif choice == "details":
            num = input("    Which job number? ").strip()
            try:
                idx = int(num) - 1
                if 0 <= idx < len(passing):
                    listing, _ = passing[idx]
                    print(f"\n    Full description:\n    {listing.description}\n")
                else:
                    print("    Invalid number.")
            except ValueError:
                print("    Enter a number.")
        else:
            try:
                indices = [int(x.strip()) - 1 for x in choice.split(",")]
                selected = [passing[i] for i in indices if 0 <= i < len(passing)]
                if selected:
                    print(f"  ✅ Selected {len(selected)} jobs for resume generation\n")
                    return selected
                else:
                    print("  No valid selections. Try again.")
            except (ValueError, IndexError):
                print("  Invalid input. Enter 'all', 'none', or comma-separated numbers.")


def save_summary(
    scored: list[tuple[JobListing, SelectionResult]],
    output_dir: str,
):
    """Save a markdown summary of all scored jobs."""
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, "summary.md")

    lines = [
        f"# JobScout V2 — Run Summary",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Jobs scored:** {len(scored)}",
        "",
        "| # | Score | Company | Title | Location | Apply Link |",
        "|---|-------|---------|-------|----------|------------|",
    ]

    for i, (listing, result) in enumerate(scored, 1):
        lines.append(
            f"| {i} | {result.overall_score:.1f}% | {listing.company} | "
            f"{listing.title} | {listing.location} | "
            f"[Apply]({listing.apply_url}) |"
        )

    lines.append("")
    lines.append("## Detailed Scores")
    lines.append("")

    for i, (listing, result) in enumerate(scored, 1):
        lines.append(f"### {i}. {listing.company} — {listing.title}")
        lines.append(f"- **Score:** {result.overall_score:.1f}%")
        lines.append(f"- **Location:** {listing.location}")
        if listing.salary_min and listing.salary_max:
            lines.append(
                f"- **Salary:** ${listing.salary_min:,.0f} - ${listing.salary_max:,.0f}"
            )
        lines.append(f"- **Apply:** {listing.apply_url}")
        lines.append(f"- **Lead skills:** {', '.join(result.lead_skills)}")

        exp_names = [
            f"{s.title} ({s.score:.0%})"
            for s in result.selected_experiences
        ]
        proj_names = [
            f"{s.title} ({s.score:.0%})"
            for s in result.selected_projects
        ]
        lines.append(f"- **Best experiences:** {', '.join(exp_names)}")
        lines.append(f"- **Best projects:** {', '.join(proj_names)}")
        lines.append("")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"  📄 Summary saved: {filepath}")
    return filepath


def main():
    parser = argparse.ArgumentParser(
        description="JobScout V2 — Automated Job Discovery & Resume Generation"
    )
    parser.add_argument(
        "--max-jobs", type=int, default=config.MAX_JOBS_TO_DISCOVER,
        help=f"Max jobs to discover (default: {config.MAX_JOBS_TO_DISCOVER})"
    )
    parser.add_argument(
        "--threshold", type=int, default=config.FIT_THRESHOLD,
        help=f"Minimum fit score (default: {config.FIT_THRESHOLD})"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Discover and score only — skip resume generation"
    )
    parser.add_argument(
        "--resume", default=config.MASTER_RESUME_PATH,
        help=f"Path to master resume (default: {config.MASTER_RESUME_PATH})"
    )
    args = parser.parse_args()

    display_banner()

    # Load and parse resume
    print(f"📝 Loading resume: {args.resume}")
    parsed = parse_resume_file(args.resume)
    print(
        f"  ✅ Found {len(parsed.experiences)} experiences, "
        f"{len(parsed.projects)} projects, "
        f"{len(parsed.skills_list)} skills\n"
    )

    # Phase 1: Discover jobs
    listings = discover_jobs(parsed, args.max_jobs)
    if not listings:
        print("  ❌ No jobs found. Check your API keys or try different search terms.")
        return

    # Phase 2: Score jobs
    passing = score_jobs(listings, parsed, args.threshold)

    # Create output directory
    timestamp = datetime.now().strftime("%Y-%m-%d")
    output_dir = os.path.join(config.OUTPUT_DIR, timestamp)

    # Human checkpoint
    selected = human_checkpoint_scoring(passing)

    # Save summary (always, even if no resumes generated)
    save_summary(
        [(l, r) for l, r in sorted(
            [(l, r) for l, r in zip(
                [x[0] for x in passing] if passing else [],
                [x[1] for x in passing] if passing else [],
            )],
            key=lambda x: x[1].overall_score,
            reverse=True,
        )] if passing else [],
        output_dir,
    )

    if args.dry_run:
        print("\n  🏃 Dry run — skipping resume generation.")
        print("  Remove --dry-run to generate tailored resumes.\n")
        return

    if not selected:
        print("\n  No jobs selected for resume generation. Done.\n")
        return

    # Phase 3: Resume generation (placeholder for Phase 3)
    print(f"\n📝 Phase 3: Resume generation for {len(selected)} jobs...")
    print("  ⚠️  Resume generation will be available after Phase 3 is built.")
    print("  For now, use the summary and apply links to apply manually.\n")

    for i, (listing, result) in enumerate(selected, 1):
        print(f"  {i}. {listing.company} — {listing.title}")
        print(f"     Score: {result.overall_score:.1f}%")
        print(f"     Apply: {listing.apply_url}")
        print(f"     Components: {', '.join(s.title for s in result.selected_experiences)}")
        print()

    print("✅ Done!\n")


if __name__ == "__main__":
    main()

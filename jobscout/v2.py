"""
JobScout V2 — Full Pipeline Runner
Discovery → Enrichment → Embedding Scoring → Human Checkpoint → Resume Gen

Usage:
    python -m jobscout.v2 --mock --dry-run          # Test: zero API calls
    python -m jobscout.v2 --mock-embeddings --dry-run  # Real jobs, mock scoring
    python -m jobscout.v2 --dry-run                  # Real everything, skip resume gen
    python -m jobscout.v2 --max-jobs 50              # Full production run
"""

import argparse
import os
import sys
from datetime import datetime

try:
    import config
except ImportError:
    print("Error: config.py not found. Run from the project root.")
    sys.exit(1)

from jobscout.tools.resume_parser import parse_resume_file
from jobscout.tools.job_search_tools import (
    search_jobs, generate_search_queries,
    enrich_listings_with_full_jd, JobListing,
)
from jobscout.tools.embedding_scorer import (
    embed_resume_components, embed_resume_components_mock,
    score_job_with_embeddings, score_job_mock,
    EmbeddingScore,
)


def display_banner():
    print("\n" + "=" * 60)
    print("  🔍 JobScout V2 — AI-Powered Job Discovery & Resume Builder")
    print("=" * 60 + "\n")


def phase1_discover(parsed_resume, max_jobs: int, use_mock: bool) -> list[JobListing]:
    """Phase 1: Discover jobs via Serper → Adzuna → Mock."""
    print("📡 Phase 1: Discovering jobs...\n")

    # Collect all skills for query generation
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

    print("  Search queries (auto-generated from your resume):")
    for i, q in enumerate(queries, 1):
        print(f"    {i}. \"{q}\"")
    print()

    if use_mock:
        priority = ["mock"]
    else:
        priority = getattr(config, "JOB_DISCOVERY_PRIORITY", ["serper", "adzuna"])

    listings = search_jobs(
        queries=queries,
        country=config.COUNTRY,
        locations=config.LOCATIONS if config.LOCATIONS else None,
        max_results_per_query=max(3, max_jobs // len(queries) + 1),
        max_days_old=config.JOB_RECENCY_HOURS // 24,
        discovery_priority=priority,
        max_total=max_jobs,
    )

    sources = {}
    for l in listings:
        sources[l.source] = sources.get(l.source, 0) + 1
    source_str = ", ".join(f"{v} from {k}" for k, v in sources.items())
    print(f"  ✅ Found {len(listings)} unique jobs ({source_str})\n")
    return listings


def phase2_enrich(listings: list[JobListing], skip: bool = False) -> list[JobListing]:
    """Phase 2: Best-effort scrape full JDs from apply URLs."""
    if skip:
        print("📄 Phase 2: Enrichment skipped (mock mode)\n")
        return listings

    print(f"📄 Phase 2: Enriching {len(listings)} jobs with full JDs...\n")
    listings = enrich_listings_with_full_jd(listings, delay=1.5)

    enriched = sum(1 for l in listings if l.full_jd)
    print(f"  ✅ {enriched}/{len(listings)} jobs enriched with full JD text\n")
    return listings


def phase3_score(
    listings: list[JobListing],
    parsed_resume,
    threshold: int,
    use_mock_embeddings: bool,
) -> list[tuple[JobListing, EmbeddingScore]]:
    """Phase 3: Score all jobs using embeddings."""
    print(f"📊 Phase 3: Scoring {len(listings)} jobs with embeddings...\n")

    # Embed resume components (one-time)
    if use_mock_embeddings:
        print("  Using mock embeddings (no API calls)\n")
        embeddings = embed_resume_components_mock(parsed_resume)
    else:
        print("  Embedding resume components via Gemini API...\n")
        embeddings = embed_resume_components(parsed_resume)

    if not embeddings:
        print("  ❌ Failed to generate embeddings. Check GOOGLE_API_KEY.")
        return []

    # Score each job
    scored = []
    for listing in listings:
        # Use full JD if available, otherwise title + snippet
        jd_text = listing.full_jd if listing.full_jd else f"{listing.title} {listing.description}"

        if use_mock_embeddings:
            result = score_job_mock(
                jd_text, embeddings, parsed_resume,
                config.MAX_EXPERIENCES_TO_SELECT, config.MAX_PROJECTS_TO_SELECT,
            )
        else:
            result = score_job_with_embeddings(
                jd_text, embeddings, parsed_resume,
                config.MAX_EXPERIENCES_TO_SELECT, config.MAX_PROJECTS_TO_SELECT,
            )

        if result:
            result.job_id = listing.id
            result.title = listing.title
            result.company = listing.company
            scored.append((listing, result))

    # Sort by score
    scored.sort(key=lambda x: x[1].overall_score, reverse=True)

    # Display results
    has_jd = lambda l: "📄" if l.full_jd else "📋"
    print(f"  {'#':<4} {'Score':<8} {'JD':<4} {'Company':<20} {'Title':<35} {'Pass'}")
    print("  " + "-" * 80)
    for i, (listing, result) in enumerate(scored, 1):
        passed = "✅" if result.overall_score >= threshold else "❌"
        print(
            f"  {i:<4} {result.overall_score:>5.1f}%  "
            f"{has_jd(listing):<4} "
            f"{listing.company[:19]:<20} "
            f"{listing.title[:34]:<35} {passed}"
        )

    passing = [(l, r) for l, r in scored if r.overall_score >= threshold]
    print(f"\n  📄 = full JD scraped, 📋 = snippet only")
    print(f"  {len(passing)}/{len(scored)} jobs pass the {threshold}% threshold\n")
    return passing


def checkpoint_scoring(
    passing: list[tuple[JobListing, EmbeddingScore]],
    parsed_resume,
) -> list[tuple[JobListing, EmbeddingScore]]:
    """Human checkpoint after scoring."""
    if not config.CHECKPOINT_AFTER_SCORING:
        return passing

    if not passing:
        print("  No jobs passed the threshold. Try lowering FIT_THRESHOLD in config.py.\n")
        return []

    print("🛑 Checkpoint: Review scored jobs\n")

    # Show details for each passing job
    for i, (listing, result) in enumerate(passing, 1):
        print(f"  --- #{i} [{result.overall_score:.1f}%] ---")
        print(f"  Company:  {listing.company}")
        print(f"  Title:    {listing.title}")
        if listing.location:
            print(f"  Location: {listing.location}")
        if listing.salary_min and listing.salary_max:
            print(f"  Salary:   ${listing.salary_min:,.0f} - ${listing.salary_max:,.0f}")
        print(f"  Apply:    {listing.apply_url}")
        print(f"  JD:       {'Full text scraped' if listing.full_jd else 'Snippet only'}")

        # Show best-matching components
        best_exp_names = []
        for eid in result.best_experience_ids:
            for exp in parsed_resume.experiences:
                if exp.id == eid:
                    score = result.experience_scores.get(eid, 0)
                    best_exp_names.append(f"{exp.title[:25]} ({score:.2f})")
        best_proj_names = []
        for pid in result.best_project_ids:
            for proj in parsed_resume.projects:
                if proj.id == pid:
                    score = result.project_scores.get(pid, 0)
                    best_proj_names.append(f"{proj.title[:25]} ({score:.2f})")

        print(f"  Best exp: {' | '.join(best_exp_names)}")
        print(f"  Best proj: {' | '.join(best_proj_names)}")
        print()

    print(f"  Options:")
    print(f"    'all'      — proceed with all {len(passing)} jobs")
    print(f"    '1,3,5'    — select specific jobs by number")
    print(f"    'details N' — show full JD for job N")
    print(f"    'none'     — skip resume generation")
    print()

    while True:
        choice = input("  → Your choice: ").strip().lower()
        if choice == "all":
            return passing
        elif choice == "none":
            return []
        elif choice.startswith("details"):
            try:
                num = int(choice.split()[1]) - 1
                if 0 <= num < len(passing):
                    listing = passing[num][0]
                    jd = listing.full_jd or listing.description
                    print(f"\n  Full JD ({len(jd)} chars):")
                    print(f"  {jd[:2000]}")
                    if len(jd) > 2000:
                        print(f"  ... ({len(jd) - 2000} more chars)")
                    print()
            except (ValueError, IndexError):
                print("  Usage: details 1")
        else:
            try:
                indices = [int(x.strip()) - 1 for x in choice.split(",")]
                selected = [passing[i] for i in indices if 0 <= i < len(passing)]
                if selected:
                    print(f"  ✅ Selected {len(selected)} jobs\n")
                    return selected
                print("  No valid selections.")
            except (ValueError, IndexError):
                print("  Enter 'all', 'none', numbers, or 'details N'")


def save_summary(
    scored: list[tuple[JobListing, EmbeddingScore]],
    output_dir: str,
) -> str:
    """Save markdown summary."""
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, "summary.md")

    lines = [
        "# JobScout V2 — Run Summary",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Jobs scored:** {len(scored)}",
        "",
        "| # | Score | Company | Title | JD | Apply |",
        "|---|-------|---------|-------|----|-------|",
    ]

    for i, (listing, result) in enumerate(scored, 1):
        jd_icon = "Full" if listing.full_jd else "Snippet"
        lines.append(
            f"| {i} | {result.overall_score:.1f}% | {listing.company} | "
            f"{listing.title} | {jd_icon} | [Link]({listing.apply_url}) |"
        )

    lines.extend(["", "## Component Selection", ""])
    for i, (listing, result) in enumerate(scored, 1):
        lines.append(f"### {i}. {listing.company} — {listing.title} ({result.overall_score:.1f}%)")
        lines.append(f"- **Apply:** {listing.apply_url}")
        lines.append(f"- **Best experiences:** {', '.join(result.best_experience_ids)}")
        lines.append(f"- **Best projects:** {', '.join(result.best_project_ids)}")
        lines.append("")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"  📄 Summary: {filepath}")
    return filepath


def main():
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="JobScout V2")
    parser.add_argument("--max-jobs", type=int, default=config.MAX_JOBS_TO_DISCOVER)
    parser.add_argument("--threshold", type=int, default=config.FIT_THRESHOLD)
    parser.add_argument("--dry-run", action="store_true", help="Skip resume generation")
    parser.add_argument("--mock", action="store_true", help="Use mock data (zero API calls)")
    parser.add_argument("--mock-embeddings", action="store_true", help="Mock embeddings only")
    parser.add_argument("--resume", default=config.MASTER_RESUME_PATH)
    args = parser.parse_args()

    display_banner()

    # Load resume
    print(f"📝 Loading resume: {args.resume}")
    parsed = parse_resume_file(args.resume)
    print(
        f"  ✅ {len(parsed.experiences)} experiences, "
        f"{len(parsed.projects)} projects, "
        f"{len(parsed.skills_list)} skills\n"
    )

    # Phase 1: Discover
    listings = phase1_discover(parsed, args.max_jobs, use_mock=args.mock)
    if not listings:
        print("  ❌ No jobs found. Check API keys or config.py settings.")
        return

    # Phase 2: Enrich with full JDs
    listings = phase2_enrich(listings, skip=args.mock)

    # Phase 3: Score with embeddings
    use_mock_emb = args.mock or args.mock_embeddings
    passing = phase3_score(listings, parsed, args.threshold, use_mock_emb)

    # Output directory
    timestamp = datetime.now().strftime("%Y-%m-%d")
    output_dir = os.path.join(config.OUTPUT_DIR, timestamp)

    # Human checkpoint
    selected = checkpoint_scoring(passing, parsed)

    # Save summary
    if passing:
        save_summary(passing, output_dir)

    if args.dry_run:
        print("\n  🏃 Dry run complete. Remove --dry-run to generate resumes.\n")
        return

    if not selected:
        print("\n  No jobs selected. Done.\n")
        return

    # Phase 4: Resume generation (Phase 3 build)
    print(f"\n📝 Phase 4: Resume generation for {len(selected)} jobs...")
    print("  ⚠️  Coming in Phase 3 build. Use summary + links to apply.\n")
    for i, (listing, result) in enumerate(selected, 1):
        print(f"  {i}. {listing.company} — {listing.title} ({result.overall_score:.1f}%)")
        print(f"     Apply: {listing.apply_url}")
    print("\n✅ Done!\n")


if __name__ == "__main__":
    main()

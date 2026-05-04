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
    search_all, search_mock,
    enrich_listings_with_full_jd, JobListing,
)
from jobscout.tools.embedding_scorer import (
    embed_resume_components, embed_resume_components_mock,
    score_job_with_embeddings, score_job_mock,
    EmbeddingScore,
)
from jobscout.utils.dedup import mark_seen, mark_applied, get_seen_count

import logging
logger = logging.getLogger(__name__)


def _wrap_latex_resume(latex_resume):
    """
    Wrap a LatexResume into a ParsedResume-compatible object
    so the rest of the pipeline works without changes.
    """
    from jobscout.tools.resume_parser import ParsedResume, ResumeComponent

    def _make_component(item, comp_type: str) -> ResumeComponent:
        title = getattr(item, "title", None) or getattr(item, "name", "")
        return ResumeComponent(
            id=item.id,
            type=comp_type,
            title=title,
            organization=getattr(item, "company", ""),
            date_range=item.dates,
            tech_line=getattr(item, "tech", ""),
            bullets=item.bullets,
            raw_text=" ".join(item.bullets),
            keywords=item.keywords,
        )

    experiences = [_make_component(e, "experience") for e in latex_resume.experiences]
    projects = [_make_component(p, "project") for p in latex_resume.projects]

    # Build flat skills list
    skills_list = []
    skills_text = ""
    for label, value in latex_resume.skills.categories.items():
        skills_text += f"{label}: {value}\n"
        for skill in value.split(","):
            s = skill.strip().lower()
            if s:
                skills_list.append(s)

    return ParsedResume(
        contact_info=f"{latex_resume.name}\n{latex_resume.email}\n{latex_resume.phone}",
        education=f"{latex_resume.education_school} | {latex_resume.education_degree} | {latex_resume.education_dates}",
        skills_text=skills_text,
        skills_list=sorted(set(skills_list)),
        experiences=experiences,
        projects=projects,
        raw_text=latex_resume.raw_tex,
    )


def llm_filter_jobs(listings: list[JobListing], use_mock: bool = False) -> list[JobListing]:
    """
    Use a single Gemini call to filter out irrelevant jobs:
    - Senior / principal / staff roles (5+ years experience)
    - PhD / Masters required
    - Internships (unless user wants them)
    - Non-US based roles
    - Citizenship/clearance required
    - Closed/expired postings

    Passes titles, companies, locations to Gemini — no JD text needed.
    Very cheap: ~1-2K tokens for 20 jobs.
    """
    if use_mock or not listings:
        return listings

    print(f"\n  🤖 LLM relevance filter ({len(listings)} jobs)...")

    # Build job list for Gemini
    job_list = "\n".join(
        f"{i}. [{l.id}] {l.company} | {l.title} | {l.location or 'Unknown'}"
        for i, l in enumerate(listings, 1)
    )

    prompt = f"""You are filtering job listings for a CS graduate (graduated Spring 2025, Green-Card Holder, Permanent Resident, no US citizenship) seeking entry-level and new grad software engineering, data science, data engineer, AI engineer, ML Engineer, and other similar roles in the United States.

KEEP jobs that are:
- Entry level, new grad, junior, associate, or early career (0-1 years experience)
- Targeting 2025 OR 2026 graduates — both are valid for this candidate
- Full-time permanent positions
- US-based or Remote (with US operations)
- Software engineering, ML/AI engineering, data engineering, DevOps, or related tech

REMOVE jobs that are:
- Explicitly senior, principal, staff, lead, or manager level
- Require 2+ years of experience as minimum
- PhD or Masters as minimum qualification (MS preferred is OK to keep)
- Summer/Fall internships or co-ops
- Located outside the US with no US remote option (UK, Canada, Europe, India, etc.)
- Require US citizenship, security clearance, or defense contractor work
- Expired ("no longer accepting applications", "position closed", "filled")

NEVER REMOVE solely because:
- Title says "2026 New Grad" or "Graduate 2026" — these are valid
- Role is at a US company even if labeled "Graduate Program"
- Graduation window says Dec 2025–June 2026 (candidate graduated June 2025, qualifies)

Here are the jobs:
{job_list}

Reply with ONLY valid JSON (no markdown):
{{"keep": [1, 3, 5], "remove": [2, 4], "reasons": {{"2": "Senior role 5+ yrs", "4": "UK based"}}}}"""

    try:
        from google import genai as _genai
        import os, json

        client = _genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
        response = client.models.generate_content(
            model=config.MODEL,
            contents=prompt,
        )

        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

        result = json.loads(raw)
        keep_indices = set(result.get("keep", []))
        reasons = result.get("reasons", {})

        # Log what was removed
        removed = result.get("remove", [])
        if removed:
            print(f"  Filtered out {len(removed)} irrelevant jobs:")
            for idx in removed:
                reason = reasons.get(str(idx), "Not relevant")
                if 1 <= idx <= len(listings):
                    print(f"    ✗ {listings[idx-1].title[:50]} — {reason}")

        # Return only kept jobs
        kept = [listings[i-1] for i in sorted(keep_indices) if 1 <= i <= len(listings)]
        print(f"  ✅ {len(kept)} jobs passed relevance filter\n")
        return kept

    except Exception as e:
        logger.warning(f"LLM filter failed ({e}), returning all jobs unfiltered")
        print(f"  ⚠️  LLM filter failed, skipping filter step\n")
        return listings


def display_banner():
    print("\n" + "=" * 60)
    print("  🔍 JobScout V2 — AI-Powered Job Discovery & Resume Builder")
    print("=" * 60 + "\n")


def phase1_discover(parsed_resume, max_jobs: int, use_mock: bool) -> list[JobListing]:
    """Phase 1: Discover jobs via Serper → Adzuna → Mock."""
    print("📡 Phase 1: Discovering jobs...\n")

    # Collect all skills
    all_skills = list(parsed_resume.skills_list)
    for exp in parsed_resume.experiences:
        all_skills.extend(exp.keywords)
    for proj in parsed_resume.projects:
        all_skills.extend(proj.keywords)
    unique_skills = sorted(set(all_skills))

    if use_mock:
        listings = search_mock("", max_jobs)
        print(f"  ✅ Found {len(listings)} mock jobs\n")
        return listings

    priority = getattr(config, "JOB_DISCOVERY_PRIORITY", ["serper", "adzuna"])

    listings = search_all(
        all_skills=unique_skills,
        base_titles=config.BASE_TITLES,
        experience_levels=config.EXPERIENCE_LEVEL,
        country=config.COUNTRY,
        locations=config.LOCATIONS if config.LOCATIONS else None,
        max_results_per_query=max(3, max_jobs // 6 + 1),
        max_days_old=config.JOB_RECENCY_HOURS // 24,
        discovery_priority=priority,
        max_total=max_jobs,
    )

    # Show source breakdown
    sources = {}
    for l in listings:
        sources[l.source] = sources.get(l.source, 0) + 1
    source_str = ", ".join(f"{v} from {k}" for k, v in sources.items())
    print(f"  ✅ Found {len(listings)} unique jobs ({source_str})")

    # LLM relevance filter
    listings = llm_filter_jobs(listings, use_mock=False)

    # Dedup — skip jobs already seen in previous runs
    before = len(listings)
    listings = mark_seen(listings)
    skipped = before - len(listings)
    if skipped:
        print(f"  ⏭️  Skipped {skipped} already-seen jobs ({get_seen_count()} total seen)")

    # Show sample of what was found
    for i, l in enumerate(listings[:5], 1):
        print(f"    {i}. [{l.source}] {l.company} — {l.title[:50]}")
    if len(listings) > 5:
        print(f"    ... and {len(listings) - 5} more")
    print()

    return listings


def phase2_enrich(listings: list[JobListing], skip: bool = False) -> list[JobListing]:
    """Phase 2: Best-effort scrape full JDs from apply URLs."""
    if skip:
        print("📄 Phase 2: Enrichment skipped (mock mode)\n")
        return listings

    print(f"📄 Phase 2: Enriching {len(listings)} jobs with full JDs...")
    print("  (This takes ~1-2 min for LinkedIn rate limiting)\n")
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

    if use_mock_embeddings:
        print("  Using mock embeddings (no API calls)\n")
        embeddings = embed_resume_components_mock(parsed_resume)
    else:
        print("  Embedding resume components via Gemini API...\n")
        embeddings = embed_resume_components(parsed_resume)

    if not embeddings:
        print("  ❌ Failed to generate embeddings. Check GOOGLE_API_KEY.")
        return []

    scored = []
    for listing in listings:
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

    scored.sort(key=lambda x: x[1].overall_score, reverse=True)

    has_jd = lambda l: "📄" if l.full_jd else "📋"
    print(f"  {'#':<4} {'Score':<8} {'JD':<4} {'Source':<8} {'Company':<20} {'Title':<35} {'Pass'}")
    print("  " + "-" * 88)
    for i, (listing, result) in enumerate(scored, 1):
        passed = "✅" if result.overall_score >= threshold else "❌"
        print(
            f"  {i:<4} {result.overall_score:>5.1f}%  "
            f"{has_jd(listing):<4} "
            f"{listing.source:<8} "
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
        print("  No jobs passed threshold. Try lowering FIT_THRESHOLD in config.py.\n")
        return []

    print("🛑 Checkpoint: Review scored jobs\n")

    for i, (listing, result) in enumerate(passing, 1):
        print(f"  --- #{i} [{result.overall_score:.1f}%] [{listing.source}] ---")
        print(f"  Company:  {listing.company}")
        print(f"  Title:    {listing.title}")
        if listing.location:
            print(f"  Location: {listing.location}")
        if listing.salary_min and listing.salary_max:
            print(f"  Salary:   ${listing.salary_min:,.0f} - ${listing.salary_max:,.0f}")
        print(f"  Apply:    {listing.apply_url}")
        print(f"  JD:       {'Full text scraped' if listing.full_jd else 'Snippet only'}")

        # Best components
        exp_names = []
        for eid in result.best_experience_ids:
            for exp in parsed_resume.experiences:
                if exp.id == eid:
                    score = result.experience_scores.get(eid, 0)
                    exp_names.append(f"{exp.title[:25]} ({score:.2f})")
        proj_names = []
        for pid in result.best_project_ids:
            for proj in parsed_resume.projects:
                if proj.id == pid:
                    score = result.project_scores.get(pid, 0)
                    proj_names.append(f"{proj.title[:25]} ({score:.2f})")

        print(f"  Best exp: {' | '.join(exp_names)}")
        print(f"  Best proj: {' | '.join(proj_names)}")
        print()

    print(f"  Options:")
    print(f"    'all'       — proceed with all {len(passing)} jobs")
    print(f"    '1,3,5'     — select specific jobs by number")
    print(f"    'details N'  — show full JD for job N")
    print(f"    'none'      — skip resume generation")
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
        "| # | Score | Source | Company | Title | JD | Apply |",
        "|---|-------|--------|---------|-------|----|-------|",
    ]

    for i, (listing, result) in enumerate(scored, 1):
        jd_icon = "Full" if listing.full_jd else "Snippet"
        lines.append(
            f"| {i} | {result.overall_score:.1f}% | {listing.source} | "
            f"{listing.company} | {listing.title} | {jd_icon} | "
            f"[Link]({listing.apply_url}) |"
        )

    lines.extend(["", "## Component Selection", ""])
    for i, (listing, result) in enumerate(scored, 1):
        lines.append(f"### {i}. {listing.company} — {listing.title} ({result.overall_score:.1f}%)")
        lines.append(f"- **Source:** {listing.source}")
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
    parser.add_argument("--mock", action="store_true", help="Mock data (zero API calls)")
    parser.add_argument("--mock-embeddings", action="store_true", help="Mock embeddings only")
    parser.add_argument("--resume", default=config.MASTER_RESUME_PATH)
    parser.add_argument("--reset-seen", action="store_true", help="Clear seen job history")
    args = parser.parse_args()

    display_banner()

    if args.reset_seen:
        from jobscout.utils.dedup import reset_seen
        reset_seen()
        print("✅ Seen job history cleared. All jobs will appear fresh.\n")

    # Load resume — prefer .tex over .txt for better quality
    print(f"📝 Loading resume: {args.resume}")
    tex_path = os.path.splitext(args.resume)[0] + ".tex"
    if not tex_path.endswith(".tex"):
        tex_path = args.resume.replace(".txt", ".tex")

    # Try LaTeX parser first
    latex_resume = None
    if os.path.exists(tex_path):
        try:
            from jobscout.tools.latex_parser import parse_latex_resume
            latex_resume = parse_latex_resume(tex_path)
            print(
                f"  ✅ {len(latex_resume.experiences)} experiences, "
                f"{len(latex_resume.projects)} projects (from LaTeX)\n"
            )
        except Exception as e:
            logger.warning(f"LaTeX parser failed: {e}, falling back to .txt")
            latex_resume = None

    # Fall back to txt parser
    if latex_resume is None:
        parsed = parse_resume_file(args.resume)
        print(
            f"  ✅ {len(parsed.experiences)} experiences, "
            f"{len(parsed.projects)} projects, "
            f"{len(parsed.skills_list)} skills\n"
        )
    else:
        # Wrap LaTeX resume in a compatible interface for the pipeline
        parsed = _wrap_latex_resume(latex_resume)

    # Phase 1: Discover
    listings = phase1_discover(parsed, args.max_jobs, use_mock=args.mock)
    if not listings:
        print("  ❌ No jobs found. Check API keys or config.py.\n")
        return

    # Phase 2: Enrich
    listings = phase2_enrich(listings, skip=args.mock)

    # Phase 3: Score
    use_mock_emb = args.mock or args.mock_embeddings
    passing = phase3_score(listings, parsed, args.threshold, use_mock_emb)

    # Output
    timestamp = datetime.now().strftime("%Y-%m-%d")
    output_dir = os.path.join(config.OUTPUT_DIR, timestamp)

    # Checkpoint
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

    # Phase 4: Resume generation
    print(f"\n📝 Phase 4: Generating resumes for {len(selected)} jobs...\n")

    from jobscout.tools.resume_generator import generate_resume

    generated = []
    for i, (listing, result) in enumerate(selected, 1):
        company_clean = "".join(c for c in listing.company if c.isalnum() or c in " -_").strip().replace(" ", "_")
        title_clean = "".join(c for c in listing.title if c.isalnum() or c in " -_").strip().replace(" ", "_")[:30]
        filename = f"Yash_Pathak_{title_clean}_{company_clean}.docx"
        filepath = os.path.join(output_dir, filename)

        print(f"  [{i}/{len(selected)}] {listing.company} — {listing.title[:40]}")

        jd_text = listing.full_jd if listing.full_jd else f"{listing.title} {listing.description}"
        # Always include Sorenson + 101gen as top 2 experiences
        fixed_exp_ids = ["exp_sorenson_communications", "exp_101gen_ai"]
        jd_lower = jd_text.lower()
        healthcare_jd = any(kw in jd_lower for kw in [
            "healthcare", "biomedical", "nlp", "medical", "clinical",
            "rlhf", "radiology", "health", "patient"
        ])
        if healthcare_jd:
            other_exp_ids = [e for e in result.best_experience_ids if e not in fixed_exp_ids]
            final_exp_ids = fixed_exp_ids + other_exp_ids[:1]
        else:
            final_exp_ids = fixed_exp_ids
            
        resume_path = generate_resume(
            parsed_resume=parsed,
            jd_text=jd_text,
            selected_experience_ids=final_exp_ids,
            selected_project_ids=result.best_project_ids,
            lead_skills=[],  # Let the LLM figure it out from JD
            resume_rules=config.RESUME_RULES,
            similar_tech_map=config.SIMILAR_TECH_MAP,
            output_path=filepath,
            model=config.MODEL,
            fallback_model=config.FALLBACK_MODEL,
            use_mock=args.mock,
        )

        if resume_path:
            generated.append((listing, resume_path))

            # Checkpoint: review generated resume
            if config.CHECKPOINT_AFTER_GENERATION and not args.mock:
                print(f"\n    → [S]ave  [R]egenerate  [N]ext (skip saving)")
                choice = input("      Your choice: ").strip().lower()
                if choice == "r":
                    print("    Regenerating...")
                    resume_path = generate_resume(
                        parsed_resume=parsed,
                        jd_text=jd_text,
                        selected_experience_ids=result.best_experience_ids,
                        selected_project_ids=result.best_project_ids,
                        lead_skills=[],
                        resume_rules=config.RESUME_RULES,
                        similar_tech_map=config.SIMILAR_TECH_MAP,
                        output_path=filepath,
                        model=config.MODEL,
                        fallback_model=config.FALLBACK_MODEL,
                        use_mock=args.mock,
                    )
                elif choice == "n":
                    if os.path.exists(filepath):
                        os.remove(filepath)
                    generated.pop()
                    print("    Skipped.")
        print()

    # Final summary
    print("=" * 60)
    print(f"  ✅ Generated {len(generated)} resumes\n")
    for i, (listing, path) in enumerate(generated, 1):
        print(f"  {i}. {listing.company} — {listing.title[:40]}")
        print(f"     Resume: {path}")
        print(f"     Apply:  {listing.apply_url}")
        # Log to applied_jobs.csv for spreadsheet import
        mark_applied(listing, resume_path=path)
        print()
    print(f"  📁 Output folder: {output_dir}")
    print(f"  📄 Summary: {output_dir}/summary.md")
    print(f"  📊 Applied log: outputs/applied_jobs.csv (import to spreadsheet)")
    print("\n✅ Done!\n")


if __name__ == "__main__":
    main()

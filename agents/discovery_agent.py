"""
Discovery Agent - Job Search with Google ADK

Multi-source job discovery using Gemini as the orchestrator.
Uses search tools to find relevant jobs based on user profile.

Location: jobscout_v3/agents/discovery_agent.py
"""

import os
import sys
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.profile import load_profile, UserProfile
from tools.search import (
    JobListing,
    search_github_newgrad,
    search_ats,
    harvest_slugs,
    search_serper,
    search_adzuna,
    search_mock,
    build_serper_query,
)
from tools.cache.job_cache import JobCache
from tools.jobs.job_store import JobStore

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class DiscoveryAgent:
    """
    Job Discovery Agent - Finds relevant jobs using multiple sources.
    
    The agent:
    1. Reads user profile (target roles, locations, preferences)
    2. Uses search tools based on profile.agent_preferences.discovery_sources
    3. Filters results by profile criteria
    4. Deduplicates across sources
    5. Returns 20-50 relevant jobs
    """
    
    def __init__(self, profile: UserProfile, mock_mode: bool = False):
        """
        Initialize Discovery Agent.
        
        Args:
            profile: User profile with job preferences
            mock_mode: If True, use mock search only (no API calls)
        """
        self.profile = profile
        self.mock_mode = mock_mode
        self.all_jobs: List[JobListing] = []
        self.seen_urls: set = set()
        
    def discover_jobs(self, max_jobs: int = 50) -> List[JobListing]:
        """
        Main discovery method - orchestrates all search sources.
        
        Args:
            max_jobs: Maximum number of jobs to return
            
        Returns:
            List of deduplicated JobListing objects
            
        Example:
            >>> agent = DiscoveryAgent(profile)
            >>> jobs = agent.discover_jobs(max_jobs=30)
            >>> print(f"Found {len(jobs)} jobs")
        """
        logger.info("🔍 Starting job discovery...")
        logger.info(f"📋 Profile: {self.profile.personal_info.name}")
        logger.info(f"🎯 Target roles: {len(self.profile.job_preferences.target_roles)}")
        
        if self.mock_mode:
            logger.info("🧪 MOCK MODE - Using fake data")
            return self._search_mock(max_jobs)
        
        # Load job cache for cross-run deduplication
        job_cache = JobCache()
        cache_stats = job_cache.stats()
        logger.info(
            f"📦 Job cache: {cache_stats['seen_urls']} previously seen URLs"
        )

        # Get search sources from profile preferences
        sources = self.profile.agent_preferences.discovery_sources
        logger.info(f"📡 Search order: {' → '.join(sources)}")

        # Target a wide candidate pool. The output cap (max_jobs) is applied
        # at the end, after profile filtering and ranking. We scrape widely
        # so the funnel has good options to choose from — wrong-fit jobs
        # are more likely to be outranked when the pool is large.
        DISCOVERY_POOL_TARGET = 200

        # Search each source in priority order
        for source in sources:
            if len(self.all_jobs) >= DISCOVERY_POOL_TARGET:
                logger.info(f"✅ Reached pool target of {DISCOVERY_POOL_TARGET} candidates")
                break

            if source == "ats":
                self._search_ats()
            elif source == "github_newgrad":
                self._search_github()
            elif source == "serper":
                self._search_serper()
            elif source == "adzuna":
                self._search_adzuna()
            else:
                logger.warning(f"⚠️  Unknown source: {source}")
        
        # Profile filtering first, so the store holds jobs this user could
        # actually apply to. Recording everything discovered would fill the
        # board with roles the profile explicitly rejects — Bosch alone posts
        # thousands, most of them nothing to do with software.
        filtered_jobs = self._filter_by_profile(self.all_jobs)

        # What survives is recorded permanently. The job cache's dedup used to
        # make this decision and it forgets after seven days, which was fine
        # when a run log was the only output and wrong now that five ATS
        # boards reach ~17,000 roles and a board is meant to accumulate.
        store = JobStore()
        recorded = store.record(filtered_jobs, run_date=datetime.now().strftime("%Y-%m-%d"))
        logger.info(f"   Job store: {recorded['added']} new, "
                    f"{recorded['updated']} already known")

        # The pipeline still only *works* on jobs it has not scored, so a
        # second run does not pay to analyse and generate the same postings.
        # The difference from before is that skipping is no longer forgetting:
        # a job seen today is still on the board next month.
        unprocessed = store.unprocessed_urls()
        new_jobs = [job for job in filtered_jobs if job.apply_url in unprocessed]
        skipped = len(filtered_jobs) - len(new_jobs)
        if skipped:
            logger.info(f"   Skipped {skipped} already-scored jobs (kept in the store)")

        filtered_jobs = new_jobs
        
        # Any job from any source whose apply URL lands on a known ATS
        # reveals that company's slug, and from then on its entire board
        # is reachable without a key. Cheap, and it compounds every run.
        try:
            harvest_slugs([job.apply_url for job in self.all_jobs])
        except Exception as e:
            logger.debug(f"Slug harvest skipped: {e}")

        store.close()

        # Persist the JD cache. The seen-URL half of this file is no longer
        # what decides which jobs get processed — the store is — but the
        # scraped-JD half still saves Enrichment a lot of work.
        job_cache.save()

        logger.info(f"✅ Discovery complete: {len(filtered_jobs)} jobs after filtering")
        return filtered_jobs[:max_jobs]
    
    def _search_ats(self) -> None:
        """
        Public ATS boards — no API key, every level, every department.

        The only keyless source that is not new-grad-only. Company boards
        carry the whole company, so `roles` does the narrowing that a search
        query does for Serper; without it the pool fills with whatever sorts
        first alphabetically, which in practice is account executives.

        These listings arrive with `full_jd` already populated, so Enrichment
        has nothing to scrape for them.
        """
        logger.info("Searching public ATS boards (no key needed)...")

        try:
            jobs = search_ats(
                max_results=200,
                roles=self.profile.job_preferences.target_roles,
            )
            added = self._deduplicate_and_add(jobs)
            logger.info(f"   Added {added} new jobs from ATS boards")
        except Exception as e:
            logger.error(f"ATS search failed: {e}")

    def _search_github(self) -> None:
        """
        Search GitHub curated new grad lists — for profiles that want them.

        These repos are new-grad by nature and have no senior equivalent, so
        for a profile whose range starts above entry level they fill the
        discovery pool with postings the body gate then throws away. Skipped
        rather than filtered, because a source that cannot serve this user is
        a request not worth making (R66).
        """
        from tools.jobs.job_filter import wants_early_career

        if not wants_early_career(self.profile):
            levels = ", ".join(self.profile.job_preferences.seniority) or "unset"
            logger.info(f"🐙 Skipping GitHub new-grad repos — this profile "
                        f"wants {levels}")
            return

        logger.info("🐙 Searching GitHub new grad repos...")

        try:
            # Scrape widely (~200 candidates) — funnel filtering downstream
            # selects the best ones. Wider pool gives better top-K choices.
            jobs = search_github_newgrad(max_results=200)
            new_jobs = self._deduplicate_and_add(jobs)
            logger.info(f"   Added {new_jobs} new jobs from GitHub")
        except Exception as e:
            logger.error(f"❌ GitHub search failed: {e}")
    
    def _search_serper(self) -> None:
        """Search Google via Serper API."""
        logger.info("🔎 Searching Google via Serper...")
        
        if not os.getenv("SERPER_API_KEY"):
            logger.warning("   ⚠️  SERPER_API_KEY not set, skipping")
            return
        
        # Build queries for each target role
        roles_to_search = self.profile.job_preferences.target_roles[:5]  # Top 5 roles

        # From the profile, not a constant. This said "new grad" for every user
        # regardless of their range (R66).
        from tools.jobs.job_filter import primary_seniority_term
        seniority = primary_seniority_term(self.profile)
        
        for role in roles_to_search:
            # Try Greenhouse first (cleanest postings)
            query = build_serper_query(role, seniority, "greenhouse.io")
            
            try:
                jobs = search_serper(query, max_results=10)
                new_jobs = self._deduplicate_and_add(jobs)
                logger.info(f"   {role}: Added {new_jobs} jobs from Greenhouse")
            except Exception as e:
                logger.error(f"   ❌ Serper failed for {role}: {e}")
            
            if len(self.all_jobs) >= 200:
                break
    
    def _search_adzuna(self) -> None:
        """Search Adzuna job API."""
        logger.info("📊 Searching Adzuna API...")
        
        if not os.getenv("ADZUNA_APP_ID") or not os.getenv("ADZUNA_APP_KEY"):
            logger.warning("   ⚠️  ADZUNA credentials not set, skipping")
            return
        
        # Search for top roles
        roles_to_search = self.profile.job_preferences.target_roles[:3]
        
        # Get priority location
        location = ""
        if self.profile.job_preferences.locations.states_priority:
            location = self.profile.job_preferences.locations.states_priority[0]
        
        from tools.jobs.job_filter import primary_seniority_term
        seniority = primary_seniority_term(self.profile)

        for role in roles_to_search:
            query = f"{role} {seniority}".strip()
            
            try:
                jobs = search_adzuna(query, location=location, max_results=15)
                new_jobs = self._deduplicate_and_add(jobs)
                logger.info(f"   {role}: Added {new_jobs} jobs")
            except Exception as e:
                logger.error(f"   ❌ Adzuna failed for {role}: {e}")
            
            if len(self.all_jobs) >= 200:
                break
    
    def _search_mock(self, max_jobs: int) -> List[JobListing]:
        """Mock search for testing."""
        logger.info("🧪 Generating mock jobs...")
        jobs = search_mock(max_results=max_jobs)
        logger.info(f"   Generated {len(jobs)} mock jobs")
        return jobs
    
    def _deduplicate_and_add(self, jobs: List[JobListing]) -> int:
        """
        Add jobs to collection, skipping duplicates.
        
        Args:
            jobs: List of jobs to add
            
        Returns:
            Number of new jobs added
        """
        added = 0
        for job in jobs:
            if job.apply_url not in self.seen_urls:
                self.seen_urls.add(job.apply_url)
                self.all_jobs.append(job)
                added += 1
        return added
    
    def _filter_by_profile(self, jobs: List[JobListing]) -> List[JobListing]:
        """
        Filter and rank jobs using profile criteria via JobFilter service.

        Filters:
        - Excluded keywords (senior, PhD, etc.)
        - Seniority level
        - Location (whitelist-based: detected country must be in profile.countries)

        Ranking (after filtering):
        - Priority state / remote → score 3
        - Acceptable state       → score 2
        - Other US               → score 0
        - Unknown location       → score -1 (kept but ranked last)

        Args:
            jobs: List of jobs to filter

        Returns:
            Filtered and ranked list of jobs
        """
        from tools.jobs.job_filter import evaluate

        logger.info("🔍 Filtering and ranking jobs by profile criteria...")

        kept = []
        excluded_reasons = {}

        for i, job in enumerate(jobs):
            decision = evaluate(job, self.profile)

            # Verbose logging for first 3 jobs
            if i < 3:
                logger.info(f"   Job {i+1}: '{job.title}' @ {job.company}")
                logger.info(f"      Location: '{job.location}' "
                           f"→ {decision.location_result or '(unparsed)'}")
                logger.info(f"      Decision: {'EXCLUDE' if decision.exclude else 'KEEP'} "
                           f"| Reason: {decision.reason or 'N/A'}")
                logger.info(f"      Score: loc={decision.location_score} "
                           f"role={decision.role_score} "
                           f"seniority={decision.seniority_score} "
                           f"overall={decision.overall_score}")

            if decision.exclude:
                reason = decision.reason or "Unknown reason"
                excluded_reasons[reason] = excluded_reasons.get(reason, 0) + 1
                continue

            # Attach decision for ranking
            job._filter_decision = decision
            kept.append(job)

        excluded = len(jobs) - len(kept)
        logger.info(f"   Kept {len(kept)}, excluded {excluded}")

        if excluded_reasons:
            for reason, count in sorted(excluded_reasons.items(), key=lambda x: -x[1]):
                logger.info(f"      - {reason}: {count} jobs")

        # Rank by overall_score with a recency tiebreaker: jobs posted
        # in the last few days should outrank slightly-older jobs of similar
        # fit. Recency penalty: ~0.5 points per day of age, capped so a
        # genuinely-better job from last week still beats a worse one from today.
        now_utc = datetime.now(timezone.utc)

        def _recency_adjusted_score(job: JobListing) -> float:
            decision = getattr(job, '_filter_decision', None)
            base_score = (decision.overall_score if decision else 0) or 0

            # Parse the posted date if available
            days_old = 0.0
            if job.created:
                try:
                    posted = datetime.fromisoformat(job.created)
                    # Ensure both have timezone info for clean subtraction
                    if posted.tzinfo is None:
                        posted = posted.replace(tzinfo=timezone.utc)
                    days_old = max(0.0, (now_utc - posted).total_seconds() / 86400.0)
                except (ValueError, TypeError):
                    pass

            # Cap recency penalty at 14 days (~7 points). Beyond that, all
            # old jobs are equally old and we let the base score decide.
            recency_penalty = min(days_old, 14.0) * 0.5
            return base_score - recency_penalty

        ranked = sorted(kept, key=_recency_adjusted_score, reverse=True)

        if ranked:
            priority = sum(
                1 for j in ranked
                if hasattr(j, '_filter_decision')
                and j._filter_decision.location_score >= 3
            )
            acceptable = sum(
                1 for j in ranked
                if hasattr(j, '_filter_decision')
                and j._filter_decision.location_score == 2
            )
            other = len(ranked) - priority - acceptable
            logger.info(f"   📍 Ranking: {priority} priority, "
                       f"{acceptable} acceptable, {other} other")

        return ranked


def main():
    """CLI for testing Discovery Agent."""
    import argparse
    
    parser = argparse.ArgumentParser(description="JobScout V3 - Discovery Agent")
    parser.add_argument(
        "--profile",
        default="yash_pathak",
        help="Profile name (default: yash_pathak)"
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock search (no API calls)"
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=30,
        help="Maximum jobs to discover (default: 30)"
    )
    parser.add_argument(
        "--source",
        choices=["github", "serper", "adzuna"],
        help="Use only specific source (for testing)"
    )
    
    args = parser.parse_args()
    
    # Load profile
    print(f"📋 Loading profile: {args.profile}")
    profile = load_profile(args.profile)
    print(f"✅ Profile loaded: {profile.personal_info.name}")
    print(f"🎯 Target roles: {', '.join(profile.job_preferences.target_roles[:3])}...")
    print()
    
    # Override discovery sources if --source specified
    if args.source:
        source_map = {
            "github": "github_newgrad",
            "serper": "serper",
            "adzuna": "adzuna",
        }
        profile.agent_preferences.discovery_sources = [source_map[args.source]]
        print(f"🔧 Using only: {args.source}")
        print()
    
    # Create agent and discover jobs
    agent = DiscoveryAgent(profile, mock_mode=args.mock)
    jobs = agent.discover_jobs(max_jobs=args.max_jobs)
    
    # Display results
    print()
    print("=" * 80)
    print(f"🎉 DISCOVERY COMPLETE - Found {len(jobs)} jobs")
    print("=" * 80)
    print()
    
    for i, job in enumerate(jobs[:10], 1):
        print(f"{i:2d}. {job}")
    
    if len(jobs) > 10:
        print(f"\n... and {len(jobs) - 10} more jobs")
    
    # Summary by source
    print()
    print("📊 Jobs by source:")
    source_counts = {}
    for job in jobs:
        source_counts[job.source] = source_counts.get(job.source, 0) + 1
    
    for source, count in sorted(source_counts.items()):
        print(f"   {source}: {count} jobs")


if __name__ == "__main__":
    main()
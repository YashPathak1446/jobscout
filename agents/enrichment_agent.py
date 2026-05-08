"""
Enrichment Agent - Scrape Full Job Descriptions

Takes job listings from Discovery Agent and enriches them with:
- Full job descriptions (5000+ chars)
- Structured requirements (must-have, nice-to-have)
- Company info and metadata

Location: jobscout_v3/agents/enrichment_agent.py
"""

import os
import sys
import logging
from pathlib import Path
from typing import List, Dict
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.search import JobListing
from tools.scraping import mock_scrape_jd
from tools.scraping.jd_scraper import scrape_jd
from tools.cache.job_cache import JobCache

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class EnrichmentAgent:
    """
    Job Enrichment Agent - Scrapes full job descriptions.
    
    The agent:
    1. Receives list of JobListings from Discovery Agent
    2. For each job, scrapes the URL to get full JD
    3. Extracts structured requirements
    4. Populates full_jd field and adds metadata
    5. Handles failures gracefully (some URLs will fail)
    """
    
    def __init__(self, mock_mode: bool = False):
        """
        Initialize Enrichment Agent.
        
        Args:
            mock_mode: If True, use mock scraper (no HTTP requests)
        """
        self.mock_mode = mock_mode
        self.success_count = 0
        self.failure_count = 0
        
    def enrich_jobs(self, jobs: List[JobListing]) -> List[Dict]:
        """
        Enrich job listings with full descriptions and requirements.
        
        Args:
            jobs: List of JobListing objects from Discovery Agent
            
        Returns:
            List of enriched job dictionaries
            
        Example:
            >>> agent = EnrichmentAgent(mock_mode=True)
            >>> enriched = agent.enrich_jobs(discovered_jobs)
            >>> print(enriched[0]['full_jd'][:200])
        """
        logger.info("📝 Starting job enrichment...")
        logger.info(f"Jobs to enrich: {len(jobs)}")
        
        if self.mock_mode:
            logger.info("🧪 MOCK MODE - Using fake job descriptions")
        
        # Load job cache for JD scrape result caching
        job_cache = None
        if not self.mock_mode:
            job_cache = JobCache()

        enriched_jobs = []
        
        for i, job in enumerate(jobs, 1):
            logger.info(f"📄 Enriching {i}/{len(jobs)}: {job.title} @ {job.company}")
            
            try:
                # Scrape the job description
                if self.mock_mode:
                    scrape_result = self._mock_scrape(job)
                else:
                    # Check JD cache first
                    cached = job_cache.get_jd(job.apply_url) if job_cache else None
                    if cached:
                        scrape_result = {
                            "full_jd": cached["full_jd"],
                            "requirements": cached["requirements"],
                            "scraped_successfully": True,
                            "scraper_used": f"cache ({cached['scraper_used']})",
                        }
                    else:
                        scrape_result = self._real_scrape(job)
                        # Save to cache if successful
                        if job_cache and scrape_result.get("scraped_successfully"):
                            job_cache.save_jd(job.apply_url, scrape_result)
                
                # Create enriched job dict
                enriched_job = {
                    # Original fields
                    'id': job.id,
                    'title': job.title,
                    'company': job.company,
                    'location': job.location,
                    'apply_url': job.apply_url,
                    'salary_min': job.salary_min,
                    'salary_max': job.salary_max,
                    'created': job.created,
                    'source': job.source,
                    
                    # Enriched fields
                    'full_jd': scrape_result['full_jd'],
                    'requirements': scrape_result['requirements'],
                    'scraped_successfully': scrape_result['scraped_successfully'],
                    'scraper_used': scrape_result['scraper_used'],
                    
                    # Short description (from discovery)
                    'short_description': job.description,
                }
                
                enriched_jobs.append(enriched_job)
                self.success_count += 1
                
                # Log success with JD length
                jd_length = len(scrape_result['full_jd'])
                logger.info(f"   ✅ Success - {jd_length} chars, {len(scrape_result['requirements']['must_have'])} must-have reqs")
                
            except Exception as e:
                logger.error(f"   ❌ Failed to enrich: {e}")
                self.failure_count += 1
                
                # Still add the job but mark as failed
                enriched_jobs.append({
                    'id': job.id,
                    'title': job.title,
                    'company': job.company,
                    'location': job.location,
                    'apply_url': job.apply_url,
                    'salary_min': job.salary_min,
                    'salary_max': job.salary_max,
                    'created': job.created,
                    'source': job.source,
                    'full_jd': job.description,  # Fallback to short description
                    'requirements': {},
                    'scraped_successfully': False,
                    'scraper_used': 'none',
                    'short_description': job.description,
                    'error': str(e),
                })
        
        logger.info(f"✅ Enrichment complete: {self.success_count} success, {self.failure_count} failed")
        
        # Persist JD cache
        if job_cache:
            job_cache.save()

        return enriched_jobs
    
    def _mock_scrape(self, job: JobListing) -> Dict:
        """Use mock scraper for testing."""
        return mock_scrape_jd(job.apply_url, job.title, job.company)
    
    def _real_scrape(self, job: JobListing) -> Dict:
        """
        Scrape a real job description using ATS-specific scrapers.

        Flow:
        1. Follow redirect (jobright.ai → real ATS URL)
        2. Detect ATS from final URL
        3. Use Greenhouse/Lever/Ashby/Workday/generic scraper
        4. Extract structured requirements
        5. Fall back to mock if scraping fails

        Args:
            job: JobListing with apply_url to scrape

        Returns:
            Scrape result dict with full_jd and requirements
        """
        result = scrape_jd(
            apply_url=job.apply_url,
            job_title=job.title,
            company=job.company,
        )

        if result["scraped_successfully"]:
            logger.info(f"   🌐 Real scrape: {result['scraper_used']} "
                       f"({len(result['full_jd'])} chars)")
            return result

        # Fall back to mock if scraping failed
        logger.warning(f"   ⚠️  Real scrape failed, using mock fallback")
        mock_result = mock_scrape_jd(job.apply_url, job.title, job.company)
        mock_result["scraper_used"] = "mock_fallback"
        return mock_result


def main():
    """CLI for testing Enrichment Agent."""
    import argparse
    from tools.profile import load_profile
    from agents.discovery_agent import DiscoveryAgent
    
    parser = argparse.ArgumentParser(description="JobScout V3 - Enrichment Agent")
    parser.add_argument(
        "--profile",
        default="yash_pathak",
        help="Profile name (default: yash_pathak)"
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock scraping (no HTTP requests)"
    )
    parser.add_argument(
        "--mock-discovery",
        action="store_true",
        help="Use mock discovery (fake jobs from Discovery Agent)"
    )
    parser.add_argument(
        "--input",
        help="JSON file with jobs from Discovery Agent (optional)"
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=10,
        help="Maximum jobs to enrich (default: 10)"
    )
    parser.add_argument(
        "--output",
        default="enriched_jobs.json",
        help="Output file for enriched jobs (default: enriched_jobs.json)"
    )
    
    args = parser.parse_args()
    
    # Get jobs to enrich
    if args.input:
        # Load from file
        print(f"📂 Loading jobs from {args.input}")
        with open(args.input, 'r') as f:
            jobs_data = json.load(f)
        
        # Convert to JobListing objects
        jobs = [JobListing(**job_dict) for job_dict in jobs_data[:args.max_jobs]]
    else:
        # Run discovery first
        print(f"📋 Loading profile: {args.profile}")
        profile = load_profile(args.profile)
        print(f"✅ Profile loaded: {profile.personal_info.name}\n")
        
        print("🔍 Running Discovery Agent to find jobs...")
        discovery = DiscoveryAgent(profile, mock_mode=args.mock_discovery)
        jobs = discovery.discover_jobs(max_jobs=args.max_jobs)
        print(f"✅ Found {len(jobs)} jobs\n")
    
    # Enrich jobs
    print("📝 Running Enrichment Agent...")
    agent = EnrichmentAgent(mock_mode=args.mock)
    enriched_jobs = agent.enrich_jobs(jobs)
    
    # Save to file
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(enriched_jobs, f, indent=2)
    
    print()
    print("=" * 80)
    print(f"🎉 ENRICHMENT COMPLETE")
    print("=" * 80)
    print(f"Success: {agent.success_count}")
    print(f"Failed: {agent.failure_count}")
    print(f"Saved to: {output_path}")
    print()
    
    # Show sample
    if enriched_jobs:
        print("📄 Sample enriched job:")
        sample = enriched_jobs[0]
        print(f"Title: {sample['title']}")
        print(f"Company: {sample['company']}")
        print(f"Full JD length: {len(sample['full_jd'])} chars")
        print(f"Must-have requirements: {len(sample['requirements'].get('must_have', []))}")
        print(f"Nice-to-have requirements: {len(sample['requirements'].get('nice_to_have', []))}")
        print()
        print("First 500 chars of JD:")
        print(sample['full_jd'][:500] + "...")


if __name__ == "__main__":
    main()
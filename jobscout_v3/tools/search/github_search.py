"""
GitHub New Grad Job Lists

Scrapes curated new grad job lists from GitHub repositories.
These are manually verified entry-level US positions, updated daily.

Sources:
- jobright-ai/2026-Software-Engineer-New-Grad
- speedyapply/2026-AI-College-Jobs

Location: jobscout_v3/tools/search/github_search.py
"""

import re
import logging
from datetime import datetime, timezone

import requests

from .job_listing import JobListing

logger = logging.getLogger(__name__)


def search_github_newgrad(max_results: int = 50) -> list[JobListing]:
    """
    Scrape curated new grad job lists from GitHub repos.
    
    These repos are manually maintained with verified:
    - Entry-level/new grad positions
    - US-based locations (or remote)
    - Active job postings
    
    Args:
        max_results: Maximum number of jobs to return
        
    Returns:
        List of JobListing objects
        
    Example:
        >>> jobs = search_github_newgrad(max_results=30)
        >>> print(f"Found {len(jobs)} new grad jobs")
    """
    sources = [
        "https://raw.githubusercontent.com/jobright-ai/2026-Software-Engineer-New-Grad/master/README.md",
        "https://raw.githubusercontent.com/speedyapply/2026-AI-College-Jobs/main/NEW_GRAD_USA.md",
    ]

    all_listings = []
    seen = set()

    for source_url in sources:
        try:
            resp = requests.get(
                source_url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=15,
            )
            
            if resp.status_code != 200:
                logger.warning(f"GitHub returned {resp.status_code}: {source_url}")
                continue

            content = resp.text

            # Parse markdown table rows: | Company | Title | Location | ... |
            # Rows look like: | **[Company](url)** | **[Title](apply_url)** | Location | ...
            table_row = re.compile(
                r'^\|\s*\*?\*?\[?([^\]|]+)\]?\(?([^)]*)\)?\*?\*?\s*\|'  # Company
                r'\s*\*?\*?\[([^\]]+)\]\(([^)]+)\)\*?\*?\s*\|'          # Title (linked)
                r'\s*([^|]*)\|',                                           # Location
                re.MULTILINE
            )

            for match in table_row.finditer(content):
                company = match.group(1).strip().strip('*').strip()
                title = match.group(3).strip().strip('*').strip()
                apply_url = match.group(4).strip()
                location = match.group(5).strip()

                # Skip header rows and non-job rows
                if not title or not apply_url or title.lower() in ("job title", "title", "position"):
                    continue
                if not apply_url.startswith("http"):
                    continue
                if not company or company.lower() in ("company", "employer"):
                    continue

                # Skip non-US locations
                skip_locs = ["canada", " uk", "london", "toronto", "india", "ireland", "germany", "australia"]
                if any(loc in location.lower() for loc in skip_locs):
                    continue

                # Deduplicate
                key = f"{company}::{title}".lower()
                if key in seen:
                    continue
                seen.add(key)

                source_tag = "swe" if "jobright" in source_url else "ai"
                all_listings.append(JobListing(
                    id=f"github_{source_tag}_{hash(apply_url) % 100000}",
                    title=title,
                    company=company,
                    location=location,
                    description=f"{title} at {company}",  # GitHub tables don't have descriptions
                    apply_url=apply_url,
                    salary_min=None,
                    salary_max=None,
                    created=datetime.now(timezone.utc).isoformat(),
                    source="github_newgrad",
                ))

        except requests.exceptions.RequestException as e:
            logger.error(f"GitHub scrape error: {e}")
            continue

    logger.info(f"GitHub: {len(all_listings)} new grad jobs")
    return all_listings[:max_results]


# CLI for testing
if __name__ == "__main__":
    print("Scraping GitHub new grad job repos...")
    jobs = search_github_newgrad(max_results=30)
    
    print(f"\nFound {len(jobs)} jobs:")
    for job in jobs[:15]:
        print(f"  - {job}")
    
    print(f"\n... and {len(jobs) - 15} more")

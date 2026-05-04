"""
Adzuna Job Search API

Uses Adzuna's free job search API as a fallback source.
Good for comprehensive coverage, includes salary data.

Location: jobscout_v3/tools/search/adzuna_search.py
"""

import os
import logging

import requests

from .job_listing import JobListing

logger = logging.getLogger(__name__)


def search_adzuna(
    query: str,
    max_results: int = 50,
    country: str = "us",
    location: str = "",
    max_days_old: int = 7
) -> list[JobListing]:
    """
    Search Adzuna job API.
    
    Args:
        query: Search query (e.g., "software engineer")
        max_results: Maximum number of results (up to 50)
        country: Country code (default: "us")
        location: Location filter (e.g., "California")
        max_days_old: Only jobs posted within N days
        
    Returns:
        List of JobListing objects
        
    Example:
        >>> jobs = search_adzuna("python developer", location="San Francisco")
        >>> print(f"Found {len(jobs)} jobs")
    """
    app_id = os.getenv("ADZUNA_APP_ID", "")
    app_key = os.getenv("ADZUNA_APP_KEY", "")
    
    if not app_id or not app_key:
        logger.warning("ADZUNA_APP_ID or ADZUNA_APP_KEY not set.")
        return []

    params = {
        "app_id": app_id,
        "app_key": app_key,
        "what": query,
        "results_per_page": min(max_results, 50),
        "content-type": "application/json",
        "sort_by": "date",
        "max_days_old": max_days_old,
        "category": "it-jobs",
    }
    
    if location:
        params["where"] = location

    try:
        resp = requests.get(
            f"https://api.adzuna.com/v1/api/jobs/{country}/search/1",
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        
        listings = []
        for job in resp.json().get("results", []):
            listings.append(JobListing(
                id=f"adzuna_{job.get('id', '')}",
                title=job.get("title", "Unknown"),
                company=job.get("company", {}).get("display_name", "Unknown"),
                location=job.get("location", {}).get("display_name", ""),
                description=job.get("description", ""),
                apply_url=job.get("redirect_url", ""),
                salary_min=job.get("salary_min"),
                salary_max=job.get("salary_max"),
                created=job.get("created", ""),
                source="adzuna",
            ))
        
        logger.info(f"Adzuna: {len(listings)} jobs for '{query}'")
        return listings
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Adzuna error: {e}")
        return []


# CLI for testing
if __name__ == "__main__":
    import sys
    
    query = sys.argv[1] if len(sys.argv) > 1 else "software engineer"
    location = sys.argv[2] if len(sys.argv) > 2 else "California"
    
    print(f"Searching Adzuna: {query} in {location}")
    jobs = search_adzuna(query, location=location, max_results=20)
    
    print(f"\nFound {len(jobs)} jobs:")
    for job in jobs[:10]:
        print(f"  - {job}")

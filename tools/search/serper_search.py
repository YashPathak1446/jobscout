"""
Serper.dev Search Tool

Uses Google search via Serper.dev API to find job postings.
Site-targeted queries for Greenhouse, Lever, and LinkedIn.

Location: jobscout_v3/tools/search/serper_search.py
"""

import os
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from .job_listing import JobListing

logger = logging.getLogger(__name__)


def search_serper(query: str, max_results: int = 10) -> list[JobListing]:
    """
    Search Google via Serper.dev API.
    
    Args:
        query: Search query (e.g., "software engineer new grad site:greenhouse.io")
        max_results: Maximum number of results to return
        
    Returns:
        List of JobListing objects
        
    Example:
        >>> jobs = search_serper("machine learning engineer new grad", max_results=20)
        >>> print(f"Found {len(jobs)} jobs")
    """
    api_key = os.getenv("SERPER_API_KEY", "")
    if not api_key:
        logger.warning("SERPER_API_KEY not set.")
        return []

    try:
        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": min(max_results, 20)},
            timeout=10,
        )
        
        if resp.status_code == 429:
            logger.warning("Serper rate limit hit.")
            return []
        
        resp.raise_for_status()
        data = resp.json()

        # Blocked sites — never job postings
        blocked_sites = [
            "reddit.com", "quora.com", "stackoverflow.com",
            "medium.com", "youtube.com", "wikipedia.org",
            "news.ycombinator.com", "geeksforgeeks.org",
            "coursera.org", "udemy.com",
            "github.com", "ziprecruiter.com",
            "builtinnyc.com", "builtin.com",
        ]

        # Blocked URL patterns — aggregator/search pages, not individual jobs
        blocked_patterns = [
            "indeed.com/q-",
            "indeed.com/jobs?q=",
            "linkedin.com/jobs/entry-level",
            "linkedin.com/jobs/junior",
            "linkedin.com/jobs/new-grad",
            "linkedin.com/jobs/software-engineer",
            "linkedin.com/jobs/machine-learning",
            "linkedin.com/jobs/devops",
            "linkedin.com/jobs/data-engineer",
            "linkedin.com/jobs/full-stack",
            "glassdoor.com/Job/",
            "glassdoor.com/Reviews",
            "glassdoor.com/Salary",
        ]

        listings = []
        for i, result in enumerate(data.get("organic", [])[:max_results]):
            link = result.get("link", "")
            link_lower = link.lower()

            # Skip blocked sites
            if any(b in link_lower for b in blocked_sites):
                continue

            # Skip aggregator search pages
            if any(b in link_lower for b in blocked_patterns):
                continue

            # Skip very short snippets (likely category pages)
            snippet = result.get("snippet", "")
            if len(snippet) < 50:
                continue

            listings.append(JobListing(
                id=f"serper_{i}_{hash(link) % 10000}",
                title=result.get("title", ""),
                company=_extract_company_from_url(link),
                location="",  # Serper doesn't provide location reliably
                description=snippet,
                apply_url=link,
                salary_min=None,
                salary_max=None,
                created=datetime.now(timezone.utc).isoformat(),
                source="serper",
            ))

        logger.info(f"Serper: {len(listings)} results for '{query}'")
        return listings

    except requests.exceptions.RequestException as e:
        logger.error(f"Serper error: {e}")
        return []


def _extract_company_from_url(url: str) -> str:
    """
    Best-effort company name extraction from job posting URL.
    
    Args:
        url: Job posting URL
        
    Returns:
        Company name (or generic placeholder if unable to extract)
    """
    url_lower = url.lower()
    
    # Greenhouse.io
    if "greenhouse.io" in url_lower:
        parts = url.split("/")
        for i, part in enumerate(parts):
            if "greenhouse" in part.lower() and i + 1 < len(parts):
                name = parts[i + 1].replace("-", " ").title()
                if name.lower() not in ("jobs", "job", "embed"):
                    return name
    
    # Lever.co
    if "lever.co" in url_lower:
        parts = url.split("/")
        for i, part in enumerate(parts):
            if "lever.co" in part.lower() and i + 1 < len(parts):
                return parts[i + 1].replace("-", " ").title()
    
    # LinkedIn
    if "linkedin.com/jobs/view" in url_lower:
        return "LinkedIn Posting"
    
    # Workday
    if "myworkdayjobs" in url_lower:
        domain = url.split("//")[1].split(".")[0] if "//" in url else ""
        return domain.replace("-", " ").title()
    
    # Fallback: extract from domain
    try:
        domain = urlparse(url).hostname or ""
        for prefix in ["www.", "careers.", "jobs.", "apply.", "job-boards."]:
            domain = domain.replace(prefix, "")
        for suffix in [".com", ".io", ".org", ".net", ".co"]:
            domain = domain.replace(suffix, "")
        return domain.replace("-", " ").title() if domain else "Unknown Company"
    except Exception:
        return "Unknown Company"


def build_serper_query(role: str, seniority: str = "", site: str = "") -> str:
    """
    Build optimized Serper query for job search.
    
    Args:
        role: Job role (e.g., "Software Engineer", "ML Engineer")
        seniority: Seniority level (e.g., "new grad", "entry level")
        site: Target site (e.g., "greenhouse.io", "lever.co")
        
    Returns:
        Formatted search query
        
    Example:
        >>> query = build_serper_query("Software Engineer", "new grad", "greenhouse.io")
        >>> print(query)
        "Software Engineer new grad site:greenhouse.io"
    """
    parts = [role]
    if seniority:
        parts.append(seniority)
    if site:
        parts.append(f"site:{site}")
    
    return " ".join(parts)


# CLI for testing
if __name__ == "__main__":
    import sys
    
    # Test query
    query = sys.argv[1] if len(sys.argv) > 1 else "software engineer new grad site:greenhouse.io"
    
    print(f"Searching: {query}")
    jobs = search_serper(query, max_results=10)
    
    print(f"\nFound {len(jobs)} jobs:")
    for job in jobs:
        print(f"  - {job}")

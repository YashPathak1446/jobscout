"""
Job Search Tools — Wrappers for job search APIs.

Currently supports:
- Adzuna (primary, free tier)
- Mock (for testing without API keys)

Each adapter returns a standardized list of JobListing objects.
"""

import os
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)


@dataclass
class JobListing:
    """Standardized job listing from any source."""
    id: str                     # Unique ID from the source
    title: str                  # Job title
    company: str                # Company name
    location: str               # Display location
    description: str            # Job description text (may be truncated)
    apply_url: str              # Direct link to apply
    salary_min: float | None    # Min salary if available
    salary_max: float | None    # Max salary if available
    created: str                # ISO date string
    source: str                 # "adzuna", "remotive", etc.


def search_adzuna(
    query: str,
    country: str = "us",
    location: str = "",
    max_results: int = 10,
    max_days_old: int = 2,
) -> list[JobListing]:
    """
    Search Adzuna for job listings.

    Args:
        query: Search keywords (e.g., "python engineer new grad")
        country: Country code (default "us")
        location: Optional location filter (e.g., "California")
        max_results: Max results to return (default 10)
        max_days_old: Only return jobs posted within N days (default 2)

    Returns:
        List of JobListing objects.
    """
    app_id = os.getenv("ADZUNA_APP_ID", "")
    app_key = os.getenv("ADZUNA_APP_KEY", "")

    if not app_id or not app_key:
        logger.warning(
            "ADZUNA_APP_ID or ADZUNA_APP_KEY not set. "
            "Get free keys at https://developer.adzuna.com/ "
            "Falling back to mock data."
        )
        return search_mock(query, max_results)

    base_url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"

    params = {
        "app_id": app_id,
        "app_key": app_key,
        "what": query,
        "results_per_page": min(max_results, 50),
        "content-type": "application/json",
        "sort_by": "date",                    # Most recent first
        "max_days_old": max_days_old,
        "category": "it-jobs",                # Filter to tech jobs
    }

    if location:
        params["where"] = location

    try:
        resp = requests.get(base_url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        listings = []
        for job in data.get("results", []):
            listing = JobListing(
                id=str(job.get("id", "")),
                title=job.get("title", "Unknown Title"),
                company=job.get("company", {}).get("display_name", "Unknown Company"),
                location=job.get("location", {}).get("display_name", "Unknown"),
                description=job.get("description", ""),
                apply_url=job.get("redirect_url", ""),
                salary_min=job.get("salary_min"),
                salary_max=job.get("salary_max"),
                created=job.get("created", ""),
                source="adzuna",
            )
            listings.append(listing)

        logger.info(f"Adzuna: found {len(listings)} jobs for '{query}'")
        return listings

    except requests.exceptions.RequestException as e:
        logger.error(f"Adzuna API error: {e}")
        return []


def search_mock(query: str, max_results: int = 5) -> list[JobListing]:
    """
    Return mock job listings for testing without API keys.
    Generates realistic-looking test data based on the query.
    """
    now = datetime.now(timezone.utc)
    mock_jobs = [
        {
            "title": "Software Engineer, New Grad",
            "company": "Stripe",
            "location": "San Francisco, CA",
            "description": (
                "We're looking for new grad software engineers to build the "
                "infrastructure that powers internet commerce. You'll work on "
                "distributed systems processing millions of API requests. "
                "Requirements: Python, Java, AWS, Docker, Kubernetes, CI/CD, "
                "REST APIs. Nice to have: Go, Ruby, Terraform."
            ),
            "salary_min": 180000,
            "salary_max": 220000,
            "apply_url": "https://stripe.com/jobs/search?query=new+grad",
        },
        {
            "title": "Junior ML Engineer",
            "company": "Scale AI",
            "location": "San Francisco, CA",
            "description": (
                "Join our ML platform team building tools for AI data labeling. "
                "Requirements: Python, PyTorch or TensorFlow, NLP or computer "
                "vision experience, familiarity with LLMs and RAG pipelines. "
                "Nice to have: vector databases, Kubernetes, AWS."
            ),
            "salary_min": 160000,
            "salary_max": 200000,
            "apply_url": "https://scale.com/careers",
        },
        {
            "title": "Backend Engineer (Entry Level)",
            "company": "Datadog",
            "location": "New York, NY",
            "description": (
                "Build and maintain observability infrastructure at scale. "
                "Requirements: Python or Go, AWS or GCP, Docker, Kubernetes, "
                "CI/CD pipelines, monitoring and observability tools. "
                "Nice to have: Terraform, Kafka, distributed systems experience."
            ),
            "salary_min": 150000,
            "salary_max": 190000,
            "apply_url": "https://careers.datadoghq.com",
        },
        {
            "title": "Full Stack Developer",
            "company": "Notion",
            "location": "Remote, US",
            "description": (
                "Build the next generation of productivity tools. "
                "Requirements: TypeScript, React, Node.js, PostgreSQL, "
                "REST APIs. Experience with real-time collaboration, "
                "WebSocket, or similar technologies is a plus."
            ),
            "salary_min": 140000,
            "salary_max": 180000,
            "apply_url": "https://notion.so/careers",
        },
        {
            "title": "Data Engineer, New Grad",
            "company": "Snowflake",
            "location": "San Mateo, CA",
            "description": (
                "Join our data platform team building next-gen cloud data "
                "warehouse features. Requirements: Python, SQL, AWS or GCP, "
                "data pipelines, ETL processes. Nice to have: Spark, Kafka, "
                "Airflow, Docker, Terraform."
            ),
            "salary_min": 155000,
            "salary_max": 195000,
            "apply_url": "https://careers.snowflake.com",
        },
        {
            "title": "Software Engineer - Infrastructure",
            "company": "Cloudflare",
            "location": "Austin, TX",
            "description": (
                "Work on our global edge network infrastructure. "
                "Requirements: Python or Go, Linux, networking fundamentals, "
                "Docker, Kubernetes, CI/CD. Experience with distributed "
                "systems, load balancing, and observability is preferred."
            ),
            "salary_min": 145000,
            "salary_max": 185000,
            "apply_url": "https://cloudflare.com/careers",
        },
        {
            "title": "AI Platform Engineer",
            "company": "Anthropic",
            "location": "San Francisco, CA",
            "description": (
                "Build the infrastructure powering Claude and our AI systems. "
                "Requirements: Python, distributed systems, AWS or GCP, "
                "Docker, Kubernetes. Experience with ML training pipelines, "
                "LLMs, RAG, or vector databases is highly valued."
            ),
            "salary_min": 200000,
            "salary_max": 280000,
            "apply_url": "https://anthropic.com/careers",
        },
        {
            "title": "DevOps Engineer (Junior)",
            "company": "HashiCorp",
            "location": "Remote, US",
            "description": (
                "Help build and maintain our cloud infrastructure products. "
                "Requirements: Terraform, AWS or GCP, Docker, Kubernetes, "
                "CI/CD pipelines, Linux, Python or Go. Experience with "
                "Infrastructure as Code and monitoring tools."
            ),
            "salary_min": 130000,
            "salary_max": 170000,
            "apply_url": "https://hashicorp.com/careers",
        },
    ]

    listings = []
    for i, job in enumerate(mock_jobs[:max_results]):
        listings.append(
            JobListing(
                id=f"mock_{i + 1}",
                title=job["title"],
                company=job["company"],
                location=job["location"],
                description=job["description"],
                apply_url=job["apply_url"],
                salary_min=job.get("salary_min"),
                salary_max=job.get("salary_max"),
                created=(now - timedelta(hours=i * 6)).isoformat(),
                source="mock",
            )
        )

    logger.info(f"Mock: returning {len(listings)} test jobs")
    return listings


def search_jobs(
    queries: list[str],
    country: str = "us",
    locations: list[str] | None = None,
    max_results_per_query: int = 10,
    max_days_old: int = 2,
    apis: list[str] | None = None,
) -> list[JobListing]:
    """
    Search for jobs across all configured APIs, merging and deduplicating results.

    Args:
        queries: List of search queries to run.
        country: Country code.
        locations: List of location filters (empty/None = nationwide).
        max_results_per_query: Max results per query.
        max_days_old: Only jobs posted within N days.
        apis: List of APIs to use (default: ["adzuna"]).

    Returns:
        Deduplicated list of JobListing objects from all sources.
    """
    if apis is None:
        apis = ["adzuna"]

    all_listings = []
    seen_ids = set()  # Dedup by source+id
    seen_titles = set()  # Dedup by company+title

    location_list = locations if locations else [""]

    for query in queries:
        for location in location_list:
            for api in apis:
                if api == "adzuna":
                    results = search_adzuna(
                        query, country, location,
                        max_results_per_query, max_days_old,
                    )
                elif api == "mock":
                    results = search_mock(query, max_results_per_query)
                else:
                    logger.warning(f"Unknown job API: {api}")
                    continue

                for listing in results:
                    # Deduplicate
                    source_id = f"{listing.source}_{listing.id}"
                    title_key = f"{listing.company}_{listing.title}".lower()

                    if source_id not in seen_ids and title_key not in seen_titles:
                        seen_ids.add(source_id)
                        seen_titles.add(title_key)
                        all_listings.append(listing)

    logger.info(f"Total unique jobs found: {len(all_listings)}")
    return all_listings


def generate_search_queries(
    skills: list[str],
    base_titles: list[str],
    experience_levels: list[str],
    max_queries: int = 8,
) -> list[str]:
    """
    Auto-generate job search queries from resume skills.

    Combines skill clusters with base titles and experience levels
    to produce diverse search queries.

    Args:
        skills: List of skills from resume (e.g., ["python", "aws", "docker"])
        base_titles: Base role titles (e.g., ["engineer", "developer"])
        experience_levels: Experience labels (e.g., ["new grad", "junior"])
        max_queries: Maximum number of queries to generate.

    Returns:
        List of search query strings.
    """
    # Group skills into clusters for targeted searches
    skill_clusters = {
        "backend": ["python", "java", "go", "rest api", "microservices", "sql"],
        "ml_ai": ["pytorch", "tensorflow", "nlp", "llm", "rag", "embeddings",
                   "huggingface", "transformers", "computer vision"],
        "infra": ["aws", "docker", "kubernetes", "terraform", "ci/cd", "linux"],
        "data": ["sql", "mongodb", "kafka", "spark", "airflow", "postgresql"],
        "frontend": ["react", "angular", "vue", "javascript", "typescript", "node.js"],
    }

    # Find which clusters the resume has skills in
    active_clusters = []
    for cluster_name, cluster_skills in skill_clusters.items():
        overlap = set(skills) & set(cluster_skills)
        if len(overlap) >= 2:
            active_clusters.append((cluster_name, overlap))

    # Sort by number of matching skills (strongest cluster first)
    active_clusters.sort(key=lambda x: len(x[1]), reverse=True)

    # Generate queries
    cluster_to_title = {
        "backend": "software engineer",
        "ml_ai": "machine learning engineer",
        "infra": "devops engineer",
        "data": "data engineer",
        "frontend": "full stack developer",
    }

    queries = []
    for cluster_name, cluster_skills in active_clusters:
        title = cluster_to_title.get(cluster_name, "software engineer")
        for level in experience_levels[:2]:  # Limit levels per cluster
            query = f"{title} {level}"
            if query not in queries:
                queries.append(query)

            if len(queries) >= max_queries:
                break
        if len(queries) >= max_queries:
            break

    # If we have room, add generic queries with top skills
    if len(queries) < max_queries:
        top_skills = " ".join(skills[:3])
        for title in base_titles[:2]:
            query = f"{top_skills} {title}"
            if query not in queries:
                queries.append(query)
            if len(queries) >= max_queries:
                break

    return queries


def print_listings(listings: list[JobListing]) -> None:
    """Pretty-print job listings for debugging."""
    print(f"\n{'#':<4} {'Score':<7} {'Company':<20} {'Title':<35} {'Location':<20}")
    print("-" * 86)
    for i, job in enumerate(listings, 1):
        salary = ""
        if job.salary_min and job.salary_max:
            salary = f"${job.salary_min/1000:.0f}K-${job.salary_max/1000:.0f}K"
        print(f"{i:<4} {'--':<7} {job.company:<20} {job.title:<35} {job.location:<20} {salary}")
    print(f"\nTotal: {len(listings)} jobs")


# === CLI for testing ===
if __name__ == "__main__":
    import sys

    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "python engineer new grad"
    print(f"Searching for: '{query}'\n")

    # Test with mock data (no API key needed)
    listings = search_jobs(
        queries=[query],
        apis=["mock"],
        max_results_per_query=5,
    )
    print_listings(listings)

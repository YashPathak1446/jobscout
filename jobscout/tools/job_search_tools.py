"""
Job Search Tools V2 — Serper.dev (primary) + Adzuna (fallback)

Serper.dev: 2,500 free Google searches/month. Best quality.
Adzuna: Unlimited free. Falls back automatically when Serper quota exhausted.
Mock: For testing without any API keys.
"""

import os
import time
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)


@dataclass
class JobListing:
    """Standardized job listing from any source."""
    id: str
    title: str
    company: str
    location: str
    description: str
    apply_url: str
    salary_min: float | None
    salary_max: float | None
    created: str
    source: str
    full_jd: str = ""


def search_serper(query: str, max_results: int = 10) -> list[JobListing]:
    """Search Google via Serper.dev for job listings."""
    api_key = os.getenv("SERPER_API_KEY", "")
    if not api_key:
        logger.warning("SERPER_API_KEY not set. Get free key at https://serper.dev/")
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

        listings = []
        job_indicators = [
            "job", "career", "greenhouse", "lever", "workday",
            "linkedin.com/jobs", "indeed.com", "glassdoor.com",
            "myworkdayjobs", "ashby", "smartrecruiters",
        ]
        for i, result in enumerate(data.get("organic", [])[:max_results]):
            link = result.get("link", "")
            if not any(kw in link.lower() for kw in job_indicators):
                continue
            listings.append(JobListing(
                id=f"serper_{i}_{hash(link) % 10000}",
                title=result.get("title", ""),
                company=_extract_company_from_url(link),
                location="",
                description=result.get("snippet", ""),
                apply_url=link,
                salary_min=None, salary_max=None,
                created=datetime.now(timezone.utc).isoformat(),
                source="serper",
            ))
        logger.info(f"Serper: {len(listings)} job results for '{query}'")
        return listings
    except requests.exceptions.RequestException as e:
        logger.error(f"Serper error: {e}")
        return []


def _extract_company_from_url(url: str) -> str:
    """Best-effort company name from URL."""
    url_lower = url.lower()
    if "greenhouse.io" in url_lower:
        parts = url.split("/")
        for i, part in enumerate(parts):
            if "greenhouse" in part and i + 1 < len(parts):
                return parts[i + 1].replace("-", " ").title()
    if "linkedin.com" in url_lower:
        return "LinkedIn Posting"
    if "myworkdayjobs" in url_lower:
        domain = url.split("//")[1].split(".")[0] if "//" in url else ""
        return domain.replace("-", " ").title()
    try:
        from urllib.parse import urlparse
        domain = (urlparse(url).hostname or "")
        for p in ["www.", "careers.", "jobs.", "apply.", "job-boards."]:
            domain = domain.replace(p, "")
        for s in [".com", ".io", ".org", ".net", ".co"]:
            domain = domain.replace(s, "")
        return domain.replace("-", " ").replace(".", " ").title().strip() or "Unknown"
    except Exception:
        return "Unknown"


def search_adzuna(
    query: str, country: str = "us", location: str = "",
    max_results: int = 10, max_days_old: int = 2,
) -> list[JobListing]:
    """Search Adzuna. Fallback when Serper is exhausted."""
    app_id = os.getenv("ADZUNA_APP_ID", "")
    app_key = os.getenv("ADZUNA_APP_KEY", "")
    if not app_id or not app_key:
        logger.warning("ADZUNA keys not set.")
        return []

    params = {
        "app_id": app_id, "app_key": app_key,
        "what": query, "results_per_page": min(max_results, 50),
        "content-type": "application/json",
        "sort_by": "date", "max_days_old": max_days_old,
        "category": "it-jobs",
    }
    if location:
        params["where"] = location

    try:
        resp = requests.get(
            f"https://api.adzuna.com/v1/api/jobs/{country}/search/1",
            params=params, timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        listings = []
        for job in data.get("results", []):
            listings.append(JobListing(
                id=str(job.get("id", "")),
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


def search_mock(query: str, max_results: int = 8) -> list[JobListing]:
    """Mock listings for testing without API keys."""
    now = datetime.now(timezone.utc)
    mock_data = [
        ("Software Engineer, New Grad", "Stripe", "San Francisco, CA",
         "Build distributed systems processing millions of API requests. "
         "Requirements: Python, Java, AWS, Docker, Kubernetes, CI/CD, REST APIs, "
         "distributed systems. Nice to have: Go, Ruby, Terraform, microservices.",
         "https://stripe.com/jobs", 180000, 220000),
        ("Junior ML Engineer", "Scale AI", "San Francisco, CA",
         "Build ML platform tools for AI data labeling and model training. "
         "Requirements: Python, PyTorch or TensorFlow, NLP, computer vision, "
         "LLMs, RAG pipelines, vector databases. Nice to have: Kubernetes, AWS.",
         "https://scale.com/careers", 160000, 200000),
        ("Backend Engineer (Entry Level)", "Datadog", "New York, NY",
         "Build observability infrastructure for monitoring at scale. "
         "Requirements: Python or Go, AWS or GCP, Docker, Kubernetes, CI/CD, "
         "monitoring, distributed systems, REST APIs, data pipelines, Terraform.",
         "https://careers.datadoghq.com", 150000, 190000),
        ("Full Stack Developer", "Notion", "Remote, US",
         "Build productivity tools with modern web technologies. "
         "Requirements: TypeScript, React, Node.js, PostgreSQL, REST APIs, "
         "full-stack development, frontend, backend, agile, Git.",
         "https://notion.so/careers", 140000, 180000),
        ("Data Engineer, New Grad", "Snowflake", "San Mateo, CA",
         "Build cloud data warehouse features and data pipelines. "
         "Requirements: Python, SQL, AWS or GCP, data pipelines, ETL, "
         "distributed systems. Nice to have: Spark, Kafka, Airflow, Docker.",
         "https://careers.snowflake.com", 155000, 195000),
        ("Software Engineer - Infrastructure", "Cloudflare", "Austin, TX",
         "Work on global edge network infrastructure and developer tools. "
         "Requirements: Python or Go, Linux, Docker, Kubernetes, CI/CD, "
         "networking, distributed systems, REST APIs, Terraform, monitoring.",
         "https://cloudflare.com/careers", 145000, 185000),
        ("AI Platform Engineer", "Anthropic", "San Francisco, CA",
         "Build infrastructure powering Claude and AI research systems. "
         "Requirements: Python, distributed systems, AWS or GCP, Docker, "
         "Kubernetes, ML pipelines, LLMs, RAG, vector databases, microservices.",
         "https://anthropic.com/careers", 200000, 280000),
        ("DevOps Engineer (Junior)", "HashiCorp", "Remote, US",
         "Build cloud infrastructure products like Terraform. "
         "Requirements: Terraform, AWS or GCP, Docker, Kubernetes, CI/CD, "
         "Linux, Python or Go, infrastructure as code, monitoring, agile.",
         "https://hashicorp.com/careers", 130000, 170000),
    ]
    listings = []
    for i, (t, c, l, d, u, smin, smax) in enumerate(mock_data[:max_results]):
        listings.append(JobListing(
            id=f"mock_{i+1}", title=t, company=c, location=l,
            description=d, apply_url=u, salary_min=smin, salary_max=smax,
            created=now.isoformat(), source="mock",
        ))
    return listings


# =========================================================================
# JD SCRAPER
# =========================================================================

def scrape_full_jd(url: str, delay: float = 1.0) -> str:
    """
    Scrape full JD from apply URL. Returns text capped at 8000 chars.
    Handles Greenhouse, LinkedIn, Lever, generic sites.
    Gracefully fails for Workday (JS), Indeed (blocked), Handshake.
    """
    from bs4 import BeautifulSoup

    if "linkedin.com" in url:
        time.sleep(delay)

    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            },
            timeout=10,
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return ""

        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        selectors = [
            "[class*=description]",
            ".posting-page",
            "[class*=job-details]",
            "article",
            "main",
            "[role=main]",
        ]
        for selector in selectors:
            elements = soup.select(selector)
            if elements:
                text = elements[0].get_text(separator=" ", strip=True)
                if len(text) > 200:
                    return text[:8000]

        text = soup.get_text(separator=" ", strip=True)
        return text[:8000] if len(text) > 200 else ""

    except Exception as e:
        logger.debug(f"Scrape failed for {url}: {e}")
        return ""


def enrich_listings_with_full_jd(
    listings: list[JobListing], delay: float = 1.0,
) -> list[JobListing]:
    """Try to scrape full JD for each listing. Modifies in-place."""
    success = 0
    for listing in listings:
        if listing.apply_url:
            jd = scrape_full_jd(listing.apply_url, delay=delay)
            if jd:
                listing.full_jd = jd
                success += 1
    logger.info(f"Enrichment: {success}/{len(listings)} full JDs scraped")
    return listings


# =========================================================================
# UNIFIED SEARCH
# =========================================================================

def search_jobs(
    queries: list[str],
    country: str = "us",
    locations: list[str] | None = None,
    max_results_per_query: int = 10,
    max_days_old: int = 2,
    discovery_priority: list[str] | None = None,
    max_total: int = 50,
) -> list[JobListing]:
    """Search with automatic fallback. Deduplicates by company+title."""
    if discovery_priority is None:
        discovery_priority = ["serper", "adzuna"]

    all_listings = []
    seen_titles = set()

    for query in queries:
        results = []
        for api in discovery_priority:
            if api == "serper":
                results = search_serper(query, max_results_per_query)
            elif api == "adzuna":
                loc = locations[0] if locations else ""
                results = search_adzuna(query, country, loc, max_results_per_query, max_days_old)
            elif api == "mock":
                results = search_mock(query, max_results_per_query)
            if results:
                break

        for listing in results:
            key = f"{listing.company}_{listing.title}".lower().strip()
            if key not in seen_titles:
                seen_titles.add(key)
                all_listings.append(listing)
        if len(all_listings) >= max_total:
            break

    return all_listings[:max_total]


def generate_search_queries(
    skills: list[str], base_titles: list[str],
    experience_levels: list[str], max_queries: int = 8,
) -> list[str]:
    """Auto-generate queries from resume skills."""
    skill_clusters = {
        "backend": ["python", "java", "go", "rest api", "microservices", "sql"],
        "ml_ai": ["pytorch", "tensorflow", "nlp", "llm", "rag", "embeddings",
                   "huggingface", "transformers", "computer vision", "ai", "ml",
                   "machine learning", "deep learning"],
        "infra": ["aws", "docker", "kubernetes", "terraform", "ci/cd", "linux"],
        "data": ["sql", "mongodb", "kafka", "spark", "airflow", "postgresql",
                 "data pipelines", "etl"],
        "frontend": ["react", "angular", "vue", "javascript", "typescript",
                     "node.js", "frontend", "full-stack", "full stack"],
    }
    active = []
    for name, cs in skill_clusters.items():
        overlap = set(skills) & set(cs)
        if len(overlap) >= 2:
            active.append((name, overlap))
    active.sort(key=lambda x: len(x[1]), reverse=True)

    title_map = {
        "backend": "software engineer",
        "ml_ai": "machine learning engineer",
        "infra": "devops engineer",
        "data": "data engineer",
        "frontend": "full stack developer",
    }
    queries = []
    for cname, _ in active:
        title = title_map.get(cname, "software engineer")
        for level in experience_levels[:2]:
            q = f"{title} {level}"
            if q not in queries:
                queries.append(q)
            if len(queries) >= max_queries:
                break
        if len(queries) >= max_queries:
            break

    if len(queries) < max_queries:
        top = " ".join(skills[:3])
        for t in base_titles[:2]:
            q = f"{top} {t}"
            if q not in queries:
                queries.append(q)
            if len(queries) >= max_queries:
                break
    return queries


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    query = " ".join(sys.argv[1:]) or "software engineer new grad"
    print(f"Searching: '{query}'\n")
    listings = search_jobs([query], discovery_priority=["serper", "adzuna", "mock"], max_results_per_query=5)
    for i, j in enumerate(listings, 1):
        print(f"{i}. [{j.source}] {j.company} — {j.title}")
        print(f"   {j.apply_url}")
        print(f"   {j.description[:120]}...")
        print()

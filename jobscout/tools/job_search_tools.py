"""
Job Search Tools V2 — Serper.dev (primary) + Adzuna (fallback)

Serper: Site-targeted Google queries → individual job postings
Adzuna: Generic job API → fallback when Serper exhausted
Mock: Testing without API keys
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


# =========================================================================
# SERPER.DEV
# =========================================================================

def search_serper(query: str, max_results: int = 10) -> list[JobListing]:
    """Search Google via Serper.dev."""
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
            if len(result.get("snippet", "")) < 50:
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

        logger.info(f"Serper: {len(listings)} results for '{query}'")
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
            if "greenhouse" in part.lower() and i + 1 < len(parts):
                name = parts[i + 1].replace("-", " ").title()
                if name.lower() not in ("jobs", "job", "embed"):
                    return name
    if "lever.co" in url_lower:
        parts = url.split("/")
        for i, part in enumerate(parts):
            if "lever.co" in part.lower() and i + 1 < len(parts):
                return parts[i + 1].replace("-", " ").title()
    if "linkedin.com/jobs/view" in url_lower:
        # Try to extract from title later; URL doesn't have company
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


# =========================================================================
# ADZUNA
# =========================================================================

def search_adzuna(
    query: str, country: str = "us", location: str = "",
    max_results: int = 10, max_days_old: int = 2,
) -> list[JobListing]:
    """Search Adzuna job API."""
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
        listings = []
        for job in resp.json().get("results", []):
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


# =========================================================================
# MOCK
# =========================================================================

def search_github_newgrad(max_results: int = 30) -> list[JobListing]:
    """
    Scrape curated new grad job lists from GitHub repos.
    These are manually verified entry-level US positions, updated daily.

    Sources:
    - jobright-ai/2026-Software-Engineer-New-Grad (SWE roles)
    - speedyapply/2026-AI-College-Jobs NEW_GRAD_USA.md (AI/ML roles)
    """
    import re as _re

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
                logger.warning(f"GitHub raw returned {resp.status_code}: {source_url}")
                continue

            content = resp.text

            # Parse markdown table rows: | Company | Title | Location | ... |
            # Rows look like: | **[Company](url)** | **[Title](apply_url)** | Location | ...
            table_row = _re.compile(
                r'^\|\s*\*?\*?\[?([^\]|]+)\]?\(?([^)]*)\)?\*?\*?\s*\|'  # Company
                r'\s*\*?\*?\[([^\]]+)\]\(([^)]+)\)\*?\*?\s*\|'          # Title (linked)
                r'\s*([^|]*)\|',                                           # Location
                _re.MULTILINE
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

                key = f"{company}::{title}".lower()
                if key in seen:
                    continue
                seen.add(key)

                source_tag = "swe" if "jobright" in source_url else "ai"
                all_listings.append(JobListing(
                    id=f"github_{source_tag}_{hash(apply_url) % 100000}",
                    title=title,
                    company=company,
                    location=location if location else "USA",
                    description=f"{title} at {company}",
                    apply_url=apply_url,
                    salary_min=None,
                    salary_max=None,
                    created="",
                    source="github_newgrad",
                ))

                if len(all_listings) >= max_results:
                    break

            logger.info(f"GitHub ({source_url.split('/')[-2]}): {len(all_listings)} total so far")

            if len(all_listings) >= max_results:
                break

        except Exception as e:
            logger.error(f"GitHub scrape error: {e}")

    logger.info(f"GitHub new grad total: {len(all_listings)}")
    return all_listings[:max_results]


def search_mock(query: str, max_results: int = 8) -> list[JobListing]:
    """Mock listings for testing."""
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
    """Scrape full JD from apply URL. Capped at 8000 chars."""
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
            timeout=10, allow_redirects=True,
        )
        if resp.status_code != 200:
            return ""

        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        for selector in [
            "[class*=description]", ".posting-page",
            "[class*=job-details]", "article", "main", "[role=main]",
        ]:
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
    """Try to scrape full JD for each listing."""
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
# QUERY GENERATORS
# =========================================================================

def generate_serper_queries(
    skills: list[str],
    experience_levels: list[str],
    max_queries: int = 9,
) -> list[str]:
    """
    Generate site-targeted Google queries for Serper.
    These return individual job postings, not aggregator pages.
    """
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

    sites = [
        "site:greenhouse.io",
        "site:lever.co",
        "site:linkedin.com/jobs/view",
    ]

    level = experience_levels[0] if experience_levels else "new grad"

    queries = []
    for cname, _ in active:
        title = title_map.get(cname, "software engineer")
        for site in sites:
            q = f"{title} {level} 2026 {site}"
            queries.append(q)
            if len(queries) >= max_queries:
                break
        if len(queries) >= max_queries:
            break

    return queries


def generate_adzuna_queries(
    skills: list[str],
    base_titles: list[str],
    experience_levels: list[str],
    max_queries: int = 8,
) -> list[str]:
    """Generate generic queries for Adzuna job API."""
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
        for t in base_titles[:1]:
            q = f"{top} {t}"
            if q not in queries:
                queries.append(q)
            if len(queries) >= max_queries:
                break

    return queries


# =========================================================================
# UNIFIED SEARCH
# =========================================================================

def search_all(
    all_skills: list[str],
    base_titles: list[str],
    experience_levels: list[str],
    country: str = "us",
    locations: list[str] | None = None,
    max_results_per_query: int = 10,
    max_days_old: int = 2,
    discovery_priority: list[str] | None = None,
    max_total: int = 50,
) -> list[JobListing]:
    """
    Search with Serper → Adzuna → Mock fallback.
    Serper uses site-targeted queries. Adzuna uses generic queries.
    Deduplicates by company+title.
    """
    if discovery_priority is None:
        discovery_priority = ["serper", "adzuna"]

    all_listings = []
    seen_titles = set()

    def _dedup_add(results: list[JobListing]):
        for listing in results:
            key = f"{listing.company}_{listing.title}".lower().strip()
            if key not in seen_titles:
                seen_titles.add(key)
                all_listings.append(listing)

    for api in discovery_priority:
        if api == "serper":
            queries = generate_serper_queries(
                all_skills, experience_levels, max_queries=9,
            )
            logger.info(f"Serper queries: {queries}")
            for q in queries:
                results = search_serper(q, max_results_per_query)
                _dedup_add(results)
                if len(all_listings) >= max_total:
                    break

        elif api == "adzuna":
            queries = generate_adzuna_queries(
                all_skills, base_titles, experience_levels, max_queries=8,
            )
            logger.info(f"Adzuna queries: {queries}")
            for q in queries:
                loc = locations[0] if locations else ""
                results = search_adzuna(q, country, loc, max_results_per_query, max_days_old)
                _dedup_add(results)
                if len(all_listings) >= max_total:
                    break

        elif api == "github_newgrad":
            results = search_github_newgrad(max_total)
            _dedup_add(results)

        elif api == "mock":
            results = search_mock("", max_results_per_query)
            _dedup_add(results)

        # If we got enough results, stop trying more APIs
        if len(all_listings) >= max_total:
            break

    all_listings = all_listings[:max_total]

    # Log source breakdown
    sources = {}
    for l in all_listings:
        sources[l.source] = sources.get(l.source, 0) + 1
    logger.info(f"Total: {len(all_listings)} jobs ({sources})")

    return all_listings


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    query = " ".join(sys.argv[1:]) or "software engineer new grad"
    print(f"Searching: '{query}'\n")
    results = search_serper(query, 5)
    for i, j in enumerate(results, 1):
        print(f"{i}. [{j.source}] {j.company} — {j.title}")
        print(f"   {j.apply_url}")
        print()

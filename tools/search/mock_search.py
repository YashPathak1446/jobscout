"""
Mock Search - Testing Without API Calls

Generates fake job listings for testing the pipeline.
Zero API calls, deterministic results.

Location: jobscout_v3/tools/search/mock_search.py
"""

import logging
from datetime import datetime, timezone

from .job_listing import JobListing

logger = logging.getLogger(__name__)


def search_mock(query: str = "", max_results: int = 30) -> list[JobListing]:
    """
    Generate mock job listings for testing.
    
    Args:
        query: Search query (ignored, for compatibility)
        max_results: Number of mock jobs to generate
        
    Returns:
        List of fake JobListing objects
        
    Example:
        >>> jobs = search_mock(max_results=10)
        >>> print(f"Generated {len(jobs)} mock jobs")
    """
    mock_companies = [
        ("Stripe", "San Francisco, CA", "https://stripe.com/jobs/listing/123"),
        ("OpenAI", "San Francisco, CA", "https://openai.com/careers/456"),
        ("Databricks", "San Francisco, CA", "https://databricks.com/company/careers/789"),
        ("Snowflake", "San Mateo, CA", "https://careers.snowflake.com/job/012"),
        ("Scale AI", "San Francisco, CA", "https://scale.com/careers/345"),
        ("Anthropic", "San Francisco, CA", "https://anthropic.com/careers/678"),
        ("Anduril", "Costa Mesa, CA", "https://anduril.com/jobs/901"),
        ("Palantir", "Palo Alto, CA", "https://palantir.com/careers/234"),
        ("Figma", "San Francisco, CA", "https://figma.com/careers/567"),
        ("Notion", "San Francisco, CA", "https://notion.so/careers/890"),
        ("Ramp", "New York, NY", "https://ramp.com/careers/111"),
        ("Brex", "San Francisco, CA", "https://brex.com/careers/222"),
        ("Navan", "Palo Alto, CA", "https://navan.com/careers/333"),
        ("Watershed", "San Francisco, CA", "https://watershed.com/careers/444"),
        ("Modal", "San Francisco, CA", "https://modal.com/careers/555"),
    ]
    
    titles = [
        "Software Engineer - New Grad",
        "ML Engineer - New Grad",
        "Backend Engineer - Entry Level",
        "Full Stack Engineer - 2025 Grad",
        "Data Engineer - New Grad",
        "Software Development Engineer - New Grad",
        "Systems Engineer - Entry Level",
        "Infrastructure Engineer - New Grad",
        "Applied Scientist - New Grad",
        "Research Engineer - New Grad",
    ]
    
    descriptions = [
        "We're looking for exceptional new grad software engineers to join our team. You'll work on distributed systems, build scalable infrastructure, and ship features to millions of users.",
        "Join our engineering team as a new grad! You'll collaborate with experienced engineers, contribute to core products, and grow your skills in a fast-paced environment.",
        "Our new grad program offers mentorship, challenging projects, and the opportunity to make an immediate impact. Looking for candidates with strong CS fundamentals.",
        "Seeking new grads passionate about building great products. You'll own projects end-to-end, work with modern tech stacks, and solve hard technical problems.",
        "We're hiring new grad engineers to work on machine learning infrastructure, data pipelines, and scalable systems. Strong coding skills required.",
    ]
    
    listings = []
    
    for i in range(min(max_results, len(mock_companies) * len(titles))):
        company_idx = i % len(mock_companies)
        title_idx = i % len(titles)
        desc_idx = i % len(descriptions)
        
        company, location, url = mock_companies[company_idx]
        title = titles[title_idx]
        description = descriptions[desc_idx]
        
        # Vary salaries
        base_salary = 120000 + (i % 10) * 10000
        
        listings.append(JobListing(
            id=f"mock_{i}",
            title=title,
            company=company,
            location=location,
            description=description,
            apply_url=url,
            salary_min=float(base_salary),
            salary_max=float(base_salary + 30000),
            created=datetime.now(timezone.utc).isoformat(),
            source="mock",
        ))
    
    logger.info(f"Mock: Generated {len(listings)} fake jobs")
    return listings


# CLI for testing
if __name__ == "__main__":
    print("Generating mock job listings...")
    jobs = search_mock(max_results=10)
    
    print(f"\nGenerated {len(jobs)} jobs:")
    for job in jobs:
        print(f"  - {job}")

"""
Search Tools Module

Provides job search functionality from multiple sources:
- Serper (Google search via API)
- Adzuna (job aggregator API)
- GitHub (curated new grad lists)
- Mock (testing without API calls)
"""

from .job_listing import JobListing
from .serper_search import search_serper, build_serper_query
from .adzuna_search import search_adzuna
from .github_search import search_github_newgrad
from .mock_search import search_mock

__all__ = [
    'JobListing',
    'search_serper',
    'search_adzuna',
    'search_github_newgrad',
    'search_mock',
    'build_serper_query',
]

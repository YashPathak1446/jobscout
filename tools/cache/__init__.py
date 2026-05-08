"""
Cache utilities for JobScout V3

Provides:
- Resume embedding cache (saves 25 API calls per run)
- Rate limiting with exponential backoff
- Job cache to avoid re-processing the same job multiple times in a run
"""

from .embedding_cache import EmbeddingCache
from .rate_limiter import retry_with_backoff, RateLimitError

__all__ = ['EmbeddingCache', 'retry_with_backoff', 'RateLimitError', 'JobCache']
"""
Cache utilities for JobScout V3

Provides:
- Resume embedding cache (saves 25 API calls per run)
- Text embedding cache for everything else that gets embedded, chiefly JDs
- Prompt-hash LLM response cache
- Rate limiting with exponential backoff
- Job cache to avoid re-processing the same job multiple times in a run
"""

from .embedding_cache import EmbeddingCache
from .job_cache import JobCache
from .llm_cache import LLMCache
from .rate_limiter import retry_with_backoff, RateLimitError
from .text_embedding_cache import TextEmbeddingCache

__all__ = [
    'EmbeddingCache',
    'JobCache',
    'LLMCache',
    'RateLimitError',
    'TextEmbeddingCache',
    'retry_with_backoff',
]

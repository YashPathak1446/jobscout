"""
Rate Limiter with Exponential Backoff

Handles API rate limits gracefully with:
- Automatic retry with exponential backoff
- Respects Retry-After headers
- Configurable max retries
"""

import time
import random
import logging
from typing import Callable, Any, Optional

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Raised when rate limit exceeded and max retries reached."""
    pass


def retry_with_backoff(
    func: Callable,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: bool = True
) -> Any:
    """
    Retry function with exponential backoff.
    
    Args:
        func: Function to retry
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        jitter: Add random jitter to delay
        
    Returns:
        Function result
        
    Raises:
        RateLimitError: If max retries exceeded
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
            
        except Exception as e:
            error_msg = str(e)
            
            # Check if it's a rate limit error
            is_rate_limit = (
                '429' in error_msg or
                'RESOURCE_EXHAUSTED' in error_msg or
                'quota' in error_msg.lower() or
                'rate limit' in error_msg.lower()
            )
            
            if not is_rate_limit:
                # Not a rate limit error, re-raise
                raise
            
            if attempt == max_retries:
                # Max retries reached
                logger.error(f"❌ Max retries ({max_retries}) exceeded")
                raise RateLimitError(f"Rate limit exceeded after {max_retries} retries") from e
            
            # Calculate delay
            delay = min(base_delay * (2 ** attempt), max_delay)
            
            # Add jitter
            if jitter:
                delay = delay * (0.5 + random.random())
            
            # Check for Retry-After header in error message
            if 'retry in' in error_msg.lower():
                try:
                    # Extract wait time from error message
                    # Example: "Please retry in 26.868412568s"
                    import re
                    match = re.search(r'retry in (\d+\.?\d*)', error_msg.lower())
                    if match:
                        suggested_delay = float(match.group(1))
                        delay = max(delay, suggested_delay)
                except:
                    pass
            
            logger.warning(
                f"⏳ Rate limit hit (attempt {attempt + 1}/{max_retries + 1}). "
                f"Waiting {delay:.1f}s before retry..."
            )
            time.sleep(delay)
    
    # Should never reach here
    raise RateLimitError("Unexpected error in retry logic")


def get_rate_limit_info(error_message: str) -> Optional[dict]:
    """
    Extract rate limit information from error message.
    
    Returns:
        Dict with quota_metric, limit, and retry_delay if available
    """
    try:
        import re
        
        info = {}
        
        # Extract quota metric
        metric_match = re.search(r"quotaMetric['\"]:\s*['\"]([^'\"]+)", error_message)
        if metric_match:
            info['quota_metric'] = metric_match.group(1)
        
        # Extract limit
        limit_match = re.search(r"limit['\"]?:\s*(\d+)", error_message)
        if limit_match:
            info['limit'] = int(limit_match.group(1))
        
        # Extract retry delay
        retry_match = re.search(r'retry in (\d+\.?\d*)', error_message.lower())
        if retry_match:
            info['retry_delay'] = float(retry_match.group(1))
        
        return info if info else None
        
    except Exception as e:
        logger.debug(f"Failed to parse rate limit info: {e}")
        return None
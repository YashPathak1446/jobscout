"""
Model Fallback — Tries the primary model, falls back on rate limits.

Wraps Gemini API calls with automatic retry using a fallback model
when the primary model returns a 429 (rate limit) error.

Production pattern: model routing with graceful degradation.
"""

import time
import logging
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)


class ModelRouter:
    """
    Routes LLM calls with automatic fallback.

    Usage:
        router = ModelRouter("gemini-3-flash-preview", "gemini-2.5-flash")
        model = router.get_model()  # Returns primary or fallback
    """

    def __init__(
        self,
        primary_model: str,
        fallback_model: str,
        max_retries: int = 2,
        retry_delay: float = 5.0,
    ):
        self.primary_model = primary_model
        self.fallback_model = fallback_model
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Track which model is currently active
        self._active_model = primary_model
        self._primary_failures = 0
        self._fallback_failures = 0
        self._total_calls = 0
        self._fallback_calls = 0

    @property
    def active_model(self) -> str:
        """Currently active model string."""
        return self._active_model

    def get_model(self) -> str:
        """
        Get the current best model to use.

        Returns primary if available, fallback if primary has been
        rate-limited recently.
        """
        return self._active_model

    def report_success(self, model: str) -> None:
        """Report a successful API call."""
        self._total_calls += 1
        if model == self.fallback_model:
            self._fallback_calls += 1
        logger.debug(f"Model {model}: success (total: {self._total_calls})")

    def report_rate_limit(self, model: str) -> str | None:
        """
        Report a rate limit error. Returns the fallback model to try,
        or None if all models are exhausted.
        """
        if model == self.primary_model:
            self._primary_failures += 1
            self._active_model = self.fallback_model
            logger.warning(
                f"Primary model {self.primary_model} rate-limited "
                f"(failures: {self._primary_failures}). "
                f"Switching to {self.fallback_model}."
            )
            return self.fallback_model

        elif model == self.fallback_model:
            self._fallback_failures += 1
            logger.error(
                f"Fallback model {self.fallback_model} also rate-limited. "
                f"Waiting {self.retry_delay}s before retry."
            )
            time.sleep(self.retry_delay)
            # Try primary again after a delay
            self._active_model = self.primary_model
            return self.primary_model

        return None

    def report_error(self, model: str, error: Exception) -> None:
        """Report a non-rate-limit error."""
        logger.error(f"Model {model}: error - {error}")

    def reset_to_primary(self) -> None:
        """Reset to primary model (e.g., after a delay between runs)."""
        self._active_model = self.primary_model

    def get_stats(self) -> dict:
        """Get usage statistics."""
        return {
            "total_calls": self._total_calls,
            "fallback_calls": self._fallback_calls,
            "primary_failures": self._primary_failures,
            "fallback_failures": self._fallback_failures,
            "active_model": self._active_model,
            "fallback_rate": (
                f"{self._fallback_calls / self._total_calls:.1%}"
                if self._total_calls > 0
                else "0%"
            ),
        }


def is_rate_limit_error(error: Exception) -> bool:
    """
    Check if an exception is a rate limit error.
    Handles various error formats from Google's API.
    """
    error_str = str(error).lower()
    return any(
        indicator in error_str
        for indicator in [
            "429",
            "rate limit",
            "resource_exhausted",
            "quota exceeded",
            "too many requests",
        ]
    )


# === Convenience: create a global router from config ===
_global_router: ModelRouter | None = None


def get_router() -> ModelRouter:
    """Get or create the global ModelRouter from config."""
    global _global_router
    if _global_router is None:
        try:
            import config
            _global_router = ModelRouter(
                primary_model=config.MODEL,
                fallback_model=config.FALLBACK_MODEL,
            )
        except ImportError:
            # Default fallback if config isn't available
            _global_router = ModelRouter(
                primary_model="gemini-3-flash-preview",
                fallback_model="gemini-2.5-flash",
            )
    return _global_router


# === CLI for testing ===
if __name__ == "__main__":
    router = get_router()
    print(f"Primary: {router.primary_model}")
    print(f"Fallback: {router.fallback_model}")
    print(f"Active: {router.get_model()}")

    # Simulate a rate limit
    print("\nSimulating rate limit on primary...")
    fallback = router.report_rate_limit(router.primary_model)
    print(f"Switched to: {fallback}")
    print(f"Active: {router.get_model()}")

    # Simulate success on fallback
    router.report_success(fallback)
    print(f"\nStats: {router.get_stats()}")

"""
Job Cache

Provides two caching functions in a single persistent store:

1. URL deduplication across runs
   - Tracks which job URLs have been seen before
   - Prevents the same jobs from appearing in every run
   - Can be cleared to rediscover jobs after N days

2. Scrape result caching
   - Stores the full_jd for each URL after scraping
   - On subsequent runs, returns cached JD instead of re-scraping
   - Invalidated per-URL after max_age_hours

Location: jobscout_v3/tools/cache/job_cache.py
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = "cache"
DEFAULT_JD_MAX_AGE_HOURS = 72       # Re-scrape JDs older than 3 days
DEFAULT_URL_MAX_AGE_HOURS = 24 * 7  # Re-show jobs after 7 days


class JobCache:
    """
    Persistent cache for job URLs and scraped JDs.

    Structure of cache/job_cache.json:
    {
        "seen_urls": {
            "https://...": {
                "first_seen": "2026-05-05T...",
                "title": "Software Engineer",
                "company": "Stripe"
            },
            ...
        },
        "scraped_jds": {
            "https://...": {
                "scraped_at": "2026-05-05T...",
                "full_jd": "...",
                "requirements": {...},
                "scraper_used": "greenhouse"
            },
            ...
        }
    }
    """

    def __init__(
        self,
        cache_dir: str = DEFAULT_CACHE_DIR,
        jd_max_age_hours: int = DEFAULT_JD_MAX_AGE_HOURS,
        url_max_age_hours: int = DEFAULT_URL_MAX_AGE_HOURS,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "job_cache.json"
        self.jd_max_age_hours = jd_max_age_hours
        self.url_max_age_hours = url_max_age_hours

        self._data = self._load()

    # =========================================================================
    # URL DEDUPLICATION
    # =========================================================================

    def is_seen(self, url: str) -> bool:
        """
        Return True if this URL was seen in a recent run.

        URLs older than url_max_age_hours are treated as unseen
        so jobs can resurface after they expire.
        """
        entry = self._data["seen_urls"].get(url)
        if not entry:
            return False

        first_seen = _parse_dt(entry.get("first_seen", ""))
        if not first_seen:
            return False

        age = datetime.now(timezone.utc) - first_seen
        if age > timedelta(hours=self.url_max_age_hours):
            # Expired — treat as unseen
            return False

        return True

    def mark_seen(self, url: str, title: str = "", company: str = "") -> None:
        """Record a URL as seen."""
        self._data["seen_urls"][url] = {
            "first_seen": _now_iso(),
            "title": title,
            "company": company,
        }

    def filter_new_jobs(self, jobs: List) -> List:
        """
        Filter a list of JobListing objects, returning only unseen ones.

        Also marks all returned jobs as seen immediately so subsequent
        calls in the same run don't return duplicates.
        """
        new_jobs = []
        skipped = 0

        for job in jobs:
            url = job.apply_url if hasattr(job, 'apply_url') else job.get('apply_url', '')
            if self.is_seen(url):
                skipped += 1
                continue
            self.mark_seen(url, getattr(job, 'title', ''), getattr(job, 'company', ''))
            new_jobs.append(job)

        if skipped:
            logger.info(f"   📦 Job cache: skipped {skipped} previously seen jobs")

        return new_jobs

    # =========================================================================
    # SCRAPE RESULT CACHING
    # =========================================================================

    def get_jd(self, url: str) -> Optional[Dict]:
        """
        Return cached scrape result for a URL if it's still fresh.

        Returns None if not cached or if older than jd_max_age_hours.
        """
        entry = self._data["scraped_jds"].get(url)
        if not entry:
            return None

        scraped_at = _parse_dt(entry.get("scraped_at", ""))
        if not scraped_at:
            return None

        age = datetime.now(timezone.utc) - scraped_at
        if age > timedelta(hours=self.jd_max_age_hours):
            # Stale — re-scrape
            logger.debug(f"   📦 JD cache stale for {url[:60]}")
            return None

        logger.info(f"   📦 JD cache hit ({int(age.total_seconds() / 3600)}h old)")
        return entry

    def save_jd(self, url: str, scrape_result: Dict) -> None:
        """Cache a scrape result for a URL."""
        self._data["scraped_jds"][url] = {
            "scraped_at": _now_iso(),
            "full_jd": scrape_result.get("full_jd", ""),
            "requirements": scrape_result.get("requirements", {}),
            "scraper_used": scrape_result.get("scraper_used", "unknown"),
        }

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    def save(self) -> None:
        """Persist cache to disk."""
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(self._data, f, indent=2)
        logger.debug(f"💾 Job cache saved ({len(self._data['seen_urls'])} URLs, "
                    f"{len(self._data['scraped_jds'])} JDs)")

    def stats(self) -> Dict:
        """Return cache statistics."""
        return {
            "seen_urls": len(self._data["seen_urls"]),
            "scraped_jds": len(self._data["scraped_jds"]),
            "cache_file": str(self.cache_file),
        }

    def clear_seen_urls(self) -> None:
        """Clear URL deduplication history (allows rediscovery of all jobs)."""
        count = len(self._data["seen_urls"])
        self._data["seen_urls"] = {}
        self.save()
        logger.info(f"🗑️  Cleared {count} seen URLs from job cache")

    def clear_jd_cache(self) -> None:
        """Clear scrape result cache (forces re-scraping on next run)."""
        count = len(self._data["scraped_jds"])
        self._data["scraped_jds"] = {}
        self.save()
        logger.info(f"🗑️  Cleared {count} cached JDs")

    # =========================================================================
    # INTERNAL
    # =========================================================================

    def _load(self) -> Dict:
        """Load cache from disk, or return empty structure."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # Ensure both keys exist (handles old cache files)
                data.setdefault("seen_urls", {})
                data.setdefault("scraped_jds", {})
                logger.debug(
                    f"📦 Loaded job cache: {len(data['seen_urls'])} URLs, "
                    f"{len(data['scraped_jds'])} JDs"
                )
                return data
            except Exception as e:
                logger.warning(f"⚠️  Job cache corrupted, starting fresh: {e}")

        return {"seen_urls": {}, "scraped_jds": {}}


# =========================================================================
# HELPERS
# =========================================================================

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None
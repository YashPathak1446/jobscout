"""
GitHub New Grad Job Lists

Scrapes curated new grad job lists from GitHub repositories.
These are manually verified entry-level US positions, updated daily.

Sources:
- jobright-ai/2026-Software-Engineer-New-Grad
- speedyapply/2026-AI-College-Jobs

Location: jobscout_v3/tools/search/github_search.py
"""

import re
import logging
from datetime import datetime, timezone, timedelta

import requests

from .job_listing import JobListing

logger = logging.getLogger(__name__)


# When one employer posts several roles, these tables put the name in the
# first row and a continuation glyph in the rows beneath it. Read literally,
# the glyph becomes the company: it reaches the summary as "**↳** - Software
# Engineer" and the output filename as an empty slot
# ("Yash_Pathak__Software_Engineer_New.tex").
_CONTINUATION_MARKERS = {
    "↳",      # U+21B3, used by jobright-ai and speedyapply
    "⤷",      # U+2937, seen in forks of the same tables
    "\"",     # ditto mark
    "''",
    "same",
    "same as above",
}


def _is_continuation(cell: str) -> bool:
    """True when a company cell means "same employer as the row above"."""
    return cell.strip().strip('*').strip().lower() in _CONTINUATION_MARKERS


def search_github_newgrad(max_results: int = 50) -> list[JobListing]:
    """
    Scrape curated new grad job lists from GitHub repos.

    These repos are manually maintained with verified:
    - Entry-level/new grad positions
    - US-based locations (or remote)
    - Active job postings

    The markdown tables include a posting-age column (e.g. "0d", "1d", "5d",
    or "2 days ago"). We parse that into a numeric `days_since_posted` and
    encode it into the JobListing's `created` field as an ISO timestamp so
    downstream ranking can prefer recent jobs.

    Args:
        max_results: Maximum number of jobs to return

    Returns:
        List of JobListing objects
    """
    sources = [
        "https://raw.githubusercontent.com/jobright-ai/2026-Software-Engineer-New-Grad/master/README.md",
        "https://raw.githubusercontent.com/speedyapply/2026-AI-College-Jobs/main/NEW_GRAD_USA.md",
    ]

    all_listings = []
    seen = set()

    now_utc = datetime.now(timezone.utc)

    for source_url in sources:
        try:
            resp = requests.get(
                source_url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=15,
            )

            if resp.status_code != 200:
                logger.warning(f"GitHub returned {resp.status_code}: {source_url}")
                continue

            content = resp.text

            # Parse markdown table rows. Capture everything from the location
            # column to end-of-line so we can sniff out the "posted X ago" cell.
            # Rows look like: | **[Company](url)** | **[Title](apply_url)** | Location | Posted | ... |
            table_row = re.compile(
                r'^\|\s*\*?\*?\[?([^\]|]+)\]?\(?([^)]*)\)?\*?\*?\s*\|'  # Company
                r'\s*\*?\*?\[([^\]]+)\]\(([^)]+)\)\*?\*?\s*\|'          # Title (linked)
                r'\s*([^|]*)\|'                                          # Location
                r'(.*)$',                                                # Rest of row (incl. posted col)
                re.MULTILINE
            )

            # Continuation glyphs refer to the row above *in this table*, so
            # this resets per source and is updated before any skip below —
            # a row we filter out (wrong country, say) still establishes the
            # employer for the rows that follow it.
            last_company = None

            for match in table_row.finditer(content):
                company = match.group(1).strip().strip('*').strip()
                title = match.group(3).strip().strip('*').strip()
                apply_url = match.group(4).strip()
                location = match.group(5).strip()
                rest_of_row = match.group(6) or ""

                # Resolve "same as the row above" before anything else reads
                # the company — dedup, filtering and the JobListing all use it.
                if _is_continuation(company):
                    if not last_company:
                        # A continuation with nothing above it to inherit from.
                        # Better to drop the row than emit a glyph as an employer.
                        logger.debug(f"Continuation row with no preceding company: {title}")
                        continue
                    company = last_company
                elif company and company.lower() not in ("company", "employer"):
                    last_company = company

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

                # Deduplicate. Location is part of the key because resolving
                # continuation glyphs made company::title collide for real,
                # distinct postings — one employer listing the same role in
                # two cities used to differ only by the unresolved glyph.
                # Location still dedups the same posting across both source
                # repos, which is what this set is for.
                key = f"{company}::{title}::{location}".lower()
                if key in seen:
                    continue
                seen.add(key)

                # Extract the posting age from the remaining cells.
                # Common formats in these repos: "0d", "1d", "5d", "2 days ago",
                # "1 month ago", or sometimes a calendar date.
                days_ago = _parse_days_ago(rest_of_row)
                if days_ago is None:
                    posted_iso = now_utc.isoformat()
                else:
                    posted_iso = (now_utc - timedelta(days=days_ago)).isoformat()

                source_tag = "swe" if "jobright" in source_url else "ai"
                all_listings.append(JobListing(
                    id=f"github_{source_tag}_{hash(apply_url) % 100000}",
                    title=title,
                    company=company,
                    location=location,
                    description=f"{title} at {company}",  # GitHub tables don't have descriptions
                    apply_url=apply_url,
                    salary_min=None,
                    salary_max=None,
                    created=posted_iso,
                    source="github_newgrad",
                ))

        except requests.exceptions.RequestException as e:
            logger.error(f"GitHub scrape error: {e}")
            continue

    logger.info(f"GitHub: {len(all_listings)} new grad jobs")
    return all_listings[:max_results]


# Match formats like "0d", "1d", "12d" (with optional whitespace, leading pipes)
_DAYS_SHORT_RE = re.compile(r'\b(\d{1,3})\s*d\b', re.IGNORECASE)
# Match "X day ago", "X days ago"
_DAYS_AGO_RE = re.compile(r'\b(\d{1,3})\s*days?\s*ago\b', re.IGNORECASE)
# Match "X month ago", "X months ago" (convert to days at 30/mo)
_MONTHS_AGO_RE = re.compile(r'\b(\d{1,3})\s*months?\s*ago\b', re.IGNORECASE)


def _parse_days_ago(text: str) -> int | None:
    """
    Extract how many days ago a job was posted from a fragment of markdown.

    The GitHub repo formats vary: "0d", "5d", "2 days ago", "1 month ago".
    Returns days as an int, or None if no recognizable age was found.

    Designed to be tolerant — these repos sometimes change their layout
    without warning, and falling back to "now" is better than crashing.
    """
    if not text:
        return None

    # "1 month ago" / "3 months ago" — check first because "5d" could otherwise
    # confuse with stray digits inside other cells
    m = _MONTHS_AGO_RE.search(text)
    if m:
        return int(m.group(1)) * 30

    # "5 days ago"
    m = _DAYS_AGO_RE.search(text)
    if m:
        return int(m.group(1))

    # "0d", "1d", "12d"
    m = _DAYS_SHORT_RE.search(text)
    if m:
        return int(m.group(1))

    return None


# CLI for testing
if __name__ == "__main__":
    print("Scraping GitHub new grad job repos...")
    jobs = search_github_newgrad(max_results=30)
    
    print(f"\nFound {len(jobs)} jobs:")
    for job in jobs[:15]:
        print(f"  - {job}")
    
    print(f"\n... and {len(jobs) - 15} more")

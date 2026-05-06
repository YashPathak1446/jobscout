"""
Job Description Scraper

Scrapes full job descriptions from ATS systems.

Supported:
- Greenhouse  (boards.greenhouse.io) — JSON API
- Lever       (jobs.lever.co)        — JSON API
- Ashby       (jobs.ashbyhq.com)     — JSON API
- Workday     (myworkdayjobs.com)    — HTML
- LinkedIn    (linkedin.com/jobs)    — HTML
- Generic     (any URL)              — BeautifulSoup HTML fallback

Flow:
1. Follow redirect (jobright.ai → real ATS URL)
2. Detect ATS from final URL
3. Use appropriate scraper
4. Extract requirements from full JD text
5. Return structured result

Location: jobscout_v3/tools/scraping/jd_scraper.py
"""

import re
import json
import logging
import time
from typing import Dict, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# HTTP session (shared across scrapes)
# ─────────────────────────────────────────────
_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})

TIMEOUT = 15
MIN_JD_LENGTH = 200  # Minimum chars to consider a scrape successful


def scrape_jd(apply_url: str, job_title: str = "", company: str = "") -> Dict:
    """
    Scrape a full job description from any ATS URL.

    Args:
        apply_url: URL to the job posting (may be a redirect)
        job_title: Job title (used for fallback context)
        company: Company name (used for fallback context)

    Returns:
        Dict with keys:
            full_jd: str — full job description text
            requirements: dict — structured must/nice-to-have
            scraped_successfully: bool
            scraper_used: str — which scraper succeeded
            final_url: str — URL after following redirects
    """
    result = _empty_result()

    if not apply_url:
        logger.warning("No URL provided")
        return result

    try:
        # Step 1: Follow redirects to get real ATS URL
        final_url = _resolve_url(apply_url)
        result["final_url"] = final_url
        logger.debug(f"   Resolved URL: {final_url}")

        # Step 2: Detect ATS and scrape
        jd_text, scraper_used = _dispatch(final_url)

        if jd_text and len(jd_text) >= MIN_JD_LENGTH:
            result["full_jd"] = jd_text
            result["requirements"] = extract_requirements(jd_text)
            result["scraped_successfully"] = True
            result["scraper_used"] = scraper_used
        else:
            logger.warning(f"   ⚠️  JD too short ({len(jd_text or '')} chars) from {scraper_used}")

    except Exception as e:
        logger.error(f"   ❌ Scrape error for {apply_url}: {e}")

    return result


# ─────────────────────────────────────────────
# URL resolution
# ─────────────────────────────────────────────

def _resolve_url(url: str) -> str:
    """Follow redirects and return the final URL."""
    try:
        resp = _SESSION.head(url, timeout=TIMEOUT, allow_redirects=True)
        return resp.url
    except Exception:
        try:
            resp = _SESSION.get(url, timeout=TIMEOUT, allow_redirects=True, stream=True)
            resp.close()
            return resp.url
        except Exception:
            return url  # Return original if we can't resolve


# ─────────────────────────────────────────────
# ATS dispatch
# ─────────────────────────────────────────────

def _dispatch(url: str):
    """Route to the appropriate scraper based on URL."""
    url_lower = url.lower()

    if "greenhouse.io" in url_lower or "greenhouse.io" in url_lower:
        return _scrape_greenhouse(url), "greenhouse"

    if "lever.co" in url_lower:
        return _scrape_lever(url), "lever"

    if "ashbyhq.com" in url_lower or "app.ashby.com" in url_lower:
        return _scrape_ashby(url), "ashby"

    if "myworkdayjobs.com" in url_lower or "workday.com" in url_lower:
        return _scrape_workday(url), "workday"

    if "linkedin.com/jobs" in url_lower:
        return _scrape_linkedin(url), "linkedin"

    if "jobright.ai" in url_lower:
        return _scrape_jobright(url), "jobright"

    # Generic fallback
    return _scrape_generic(url), "generic"


# ─────────────────────────────────────────────
# Greenhouse
# ─────────────────────────────────────────────

def _scrape_greenhouse(url: str) -> str:
    """
    Greenhouse jobs have a public JSON API:
    boards-api.greenhouse.io/v1/boards/{company}/jobs/{id}
    """
    # Extract company slug and job ID from URL
    # Patterns:
    #   boards.greenhouse.io/company/jobs/12345
    #   job-boards.greenhouse.io/company/jobs/12345
    match = re.search(
        r'greenhouse\.io/([^/]+)/jobs/(\d+)',
        url,
        re.IGNORECASE,
    )

    if match:
        company_slug = match.group(1)
        job_id = match.group(2)
        api_url = (
            f"https://boards-api.greenhouse.io/v1/boards"
            f"/{company_slug}/jobs/{job_id}"
        )
        try:
            resp = _SESSION.get(api_url, timeout=TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                content = data.get("content", "")
                title = data.get("title", "")

                # content is HTML — extract text
                soup = BeautifulSoup(content, "html.parser")
                text = soup.get_text(separator="\n", strip=True)
                if title:
                    text = f"{title}\n\n{text}"
                return _clean_text(text)
        except Exception as e:
            logger.debug(f"Greenhouse API failed: {e}")

    # Fall back to generic HTML scraping
    return _scrape_generic(url)


# ─────────────────────────────────────────────
# Lever
# ─────────────────────────────────────────────

def _scrape_lever(url: str) -> str:
    """
    Lever jobs have a public JSON API:
    api.lever.co/v0/postings/{company}/{id}
    """
    # Pattern: jobs.lever.co/company/uuid
    match = re.search(
        r'lever\.co/([^/]+)/([a-f0-9-]{36})',
        url,
        re.IGNORECASE,
    )

    if match:
        company_slug = match.group(1)
        job_id = match.group(2)
        api_url = f"https://api.lever.co/v0/postings/{company_slug}/{job_id}"
        try:
            resp = _SESSION.get(api_url, timeout=TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                parts = []

                if data.get("text"):
                    parts.append(data["text"])  # Job title

                if data.get("descriptionPlain"):
                    parts.append(data["descriptionPlain"])
                elif data.get("description"):
                    soup = BeautifulSoup(data["description"], "html.parser")
                    parts.append(soup.get_text(separator="\n", strip=True))

                for list_item in data.get("lists", []):
                    if list_item.get("text"):
                        parts.append(f"\n{list_item['text']}")
                    if list_item.get("content"):
                        soup = BeautifulSoup(list_item["content"], "html.parser")
                        parts.append(soup.get_text(separator="\n", strip=True))

                if data.get("additionalPlain"):
                    parts.append(data["additionalPlain"])

                return _clean_text("\n\n".join(parts))
        except Exception as e:
            logger.debug(f"Lever API failed: {e}")

    return _scrape_generic(url)


# ─────────────────────────────────────────────
# Ashby
# ─────────────────────────────────────────────

def _scrape_ashby(url: str) -> str:
    """
    Ashby has a GraphQL API but also renders job content in HTML.
    Try HTML scraping first since GraphQL requires auth.
    """
    try:
        resp = _SESSION.get(url, timeout=TIMEOUT)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")

            # Ashby renders job content in a div with specific classes
            content_selectors = [
                "div[class*='job-description']",
                "div[class*='posting-description']",
                "div[class*='description']",
                "main",
            ]

            for selector in content_selectors:
                el = soup.select_one(selector)
                if el:
                    text = el.get_text(separator="\n", strip=True)
                    if len(text) >= MIN_JD_LENGTH:
                        return _clean_text(text)

            # Fallback: try to extract from JSON in page
            script = soup.find("script", {"id": "__NEXT_DATA__"})
            if script:
                try:
                    data = json.loads(script.string)
                    # Navigate the Next.js data structure
                    props = data.get("props", {}).get("pageProps", {})
                    job = props.get("job", props.get("posting", {}))
                    description = (
                        job.get("descriptionHtml")
                        or job.get("description")
                        or ""
                    )
                    if description:
                        soup2 = BeautifulSoup(description, "html.parser")
                        return _clean_text(soup2.get_text(separator="\n", strip=True))
                except Exception:
                    pass

    except Exception as e:
        logger.debug(f"Ashby scrape failed: {e}")

    return _scrape_generic(url)


# ─────────────────────────────────────────────
# Workday
# ─────────────────────────────────────────────

def _scrape_workday(url: str) -> str:
    """
    Workday renders job descriptions in JavaScript-heavy pages.
    Try to extract from the HTML directly.
    """
    try:
        resp = _SESSION.get(url, timeout=TIMEOUT)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")

            # Workday job content
            selectors = [
                "div[data-automation-id='jobPostingDescription']",
                "div[class*='css-'][class*='job']",
                "section[class*='description']",
                "div[class*='jobDescription']",
            ]

            for selector in selectors:
                el = soup.select_one(selector)
                if el:
                    text = el.get_text(separator="\n", strip=True)
                    if len(text) >= MIN_JD_LENGTH:
                        return _clean_text(text)

            # Try JSON-LD structured data
            json_ld = soup.find("script", {"type": "application/ld+json"})
            if json_ld:
                try:
                    data = json.loads(json_ld.string)
                    description = data.get("description", "")
                    if description and len(description) >= MIN_JD_LENGTH:
                        soup2 = BeautifulSoup(description, "html.parser")
                        return _clean_text(soup2.get_text(separator="\n", strip=True))
                except Exception:
                    pass

    except Exception as e:
        logger.debug(f"Workday scrape failed: {e}")

    return _scrape_generic(url)


# ─────────────────────────────────────────────
# LinkedIn
# ─────────────────────────────────────────────

def _scrape_linkedin(url: str) -> str:
    """
    LinkedIn blocks most scraping. Try anyway, fall back to generic.
    Note: LinkedIn requires login for many job postings.
    """
    try:
        # LinkedIn job ID from URL
        match = re.search(r'/jobs/view/(\d+)', url)
        if match:
            job_id = match.group(1)
            # Try the guest API endpoint
            api_url = (
                f"https://www.linkedin.com/jobs-guest/jobs/api"
                f"/jobPosting/{job_id}"
            )
            resp = _SESSION.get(api_url, timeout=TIMEOUT)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                # Extract from the job description section
                desc = soup.find("div", {"class": "description__text"})
                if desc:
                    text = desc.get_text(separator="\n", strip=True)
                    if len(text) >= MIN_JD_LENGTH:
                        return _clean_text(text)

        return _scrape_generic(url)

    except Exception as e:
        logger.debug(f"LinkedIn scrape failed: {e}")
        return _scrape_generic(url)


# ─────────────────────────────────────────────
# Jobright.ai
# ─────────────────────────────────────────────

def _scrape_jobright(url: str) -> str:
    """
    Try to extract JD content from jobright.ai job page.
    Jobright renders job data in Next.js page props.
    """
    try:
        resp = _SESSION.get(url, timeout=TIMEOUT)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")

            # Try Next.js __NEXT_DATA__ JSON
            script = soup.find("script", {"id": "__NEXT_DATA__"})
            if script:
                try:
                    data = json.loads(script.string)
                    props = data.get("props", {}).get("pageProps", {})
                    job = props.get("job", props.get("jobPost", {}))
                    description = (
                        job.get("description")
                        or job.get("jobDescription")
                        or job.get("content")
                        or ""
                    )
                    if description and len(description) >= MIN_JD_LENGTH:
                        soup2 = BeautifulSoup(description, "html.parser")
                        return _clean_text(soup2.get_text(separator="\n", strip=True))
                except Exception:
                    pass

            # Try generic content extraction
            return _scrape_generic(url)

    except Exception as e:
        logger.debug(f"Jobright scrape failed: {e}")

    return ""


# ─────────────────────────────────────────────
# Generic HTML scraper
# ─────────────────────────────────────────────

def _scrape_generic(url: str) -> str:
    """
    Generic HTML scraper using BeautifulSoup.

    Tries multiple content selectors in priority order.
    Strips navigation, headers, footers, and boilerplate.
    """
    try:
        resp = _SESSION.get(url, timeout=TIMEOUT)
        if resp.status_code != 200:
            logger.debug(f"Generic scraper got {resp.status_code} for {url}")
            return ""

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove boilerplate elements
        for tag in soup(["nav", "header", "footer", "script", "style",
                         "noscript", "iframe", "img", "svg"]):
            tag.decompose()

        # Try content selectors in priority order
        selectors = [
            # Semantic
            "article",
            "main",
            # Common job posting patterns
            "[class*='job-description']",
            "[class*='jobDescription']",
            "[class*='job_description']",
            "[class*='posting']",
            "[class*='description']",
            "[class*='content']",
            "[id*='job-description']",
            "[id*='jobDescription']",
            "[id*='description']",
            # JSON-LD
        ]

        # Try JSON-LD structured data first (most reliable)
        json_ld = soup.find("script", {"type": "application/ld+json"})
        if json_ld:
            try:
                data = json.loads(json_ld.string)
                # Handle both single object and list
                if isinstance(data, list):
                    data = data[0]
                description = data.get("description", "")
                if description and len(description) >= MIN_JD_LENGTH:
                    soup2 = BeautifulSoup(description, "html.parser")
                    return _clean_text(soup2.get_text(separator="\n", strip=True))
            except Exception:
                pass

        # Try CSS selectors
        for selector in selectors:
            try:
                el = soup.select_one(selector)
                if el:
                    text = el.get_text(separator="\n", strip=True)
                    if len(text) >= MIN_JD_LENGTH:
                        return _clean_text(text)
            except Exception:
                continue

        # Last resort: body text
        body = soup.find("body")
        if body:
            text = body.get_text(separator="\n", strip=True)
            if len(text) >= MIN_JD_LENGTH:
                return _clean_text(text[:8000])  # Cap at 8K chars

        return ""

    except Exception as e:
        logger.debug(f"Generic scraper error: {e}")
        return ""


# ─────────────────────────────────────────────
# Requirements extraction
# ─────────────────────────────────────────────

def extract_requirements(jd_text: str) -> Dict:
    """
    Extract structured requirements from JD text.

    Looks for must-have and nice-to-have sections using
    common section headers found in job postings.

    Args:
        jd_text: Full job description text

    Returns:
        Dict with must_have, nice_to_have, education, experience_years
    """
    requirements = {
        "must_have": [],
        "nice_to_have": [],
        "education": [],
        "experience_years": "",
    }

    lines = jd_text.split("\n")

    # Section detection
    MUST_HAVE_HEADERS = [
        "requirements", "required", "qualifications", "what you need",
        "what we're looking for", "must have", "basic qualifications",
        "minimum qualifications", "you have", "you'll need",
        "what you'll bring", "your background",
    ]

    NICE_TO_HAVE_HEADERS = [
        "nice to have", "preferred", "bonus", "plus", "ideally",
        "nice-to-have", "additional qualifications", "preferred qualifications",
        "what would be nice", "not required but", "advantageous",
    ]

    EDUCATION_PATTERNS = [
        r"bachelor'?s? degree",
        r"master'?s? degree",
        r"phd|doctorate",
        r"bs/ms",
        r"b\.s\.",
        r"m\.s\.",
        r"computer science",
        r"engineering degree",
    ]

    EXPERIENCE_PATTERNS = [
        r"(\d+)\+?\s*(?:to\s*\d+)?\s*years?",
        r"(\d+)-(\d+)\s*years?",
    ]

    current_section = "must_have"
    bullet_chars = {"-", "•", "·", "✓", "▪", "*", "◦"}

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        line_lower = line_stripped.lower()

        # Detect section changes
        if any(h in line_lower for h in MUST_HAVE_HEADERS):
            current_section = "must_have"
            continue
        if any(h in line_lower for h in NICE_TO_HAVE_HEADERS):
            current_section = "nice_to_have"
            continue

        # Extract bullet points
        if line_stripped and (line_stripped[0] in bullet_chars or
                              re.match(r"^\d+\.", line_stripped)):
            text = line_stripped.lstrip("".join(bullet_chars)).strip()
            text = re.sub(r"^\d+\.\s*", "", text)

            if not text or len(text) < 10:
                continue

            # Check for education
            if any(re.search(p, text, re.IGNORECASE) for p in EDUCATION_PATTERNS):
                requirements["education"].append(text)

            # Check for experience years
            for pattern in EXPERIENCE_PATTERNS:
                match = re.search(pattern, text, re.IGNORECASE)
                if match and not requirements["experience_years"]:
                    requirements["experience_years"] = match.group(0)

            # Add to current section (cap at 10 items each)
            if len(requirements[current_section]) < 10:
                requirements[current_section].append(text)

    return requirements


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _clean_text(text: str) -> str:
    """Clean extracted text: normalize whitespace, remove excess blank lines."""
    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Remove excess blank lines (max 2 consecutive)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Remove trailing whitespace per line
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines).strip()
    # Cap at 8K chars — enough for any JD, avoids token waste
    return text[:8000]


def _empty_result() -> Dict:
    return {
        "full_jd": "",
        "requirements": {
            "must_have": [],
            "nice_to_have": [],
            "education": [],
            "experience_years": "",
        },
        "scraped_successfully": False,
        "scraper_used": "none",
        "final_url": "",
    }
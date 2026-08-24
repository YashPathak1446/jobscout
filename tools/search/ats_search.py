"""
Keyless job discovery from ATS boards.

Every source this project had before was either narrow or keyed.
`github_newgrad` needs no key but is new-grad only by construction, and Serper
and Adzuna generalise to any level but cost a key. That left no way to find,
say, a mid-level backend role without paying for search.

Greenhouse, Lever, Ashby, Workable and SmartRecruiters all serve their
customers' job boards as public JSON with no authentication. One request to Greenhouse returns Stripe's 578
open roles across every department and level — so seniority stops being a
property of the *source* and becomes a filter applied afterwards, which is
what makes non-new-grad discovery possible without a key.

Two further gains over the existing sources:

- **The JD comes with the job.** Greenhouse honours `?content=true` and Ashby
  returns `descriptionPlain`, so discovery and enrichment collapse into one
  call. Enrichment's per-JD scraping is the slowest and most breakable stage
  in the pipeline, and ATS-sourced jobs skip it entirely.
- **It is first-party data.** No markdown tables to parse, no continuation
  glyphs (R13), no redirect shims.

They cover different segments, which is the point of carrying five rather
than one: Greenhouse and Ashby are where venture-backed startups post,
SmartRecruiters is where enterprises do — Bosch alone lists nearly five
thousand roles — and Workable covers small and European employers neither of
the others reach. Breezy was evaluated and dropped: one live board, three jobs.

The catch is that none of these APIs can enumerate companies — you must know
the slug. `data/ats_companies.json` seeds it, and `harvest_slugs()` grows it
from any apply URL that lands on one of these hosts.

Location: jobscout_v3/tools/search/ats_search.py
"""

import json
import logging
import random
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .job_listing import JobListing

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent.parent
COMPANIES_FILE = ROOT / "data" / "ats_companies.json"

USER_AGENT = "jobscout/1.0 (+https://github.com/YashPathak1446/jobscout)"
TIMEOUT_SECONDS = 25

# Apply-URL patterns that reveal which board a company uses. Used by
# harvest_slugs() so the seed list grows from whatever the keyed sources find.
SLUG_PATTERNS = {
    "greenhouse": re.compile(r"(?:boards|job-boards)\.greenhouse\.io/([a-z0-9_-]+)", re.I),
    "lever": re.compile(r"jobs\.lever\.co/([a-z0-9_-]+)", re.I),
    "ashby": re.compile(r"jobs\.ashbyhq\.com/([a-z0-9_-]+)", re.I),
    "workable": re.compile(r"apply\.workable\.com/([a-z0-9_-]+)", re.I),
    "smartrecruiters": re.compile(r"jobs\.smartrecruiters\.com/([A-Za-z0-9_-]+)", re.I),
}

# Boards that do not return the job description in their listing call. Their
# listings come back with an empty `full_jd`, filled in afterwards for the
# jobs that actually survive filtering — see `_hydrate`.
NEEDS_HYDRATION = {"smartrecruiters"}


def _fetch(url: str):
    """GET and parse JSON, or None. A dead board must not end the run."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # 404 is the normal signal that a company left this ATS. Expected
        # often enough that it is not worth a warning.
        level = logger.debug if exc.code == 404 else logger.warning
        level(f"ATS {exc.code} for {url}")
    except (urllib.error.URLError, ValueError, OSError) as exc:
        logger.warning(f"ATS fetch failed for {url}: {exc}")
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _listing(board, slug, job_id, title, company, location, url, jd) -> JobListing:
    text = (jd or "").strip()
    return JobListing(
        id=f"{board}_{slug}_{job_id}",
        title=title or "Unknown",
        company=company or slug.replace("-", " ").title(),
        location=location or "Not specified",
        # The snippet is the head of the JD rather than a separate summary;
        # these boards do not publish one and inventing it would be worse.
        description=text[:300],
        apply_url=url or "",
        salary_min=None,
        salary_max=None,
        created=_now(),
        source=f"ats_{board}",
        full_jd=text,
    )


# --- per-board readers -------------------------------------------------------

def _greenhouse(slug: str) -> list:
    payload = _fetch(
        f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    )
    if not payload:
        return []

    listings = []
    for job in payload.get("jobs", []):
        listings.append(_listing(
            "greenhouse", slug, job.get("id"),
            job.get("title"),
            job.get("company_name"),
            (job.get("location") or {}).get("name"),
            job.get("absolute_url"),
            _strip_html(job.get("content", "")),
        ))
    return listings


def _lever(slug: str) -> list:
    payload = _fetch(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if not payload:
        return []

    listings = []
    for job in payload:
        categories = job.get("categories") or {}
        listings.append(_listing(
            "lever", slug, job.get("id"),
            job.get("text"),
            None,
            categories.get("location"),
            job.get("hostedUrl"),
            job.get("descriptionPlain") or _strip_html(job.get("description", "")),
        ))
    return listings


def _ashby(slug: str) -> list:
    payload = _fetch(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    if not payload:
        return []

    listings = []
    for job in payload.get("jobs", []):
        if job.get("isListed") is False:
            continue
        listings.append(_listing(
            "ashby", slug, job.get("id"),
            job.get("title"),
            None,
            job.get("location"),
            job.get("jobUrl") or job.get("applyUrl"),
            job.get("descriptionPlain") or _strip_html(job.get("descriptionHtml", "")),
        ))
    return listings


def _workable(slug: str) -> list:
    payload = _fetch(
        f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true"
    )
    if not payload:
        return []

    company = payload.get("name")
    listings = []
    for job in payload.get("jobs", []):
        # The widget leaves `location` null and splits the parts out instead.
        where = ", ".join(
            part for part in (job.get("city"), job.get("state"), job.get("country"))
            if part
        )
        listings.append(_listing(
            "workable", slug, job.get("shortcode") or job.get("id"),
            job.get("title"),
            company,
            where or ("Remote" if job.get("telecommuting") else None),
            job.get("url") or job.get("shortlink") or job.get("application_url"),
            _strip_html(job.get("description", "")),
        ))
    return listings


def _smartrecruiters(slug: str) -> list:
    """
    Enterprise boards. One company here can dwarf a whole startup segment —
    Bosch alone posts nearly five thousand roles — which is exactly the
    coverage Greenhouse and Ashby do not give you.

    Unlike the others, the listing call carries no description, so these come
    back with an empty `full_jd` and are hydrated after filtering. Fetching
    4,774 descriptions to then discard 4,700 of them would be absurd.
    """
    payload = _fetch(
        f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100"
    )
    if not payload:
        return []

    listings = []
    for job in payload.get("content", []):
        location = job.get("location") or {}
        where = ", ".join(
            part for part in (location.get("city"), location.get("region"),
                              (location.get("country") or "").upper())
            if part
        )
        listing = _listing(
            "smartrecruiters", slug, job.get("id"),
            job.get("name"),
            (job.get("company") or {}).get("name"),
            where or None,
            f"https://jobs.smartrecruiters.com/{slug}/{job.get('id')}",
            "",
        )
        # Seniority as a structured field, rather than inferred from a title.
        level = (job.get("experienceLevel") or {}).get("label")
        if level:
            listing.description = level
        listings.append(listing)
    return listings


BOARDS = {
    "greenhouse": _greenhouse,
    "lever": _lever,
    "ashby": _ashby,
    "workable": _workable,
    "smartrecruiters": _smartrecruiters,
}


def _strip_html(html: str) -> str:
    """
    Crude tag removal, deliberately.

    Greenhouse returns HTML-escaped markup and Ashby offers a plain-text field
    already. A real parser would be a dependency for one field on one source,
    and the JD only has to be good enough to embed and keyword-match.
    """
    if not html:
        return ""
    import html as html_module

    text = html_module.unescape(html)
    text = re.sub(r"<(br|/p|/div|/li)[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


# --- public API --------------------------------------------------------------

def load_companies(path=None) -> dict:
    """The slug list, keyed by board. Missing or unreadable means empty."""
    file = Path(path) if path else COMPANIES_FILE
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning(f"Could not read {file}: {exc}")
        return {}

    return {
        board: [s for s in slugs if isinstance(s, str)]
        for board, slugs in data.items()
        if board in BOARDS and isinstance(slugs, list)
    }


def harvest_slugs(urls, path=None) -> dict:
    """
    Learn new company slugs from apply URLs and add them to the seed list.

    Any job found by *any* source whose apply URL lands on a known ATS host
    tells us that company's slug, and from then on its whole board is
    reachable without a key. Returns what was added, keyed by board.
    """
    file = Path(path) if path else COMPANIES_FILE
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

    added = {}
    for url in urls or []:
        for board, pattern in SLUG_PATTERNS.items():
            match = pattern.search(url or "")
            if not match:
                continue
            slug = match.group(1).lower()
            known = data.setdefault(board, [])
            if slug not in known:
                known.append(slug)
                added.setdefault(board, []).append(slug)

    if added:
        for board in added:
            data[board] = sorted(data[board])
        try:
            file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            total = sum(len(v) for v in added.values())
            logger.info(f"🌱 Learned {total} new ATS company slug(s): {added}")
        except OSError as exc:
            logger.warning(f"Could not update {file}: {exc}")
            return {}

    return added


def title_matches_roles(title: str, roles) -> bool:
    """
    Does this job title look like one of the roles the user wants?

    Matched on the *title* only, and on whole words. A company board is the
    entire company — Stripe's is 578 roles across sales, legal, support and
    engineering — so without this the caller gets whatever sorts first
    alphabetically, which in practice means account executives.

    Bounded by lookarounds rather than substrings, for R18's reason: `"ai"`
    inside `"Retail"` is not a match. Multi-word roles match as phrases, so
    "Software Engineer" hits "Senior Software Engineer II" but not
    "Engineering Manager".

    Lookarounds on alphanumerics rather than a word boundary, because a word
    boundary treats `-` and `/` as separators — which would let "Stack
    Engineer" match "Full-Stack Engineer" while "Full-Stack Engineer" itself
    failed to match "Full-Stack Engineer II". Titles are full of hyphens.
    """
    if not roles:
        return True

    lowered = (title or "").lower()
    for role in roles:
        phrase = (role or "").strip().lower()
        if phrase and re.search("(?<![a-z0-9])" + re.escape(phrase) + "(?![a-z0-9])", lowered):
            return True
    return False


def _spread(by_company: dict, max_results: int) -> list:
    """
    Fill the cap round-robin across employers, not first-come.

    Every company is asked before anything is cut, and then one job is taken
    from each in turn until the cap is reached. Without this the cap goes to
    whoever sorts first: a run capped at 20 came back 18 Affirm, 3 Airtable,
    2 Airbnb — the alphabetical head of the seed file — while 54 Greenhouse
    companies were never contacted and Lever, Ashby, Workable and
    SmartRecruiters were never reached at all.

    `title_matches_roles` already solved this *within* a company, and its
    docstring says why: truncate first and you get whatever sorts first
    rather than what you asked for. The same argument applies one level up,
    and this is the level it was missing from.

    Order within a company is preserved, so a board that lists its newest
    roles first still surfaces them first.
    """
    if max_results <= 0:
        return []

    queues = [list(jobs) for jobs in by_company.values()]
    spread = []

    while queues and len(spread) < max_results:
        for queue in list(queues):
            if len(spread) >= max_results:
                break
            spread.append(queue.pop(0))
            if not queue:
                queues.remove(queue)

    return spread


def search_ats(max_results: int = 50, companies=None, boards=None, roles=None) -> list:
    """
    Pull open roles from public ATS boards. No API key.

    Args:
        max_results: Cap on listings returned.
        companies: {board: [slug, ...]}. Defaults to the seed file.
        boards: Restrict to these boards. Defaults to all supported.
        roles: Job titles of interest, e.g. the profile's `target_roles`.
            Filtering happens **before** the cap, which is the whole point:
            these boards carry every department a company hires for, so
            truncating first returns an alphabetical slice of the wrong jobs.

    Returns:
        JobListing objects with `full_jd` already populated, so ATS-sourced
        jobs need no enrichment pass.
    """
    companies = companies if companies is not None else load_companies()
    wanted = boards or list(BOARDS)

    by_company, reached, failed, seen_total = {}, 0, 0, 0
    for board in wanted:
        reader = BOARDS.get(board)
        if not reader:
            continue

        for slug in companies.get(board, []):
            found = reader(slug)
            if not found:
                failed += 1
                continue

            reached += 1
            seen_total += len(found)
            matching = [job for job in found
                        if title_matches_roles(job.title, roles)]
            if matching:
                by_company[f"{board}:{slug}"] = matching

    matched = sum(len(jobs) for jobs in by_company.values())
    logger.info(
        f"ATS: {matched} matching listings from {seen_total} open roles "
        f"across {reached} board(s), {len(by_company)} hiring"
        + (f", {failed} unreachable" if failed else "")
    )

    # Which companies the cap reaches is randomised per run. Round-robin over
    # a fixed order still hands every run the same alphabetical head — 79
    # companies are hiring and a cap of 20 would only ever show A through D.
    # The job store is durable (R35), so varying the order means successive
    # runs widen the board instead of re-finding the same twenty employers.
    #
    # Deterministic replay is not lost: `--input` re-runs analysis and
    # generation over a saved enriched_jobs.json, which is where reproducing
    # a result actually matters.
    ordered = list(by_company.items())
    random.shuffle(ordered)

    final = _spread(dict(ordered), max_results)
    _hydrate(final)
    return final


def _hydrate(listings) -> None:
    """
    Fetch descriptions for boards that do not inline them.

    Called only on the listings actually being returned, after role filtering
    and after the cap. That ordering is the whole reason this is affordable:
    a SmartRecruiters enterprise board can carry thousands of roles, and
    fetching every description to then discard almost all of them would cost
    more than the source is worth.

    A description that will not load leaves `full_jd` empty rather than
    failing — Enrichment can still scrape it the ordinary way.
    """
    for listing in listings:
        if listing.full_jd:
            continue
        board = listing.source.replace("ats_", "")
        if board not in NEEDS_HYDRATION:
            continue

        _, slug, job_id = listing.id.split("_", 2)
        payload = _fetch(
            f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{job_id}"
        )
        if not payload:
            continue

        sections = ((payload.get("jobAd") or {}).get("sections") or {})
        text = "\n\n".join(
            _strip_html((sections.get(name) or {}).get("text", ""))
            for name in ("companyDescription", "jobDescription",
                         "qualifications", "additionalInformation")
        ).strip()
        if text:
            listing.full_jd = text
            if not listing.description or len(listing.description) < 40:
                listing.description = text[:300]

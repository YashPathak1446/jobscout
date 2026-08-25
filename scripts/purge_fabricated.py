"""
Remove fabricated job descriptions, and the scores taken against them.

Until R61 a failed scrape fell back to `mock_scrape_jd`, which returns
invented boilerplate and hard-codes `scraped_successfully: True`. Nothing
downstream read `scraper_used`, so the invention was scored, cached, ranked
and turned into resumes exactly as if it were a real posting.

Fixing the code stops it happening again. It does not undo what is already on
disk: the fabricated text sits in `cache/job_cache.json`, where a cache hit
serves it back without even the warning, and the scores taken against it sit
in `data/jobs.db` holding the top of the board.

Measured when this was written: 36 of 178 cached JDs fabricated, 34 of 103
scored jobs derived from one, 8 of those with a generated resume.

This is a one-off repair rather than a migration — after R61 no new fabricated
entry can be written, so there is nothing for it to do on a clean install. It
is kept because the damage is invisible from the board and someone re-reading
this later deserves to know how it was cleaned up.

    python scripts/purge_fabricated.py --dry-run
    python scripts/purge_fabricated.py

Location: jobscout_v3/scripts/purge_fabricated.py
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

CACHE = ROOT / "cache" / "job_cache.json"


def fabricated_urls(cache_path=CACHE) -> set:
    """URLs whose cached description came from the mock, not the employer."""
    if not cache_path.exists():
        return set()

    data = json.loads(cache_path.read_text(encoding="utf-8"))
    return {
        url for url, entry in (data.get("scraped_jds") or {}).items()
        if "mock" in str(entry.get("scraper_used", "")).lower()
    }


def purge_cache(urls, cache_path=CACHE, dry_run=False) -> int:
    """Drop the fabricated entries. The URL stays in `seen_urls`."""
    if not urls or not cache_path.exists():
        return 0

    data = json.loads(cache_path.read_text(encoding="utf-8"))
    jds = data.get("scraped_jds") or {}
    removed = [url for url in urls if url in jds]

    if not dry_run:
        for url in removed:
            del jds[url]
        cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    return len(removed)


def clear_scores(urls, store, dry_run=False) -> int:
    """
    Forget the score and the selection, keep the job.

    The job is real — discovery found it on a real board. Only what was
    concluded *about* it is worthless, so the row stays and `scored_at` goes
    back to null, which is what puts it back in `unprocessed_urls()` for the
    next run to score properly.
    """
    cleared = 0
    for url in urls:
        row = store.get(url)
        if not row or row["score"] is None:
            continue
        cleared += 1
        if not dry_run:
            store._db.execute(
                "UPDATE jobs SET score = NULL, scored_at = NULL,"
                " selection = NULL WHERE url = ?", (url,))
    if not dry_run and cleared:
        store._db.commit()
    return cleared


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change and touch nothing")
    args = parser.parse_args()

    from tools.jobs.job_store import JobStore

    urls = fabricated_urls()
    if not urls:
        print("No fabricated descriptions found. Nothing to do.")
        return 0

    store = JobStore()
    try:
        resumed = [url for url in urls
                   if (store.get(url) or {}) and (store.get(url) or {})["resume_tex"]]
        cleared = clear_scores(urls, store, dry_run=args.dry_run)
    finally:
        store.close()

    removed = purge_cache(urls, dry_run=args.dry_run)

    verb = "would remove" if args.dry_run else "removed"
    print(f"Fabricated descriptions found : {len(urls)}")
    print(f"Cache entries {verb:<15}: {removed}")
    print(f"Scores {'would clear' if args.dry_run else 'cleared':<22}: {cleared}")
    if resumed:
        print(f"\n{len(resumed)} of these already have a generated resume on "
              f"disk.\nThose files are left alone — delete them yourself if "
              f"you sent none of them.\nThey were written against invented "
              f"requirements.")
    if not args.dry_run:
        print("\nRe-run the pipeline to score these jobs against real text.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

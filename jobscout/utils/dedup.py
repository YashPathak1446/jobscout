"""
Job Deduplication and Application Tracker.

Tracks jobs across pipeline runs so you never see the same job twice.
Also maintains an applied jobs log that syncs with your spreadsheet.
"""

import json
import os
import csv
from datetime import datetime

SEEN_FILE = ".jobscout_seen.json"
APPLIED_FILE = "outputs/applied_jobs.csv"


def _load_seen(path: str = SEEN_FILE) -> dict:
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {"seen": {}}


def _save_seen(data: dict, path: str = SEEN_FILE):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def is_seen(listing) -> bool:
    """Check if a job has been shown before."""
    data = _load_seen()
    key = _job_key(listing)
    return key in data["seen"]


def mark_seen(listings: list) -> list:
    """
    Filter out already-seen jobs and mark new ones as seen.
    Returns only new (unseen) listings.
    """
    data = _load_seen()
    new_listings = []
    for listing in listings:
        key = _job_key(listing)
        if key not in data["seen"]:
            data["seen"][key] = {
                "title": listing.title,
                "company": listing.company,
                "url": listing.apply_url,
                "first_seen": datetime.now().isoformat(),
            }
            new_listings.append(listing)

    _save_seen(data)
    return new_listings


def mark_applied(listing, resume_path: str = "", notes: str = ""):
    """
    Mark a job as applied. Appends to applied_jobs.csv for spreadsheet import.
    """
    os.makedirs(os.path.dirname(APPLIED_FILE), exist_ok=True)

    # Write header if new file
    write_header = not os.path.exists(APPLIED_FILE)

    with open(APPLIED_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow([
                "Date Applied", "Company", "Title", "Location",
                "Apply URL", "Resume Used", "Score", "Status", "Notes"
            ])
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d"),
            listing.company,
            listing.title,
            getattr(listing, "location", ""),
            listing.apply_url,
            resume_path,
            "",  # Score filled in separately
            "Applied",
            notes,
        ])


def get_seen_count() -> int:
    """How many unique jobs have been seen total."""
    return len(_load_seen()["seen"])


def reset_seen():
    """Clear seen history — use when you want fresh results."""
    _save_seen({"seen": {}})
    print("Seen job history cleared.")


def _job_key(listing) -> str:
    """Unique key for a job — company + title (URL changes, these don't)."""
    return f"{listing.company.lower().strip()}::{listing.title.lower().strip()[:60]}"

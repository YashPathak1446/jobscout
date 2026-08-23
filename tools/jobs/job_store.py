"""
Durable record of every job ever discovered.

`tools/cache/job_cache.py` looks like this and is not this. It is a dedup
tracker: it remembers a URL for seven days so the same posting does not appear
in consecutive runs, then forgets. That is right for a run log and wrong for a
board — a tracker is built to forget, a board must never lose anything. Those
are opposite intents, which is why this is a separate file rather than a
retention flag on that one.

The pressure came from R34. Five ATS boards reach ~17,000 roles, and under a
seven-day expiry a second run over them returns almost nothing — most of the
discovery was being thrown away.

**SQLite, not JSON.** Everything else here is a JSON file and that is usually
right, but this is the one artefact that grows without bound and gets asked
questions: R33's board filters by role, score, date and status. Re-parsing a
multi-megabyte document on every run to do that is the wrong shape, and
`sqlite3` is in the standard library, so it costs no dependency.

**A job's status belongs to the user.** Re-discovering a posting someone
marked `applied` must never reset it. Every write path here preserves user
state and touches only what discovery legitimately owns.

Location: jobscout_v3/tools/jobs/job_store.py
"""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent.parent
DEFAULT_DB = ROOT / "data" / "jobs.db"

# What a user can say about a job. `new` is the only one the pipeline sets;
# the rest are theirs.
STATUSES = ("new", "seen", "applied", "rejected", "archived")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    url         TEXT PRIMARY KEY,
    job_id      TEXT,
    title       TEXT NOT NULL,
    company     TEXT,
    location    TEXT,
    source      TEXT,
    full_jd     TEXT,
    score       REAL,
    status      TEXT NOT NULL DEFAULT 'new',
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    scored_at   TEXT,
    resume_tex  TEXT,
    resume_pdf  TEXT,
    run_date    TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_score  ON jobs(score);
CREATE INDEX IF NOT EXISTS idx_jobs_seen   ON jobs(last_seen);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    """Every job ever seen, keyed by apply URL."""

    def __init__(self, path=None):
        self.path = Path(path) if path else DEFAULT_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path))
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._db.commit()

    # -- writing --------------------------------------------------------------

    def record(self, listings, run_date=None) -> dict:
        """
        Upsert discovered jobs. Returns {'added': n, 'updated': n}.

        A job already in the store keeps its status, score and resume paths —
        only `last_seen` moves, plus any field discovery can legitimately
        refresh, like a JD that arrived empty last time. Re-running discovery
        must never undo what the user has recorded about a job.
        """
        stamp = _now()
        added = updated = 0

        for job in listings or []:
            url = getattr(job, "apply_url", "") or ""
            if not url:
                continue

            row = self._db.execute(
                "SELECT url, full_jd FROM jobs WHERE url = ?", (url,)
            ).fetchone()

            if row is None:
                self._db.execute(
                    "INSERT INTO jobs (url, job_id, title, company, location,"
                    " source, full_jd, status, first_seen, last_seen, run_date)"
                    " VALUES (?,?,?,?,?,?,?,'new',?,?,?)",
                    (url, getattr(job, "id", ""), getattr(job, "title", ""),
                     getattr(job, "company", ""), getattr(job, "location", ""),
                     getattr(job, "source", ""), getattr(job, "full_jd", ""),
                     stamp, stamp, run_date),
                )
                added += 1
            else:
                # Only fill a JD that is missing; never overwrite a good one
                # with an empty re-discovery.
                incoming = getattr(job, "full_jd", "") or ""
                if incoming and not row["full_jd"]:
                    self._db.execute(
                        "UPDATE jobs SET last_seen = ?, full_jd = ? WHERE url = ?",
                        (stamp, incoming, url))
                else:
                    self._db.execute(
                        "UPDATE jobs SET last_seen = ? WHERE url = ?", (stamp, url))
                updated += 1

        self._db.commit()
        return {"added": added, "updated": updated}

    def set_score(self, url: str, score: float) -> None:
        """Record what analysis thought of a job."""
        self._db.execute(
            "UPDATE jobs SET score = ?, scored_at = ? WHERE url = ?",
            (float(score), _now(), url))
        self._db.commit()

    def attach_resume(self, url: str, tex_path=None, pdf_path=None) -> None:
        """Point a job at the resume written for it."""
        self._db.execute(
            "UPDATE jobs SET resume_tex = COALESCE(?, resume_tex),"
            " resume_pdf = COALESCE(?, resume_pdf) WHERE url = ?",
            (str(tex_path) if tex_path else None,
             str(pdf_path) if pdf_path else None, url))
        self._db.commit()

    def set_status(self, url: str, status: str) -> None:
        """Record what the *user* decided. Rejects anything not in STATUSES."""
        if status not in STATUSES:
            raise ValueError(f"Unknown status {status!r}; expected one of {STATUSES}")
        self._db.execute("UPDATE jobs SET status = ? WHERE url = ?", (status, url))
        self._db.commit()

    # -- reading --------------------------------------------------------------

    def get(self, url: str):
        row = self._db.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()
        return dict(row) if row else None

    def query(self, status=None, min_score=None, company=None, source=None,
              unscored=False, has_resume=None, limit=200) -> list:
        """
        The board's read path: filter, newest-scored first.

        Args:
            status: One status, or a list of them.
            min_score: Only jobs scoring at least this.
            company / source: Exact matches.
            unscored: Only jobs analysis has not looked at yet.
            has_resume: True for jobs with a generated resume, False without.
            limit: Row cap.
        """
        where, params = [], []

        if status:
            wanted = [status] if isinstance(status, str) else list(status)
            where.append(f"status IN ({','.join('?' * len(wanted))})")
            params.extend(wanted)
        if min_score is not None:
            where.append("score >= ?")
            params.append(float(min_score))
        if company:
            where.append("company = ?")
            params.append(company)
        if source:
            where.append("source = ?")
            params.append(source)
        if unscored:
            where.append("score IS NULL")
        if has_resume is True:
            where.append("resume_tex IS NOT NULL")
        elif has_resume is False:
            where.append("resume_tex IS NULL")

        sql = "SELECT * FROM jobs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        # Scored jobs first and best-scoring at the top; unscored fall to the
        # bottom rather than sorting as if they scored zero.
        sql += " ORDER BY score IS NULL, score DESC, last_seen DESC LIMIT ?"
        params.append(int(limit))

        return [dict(r) for r in self._db.execute(sql, params).fetchall()]

    def unprocessed_urls(self) -> set:
        """URLs the pipeline has not scored yet."""
        return {
            r["url"] for r in
            self._db.execute("SELECT url FROM jobs WHERE score IS NULL").fetchall()
        }

    def stats(self) -> dict:
        total = self._db.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
        scored = self._db.execute(
            "SELECT COUNT(*) c FROM jobs WHERE score IS NOT NULL").fetchone()["c"]
        with_resume = self._db.execute(
            "SELECT COUNT(*) c FROM jobs WHERE resume_tex IS NOT NULL").fetchone()["c"]
        by_status = {
            r["status"]: r["c"] for r in
            self._db.execute("SELECT status, COUNT(*) c FROM jobs GROUP BY status")
        }
        return {"total": total, "scored": scored, "with_resume": with_resume,
                "by_status": by_status, "path": str(self.path)}

    def close(self) -> None:
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

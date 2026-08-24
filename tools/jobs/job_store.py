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
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent.parent
DEFAULT_DB = ROOT / "data" / "jobs.db"

# What a user can say about a job. `new` is the only one the pipeline sets;
# the rest are theirs.
STATUSES = ("new", "seen", "applied", "rejected", "archived")

# How long after applying silence starts to mean something. Four weeks is the
# point most advice treats a non-answer as an answer; it is a default, not a
# fact, which is why `ghosted_after_days` is a parameter everywhere below.
GHOSTED_AFTER_DAYS = 28

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

-- When each status was set, not just what it is now.
--
-- "Ghosted" is the status this board most wants and the one a user should
-- never have to click: it means "applied, and silence since", which is a fact
-- about *time*, not a decision. Without a record of when a status changed
-- there is nothing to measure that silence from — so the board could offer a
-- `ghosted` button and would be asking the user to do the arithmetic.
--
-- It also answers the question a log exists for: how long between applying
-- and hearing back, across everything.
CREATE TABLE IF NOT EXISTS status_history (
    url        TEXT NOT NULL,
    status     TEXT NOT NULL,
    changed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_url ON status_history(url, changed_at);
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
        """
        Record what the *user* decided, and when.

        The timestamp is the point: `applied` alone cannot tell you a reply is
        overdue, and asking someone to remember the date defeats the purpose
        of keeping a log for them.
        """
        if status not in STATUSES:
            raise ValueError(f"Unknown status {status!r}; expected one of {STATUSES}")

        self._db.execute("UPDATE jobs SET status = ? WHERE url = ?", (status, url))
        self._db.execute(
            "INSERT INTO status_history (url, status, changed_at) VALUES (?,?,?)",
            (url, status, _now()))
        self._db.commit()

    def history(self, url: str) -> list:
        """Every status this job has held, oldest first."""
        return [
            dict(row) for row in self._db.execute(
                "SELECT status, changed_at FROM status_history WHERE url = ?"
                " ORDER BY changed_at", (url,))
        ]

    def status_changed_at(self, url: str, status: str):
        """When a job most recently entered a status, or None."""
        row = self._db.execute(
            "SELECT changed_at FROM status_history WHERE url = ? AND status = ?"
            " ORDER BY changed_at DESC LIMIT 1", (url, status)).fetchone()
        return row["changed_at"] if row else None

    def ghosted(self, after_days: int = GHOSTED_AFTER_DAYS) -> list:
        """
        Applied to, and silent since.

        Derived rather than stored, because it is not a decision anybody makes
        — it is what has happened to a job while nobody did anything. A stored
        `ghosted` status would go stale the moment a reply arrived, and would
        need the user to notice the anniversary in the first place.

        A job that moved on from `applied` is excluded by construction: the
        current status is what it is now, and only jobs still sitting at
        `applied` can have been ignored.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=after_days)).isoformat()
        rows = self._db.execute(
            "SELECT j.*, MAX(h.changed_at) AS applied_at"
            "  FROM jobs j JOIN status_history h ON h.url = j.url"
            " WHERE j.status = 'applied' AND h.status = 'applied'"
            " GROUP BY j.url"
            " HAVING applied_at < ?"
            " ORDER BY applied_at", (cutoff,)).fetchall()
        return [dict(row) for row in rows]

    # -- reading --------------------------------------------------------------

    def get(self, url: str):
        row = self._db.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()
        return dict(row) if row else None

    # How the board may order itself. Kept here rather than in the view so the
    # screen never builds SQL, and so an unknown value cannot reach the query.
    SORTS = {
        "best": "score IS NULL, score DESC, last_seen DESC",
        "newest": "first_seen DESC",
        "recent": "last_seen DESC",
        "company": "company COLLATE NOCASE, score IS NULL, score DESC",
    }

    def query(self, status=None, min_score=None, company=None, source=None,
              unscored=False, has_resume=None, search=None, sort="best",
              limit=200, offset=0) -> list:
        """
        The board's read path: filter, then order.

        Args:
            status: One status, or a list of them.
            min_score: Only jobs scoring at least this.
            company / source: One value, or a list of them.
            unscored: Only jobs analysis has not looked at yet.
            has_resume: True for jobs with a generated resume, False without.
            search: Case-insensitive substring of the title or company.
            sort: A key from `SORTS`. Unknown values fall back to "best"
                rather than raising, because a stale bookmark in a UI should
                not be an error.
            limit / offset: Page window. The board reached ~11,600 discovered
                roles once discovery stopped stopping early (R46), so a fixed
                cap silently hid most of the store.
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
            wanted = [company] if isinstance(company, str) else list(company)
            where.append(f"company IN ({','.join('?' * len(wanted))})")
            params.extend(wanted)
        if source:
            wanted = [source] if isinstance(source, str) else list(source)
            where.append(f"source IN ({','.join('?' * len(wanted))})")
            params.extend(wanted)
        if unscored:
            where.append("score IS NULL")
        if has_resume is True:
            where.append("resume_tex IS NOT NULL")
        elif has_resume is False:
            where.append("resume_tex IS NULL")
        if search and search.strip():
            # Escaped so a literal % or _ in a search box matches itself
            # rather than turning into a wildcard.
            term = search.strip().replace("\\", "\\\\")
            term = term.replace("%", "\\%").replace("_", "\\_")
            where.append(r"(title LIKE ? ESCAPE '\' OR company LIKE ? ESCAPE '\')")
            params.extend([f"%{term}%", f"%{term}%"])

        sql = "SELECT * FROM jobs"
        if where:
            sql += " WHERE " + " AND ".join(where)

        # Scored jobs first and best-scoring at the top; unscored fall to the
        # bottom rather than sorting as if they scored zero.
        sql += f" ORDER BY {self.SORTS.get(sort, self.SORTS['best'])}"
        sql += " LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])

        return [dict(r) for r in self._db.execute(sql, params).fetchall()]

    def count(self, **filters) -> int:
        """
        How many rows those filters match, ignoring the page window.

        The board needs this to say "showing 50 of 412" — without it a page
        cap is indistinguishable from having run out of jobs, which is the
        silent-truncation shape this project keeps finding.
        """
        filters.pop("limit", None)
        filters.pop("offset", None)
        filters.pop("sort", None)
        return len(self.query(sort="best", limit=-1, offset=0, **filters))

    # Below this many scored jobs, quartiles are noise dressed as a judgement.
    MIN_FOR_BANDS = 8

    def score_bands(self) -> dict:
        """
        Where the quartiles of *your* scored jobs fall.

        The displayed score is already normalised onto 0-100, but against a
        window far wider than reality: the Gemini calibration maps raw cosine
        0.30-0.90, and 95 scored jobs across seven runs used 0.563-0.653 —
        **15% of the span**. Everything therefore lands between 44 and 59 and
        reads as "about 53" whatever it is.

        Re-cutting the calibration would fix the look and break the meaning:
        `scoring_threshold` gates the pipeline at 40, and moving the scale
        moves that gate silently. That is R24's failure exactly — a number
        used as a quality bar that could not grade — so the scale stays and
        the *presentation* learns to divide it.

        Computed from the store rather than hardcoded, so it calibrates to
        whoever is using it. A resume and a corpus this has never seen will
        produce a different band of raw similarities, and constants tuned to
        one person would be wrong for everyone else.

        Returns empty when there is too little to divide, because a quartile
        over three jobs is not information.
        """
        scores = [
            row["score"] for row in self._db.execute(
                "SELECT score FROM jobs WHERE score IS NOT NULL ORDER BY score")
        ]
        if len(scores) < self.MIN_FOR_BANDS:
            return {}

        def at(fraction):
            return scores[min(len(scores) - 1, int(len(scores) * fraction))]

        return {"strong": at(0.75), "typical": at(0.25),
                "n": len(scores), "low": scores[0], "high": scores[-1]}

    def facets(self) -> dict:
        """
        The values worth offering as filters, with counts.

        Read from the store rather than hardcoded, so a board that has just
        learned a new ATS shows it without anyone editing a list.
        """
        companies = [
            {"value": r["company"], "count": r["n"]}
            for r in self._db.execute(
                "SELECT company, COUNT(*) n FROM jobs WHERE company IS NOT NULL"
                " GROUP BY company ORDER BY n DESC, company COLLATE NOCASE")
        ]
        sources = [
            {"value": r["source"], "count": r["n"]}
            for r in self._db.execute(
                "SELECT source, COUNT(*) n FROM jobs WHERE source IS NOT NULL"
                " GROUP BY source ORDER BY n DESC, source")
        ]
        return {"companies": companies, "sources": sources}

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

"""
Runs that outlive the tab that started them (R33).

A pipeline run takes minutes. Until now it happened inside the request that
asked for it, so the browser had to stay open for the whole thing and a reload
lost the progress bar — and with it any idea whether the run was still going.
R33 decided runs are background jobs for that reason, and named the shape a
hosted tier would need: an id back immediately, progress readable afterwards.

**Progress lives on disk, not in memory.** Streamlit's `session_state` does
not survive a browser reload, so anything kept there is exactly as fragile as
the thing this replaces. SQLite alongside the job store means the run can be
asked about from a different tab, a different session, or a different process
— which is also what makes this portable to FastAPI without a rewrite.

**A thread, not a subprocess.** The requirement is that closing the tab does
not cancel the run, and the server outlives the tab, so a thread satisfies it.
A subprocess would additionally survive the server restarting, which is worth
having and is not what was asked for; the registry's shape does not change if
that is swapped in later, because callers only ever see an id.

Location: jobscout_v3/tools/jobs/run_registry.py
"""

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent.parent
DEFAULT_DB = ROOT / "data" / "runs.db"

# `failed` means the pipeline raised. A run that completes having generated
# nothing is still `finished` — that is a result, not an error.
STATES = ("queued", "running", "finished", "failed")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    profile     TEXT NOT NULL,
    state       TEXT NOT NULL,
    stage       TEXT,
    done        INTEGER DEFAULT 0,
    total       INTEGER DEFAULT 0,
    message     TEXT,
    error       TEXT,
    output_dir  TEXT,
    result      TEXT,
    started_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_state ON runs(state, started_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunRegistry:
    """Every run, and how far it has got."""

    def __init__(self, path=None):
        self.path = Path(path) if path else DEFAULT_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Written from a worker thread and read from the request thread, so
        # the connection has to be usable across both. Serialised by the lock
        # below rather than by sqlite's own thread check.
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._db.commit()
        self._lock = threading.Lock()

    # -- writing --------------------------------------------------------------

    def create(self, profile: str) -> str:
        """Register a run before it starts. Returns its id."""
        run_id = uuid.uuid4().hex[:12]
        stamp = _now()
        with self._lock:
            self._db.execute(
                "INSERT INTO runs (id, profile, state, started_at, updated_at)"
                " VALUES (?,?,'queued',?,?)", (run_id, profile, stamp, stamp))
            self._db.commit()
        return run_id

    def progress(self, run_id, stage, done=0, total=0, message="") -> None:
        """One tick. Cheap enough to call per job."""
        with self._lock:
            self._db.execute(
                "UPDATE runs SET state='running', stage=?, done=?, total=?,"
                " message=?, updated_at=? WHERE id=?",
                (stage, int(done), int(total), message, _now(), run_id))
            self._db.commit()

    def finish(self, run_id, result=None, output_dir=None) -> None:
        """
        The run ended without raising.

        `result` is a small summary, not the whole state: the pipeline already
        writes `state.json` next to the resumes, and copying a multi-megabyte
        document into a status row would make every poll expensive.
        """
        stamp = _now()
        with self._lock:
            self._db.execute(
                "UPDATE runs SET state='finished', result=?, output_dir=?,"
                " updated_at=?, finished_at=? WHERE id=?",
                (json.dumps(result or {}), str(output_dir or ""), stamp,
                 stamp, run_id))
            self._db.commit()

    def fail(self, run_id, error: str) -> None:
        stamp = _now()
        with self._lock:
            self._db.execute(
                "UPDATE runs SET state='failed', error=?, updated_at=?,"
                " finished_at=? WHERE id=?", (str(error)[:2000], stamp,
                                              stamp, run_id))
            self._db.commit()

    # -- reading --------------------------------------------------------------

    def get(self, run_id: str):
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None

        run = dict(row)
        run["result"] = json.loads(run["result"]) if run["result"] else {}
        run["fraction"] = (run["done"] / run["total"]) if run["total"] else 0.0
        run["active"] = run["state"] in ("queued", "running")
        return run

    def recent(self, limit: int = 10) -> list:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?",
                (int(limit),)).fetchall()
        return [self.get(row["id"]) for row in rows]

    def active(self) -> list:
        """
        Runs still going. This is what a reloaded page asks for: it has no
        memory of starting anything, and the answer has to come from disk.
        """
        with self._lock:
            rows = self._db.execute(
                "SELECT id FROM runs WHERE state IN ('queued','running')"
                " ORDER BY started_at").fetchall()
        return [self.get(row["id"]) for row in rows]

    def close(self) -> None:
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

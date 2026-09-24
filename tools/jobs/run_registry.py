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

from config import redact_keys
from tools import paths

logger = logging.getLogger(__name__)


def db_path(user_id) -> Path:
    """
    Where one user's runs are recorded: `data/runs.db` under their home.

    See `job_store.db_path`: the user's data home, not the install location,
    and a function rather than an import-time constant so it can be somebody
    in particular. Per user, `recent()` and `active()` stop handing one
    person's `output_dir` and `error` text to another, and a run id from
    somebody else's registry is simply not found.
    """
    return paths.user_path("data", "runs.db", user_id=user_id)

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
    finished_at TEXT,
    owner       TEXT,
    heartbeat_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_state ON runs(state, started_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# The two columns A10 added (R120), for a `runs.db` written before them.
# `owner` names the process whose thread runs the row; `heartbeat_at` is that
# thread saying it is still alive, on a timer rather than on a progress tick,
# because discovery can go minutes between ticks (Q49).
_ADDED_COLUMNS = {"owner": "TEXT", "heartbeat_at": "TEXT"}

# Why a reaped run failed, in the words both UIs' failed screens show.
REAPED_RESTART = "interrupted — the server restarted"
REAPED_WORKER = "interrupted — the run stopped without reporting"


class RunAlreadyActive(RuntimeError):
    """`claim` refused: this registry already has a queued or running run."""

    def __init__(self, run: dict):
        super().__init__(f"run {run['id']} is still {run['state']}")
        self.run = run


def every_db_path() -> list:
    """
    Every `runs.db` that exists: the unscoped one, then each user's (R120).

    Only files that exist, because opening a registry creates one, and a
    sweep that created a database for every directory it walked would be
    writing where it came to read. A directory under `users/` that is not a
    valid user id is skipped rather than trusted as a path.
    """
    found = [db_path(None)]
    users = paths.user_home(None) / paths.USERS_DIR
    if users.is_dir():
        for home in sorted(users.iterdir()):
            try:
                found.append(db_path(home.name))
            except ValueError:
                continue
    return [path for path in found if path.is_file()]


class RunRegistry:
    """Every run, and how far it has got."""

    def __init__(self, path):
        # Required, as for JobStore: no default registry to fall back to.
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Written from a worker thread and read from the request thread, so
        # the connection has to be usable across both. Serialised by the lock
        # below rather than by sqlite's own thread check.
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        have = {row["name"] for row in self._db.execute("PRAGMA table_info(runs)")}
        for column, kind in _ADDED_COLUMNS.items():
            if column not in have:
                self._db.execute(f"ALTER TABLE runs ADD COLUMN {column} {kind}")
        self._db.commit()
        self._lock = threading.Lock()

    # -- writing --------------------------------------------------------------

    # Every text column is scrubbed of any key in use (R117): a progress
    # message, a result and an error all carry exception text, which is not
    # ours to vouch for, and this table is read back to the browser.

    def create(self, profile: str) -> str:
        """
        Register a run before it starts, unchecked. Returns its id.

        Not what `start_run` calls: that is `claim`, which refuses a second
        active run. This stays as the plain insert tests build rows with, and
        its rows have no owner, so the reaper judges them by `updated_at`.
        """
        run_id = uuid.uuid4().hex[:12]
        stamp = _now()
        with self._lock:
            self._db.execute(
                "INSERT INTO runs (id, profile, state, started_at, updated_at)"
                " VALUES (?,?,'queued',?,?)", (run_id, profile, stamp, stamp))
            self._db.commit()
        return run_id

    def claim(self, profile: str, owner: str) -> str:
        """
        Register a run unless one is already going here (R120). Returns its id.

        One registry is one user, so this is "one run per user". The check and
        the insert are one `BEGIN IMMEDIATE` transaction, which SQLite
        serialises across connections and processes: two requests racing for
        the same user cannot both see "none active" and both insert. Raises
        `RunAlreadyActive` carrying the run that is in the way.
        """
        run_id = uuid.uuid4().hex[:12]
        stamp = _now()
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT id FROM runs WHERE state IN ('queued','running')"
                    " ORDER BY started_at LIMIT 1").fetchone()
                if row is None:
                    self._db.execute(
                        "INSERT INTO runs (id, profile, state, started_at,"
                        " updated_at, owner, heartbeat_at)"
                        " VALUES (?,?,'queued',?,?,?,?)",
                        (run_id, profile, stamp, stamp, owner, stamp))
                self._db.commit()
            except BaseException:
                self._db.rollback()
                raise
        if row is not None:
            raise RunAlreadyActive(self.get(row["id"]))
        return run_id

    def heartbeat(self, run_id) -> None:
        """The worker is alive. Moves nothing but `heartbeat_at`."""
        with self._lock:
            self._db.execute(
                "UPDATE runs SET heartbeat_at=? WHERE id=?"
                " AND state IN ('queued','running')", (_now(), run_id))
            self._db.commit()

    # `progress`, `finish` and `fail` only move a row that is still active.
    # Without that, a run reaped while alive flips back to `running` on its
    # next tick, and the user watches "failed" become "running" (Q49).

    def progress(self, run_id, stage, done=0, total=0, message="") -> None:
        """One tick. Cheap enough to call per job."""
        with self._lock:
            self._db.execute(
                "UPDATE runs SET state='running', stage=?, done=?, total=?,"
                " message=?, updated_at=? WHERE id=?"
                " AND state IN ('queued','running')",
                (stage, int(done), int(total), redact_keys(message), _now(),
                 run_id))
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
                " updated_at=?, finished_at=? WHERE id=?"
                " AND state IN ('queued','running')",
                (redact_keys(json.dumps(result or {})), str(output_dir or ""),
                 stamp, stamp, run_id))
            self._db.commit()

    def fail(self, run_id, error: str) -> None:
        stamp = _now()
        with self._lock:
            self._db.execute(
                "UPDATE runs SET state='failed', error=?, updated_at=?,"
                " finished_at=? WHERE id=? AND state IN ('queued','running')",
                (redact_keys(str(error))[:2000], stamp, stamp, run_id))
            self._db.commit()

    def reap(self, owner: str, live: set, stale_after: float,
             every_foreign: bool = False) -> list:
        """
        Fail every active run with no live worker, and return their ids (R120).

        Which worker is live is known exactly for this process and only
        inferred for any other, so the rule has two halves:

        - **Owned by `owner` (this process):** live iff its id is in `live`,
          the set of runs whose thread has not exited.
        - **Owned by anyone else,** including a row from before these columns
          existed: live iff its heartbeat (else its last update) is under
          `stale_after` seconds old. Local mode needs this: Streamlit and the
          API are two processes sharing one unscoped `runs.db`, and neither
          may reap the other's live run.

        `every_foreign` drops the heartbeat test and treats every other
        process's run as dead. That is the hosted startup sweep: one process
        serves every run (`--workers 1`), so at boot nothing else can be
        running one.
        """
        now = datetime.now(timezone.utc)
        dead = []
        with self._lock:
            rows = self._db.execute(
                "SELECT id, owner, heartbeat_at, updated_at FROM runs"
                " WHERE state IN ('queued','running')").fetchall()
        for row in rows:
            if row["owner"] == owner:
                if row["id"] not in live:
                    dead.append((row["id"], REAPED_WORKER))
                continue
            seen = datetime.fromisoformat(row["heartbeat_at"] or row["updated_at"])
            if every_foreign or (now - seen).total_seconds() > stale_after:
                dead.append((row["id"], REAPED_RESTART))
        for run_id, reason in dead:
            self.fail(run_id, reason)
        return [run_id for run_id, _ in dead]

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

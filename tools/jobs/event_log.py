"""
Who got how far: one user's pilot events (pilot plan A8, R118).

One table in `data/events.db` under the user's own partition, so a deletion
takes it with the tree (A6) and nobody's rows sit in anybody else's file.

**Counts and moments, never content.** A row is a user id, an event name, a
short reason and a timestamp. The event names are a fixed list, and so is
every reason except a failed run's, which is an exception's class name. So
neither column can carry resume text, job text or a key. The store refuses
anything else rather than trimming it: a reason that did not fit the rule
means something upstream passed content, and that is a bug to see, not one
to hide.

Written only for a scoped (hosted) user. The unscoped checkout has no account,
and `scripts/admin.py events` reads accounts, so events written there would
be read by nothing. That would be the recurring bug in CLAUDE.md, a record
computed and never read.
"""

import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools import paths

logger = logging.getLogger(__name__)

# Every event, and the reasons it may carry. `None` in a set is "no reason".
EVENTS = {
    "account_created": {None},
    # Which reader built the schema the person then confirmed. `tex` is the
    # third path: a LaTeX upload is read by nothing, it is already the format.
    "resume_imported": {"model", "pattern", "tex"},
    "run_started": {None},
    # "ok", or "failed:<ExceptionClass>". Checked by `_FAILED` below.
    "run_finished": {"ok"},
    "resume_generated": {"valid", "needs_review"},
    "job_marked": {"applied", "rejected"},
}

_FAILED = re.compile(r"failed:[A-Za-z_][A-Za-z0-9_]{0,63}")

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    event   TEXT NOT NULL,
    reason  TEXT,
    at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_event ON events(event, at);
"""


def db_path(user_id) -> Path:
    """One user's event log. `None` is refused: the checkout has no account."""
    if user_id is None:
        raise ValueError("the event log is per account; the unscoped user has none")
    return paths.user_path("data", "events.db", user_id=user_id)


def allowed(event: str, reason) -> bool:
    """Whether `(event, reason)` is something this table may hold."""
    if event not in EVENTS:
        return False
    if reason in EVENTS[event]:
        return True
    return (event == "run_finished" and isinstance(reason, str)
            and _FAILED.fullmatch(reason) is not None)


class EventLog:
    """One user's events. Opened per call, like the other stores."""

    def __init__(self, *, user_id):
        self.user_id = user_id
        path = db_path(user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path))
        self._db.executescript(SCHEMA)

    def record(self, event: str, reason=None, *, once: bool = False) -> bool:
        """
        Append one event. Returns whether a row was written.

        `once` writes only if this user has no `event` yet. It is for
        `account_created`: a passphrase reset is redeemed like an invite, and
        the account it re-opens was not created a second time.
        """
        if not allowed(event, reason):
            raise ValueError(f"not an event this log holds: {event!r} {reason!r}")
        stamp = datetime.now(timezone.utc).isoformat()
        with self._db:
            if once:
                written = self._db.execute(
                    "INSERT INTO events (user_id, event, reason, at) "
                    "SELECT ?, ?, ?, ? WHERE NOT EXISTS "
                    "(SELECT 1 FROM events WHERE event = ?)",
                    (self.user_id, event, reason, stamp, event)).rowcount
            else:
                written = self._db.execute(
                    "INSERT INTO events (user_id, event, reason, at) "
                    "VALUES (?, ?, ?, ?)",
                    (self.user_id, event, reason, stamp)).rowcount
        return bool(written)

    def all(self) -> list:
        """Every row, oldest first, as dicts."""
        rows = self._db.execute(
            "SELECT user_id, event, reason, at FROM events ORDER BY id").fetchall()
        return [dict(zip(("user_id", "event", "reason", "at"), row)) for row in rows]

    def close(self) -> None:
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def record(user_id, event: str, reason=None, *, once: bool = False) -> bool:
    """
    The one call the facades make. Nothing for the unscoped user (see above).

    A storage failure is logged and swallowed. The events count what people
    did, and a friend's import or run must not fail because the count of it
    could not be written. A disallowed event or reason is not swallowed: that
    is content reaching the log, and it should fail where it is written.
    """
    if user_id is None:
        return False
    if not allowed(event, reason):
        raise ValueError(f"not an event this log holds: {event!r} {reason!r}")
    try:
        with EventLog(user_id=user_id) as log:
            return log.record(event, reason, once=once)
    except (sqlite3.Error, OSError) as exc:
        logger.warning("could not record %s: %s", event, type(exc).__name__)
        return False


def read(user_id) -> list:
    """Every event this user has, oldest first; `[]` if they have none yet."""
    if not db_path(user_id).exists():
        return []
    with EventLog(user_id=user_id) as log:
        return log.all()


# The pilot's success criterion (docs/pilot-plan.md, A8): a run completed and
# a job marked applied or rejected, both within this long of the account.
FIRST_WEEK = timedelta(days=7)


def summarise(events: list) -> dict:
    """
    One user's counts, and whether they met the criterion in their first week.

    `met_in_first_week` is three states, not two. `None` means there is no
    `account_created` to count a week from (an account redeemed before A8),
    which is not the same as "did not meet it".
    """
    counts = {}
    for row in events:
        key = row["event"] if row["reason"] is None else f"{row['event']}:{row['reason']}"
        if row["event"] == "run_finished" and row["reason"] != "ok":
            key = "run_finished:failed"
        counts[key] = counts.get(key, 0) + 1

    created = next((row["at"] for row in events
                    if row["event"] == "account_created"), None)
    met = None
    if created is not None:
        deadline = datetime.fromisoformat(created) + FIRST_WEEK

        def within(event, reasons):
            return any(row["event"] == event and row["reason"] in reasons
                       and datetime.fromisoformat(row["at"]) <= deadline
                       for row in events)

        met = (within("run_finished", {"ok"})
               and within("job_marked", {"applied", "rejected"}))
    return {
        "counts": counts,
        "account_created": created,
        "last_event": events[-1]["at"] if events else None,
        "met_in_first_week": met,
    }

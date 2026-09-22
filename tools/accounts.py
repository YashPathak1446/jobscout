"""
Who is asking: accounts, sessions, and which mode the instance runs in
(pilot plan A5).

**Two modes, and the difference is the whole of hosting's security.**

* `local` — one person on their own machine. No accounts, no cookie, and every
  facade call is the unscoped user (`None`). This is what a checkout, the CLI
  and `uvicorn api.main:app` on a laptop have always been.
* `hosted` — every `/api` request names its caller through a signed session
  cookie, and that caller's id is what every facade call is scoped to.

`JOBSCOUT_MODE` picks one. Unset is `local`, because that is the developer's
world and the frozen baselines measure it. **Anything else that is not one of
the two words refuses to boot** — a typo that fell back to local would be the
one failure this module exists to prevent. `hosted` with no session secret, or
a short one, refuses too (plan decision 3).

The weak point is the flag itself: a deploy that drops it gets local mode,
which is unauthenticated and unscoped. Three things stand between that and a
silently open instance, and none of them is this docstring:

1. `fly.toml` carries `JOBSCOUT_MODE = "hosted"` in `[env]`, committed rather
   than a secret, and `test_hosted_boundary` fails if it stops.
2. `check_boot` refuses local mode when a hosting platform's own marker is in
   the environment (`FLY_APP_NAME` and friends).
3. `api.main` refuses any request in local mode whose peer is not loopback, and
   logs it at ERROR. A deploy that lost the flag is a wall of 403s and red log
   lines, not an open board.

**Accounts** live in `data_home()/data/accounts.db`. That store is *global by
design*: it is how a request finds out which user it is, so it cannot live
under a user. It is not in `scripts/path_snapshot.py`'s table, which lists user
stores.

Invite-only (plan decision 2). `invite()` makes a row with a fresh `user_id` and
a one-time code; `redeem()` attaches an email and passphrase to it. There is no
public signup and no password reset — `scripts/admin.py` is the reset flow.
Only the code's SHA-256 is stored, so a copy of this file cannot claim an
invite nobody has redeemed yet.

**Sessions** are `user_id.expiry.mac`, where the MAC is HMAC-SHA256 over
`user_id|expiry` under `JOBSCOUT_SESSION_SECRET`. The expiry is inside the
signed payload, so it cannot be extended by editing the cookie. A valid
signature is necessary and not sufficient: the account row is read on every
request, so a deleted account (A6) stops working at once rather than when its
cookie runs out.

Not here, logged instead: invalidating sessions when a passphrase is reset
(Q45 — needs a session epoch, which ships with A6's `reset-passphrase` so the
field has a reader the day it exists), and sign-in rate limiting (Q46).
"""

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tools import paths

MODE_ENV = "JOBSCOUT_MODE"
SECRET_ENV = "JOBSCOUT_SESSION_SECRET"
MODES = ("local", "hosted")

# 32 bytes is the HMAC-SHA256 key length; anything shorter is guessable in a
# way the rest of this module cannot compensate for.
MIN_SECRET_BYTES = 32

# Environment variables a hosting platform sets on its own. Local mode in their
# presence is a deploy that lost `JOBSCOUT_MODE`, not a laptop.
PLATFORM_MARKERS = ("FLY_APP_NAME", "FLY_MACHINE_ID", "K_SERVICE", "DYNO",
                    "RENDER", "RAILWAY_ENVIRONMENT")

SESSION_COOKIE = "jobscout_session"
SESSION_TTL_SECONDS = 14 * 24 * 3600

MIN_PASSPHRASE = 12
# scrypt cost scales with input length only mildly, but an unbounded body is
# an unbounded allocation before the check even starts.
MAX_PASSPHRASE = 1024

# scrypt parameters, stored beside each hash so they can be raised later
# without invalidating anything already written. n=2^14, r=8 is 16 MB a hash.
_N, _R, _P = 2 ** 14, 8, 1


class HostingMisconfigured(RuntimeError):
    """The instance cannot tell who is asking, so it will not start."""


class InviteRefused(ValueError):
    """No unredeemed invite has that code. Deliberately says no more."""


class EmailTaken(ValueError):
    """Another account already signs in with that email."""


class PassphraseRefused(ValueError):
    """Too short or too long. The message says which, for the person."""


# ------------------------------------------------------------------ mode ----

def hosting_mode() -> str:
    """`local` or `hosted`. Anything else raises rather than guessing."""
    raw = os.getenv(MODE_ENV, "").strip()
    if not raw:
        return "local"
    if raw not in MODES:
        raise HostingMisconfigured(
            f"{MODE_ENV}={raw!r} is not one of {MODES}. Refusing to guess, "
            f"because guessing wrong means serving everyone as one user.")
    return raw


def session_secret() -> bytes:
    """The HMAC key. Raises if it is missing or too short to be a key."""
    secret = os.getenv(SECRET_ENV, "")
    if len(secret.encode("utf-8")) < MIN_SECRET_BYTES:
        raise HostingMisconfigured(
            f"{MODE_ENV}=hosted needs {SECRET_ENV} set to at least "
            f"{MIN_SECRET_BYTES} bytes (try `python -c \"import secrets; "
            f"print(secrets.token_urlsafe(48))\"`).")
    return secret.encode("utf-8")


def check_boot() -> str:
    """
    Refuse to start an instance that cannot name its callers. Returns the mode.

    Called when `api.main` is imported, so uvicorn exits before it binds
    rather than failing on the first request.
    """
    mode = hosting_mode()
    if mode == "hosted":
        session_secret()
        return mode
    present = [name for name in PLATFORM_MARKERS if os.getenv(name)]
    if present:
        raise HostingMisconfigured(
            f"{MODE_ENV} is unset or 'local', but {present[0]} says this is a "
            f"hosting platform. Local mode has no accounts and serves every "
            f"caller one directory. Set {MODE_ENV}=hosted and {SECRET_ENV}.")
    return mode


# ---------------------------------------------------------------- store ----

def db_path() -> Path:
    """Global, not per user: this is how a request learns which user it is."""
    return paths.data_home() / "data" / "accounts.db"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    user_id         TEXT PRIMARY KEY,
    email           TEXT UNIQUE,
    passphrase_hash TEXT,
    invite_code     TEXT UNIQUE NOT NULL,
    created_at      TEXT NOT NULL,
    deleted_at      TEXT
)
"""


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute(_SCHEMA)
    return db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _code_digest(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


def _normalise_email(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email or len(email) > 320:
        raise ValueError("That does not look like an email address.")
    return email


def invite() -> tuple:
    """
    A new, unredeemed account. Returns `(user_id, code)`.

    The code is shown once, here, and stored only as a digest. The user id is
    random rather than derived from anything about the person: it becomes a
    directory name under `users/`, and an email in a path is personal data in
    every listing of the volume.
    """
    user_id = secrets.token_hex(8)
    code = secrets.token_urlsafe(16)
    db = _connect()
    try:
        db.execute("INSERT INTO accounts (user_id, invite_code, created_at) "
                   "VALUES (?, ?, ?)", (user_id, _code_digest(code), _now()))
        db.commit()
    finally:
        db.close()
    return user_id, code


def _check_passphrase(passphrase: str) -> None:
    if len(passphrase or "") < MIN_PASSPHRASE:
        raise PassphraseRefused(
            f"A passphrase needs at least {MIN_PASSPHRASE} characters.")
    if len(passphrase) > MAX_PASSPHRASE:
        raise PassphraseRefused(
            f"A passphrase can be at most {MAX_PASSPHRASE} characters.")


def hash_passphrase(passphrase: str, *, salt: Optional[bytes] = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(passphrase.encode("utf-8"), salt=salt,
                            n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def _passphrase_matches(passphrase: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(passphrase.encode("utf-8"),
                                   salt=bytes.fromhex(salt), n=int(n), r=int(r),
                                   p=int(p), dklen=len(bytes.fromhex(digest)))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate.hex(), digest)


# Hashed against when the email is unknown, so "no such account" and "wrong
# passphrase" take the same time. Computed on first use: an import-time scrypt
# would cost every process that never signs anyone in.
_DECOY = []


def _decoy() -> str:
    if not _DECOY:
        _DECOY.append(hash_passphrase(secrets.token_urlsafe(16)))
    return _DECOY[0]


def redeem(code: str, email: str, passphrase: str) -> str:
    """
    Attach an email and passphrase to an unredeemed invite. Returns the user id.

    A code that never existed, one already redeemed, and one whose account was
    deleted all raise the same `InviteRefused`: which of the three it was is a
    fact about somebody else's invite.
    """
    email = _normalise_email(email)
    _check_passphrase(passphrase)
    db = _connect()
    try:
        row = db.execute(
            "SELECT user_id FROM accounts WHERE invite_code = ? "
            "AND email IS NULL AND deleted_at IS NULL",
            (_code_digest(code or ""),)).fetchone()
        if row is None:
            raise InviteRefused("That invite code is not valid.")
        if db.execute("SELECT 1 FROM accounts WHERE email = ?",
                      (email,)).fetchone():
            raise EmailTaken("An account already uses that email. Sign in instead.")
        # `email IS NULL` again here, not only in the SELECT above: two
        # redeems of one code can both pass the SELECT, and an unconditional
        # UPDATE would let the second overwrite the first account's email and
        # passphrase. The UNIQUE on email closes the same race for two codes.
        try:
            claimed = db.execute(
                "UPDATE accounts SET email = ?, passphrase_hash = ? "
                "WHERE user_id = ? AND email IS NULL AND deleted_at IS NULL",
                (email, hash_passphrase(passphrase), row["user_id"])).rowcount
        except sqlite3.IntegrityError as exc:
            raise EmailTaken("An account already uses that email. "
                             "Sign in instead.") from exc
        if not claimed:
            raise InviteRefused("That invite code is not valid.")
        db.commit()
        return row["user_id"]
    finally:
        db.close()


def authenticate(email: str, passphrase: str) -> Optional[str]:
    """The user id whose email and passphrase these are, or None."""
    try:
        email = _normalise_email(email)
    except ValueError:
        email = ""
    db = _connect()
    try:
        row = db.execute(
            "SELECT user_id, passphrase_hash FROM accounts WHERE email = ? "
            "AND deleted_at IS NULL AND passphrase_hash IS NOT NULL",
            (email,)).fetchone()
    finally:
        db.close()
    if row is None:
        _passphrase_matches(passphrase or "", _decoy())
        return None
    if len(passphrase or "") > MAX_PASSPHRASE:
        return None
    return row["user_id"] if _passphrase_matches(passphrase or "",
                                                 row["passphrase_hash"]) else None


def active(user_id: str) -> bool:
    """Redeemed and not deleted. Read on every request, not only at sign-in."""
    db = _connect()
    try:
        return db.execute(
            "SELECT 1 FROM accounts WHERE user_id = ? AND email IS NOT NULL "
            "AND deleted_at IS NULL", (user_id,)).fetchone() is not None
    finally:
        db.close()


def email_of(user_id: str) -> Optional[str]:
    db = _connect()
    try:
        row = db.execute("SELECT email FROM accounts WHERE user_id = ? "
                         "AND deleted_at IS NULL", (user_id,)).fetchone()
    finally:
        db.close()
    return row["email"] if row else None


# -------------------------------------------------------------- session ----

def _mac(payload: str, secret: bytes) -> str:
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def issue_session(user_id: str, *, now: Optional[float] = None) -> str:
    """A cookie value naming `user_id` until the expiry signed into it."""
    paths.user_home(user_id)  # the id is a directory name; refuse a bad one here
    expiry = int(now if now is not None else time.time()) + SESSION_TTL_SECONDS
    payload = f"{user_id}|{expiry}"
    return f"{user_id}.{expiry}.{_mac(payload, session_secret())}"


def session_user(token: str, *, now: Optional[float] = None) -> Optional[str]:
    """
    The user a cookie names, or None if it names nobody.

    None for: absent, malformed, a MAC that does not match (tampered, or signed
    under another secret), expired, or an account that is no longer active.
    Every one of those is the same answer to the caller — sign in — so none of
    them is distinguished outside this function.
    """
    parts = (token or "").split(".")
    if len(parts) != 3:
        return None
    user_id, expiry, mac = parts
    if not hmac.compare_digest(_mac(f"{user_id}|{expiry}", session_secret()), mac):
        return None
    try:
        if int(expiry) <= (now if now is not None else time.time()):
            return None
    except ValueError:
        return None
    return user_id if active(user_id) else None

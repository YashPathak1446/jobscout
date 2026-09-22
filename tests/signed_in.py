"""
A hosted instance for a test: the mode, a session secret, and accounts.

Not a test module (discovery collects `test*.py`); the helpers every hosted
test shares, so the cookie a test signs in with is minted the one way the
product mints it — through `POST /api/session` — rather than forged here.
"""

import os
import sqlite3
from contextlib import contextmanager
from unittest import mock

# Test-only. Long enough to pass `session_secret`'s bound, and not a secret.
SECRET = "test-session-secret-" + "x" * 40
PASSPHRASE = "correct horse battery staple"


def hosted_env(home=None, secret=SECRET) -> dict:
    env = {"JOBSCOUT_MODE": "hosted", "JOBSCOUT_SESSION_SECRET": secret}
    if home is not None:
        env["JOBSCOUT_HOME"] = str(home)
    return env


@contextmanager
def hosted(home=None, secret=SECRET):
    """Hosted mode, with a valid secret, for the duration."""
    with mock.patch.dict(os.environ, hosted_env(home, secret)):
        yield


def make_account(email: str, *, user_id: str = None,
                 passphrase: str = PASSPHRASE) -> str:
    """
    Invite and redeem an account in the current data home. Returns its id.

    `user_id` pins the id, for tests whose fixtures already live under a named
    user (`test_two_users`). The product never chooses an id; this rewrites
    the random one `invite` made, before anything else refers to it.
    """
    from tools import accounts

    made, code = accounts.invite()
    if user_id is not None:
        db = sqlite3.connect(accounts.db_path())
        try:
            db.execute("UPDATE accounts SET user_id = ? WHERE user_id = ?",
                       (user_id, made))
            db.commit()
        finally:
            db.close()
        made = user_id
    accounts.redeem(code, email, passphrase)
    return made


def client(app, *, email: str = None, passphrase: str = PASSPHRASE, **kwargs):
    """
    A TestClient over HTTPS (the cookie is `Secure`), signed in if `email`.

    Signs in through the route, and fails loudly if that does not work: a
    helper that silently returned an anonymous client would turn every
    ownership test into a test of the 401.
    """
    from fastapi.testclient import TestClient

    test_client = TestClient(app, base_url="https://testserver", **kwargs)
    if email is not None:
        response = test_client.post("/api/session",
                                    json={"email": email, "passphrase": passphrase})
        if response.status_code != 200:
            raise AssertionError(f"could not sign in as {email}: "
                                 f"{response.status_code} {response.text}")
    return test_client

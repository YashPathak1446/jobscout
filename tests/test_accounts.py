"""
Accounts, sessions and the mode switch (pilot plan A5), below the HTTP layer.

The plan's mitigation for "a signing mistake means forged identity and a
friend's resume read" is these tests: a tampered, expired, foreign-secret or
absent cookie names nobody, and a deleted account stops working at once.
"""

import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tests.signed_in import PASSPHRASE, SECRET, hosted, make_account  # noqa: E402
from tools import accounts  # noqa: E402


class _Home(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self._env = hosted(self.home)
        self._env.__enter__()

    def tearDown(self):
        self._env.__exit__(None, None, None)
        self._tmp.cleanup()


class TestTheModeFailsClosed(_Home):

    def test_unset_is_local(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(accounts.MODE_ENV)
            self.assertEqual(accounts.hosting_mode(), "local")

    def test_a_typo_is_not_local(self):
        for typo in ("hostd", "Hosted", "production", "true"):
            with self.subTest(typo), mock.patch.dict(os.environ,
                                                     {accounts.MODE_ENV: typo}):
                with self.assertRaises(accounts.HostingMisconfigured):
                    accounts.check_boot()

    def test_hosted_without_a_secret_refuses_to_boot(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(accounts.SECRET_ENV)
            with self.assertRaises(accounts.HostingMisconfigured):
                accounts.check_boot()

    def test_hosted_with_a_short_secret_refuses_to_boot(self):
        with mock.patch.dict(os.environ, {accounts.SECRET_ENV: "x" * 31}):
            with self.assertRaises(accounts.HostingMisconfigured):
                accounts.check_boot()

    def test_hosted_with_a_secret_boots(self):
        self.assertEqual(accounts.check_boot(), "hosted")

    def test_local_mode_on_a_hosting_platform_refuses_to_boot(self):
        """The deploy that lost `JOBSCOUT_MODE`: Fly sets FLY_APP_NAME itself."""
        for marker in accounts.PLATFORM_MARKERS:
            with self.subTest(marker), mock.patch.dict(os.environ, {marker: "x"}):
                os.environ.pop(accounts.MODE_ENV)
                with self.assertRaises(accounts.HostingMisconfigured):
                    accounts.check_boot()

    def test_local_mode_on_a_laptop_boots(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(accounts.MODE_ENV)
            for marker in accounts.PLATFORM_MARKERS:
                os.environ.pop(marker, None)
            self.assertEqual(accounts.check_boot(), "local")


class TestInvites(_Home):

    def test_an_invite_is_redeemed_once(self):
        user_id, code = accounts.invite()
        self.assertEqual(accounts.redeem(code, "a@example.com", PASSPHRASE), user_id)
        with self.assertRaises(accounts.InviteRefused):
            accounts.redeem(code, "b@example.com", PASSPHRASE)

    def test_a_used_code_and_a_made_up_one_are_the_same_refusal(self):
        _, code = accounts.invite()
        accounts.redeem(code, "a@example.com", PASSPHRASE)
        messages = set()
        for attempt in (code, "not-a-code-anyone-issued"):
            with self.assertRaises(accounts.InviteRefused) as caught:
                accounts.redeem(attempt, "b@example.com", PASSPHRASE)
            messages.add(str(caught.exception))
        self.assertEqual(len(messages), 1)

    def test_a_redeem_that_lost_the_race_does_not_overwrite_the_winner(self):
        """Both passed the SELECT; only one may claim the row."""
        user_id, code = accounts.invite()
        real_connect = accounts._connect

        def racing():
            db = real_connect()
            # The rival claims the row between this redeem's SELECT and UPDATE.
            original = db.execute

            class Racing:
                def __getattr__(self, name):
                    return getattr(db, name)

                def execute(self, sql, params=()):
                    if sql.startswith("UPDATE"):
                        other = real_connect()
                        other.execute("UPDATE accounts SET email = 'winner@example.com', "
                                      "passphrase_hash = 'x' WHERE user_id = ?",
                                      (user_id,))
                        other.commit()
                        other.close()
                    return original(sql, params)
            return Racing()

        with mock.patch.object(accounts, "_connect", racing):
            with self.assertRaises(accounts.InviteRefused):
                accounts.redeem(code, "loser@example.com", PASSPHRASE)
        self.assertEqual(accounts.email_of(user_id), "winner@example.com")

    def test_the_code_itself_is_not_stored(self):
        _, code = accounts.invite()
        self.assertNotIn(code.encode(), accounts.db_path().read_bytes())

    def test_an_email_signs_in_to_one_account(self):
        make_account("a@example.com")
        _, code = accounts.invite()
        with self.assertRaises(accounts.EmailTaken):
            accounts.redeem(code, " A@Example.com ", PASSPHRASE)

    def test_a_short_passphrase_is_refused_and_the_invite_survives(self):
        _, code = accounts.invite()
        with self.assertRaises(accounts.PassphraseRefused):
            accounts.redeem(code, "a@example.com", "short")
        accounts.redeem(code, "a@example.com", PASSPHRASE)

    def test_the_user_id_is_a_valid_home_and_says_nothing_about_the_person(self):
        from tools import paths
        user_id = make_account("priya@example.com")
        paths.user_home(user_id)
        self.assertNotIn("priya", user_id)

    def test_the_accounts_store_is_global_not_a_user_store(self):
        make_account("a@example.com")
        self.assertEqual(accounts.db_path(), self.home / "data" / "accounts.db")
        self.assertFalse((self.home / "users").exists(),
                         "creating an account made a user home")


class TestSignIn(_Home):

    def test_the_right_passphrase_names_the_account(self):
        user_id = make_account("a@example.com")
        self.assertEqual(accounts.authenticate("A@example.com", PASSPHRASE), user_id)

    def test_a_wrong_passphrase_and_an_unknown_email_both_name_nobody(self):
        make_account("a@example.com")
        self.assertIsNone(accounts.authenticate("a@example.com", PASSPHRASE + "!"))
        self.assertIsNone(accounts.authenticate("nobody@example.com", PASSPHRASE))
        self.assertIsNone(accounts.authenticate("", ""))

    def test_an_unredeemed_invite_cannot_sign_in(self):
        accounts.invite()
        self.assertIsNone(accounts.authenticate("", PASSPHRASE))

    def test_the_passphrase_is_not_stored(self):
        make_account("a@example.com")
        self.assertNotIn(PASSPHRASE.encode(), accounts.db_path().read_bytes())


class TestSessions(_Home):

    def setUp(self):
        super().setUp()
        self.user = make_account("a@example.com")
        self.token = accounts.issue_session(self.user)

    def test_a_fresh_session_names_its_user(self):
        self.assertEqual(accounts.session_user(self.token), self.user)

    def test_absent_and_malformed_name_nobody(self):
        for token in ("", "garbage", "a.b", "a.b.c.d", None):
            with self.subTest(token=token):
                self.assertIsNone(accounts.session_user(token))

    def test_a_tampered_user_names_nobody(self):
        other = make_account("b@example.com")
        _, expiry, mac = self.token.split(".")
        self.assertIsNone(accounts.session_user(f"{other}.{expiry}.{mac}"),
                          "a cookie edited to name another user was accepted")

    def test_a_tampered_expiry_names_nobody(self):
        user, expiry, mac = self.token.split(".")
        later = int(expiry) + 10 ** 6
        self.assertIsNone(accounts.session_user(f"{user}.{later}.{mac}"))

    def test_a_tampered_mac_names_nobody(self):
        flipped = self.token[:-1] + ("0" if self.token[-1] != "0" else "1")
        self.assertIsNone(accounts.session_user(flipped))

    def test_an_expired_session_names_nobody(self):
        past = time.time() - accounts.SESSION_TTL_SECONDS - 1
        token = accounts.issue_session(self.user, now=past)
        self.assertIsNone(accounts.session_user(token))
        self.assertIsNone(accounts.session_user(
            self.token, now=time.time() + accounts.SESSION_TTL_SECONDS + 1))

    def test_a_session_signed_under_another_secret_names_nobody(self):
        with mock.patch.dict(os.environ, {accounts.SECRET_ENV: "y" * 48}):
            self.assertIsNone(accounts.session_user(self.token),
                              "rotating the secret did not sign everyone out")
        self.assertNotEqual(SECRET, "y" * 48)

    def test_a_deleted_account_stops_at_once(self):
        """A valid signature is necessary, not sufficient (A6 relies on this)."""
        self.assertEqual(accounts.delete(self.user), 1)
        self.assertIsNone(accounts.session_user(self.token))
        self.assertEqual(accounts.delete(self.user), 0, "a second delete found a row")

    def test_a_deleted_accounts_email_is_not_left_in_the_file(self):
        """
        SQLite leaves a deleted row's bytes in the free list unless told not
        to; the residue walker reads bytes, so this is the store-level half.
        """
        accounts.delete(self.user)
        self.assertNotIn(b"a@example.com", accounts.db_path().read_bytes())
        self.assertNotIn(self.user.encode(), accounts.db_path().read_bytes())


class TestAResetEndsEverySession(_Home):
    """
    Q45. A reset because a passphrase leaked is worthless if a cookie taken
    with it keeps working, and it would have for up to 14 days.
    """

    def setUp(self):
        super().setUp()
        self.user = make_account("a@example.com")
        self.stolen = accounts.issue_session(self.user)

    def test_a_session_from_before_the_reset_names_nobody(self):
        accounts.reset(self.user)
        self.assertIsNone(accounts.session_user(self.stolen))

    def test_and_stays_ended_once_the_friend_redeems(self):
        """
        The case the epoch exists for. Clearing the email alone ends the
        session only until the redeem makes the row active again.
        """
        code = accounts.reset(self.user)
        self.assertEqual(accounts.redeem(code, "a@example.com", "a new passphrase!"),
                         self.user, "the reset code claimed a different account")
        self.assertIsNone(accounts.session_user(self.stolen),
                          "a cookie issued before the reset works again after it")
        fresh = accounts.issue_session(self.user)
        self.assertEqual(accounts.session_user(fresh), self.user)

    def test_the_old_passphrase_stops_and_the_new_one_works(self):
        code = accounts.reset(self.user)
        self.assertIsNone(accounts.authenticate("a@example.com", PASSPHRASE))
        accounts.redeem(code, "a@example.com", "a new passphrase!")
        self.assertIsNone(accounts.authenticate("a@example.com", PASSPHRASE))
        self.assertEqual(accounts.authenticate("a@example.com", "a new passphrase!"),
                         self.user)

    def test_the_old_invite_code_does_not_redeem_the_reset(self):
        old = make_account("b@example.com")
        code = accounts.reset(old)
        accounts.reset(old)  # superseded
        with self.assertRaises(accounts.InviteRefused):
            accounts.redeem(code, "b@example.com", PASSPHRASE)

    def test_resetting_nobody_is_an_error(self):
        with self.assertRaises(KeyError):
            accounts.reset("0000000000000000")

    def test_other_accounts_keep_their_sessions(self):
        other = make_account("b@example.com")
        theirs = accounts.issue_session(other)
        accounts.reset(self.user)
        self.assertEqual(accounts.session_user(theirs), other)


class TestAStoreFromA5(_Home):
    """
    `accounts.db` written before the epoch existed: no `session_epoch`, and a
    `deleted_at` nothing writes any more. It must open, and its accounts sign
    in at epoch 0.
    """

    def test_it_gains_the_epoch_and_keeps_its_accounts(self):
        path = accounts.db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path)
        db.execute("""CREATE TABLE accounts (
            user_id TEXT PRIMARY KEY, email TEXT UNIQUE, passphrase_hash TEXT,
            invite_code TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL,
            deleted_at TEXT)""")
        db.execute("INSERT INTO accounts VALUES (?, ?, ?, ?, ?, NULL)",
                   ("00000000000000aa", "old@example.com",
                    accounts.hash_passphrase(PASSPHRASE), "digest", "then"))
        db.commit()
        db.close()
        self.assertEqual(accounts.authenticate("old@example.com", PASSPHRASE),
                         "00000000000000aa")
        token = accounts.issue_session("00000000000000aa")
        self.assertEqual(accounts.session_user(token), "00000000000000aa")
        accounts.reset("00000000000000aa")
        self.assertIsNone(accounts.session_user(token))

    def test_a_session_cannot_be_issued_for_an_id_that_is_not_one(self):
        with self.assertRaises(ValueError):
            accounts.issue_session("../etc")


class TestTheAdminScriptInvites(_Home):

    def test_invite_prints_a_code_that_redeems(self):
        import contextlib
        import io

        from scripts import admin

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(admin.main(["invite"]), 0)
        code = out.getvalue().splitlines()[0].split(": ", 1)[1]
        accounts.redeem(code, "friend@example.com", PASSPHRASE)
        self.assertIsNotNone(accounts.authenticate("friend@example.com", PASSPHRASE))


class TestTheAdminScriptResetsListsAndDeletes(_Home):
    """The other three subcommands (A6), through `main` as the operator runs it."""

    def _admin(self, *argv):
        import contextlib
        import io

        from scripts import admin

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = admin.main(list(argv))
        return status, out.getvalue(), err.getvalue()

    def test_list_users_names_every_account_and_no_secret(self):
        a = make_account("a@example.com")
        pending, _ = accounts.invite()
        status, out, _ = self._admin("list-users")
        self.assertEqual(status, 0)
        self.assertIn(f"{a}  ", out)
        self.assertIn("a@example.com", out)
        self.assertIn(f"{pending}  ", out)
        self.assertIn("(awaiting redeem)", out)
        self.assertIn("2 account(s)", out)
        self.assertNotIn("scrypt", out)

    def test_reset_passphrase_by_email_ends_the_session_and_prints_a_code(self):
        a = make_account("a@example.com")
        token = accounts.issue_session(a)
        status, out, _ = self._admin("reset-passphrase", "a@example.com")
        self.assertEqual(status, 0)
        self.assertIsNone(accounts.session_user(token))
        code = out.splitlines()[0].split(": ", 1)[1].strip()
        accounts.redeem(code, "a@example.com", "a new passphrase!")
        self.assertEqual(accounts.authenticate("a@example.com", "a new passphrase!"), a)

    def test_an_unknown_account_is_said_and_nothing_changes(self):
        make_account("a@example.com")
        for argv in (("reset-passphrase", "nobody@example.com"),
                     ("delete-user", "nobody@example.com", "--yes")):
            with self.subTest(argv[0]):
                status, _, err = self._admin(*argv)
                self.assertEqual(status, 1)
                self.assertIn("no account", err)
        self.assertEqual(len(accounts.list_accounts()), 1)

    def test_delete_user_goes_through_the_facade_the_api_uses(self):
        """One deletion path: the script must not grow its own."""
        a = make_account("a@example.com")
        calls = []

        def spy(user_id, **kwargs):
            calls.append((user_id, kwargs))
            return {"user_id": user_id, "account": 1, "files": 0, "bytes": 0,
                    "areas": {}}

        with mock.patch("agents.orchestrator.delete_user_data", spy):
            status, out, _ = self._admin("delete-user", a, "--yes")
        self.assertEqual(status, 0)
        self.assertEqual(calls, [(a, {"ignore_active_runs": False})])
        self.assertIn("account row 1", out)

    def test_delete_user_finishes_a_deletion_that_lost_its_row(self):
        from tools import paths

        a = make_account("a@example.com")
        (paths.user_home(a) / "outputs").mkdir(parents=True)
        (paths.user_home(a) / "outputs" / "resume.tex").write_text("x")
        accounts.delete(a)  # the row went; the tree did not
        status, out, _ = self._admin("delete-user", a, "--yes")
        self.assertEqual(status, 0)
        self.assertIn("account row 0, 1 file(s)", out)
        self.assertFalse(paths.user_home(a).exists())
        status, _, err = self._admin("delete-user", a, "--yes")
        self.assertEqual(status, 1)
        self.assertIn("nothing was deleted", err)

    def test_delete_user_asks_and_a_wrong_answer_deletes_nothing(self):
        a = make_account("a@example.com")
        with mock.patch("builtins.input", return_value="not the id"):
            status, _, err = self._admin("delete-user", a)
        self.assertEqual(status, 1)
        self.assertTrue(accounts.active(a))
        with mock.patch("builtins.input", return_value=a):
            status, _, _ = self._admin("delete-user", a)
        self.assertEqual(status, 0)
        self.assertFalse(accounts.active(a))
        self.assertIsNone(accounts.find(a))


if __name__ == "__main__":
    unittest.main()

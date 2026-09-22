"""
The operator's side of an invite-only instance (pilot plan A5, A6).

There is no public signup and no self-service reset, so this script is both.
It runs where the data lives — on Fly, `fly ssh console -C "python
scripts/admin.py invite"` — and it reaches accounts through the facade, the
same way both UIs do, so there is one path into the store rather than two.

    python scripts/admin.py invite                    # new account; prints its code
    python scripts/admin.py list-users                # id, email, created
    python scripts/admin.py reset-passphrase <who>    # prints a re-invite code
    python scripts/admin.py delete-user <who> --yes   # everything, for good

`<who>` is a user id or the email the account signs in with.

A code is printed once and stored only as a digest. Send it to the friend;
they redeem it on the sign-in screen with their email and a passphrase. Lost
before it is redeemed, it cannot be recovered — run the command again.

**A reset is a re-invite of the same account.** It ends every session the
account has, at once and for good (Q45), and the friend chooses the new
passphrase themselves when they redeem the code, so you never know it. Their
jobs, profiles and resumes are untouched.

**`delete-user` calls `delete_user_data`, the facade `DELETE /api/account`
calls.** Two deletion paths would be the twin-path bug pointed at the one
thing that has to be provably complete. It refuses while the user has a run
in progress; a run a crashed server left marked `running` never clears, so
`--ignore-active-runs` is there for after you have checked that no server is
actually running it.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Everything printed here is ASCII (token_hex / token_urlsafe ids and codes,
# fixed labels) except an email, which goes through `_say` so a cp1252
# console cannot kill the one line a command exists to print (R81).


def _say(line: str) -> None:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(line.encode(encoding, errors="backslashreplace").decode(encoding))


def _resolve(who: str):
    from agents.orchestrator import find_account

    user_id = find_account(who)
    if user_id is None:
        print(f"no account is {who!r} (try list-users)", file=sys.stderr)
    return user_id


def invite(args) -> int:
    from agents.orchestrator import invite_account

    user_id, code = invite_account()
    print(f"invite code: {code}")
    print(f"user id:     {user_id}")
    return 0


def list_users(args) -> int:
    from agents.orchestrator import list_accounts

    accounts = list_accounts()
    for account in accounts:
        # None is "not redeemed yet", and says so: a blank column would read
        # as an account with no email, which no redeemed account is.
        email = account["email"] or "(awaiting redeem)"
        _say(f"{account['user_id']}  {account['created_at']}  {email}")
    print(f"{len(accounts)} account(s)")
    return 0


def reset_passphrase(args) -> int:
    from agents.orchestrator import reset_passphrase as reset

    user_id = _resolve(args.who)
    if user_id is None:
        return 1
    code = reset(user_id)
    print(f"reset code:  {code}")
    print(f"user id:     {user_id}")
    print("Every session this account had has ended. The friend redeems the "
          "code on the sign-in screen, as an invite, with their email and a "
          "new passphrase.")
    return 0


def delete_user(args) -> int:
    from agents.orchestrator import RunInProgress, delete_user_data, find_account

    # An id with no account row is still passed on: a deletion that removed
    # the row and then failed on the tree is finished by running this again.
    user_id = find_account(args.who) or (args.who if "@" not in args.who else None)
    if user_id is None:
        print(f"no account is {args.who!r} (try list-users)", file=sys.stderr)
        return 1
    if not args.yes:
        answer = input(f"Delete {user_id} and everything they have? This cannot "
                       f"be undone. Type the user id to confirm: ")
        if answer.strip() != user_id:
            print("not deleted", file=sys.stderr)
            return 1
    try:
        removed = delete_user_data(user_id,
                                   ignore_active_runs=args.ignore_active_runs)
    except RunInProgress as exc:
        print(f"not deleted: {exc}. If no server is running it, re-run with "
              f"--ignore-active-runs.", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"not deleted: {exc}", file=sys.stderr)
        return 1
    if not removed["account"] and not removed["files"]:
        print(f"no account and no data for {user_id!r}; nothing was deleted",
              file=sys.stderr)
        return 1
    areas = ", ".join(f"{name} {count}" for name, count
                      in sorted(removed["areas"].items())) or "none"
    print(f"deleted {user_id}: account row {removed['account']}, "
          f"{removed['files']} file(s), {removed['bytes']} bytes ({areas})")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("invite", help="create an account and print its invite code")
    commands.add_parser("list-users", help="every account: id, created, email")
    reset = commands.add_parser(
        "reset-passphrase",
        help="end an account's sessions and print a code to choose a new passphrase")
    reset.add_argument("who", help="user id or email")
    delete = commands.add_parser(
        "delete-user", help="delete an account and all of its data, for good")
    delete.add_argument("who", help="user id or email")
    delete.add_argument("--yes", action="store_true",
                        help="do not ask (for `fly ssh console -C`)")
    delete.add_argument("--ignore-active-runs", action="store_true",
                        help="delete even if the registry says a run is live")
    args = parser.parse_args(argv)
    return {"invite": invite, "list-users": list_users,
            "reset-passphrase": reset_passphrase,
            "delete-user": delete_user}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

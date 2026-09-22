"""
The operator's side of an invite-only instance (pilot plan A5, A6).

There is no public signup and no password reset, so this script is both. It
runs where the data lives — on Fly, `fly ssh console -C "python
scripts/admin.py invite"` — and it reaches accounts through the facade, the
same way both UIs do, so there is one path into the store rather than two.

    python scripts/admin.py invite      # a new account; prints its one-time code

Only `invite` exists yet. `reset-passphrase`, `list-users` and `delete-user`
ship with A6, beside the deletion facade `delete-user` must share with
`DELETE /api/account` — two deletion paths is the twin-path bug pointed at the
one thing that has to be provably complete.

The code is printed once and stored only as a digest. Send it to the friend;
they redeem it on the sign-in screen with their email and a passphrase. Lost
before it is redeemed, it cannot be recovered — invite again.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def invite() -> int:
    from agents.orchestrator import invite_account

    user_id, code = invite_account()
    # ASCII only (token_hex / token_urlsafe), so a cp1252 console cannot
    # swallow the one line this command exists to print.
    print(f"invite code: {code}")
    print(f"user id:     {user_id}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("invite", help="create an account and print its invite code")
    args = parser.parse_args(argv)
    return {"invite": invite}[args.command]()


if __name__ == "__main__":
    sys.exit(main())

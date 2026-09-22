"""
Where every store resolves, recorded so a later change can be held to it.

**Why this exists.** The pilot plan's A3 partitions the data home per user,
under a hard constraint: the *unscoped* layout — the checkout, the CLI, the
frozen baselines — must not move by a byte. `baseline.py verify --all` checks
the baseline files, but only on the one machine that has them, and it cannot
see a store that quietly started resolving somewhere else. This can: it asks
every store where it lives, the way the program asks, and compares the answer
with the one recorded before A3 touched anything.

Every stage after A3 that touches a path — A5's session, A7's deletion walk —
re-runs the same comparison rather than writing its own.

    python scripts/path_snapshot.py                 # print the unscoped layout
    python scripts/path_snapshot.py --user alice    # print alice's layout
    python scripts/path_snapshot.py write           # record the unscoped layout
    python scripts/path_snapshot.py verify          # hold the code to the record

`verify` checks three things and exits non-zero on any of them:

1. The unscoped layout, resolved from the repo root, equals the record.
2. The same layout resolved from a *foreign working directory* equals it too.
   Four caches used to resolve against the cwd (Q31), which is right on a
   laptop and wrong in a container; this is what keeps that from coming back.
3. Every path a scoped user resolves sits inside that user's home. A store
   that resolves outside it is shared between users, and nothing here is
   meant to be.

**Resolving must not create anything.** A snapshot that makes the directories
it reports is a snapshot that agrees with itself, and `verify` would litter a
`users/` tree into the checkout. Every resolver below is a pure path
computation; `test_path_snapshot` asserts the data home is untouched.

Paths are recorded relative to `data_home()`, so the record means the same
thing on every machine. Anything outside it is recorded as `!outside:<path>`,
which in the unscoped record should never appear.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RECORD = ROOT / "baselines" / "paths.unscoped.json"

# A profile whose master resume the snapshot resolves. Priya because she is
# committed, so the record means the same thing on a clean clone.
PROFILE = "priya_raghunathan"

# The user `verify` resolves a scoped layout for. Never created on disk.
PROBE_USER = "path-snapshot-probe"


def resolvers(user_id) -> dict:
    """
    Every store, asked where it lives for `user_id` (None = unscoped).

    One entry per thing the program writes. Adding a store means adding a line
    here, and `test_no_store_resolves_a_path_outside_paths` fails until
    somebody does — which is how this table stays a complete list rather than
    the list somebody remembered.
    """
    import config
    from agents import orchestrator
    from scripts import init_profile
    from tools import paths
    from tools.cache import job_cache
    from tools.cache import embedding_cache
    from tools.jobs import job_store, run_registry
    from tools.profile import profile_loader
    from tools.search import ats_search

    return {
        "jobs_db": lambda: job_store.db_path(user_id),
        "runs_db": lambda: run_registry.db_path(user_id),
        "profiles_dir": lambda: profile_loader.profiles_dir(user_id),
        "resumes_dir": lambda: init_profile.resume_dir(user_id),
        "outputs_root": lambda: orchestrator.user_outputs_root(user_id),
        "job_cache_dir": lambda: job_cache.cache_dir(user_id),
        "resume_embedding_cache_dir": lambda: embedding_cache.cache_dir(user_id),
        "llm_cache_dir": lambda: config.llm_cache_dir(user_id),
        "text_embedding_cache_dir": lambda: config.embedding_cache_dir(user_id),
        "learned_ats_file": lambda: ats_search.learned_file(user_id),
        "master_resume": lambda: orchestrator.master_resume_path(
            user_id, f"data/master_resumes/{PROFILE}.tex"),
        "home": lambda: paths.user_home(user_id),
    }


def snapshot(user_id=None) -> dict:
    from tools import paths

    base = paths.data_home().resolve()
    out = {}
    for name, resolve in resolvers(user_id).items():
        where = Path(resolve()).resolve()
        try:
            out[name] = where.relative_to(base).as_posix() or "."
        except ValueError:
            out[name] = f"!outside:{where.as_posix()}"
    return out


def _from_elsewhere() -> dict:
    """The unscoped layout as a process started in a foreign cwd sees it."""
    with tempfile.TemporaryDirectory() as elsewhere:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        done = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--json"],
            cwd=elsewhere, env=env, capture_output=True, text=True,
            encoding="utf-8",
        )
        if done.returncode != 0:
            raise RuntimeError(f"snapshot from a foreign cwd failed:\n{done.stderr}")
        return json.loads(done.stdout)


def _diff(label: str, expected: dict, got: dict) -> list:
    problems = []
    for name in sorted(set(expected) | set(got)):
        if expected.get(name) != got.get(name):
            problems.append(f"{label}: {name}: recorded {expected.get(name)!r}, "
                            f"resolved {got.get(name)!r}")
    return problems


def verify() -> list:
    if not RECORD.is_file():
        return [f"no record at {RECORD}; run `write` first"]
    recorded = json.loads(RECORD.read_text(encoding="utf-8"))

    problems = _diff("from the repo root", recorded, snapshot(None))
    problems += _diff("from a foreign cwd", recorded, _from_elsewhere())

    home = f"users/{PROBE_USER}"
    for name, where in snapshot(PROBE_USER).items():
        if where != home and not where.startswith(home + "/"):
            problems.append(f"scoped: {name} resolves to {where!r}, outside {home}/")
    return problems


def _print(text: str) -> None:
    # R81: a harness that dies printing its finding reports nothing.
    stream = sys.stdout
    try:
        stream.write(text + "\n")
    except UnicodeEncodeError:
        stream.write(text.encode("ascii", "backslashreplace").decode("ascii") + "\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", nargs="?", choices=("show", "write", "verify"),
                        default="show")
    parser.add_argument("--user", default=None,
                        help="resolve this user's layout instead of the unscoped one")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    if args.command == "write":
        RECORD.parent.mkdir(parents=True, exist_ok=True)
        RECORD.write_text(json.dumps(snapshot(None), indent=2) + "\n", encoding="utf-8")
        _print(f"recorded {RECORD.relative_to(ROOT).as_posix()}")
        return 0

    if args.command == "verify":
        problems = verify()
        for line in problems:
            _print(line)
        _print("path snapshot: " + ("MOVED" if problems else "unmoved"))
        return 1 if problems else 0

    layout = snapshot(args.user)
    if args.json:
        _print(json.dumps(layout))
    else:
        width = max(map(len, layout))
        for name, where in layout.items():
            _print(f"{name:<{width}}  {where}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

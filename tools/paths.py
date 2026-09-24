"""
Where things live, answered once, for both layouts this code runs in.

**The problem.** Ten modules compute `ROOT = Path(__file__).parent.parent...`
and reach out to `data/`, `user_profiles/` and `cache/` from there. That is
correct in a git checkout, where `ROOT` is the repo. It is wrong the moment
the package is installed, where `ROOT` is `site-packages` — and it fails in
two different ways depending on what the path is for:

* **Read-only assets** — `base_preamble.tex`, the ATS seed list, the profile
  template — simply are not there. The wheel built from this project contained
  nothing but `.py` files, so an installed copy could not render a resume at
  all. No test caught it because every test runs from the checkout.
* **User data** — profiles, resumes, the job and run databases, caches — would
  be *written into site-packages*. Where that is read-only it fails on first
  use; where it is not, it succeeds and puts somebody's resume inside their
  Python installation, to be deleted by the next upgrade.

The second is the same shape as Q15's multi-user blockers: a hardcoded path
that assumes one situation. Q15 says "cheap now, expensive later" about
threading a user id through these; this is the seam that makes that a
parameter rather than a rewrite.

**The rule.** Assets resolve *relative to the code*, because they ship with
it. User data resolves to a *writable base* that is nothing to do with where
the code is.

Running from a checkout keeps behaving exactly as before — same directories,
same files — because a developer's `data/` and `outputs/` are where they
expect them and the frozen baselines are measured against them. Installed, it
uses a real user directory.
"""

import os
import re
from pathlib import Path

# This file is `tools/paths.py`, so the package root is its parent and the
# repo root — in a checkout — is one above that.
PACKAGE = Path(__file__).resolve().parent
_ABOVE = PACKAGE.parent

# Assets that ship inside the wheel. Read-only at runtime; anything that grows
# is seeded from here and written to `data_home()`.
ASSETS = PACKAGE / "assets"

# Override for anyone who wants their data somewhere specific — a container
# volume, a test, a second profile set. Read at call time rather than import,
# so a test can set it without reloading modules.
HOME_ENV = "JOBSCOUT_HOME"


def in_checkout() -> bool:
    """
    Are we running from a source tree rather than an installed package?

    Decided by looking for the things only a checkout has next to the code.
    `pyproject.toml` alone is not enough — a wheel can land beside stray
    files — so this wants the project's own marker directories too.
    """
    return (_ABOVE / "pyproject.toml").is_file() and (_ABOVE / "tests").is_dir()


def data_home() -> Path:
    """
    The writable base for everything this program produces.

    Precedence, highest first:

        JOBSCOUT_HOME  >  the repo root, when running from a checkout
                       >  the platform's user data directory

    The middle case is what keeps a developer's world unchanged: `data/`,
    `outputs/` and `user_profiles/` stay exactly where they are, so the frozen
    baselines still measure the same files.

    The last case is hand-rolled rather than taking a dependency on
    `platformdirs` for three lines. `%LOCALAPPDATA%` on Windows,
    `$XDG_DATA_HOME` or `~/.local/share` elsewhere — the conventional places,
    and `JOBSCOUT_HOME` exists for anyone the conventions do not suit.
    """
    override = os.getenv(HOME_ENV)
    if override:
        return Path(override).expanduser()

    if in_checkout():
        return _ABOVE

    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    else:
        base = os.getenv("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "jobscout"


def asset(*parts) -> Path:
    """A read-only file that ships with the package."""
    return ASSETS.joinpath(*parts)


# Where a scoped user's data lives, under the data home. A directory, not a
# prefix on file names, so deleting a person is deleting one directory (A7).
USERS_DIR = "users"

# What a user id may look like. Strict because it becomes a directory name:
# no dots means no `..`, no separators means no escaping the users/ tree, and
# a URL or a profile name passed in the wrong argument slot fails here rather
# than becoming somebody's home.
_USER_ID = re.compile(r"[a-z0-9_-]{1,64}")


def user_home(user_id) -> Path:
    """
    The base under which one user's data lives. **`user_id` has no default.**

    `None` is the unscoped layout — the checkout, the CLI, one person's
    laptop — and it returns `data_home()` itself, not a computation that
    happens to agree with it. That is what keeps the frozen baselines and
    every developer's `data/` exactly where they were (pilot plan A3's hard
    constraint, checked by `scripts/path_snapshot.py verify`).

    A string is a scoped user: `data_home()/users/<user_id>/`, holding the
    same tree the unscoped layout holds at the root.

    `None` is a *stated* choice, never an omitted one. Leaving the argument
    out is a `TypeError`; there is no ambient current user, because an
    ambient default is unknown rendered as a value, and a `ContextVar` would
    not follow `start_run` into its worker thread. Hosted mode passing `None`
    is the gap A5 closes (`test_hosted_mode_has_no_unscoped_call_site`).
    """
    if user_id is None:
        return data_home()
    if not isinstance(user_id, str) or not _USER_ID.fullmatch(user_id):
        raise ValueError(f"not a user id: {user_id!r}")
    return data_home() / USERS_DIR / user_id


def remove_user_home(user_id: str) -> dict:
    """
    Delete one scoped user's whole tree and say what went (pilot plan A6).

    Returns `{"files": n, "bytes": n, "areas": {top-level entry: files}}`,
    all zero when there was no tree: a deletion states its count, as a filter
    does. Symlinks are removed, never followed, so nothing outside the tree is
    touched or counted.

    **Refuses `None`.** The unscoped home is `data_home()` itself — in a
    checkout, the repository — and there is no reading of "delete the user"
    under which that is the thing to remove. `user_home` refuses an id that is
    not one, so a `..` cannot reach this either.
    """
    import shutil

    if user_id is None:
        raise ValueError("refusing to delete the unscoped data home")
    home = user_home(user_id)
    removed = {"files": 0, "bytes": 0, "areas": {}}
    if not home.is_dir() or home.is_symlink():
        return removed
    for root, dirs, files in os.walk(home):
        area = Path(root).relative_to(home).parts[:1]
        for name in files + [d for d in dirs if os.path.islink(os.path.join(root, d))]:
            path = Path(root, name)
            key = area[0] if area else name
            removed["files"] += 1
            removed["bytes"] += path.lstat().st_size
            removed["areas"][key] = removed["areas"].get(key, 0) + 1
    shutil.rmtree(home)
    return removed


def user_path(*parts, user_id, create_parent: bool = False) -> Path:
    """
    A file or directory under `user_home(user_id)`.

    `user_id` is keyword-only and required. It was not always here, and the
    signature before A3 was `user_path(*parts)` — so a positional first
    argument would have taken an old `user_path("data", "jobs.db")` and
    quietly made `"data"` a user. Keyword-only turns every unmigrated call
    into a `TypeError` instead of a directory nobody asked for.

    `create_parent` because most callers are about to write, and every one of
    them making its own `mkdir(parents=True)` is how a directory ends up
    created in four places and missed in a fifth.
    """
    path = user_home(user_id).joinpath(*parts)
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def stored_path(stored, *, user_id) -> Path:
    """
    Resolve a path a user's data *stores* — a profile's `master_resume_path`
    — for the user it belongs to.

    A relative path anchors at the user's home, not at the code:
    `data/master_resumes/` is the user's own file and lives wherever their
    data lives, while `Path(__file__).parent.parent` is the install directory.
    In a checkout those are the same directory, which is the only reason the
    orchestrator's copy of this survived being written the wrong way (R86).
    In a container it is `/app/data/` against `/data/data/` — and `/app/data/`
    is dockerignored, so it never exists and every run dies on a profile that
    was imported perfectly.

    Stored relative, resolved per user: one profile file means the same thing
    in the unscoped layout and under `users/<id>/`, so nothing is rewritten
    when a profile moves between them.

    Unscoped, any path is honoured: the CLI's user owns the whole disk and may
    keep a resume anywhere. **Scoped, the resolved path must lie inside the
    user's own home**, or a profile field is a way to make the pipeline read
    somebody else's resume, the partition's whole purpose undone by one
    string. Resolved means `..` collapsed and symlinks followed, and the test
    is by path component, so `users/bobby` is not inside `users/bob`.

    This checked absolute paths only, and joined a relative one unresolved:
    `../bob/data/master_resumes/r.tex` left alice's home (Q64, R108). The
    check now runs on whatever the stored string becomes. It refuses rather
    than falling back, because there is no right file to fall back to.
    """
    path = Path(stored)
    if not path.is_absolute():
        path = user_home(user_id) / path
    if user_id is not None:
        home = user_home(user_id).resolve()
        if not path.resolve().is_relative_to(home):
            raise ValueError(
                f"The resume path {stored!r} points outside this account's own "
                "files, so it was not read.")
    return path


# There was a `seeded_user_file()` here that copied a shipped file into the
# data home on first touch, for the one case that needed it —
# `ats_companies.json`, which ships a starter list and grows as jobs are
# discovered.
#
# It is gone because the copy is taken **once**: a later release shipping more
# company slugs would never reach anyone who had already run the program, and
# there would be no error to notice — just a list frozen on the day they
# installed. `ats_search` now keeps the two files apart and returns their
# union, so upgrades bring new slugs and learned ones survive.
#
# Deleted rather than left for a future caller. A helper with no callers is
# the recurring bug of this codebase pointed at itself.


def outputs_root(output_dir: str = "outputs", *, user_id) -> Path:
    """
    Where generated resumes go, anchored somewhere that survives a deploy.

    R80 moved ten modules off `__file__` so an installed copy could find its
    assets. This is the eleventh, missed because it resolves a directory the
    program *writes* rather than one it reads at import — `Path("outputs")`
    is relative to the working directory, which is fine on a laptop where the
    working directory is the checkout and fatal in a container where it is a
    layer that gets replaced on every deploy.

    The symptom would have been quiet: `data/` on the volume, so runs.db and
    the board survive, while every PDF the board links to is gone. A job list
    that remembers everything and can produce nothing.

    An absolute path is honoured as given. A relative one is anchored at
    `user_home(user_id)`, which unscoped **is the repo root** in a checkout —
    so a developer's `outputs/` does not move and the frozen baselines still
    measure the same files — and scoped is that user's own directory, so two
    people's runs on one day are two directories (A2.3).
    """
    given = Path(output_dir)
    return given if given.is_absolute() else user_home(user_id) / given

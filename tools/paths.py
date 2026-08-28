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


def user_path(*parts, create_parent: bool = False) -> Path:
    """
    A file or directory under `data_home()`.

    `create_parent` because most callers are about to write, and every one of
    them making its own `mkdir(parents=True)` is how a directory ends up
    created in four places and missed in a fifth.
    """
    path = data_home().joinpath(*parts)
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def seeded_user_file(*parts) -> Path:
    """
    A file the program grows, starting from a copy of the shipped seed.

    `ats_companies.json` is the case: it ships with a starter list of company
    slugs and `harvest_slugs()` adds to it as jobs are discovered. Read-only
    in the package and mutable in use, so the seed is copied out on first
    touch rather than written back into the installation.
    """
    target = user_path(*parts, create_parent=True)
    if not target.exists():
        source = asset(parts[-1])
        if source.is_file():
            target.write_bytes(source.read_bytes())
    return target

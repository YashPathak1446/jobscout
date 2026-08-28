r"""
What the wheel claims to need, against what the code actually imports.

R80 cost most of a day to a packaging bug — ten modules resolving paths from
`__file__`, so an installed copy had no LaTeX preamble. It was fixed and **no
test was written**, and the same class of bug was sitting in the same file the
whole time: `api/main.py` imports FastAPI, the README tells you to run
`uvicorn`, `.claude/launch.json` launches it, and neither was declared in
`pyproject.toml` or `requirements.txt`. `api` was not in `packages` either, so
the wheel did not contain it.

It resolved anyway because `google-adk` pulls FastAPI in transitively. That is
not a dependency, it is a coincidence, and a version bump ends it.

**Why nothing caught it:** every other test imports from a checkout, where the
repo root is on `sys.path` and the developer's environment already has
everything. The manifest is the one artifact that is never exercised by
running the suite the normal way. So these read the manifest directly.

The rule this file enforces, in one line: **a third-party module that shipped
code imports must be a declared dependency, and a first-party package it
imports must be in the wheel.**
"""

import ast
import sys
import unittest
from importlib.metadata import packages_distributions
from pathlib import Path

ROOT = Path(__file__).parent.parent

try:
    import tomllib
except ModuleNotFoundError:                      # Python 3.10
    tomllib = None


def _normalise(name: str) -> str:
    """PEP 503: `uvicorn[standard]` and `Python-DotEnv` are one name."""
    return name.split("[")[0].split(">")[0].split("=")[0].split("<")[0] \
        .strip().lower().replace("_", "-").replace(".", "-")


def _manifest():
    with open(ROOT / "pyproject.toml", "rb") as handle:
        return tomllib.load(handle)


def _declared(manifest) -> set:
    """Every distribution the wheel says it needs, extras included."""
    project = manifest["project"]
    names = list(project.get("dependencies") or [])
    for extra in (project.get("optional-dependencies") or {}).values():
        names.extend(extra)
    return {_normalise(n) for n in names}


def _shipped_roots(manifest):
    """The import roots the wheel **claims** to contain."""
    setuptools = manifest["tool"]["setuptools"]
    packages = setuptools.get("packages") or []
    modules = setuptools.get("py-modules") or []
    return {p.split(".")[0] for p in packages} | set(modules)


# Directories that hold Python and are deliberately not shipped, with the
# reason. Anything else holding Python has to be in the manifest.
NOT_SHIPPED = {"tests": "the suite is not part of the product"}


def _source_roots():
    """
    Every first-party import root, **read off the filesystem**.

    Deliberately not derived from the manifest. The first draft of this file
    walked `_shipped_roots`, which meant deleting `api` from `packages` also
    deleted `api/main.py` from what the tests looked at — so both of them
    passed on the broken manifest. A test that asks its subject which parts of
    itself to examine cannot fail on the part left out.
    """
    roots = set()
    for path in ROOT.iterdir():
        if path.name.startswith(".") or path.name in NOT_SHIPPED:
            continue
        if path.suffix == ".py":
            roots.add(path.stem)
        elif path.is_dir() and any(
                p for p in path.rglob("*.py")
                if "node_modules" not in p.parts and "__pycache__" not in p.parts):
            roots.add(path.name)
    return roots


def _source_files():
    for root in sorted(_source_roots()):
        path = ROOT / root
        if path.is_dir():
            yield from (p for p in sorted(path.rglob("*.py"))
                        if "__pycache__" not in p.parts)
        elif (ROOT / f"{root}.py").exists():
            yield ROOT / f"{root}.py"


def _imports(path: Path) -> set:
    """Top-level names imported by one module, relative imports excluded."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # `level` > 0 is a relative import: first-party by construction.
            if node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found


@unittest.skipIf(tomllib is None, "needs tomllib (Python 3.11+)")
class TestTheManifestCoversWhatTheCodeImports(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.manifest = _manifest()
        cls.declared = _declared(cls.manifest)
        cls.shipped = _shipped_roots(cls.manifest)
        cls.roots = _source_roots()
        cls.files = list(_source_files())

    def test_the_wheel_ships_the_code_it_is_made_of(self):
        """
        `api` was importable in a checkout and absent from the wheel.

        Every directory holding first-party Python is either in the manifest
        or in `NOT_SHIPPED` with a reason. Nothing gets to be neither, which
        is what `api` was — reachable from the repo root, absent from a
        `pip install`, and nothing said so.
        """
        missing = sorted(self.roots - self.shipped)
        self.assertEqual(missing, [], (
            "these hold first-party Python and are in neither "
            "[tool.setuptools] packages / py-modules nor NOT_SHIPPED, so a "
            f"pip install does not contain them: {missing}"))

    def test_every_third_party_import_is_a_declared_dependency(self):
        """
        The one that would have caught FastAPI.

        Resolved via `packages_distributions`, which maps an import name to
        the distributions providing it in *this* environment — so `bs4` finds
        beautifulsoup4 and `dotenv` finds python-dotenv without a hand-written
        table that would rot. An import satisfied only by something else's
        transitive dependency has no entry in `declared` and fails here.
        """
        provided = packages_distributions()
        offenders = []

        for path in self.files:
            for name in sorted(_imports(path)):
                if (name in self.roots or name in sys.stdlib_module_names
                        or (ROOT / name).is_dir()
                        or (ROOT / f"{name}.py").exists()):
                    continue
                dists = {_normalise(d) for d in provided.get(name, [])}
                if not dists:
                    # Not installed here. Cannot judge it, and guessing would
                    # make this test fail for the wrong reason on a machine
                    # with a lean environment.
                    continue
                if not (dists & self.declared):
                    offenders.append(
                        f"  {path.relative_to(ROOT).as_posix()}: "
                        f"imports `{name}` (from {sorted(dists)}), "
                        f"declared: no")

        self.assertEqual(offenders, [], "\n".join(
            ["these are imported by shipped code and declared in no manifest, "
             "so they resolve only by someone else's transitive dependency:"]
            + sorted(set(offenders))))

    def test_requirements_and_pyproject_do_not_disagree(self):
        """
        Two manifests are two places to forget, which is how this started.

        `requirements.txt` is the file people already know; `pyproject.toml`
        is what pip installs from. A package in neither is the bug above; a
        package in only one is the same bug with a delay on it.
        """
        text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        listed = {
            _normalise(line) for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        only_in_requirements = listed - self.declared
        self.assertEqual(sorted(only_in_requirements), [], (
            "declared in requirements.txt and not in pyproject.toml, so a "
            "pip install of the package does not get them: "
            f"{sorted(only_in_requirements)}"))


if __name__ == "__main__":
    unittest.main()

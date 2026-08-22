"""
Freeze, verify and archive measurement baselines.

Every scoring claim in `known_questions.md` — R14's 8/20, R15's 4/20, Q7's
0/20 — is a comparison against a frozen set of enriched JDs and the analysis
they produced. Those files are gitignored, because they carry employer names
and resume content that does not belong in a public repo. That leaves them
existing on exactly one machine, which is the same failure shape as R12: a
load-bearing thing invisible from inside the repo.

This does not put the content in git. It records a manifest — checksums,
record counts, provenance — so you can always answer "is the baseline I have
the one those numbers were taken against?", and it can pack the baseline into
a single archive you store wherever you keep backups.

Usage:
    python scripts/baseline.py write   <name>   # record a manifest
    python scripts/baseline.py verify  <name>   # check files against it
    python scripts/baseline.py archive <name>   # pack into a .zip to store
    python scripts/baseline.py verify  --all

Location: jobscout_v3/scripts/baseline.py
"""

import argparse
import hashlib
import json
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
BASELINES = ROOT / "baselines"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_path(name: str) -> Path:
    return BASELINES / f"{name}.manifest.json"


def describe(path: Path) -> dict:
    """Checksum plus a record count, so a truncated file is obvious."""
    entry = {"sha256": sha256(path), "bytes": path.stat().st_size}

    if path.suffix == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                entry["records"] = len(data)
        except (json.JSONDecodeError, OSError):
            entry["records"] = None

    return entry


def cmd_write(name: str) -> int:
    directory = BASELINES / name
    if not directory.is_dir():
        print(f"No such baseline: {directory}")
        return 1

    files = sorted(f for f in directory.iterdir() if f.is_file())
    manifest = {
        "baseline": name,
        "recorded": date.today().isoformat(),
        "note": (
            "Frozen measurement set. Contents are gitignored; this manifest is "
            "committed so a lost or altered baseline is detectable."
        ),
        "files": {f.name: describe(f) for f in files},
    }

    manifest_path(name).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {manifest_path(name).relative_to(ROOT)}")
    for filename, entry in manifest["files"].items():
        records = f"{entry['records']} records" if entry.get("records") else ""
        print(f"    {filename:56} {entry['bytes']//1024:5} KB  {records}")
    return 0


def cmd_verify(name: str) -> int:
    path = manifest_path(name)
    if not path.exists():
        print(f"No manifest for {name}. Run: python scripts/baseline.py write {name}")
        return 1

    manifest = json.loads(path.read_text(encoding="utf-8"))
    directory = BASELINES / name

    print(f"{name}  (recorded {manifest['recorded']})")

    if not directory.is_dir():
        print("  MISSING ENTIRELY — every measurement against this baseline is "
              "unreproducible until it is restored from your archive.")
        return 2

    problems = 0
    for filename, expected in manifest["files"].items():
        target = directory / filename
        if not target.exists():
            print(f"  MISSING   {filename}")
            problems += 1
            continue
        actual = sha256(target)
        if actual != expected["sha256"]:
            print(f"  CHANGED   {filename}")
            print(f"            expected {expected['sha256'][:16]}…")
            print(f"            actual   {actual[:16]}…")
            problems += 1
        else:
            print(f"  ok        {filename}")

    extra = sorted(
        f.name for f in directory.iterdir()
        if f.is_file() and f.name not in manifest["files"]
    )
    for filename in extra:
        print(f"  UNTRACKED {filename}  (present but not in the manifest)")

    if problems:
        print(f"\n{problems} problem(s). Measurements taken against this baseline "
              f"are not comparable to ones taken before the change.")
        return 2

    print("\nBaseline matches the manifest.")
    return 0


def cmd_archive(name: str) -> int:
    directory = BASELINES / name
    if not directory.is_dir():
        print(f"No such baseline: {directory}")
        return 1

    out = ROOT.parent / f"jobscout-baseline-{name}"
    archive = shutil.make_archive(str(out), "zip", root_dir=directory)
    size = Path(archive).stat().st_size // 1024

    print(f"Wrote {archive}  ({size} KB)")
    print()
    print("This is outside the repo on purpose — it holds resume content and")
    print("employer names. Move it somewhere durable (cloud drive, password")
    print("manager vault, external disk). It is the only copy that survives")
    print("losing this machine.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Manage measurement baselines.")
    ap.add_argument("command", choices=["write", "verify", "archive"])
    ap.add_argument("name", nargs="?", help="Baseline directory name")
    ap.add_argument("--all", action="store_true", help="verify: check every manifest")
    args = ap.parse_args()

    if args.command == "verify" and args.all:
        manifests = sorted(BASELINES.glob("*.manifest.json"))
        if not manifests:
            print("No manifests found.")
            return 1
        worst = 0
        for m in manifests:
            worst = max(worst, cmd_verify(m.name.replace(".manifest.json", "")))
            print()
        return worst

    if not args.name:
        ap.error("a baseline name is required (or --all with verify)")

    return {"write": cmd_write, "verify": cmd_verify, "archive": cmd_archive}[
        args.command
    ](args.name)


if __name__ == "__main__":
    sys.exit(main())

"""
Bootstrap a user profile from a master resume.

Onboarding today means hand-writing every field of a profile JSON, including
the eight in `personal_info` that the resume header already states and an
importance tier for every component. This fills in everything derivable and
leaves placeholders only where a human genuinely has to decide.

Usage:
    python scripts/init_profile.py --resume data/master_resumes/jane.tex --name jane
    python scripts/init_profile.py --resume ... --name jane --force   # overwrite

What it derives (see tools/profile/derivation.py):
    personal_info        name, email, phone, github, linkedin, school,
                         degree, graduation date and term
    component_importance from resume order — top-2 high, next-4 medium

What it deliberately leaves for you:
    location, visa_status, us_citizen, permanent_resident
        Legal and eligibility meaning a resume does not reliably state. An
        address line is where you live, not where you are allowed to work.
    target_roles, locations, exclude_keywords
        Preferences, not facts about the resume.

Location: jobscout_v3/scripts/init_profile.py
"""

import argparse
import json
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.profile.derivation import (  # noqa: E402
    derive_component_importance,
    derive_conditional_triggers,
    derive_personal_info,
    merge_conditional_triggers,
)
from tools.resume.resume_parser import ResumeParser  # noqa: E402

ROOT = Path(__file__).parent.parent
TEMPLATE = ROOT / "user_profiles" / "template.json"

# Fields a human must confirm. Listed so the script can report them rather
# than let a placeholder slip into a live run.
NEEDS_HUMAN = {
    "personal_info": ["location", "visa_status", "us_citizen", "permanent_resident"],
    "job_preferences": ["target_roles", "locations", "exclude_keywords"],
}


def build_profile(resume_path: Path, name: str) -> dict:
    parser = ResumeParser(str(resume_path), skip_embeddings=True)
    resume = parser.parsed_resume

    profile = json.loads(TEMPLATE.read_text(encoding="utf-8"))

    profile["user_id"] = name
    profile["created"] = date.today().isoformat()
    profile["description"] = f"Profile for {resume.name or name}"

    derived_info = derive_personal_info(resume)
    profile["personal_info"].update(derived_info)

    rp = profile["resume_preferences"]
    try:
        rel = resume_path.resolve().relative_to(ROOT.resolve())
        rp["master_resume_path"] = str(rel).replace("\\", "/")
    except ValueError:
        rp["master_resume_path"] = str(resume_path)

    rp["component_importance"] = {
        "experiences": derive_component_importance([e.id for e in resume.experiences]),
        "projects": derive_component_importance([p.id for p in resume.projects]),
    }

    # Conditional triggers. The template ships none, so in practice this is
    # pure derivation — but it goes through the merge so that regenerating
    # over a profile someone has since tuned keeps their rules rather than
    # flattening them.
    for section, components in (("experiences", resume.experiences),
                                ("projects", resume.projects)):
        rp[section]["conditional_inclusion"] = merge_conditional_triggers(
            rp[section].get("conditional_inclusion"),
            derive_conditional_triggers(components),
        )

    return profile, derived_info, resume


RESUME_DIR = ROOT / "data" / "master_resumes"


def save_resume(file_bytes: bytes, filename: str) -> Path:
    """
    Put an uploaded .tex where master resumes live, and return its path.

    The UI should not decide where resumes belong — that is a fact about this
    project's layout, and keeping it here is what lets `app.py` stay a view
    layer (R25).
    """
    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    target = RESUME_DIR / Path(filename).name
    target.write_bytes(file_bytes)
    return target


def create_profile(resume_path, name: str, force: bool = False) -> dict:
    """
    Build, validate and write a profile in one call.

    `main()` below does the same thing with printing in between; a UI needs
    the outcome as data. Returns what a caller needs to report:

        {profile_path, derived, needs_you, counts}

    Raises FileExistsError when a profile of that name exists and `force` is
    not set, so the caller can offer to overwrite rather than silently clobber.
    """
    resume_path = Path(resume_path)
    out_path = ROOT / "user_profiles" / f"{name}.json"

    if out_path.exists() and not force:
        raise FileExistsError(f"A profile named '{name}' already exists.")

    # A profile is the only artefact here that is both hand-tuned and unbacked:
    # everything else is derived, in git, or reproducible. Profiles are
    # gitignored, and `state.json` records only the profile's *name*, so an
    # overwrite is unrecoverable. One was lost this way (R30) — a dozen
    # hand-authored JD trigger lists, worth 11 of 20 project selections.
    backup = None
    if out_path.exists():
        backup = out_path.with_name(
            f"{name}.{datetime.now().strftime('%Y%m%dT%H%M%S')}.bak.json"
        )
        shutil.copy2(out_path, backup)

    profile, derived_info, resume = build_profile(resume_path, name)
    out_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")

    rp = profile["resume_preferences"]
    return {
        "profile_path": out_path,
        "backup_path": backup,
        "derived": derived_info,
        "needs_you": {
            section: [f for f in fields if f not in derived_info]
            for section, fields in NEEDS_HUMAN.items()
        },
        "counts": {
            "experiences": len(resume.experiences),
            "projects": len(resume.projects),
            "trigger_rules": (len(rp["experiences"]["conditional_inclusion"])
                              + len(rp["projects"]["conditional_inclusion"])),
        },
    }


def update_profile_fields(name: str, updates: dict) -> Path:
    """
    Merge answers into an existing profile and write it back.

    `updates` is nested by section, e.g.
    ``{"personal_info": {"location": "Irvine, CA"}}``. Only the keys given are
    touched, so a form that collects three fields cannot wipe the other
    thirty.

    Kept here rather than in the UI so that knowing a profile is JSON on disk,
    and where, stays out of the view layer (R25).
    """
    path = ROOT / "user_profiles" / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"No profile named '{name}'.")

    profile = json.loads(path.read_text(encoding="utf-8"))

    for section, fields in (updates or {}).items():
        if isinstance(fields, dict):
            profile.setdefault(section, {}).update(fields)
        else:
            profile[section] = fields

    path.write_text(json.dumps(profile, indent=2) + chr(10), encoding="utf-8")
    return path


def read_component_rules(name: str) -> dict:
    """
    Every component with its importance tier and JD triggers, for an editor.

    Derivation reaches a component's *tech stack* — `ionic`, `capacitor` — but
    not the *domain* words a posting actually uses, like `android` or `mobile
    app` (R21). That gap is not closable from the resume alone, because the
    resume never contains those words. A person can close it in ten seconds
    per component, which is why this exists.

    Returns experiences and projects in resume order, each entry carrying the
    id, a human label, the effective tier and the current trigger list.
    """
    path = ROOT / "user_profiles" / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"No profile named '{name}'.")

    profile = json.loads(path.read_text(encoding="utf-8"))
    rp = profile["resume_preferences"]

    parser = ResumeParser(str(ROOT / rp["master_resume_path"]), skip_embeddings=True)
    resume = parser.parsed_resume

    from tools.profile.derivation import merge_importance

    def collect(section, components, label_of):
        tiers = merge_importance(
            rp["component_importance"].get(section, {}),
            parser.derived_importance.get(section, {}),
        )
        rules = rp[section].get("conditional_inclusion", {})
        return [
            {
                "id": c.id,
                "label": label_of(c),
                "tier": tiers.get(c.id, "medium"),
                "triggers": list(rules.get(c.id, {}).get("include_if_jd_contains", [])),
            }
            for c in components
        ]

    return {
        "experiences": collect(
            "experiences", resume.experiences,
            lambda c: f"{c.title} — {c.company}",
        ),
        "projects": collect("projects", resume.projects, lambda c: c.name),
    }


def write_component_rules(name: str, importance: dict, triggers: dict) -> Path:
    """
    Save edited tiers and trigger lists back to the profile.

    Only the two maps an editor owns are touched; everything else in the
    profile is left exactly as it was. A component whose trigger list is
    emptied has its rule removed rather than stored empty — an empty rule
    cannot fire and is indistinguishable from one that never matched, which is
    the silence R17 set out to remove.
    """
    path = ROOT / "user_profiles" / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"No profile named '{name}'.")

    profile = json.loads(path.read_text(encoding="utf-8"))
    rp = profile["resume_preferences"]

    # Read the component list once. Resolving section membership per component
    # would re-parse the resume for every id on the screen.
    known = read_component_rules(name)

    for section in ("experiences", "projects"):
        ids = {c["id"] for c in known[section]}

        tiers = {k: v for k, v in (importance or {}).items() if k in ids}
        if tiers:
            rp["component_importance"].setdefault(section, {}).update(tiers)

        rules = rp[section].setdefault("conditional_inclusion", {})
        for comp_id, terms in (triggers or {}).items():
            if comp_id not in ids:
                continue
            cleaned = [t.strip().lower() for t in terms if t and t.strip()]
            if cleaned:
                existing = rules.get(comp_id, {})
                rules[comp_id] = {
                    "include_if_jd_contains": sorted(set(cleaned)),
                    "description": existing.get("description", "Edited by hand"),
                }
            else:
                rules.pop(comp_id, None)

    path.write_text(json.dumps(profile, indent=2) + chr(10), encoding="utf-8")
    return path


def main():
    ap = argparse.ArgumentParser(description="Bootstrap a profile from a resume.")
    ap.add_argument("--resume", required=True, help="Path to the master .tex resume")
    ap.add_argument("--name", required=True, help="Profile name (file becomes <name>.json)")
    ap.add_argument("--force", action="store_true", help="Overwrite an existing profile")
    args = ap.parse_args()

    resume_path = Path(args.resume)
    if not resume_path.exists():
        sys.exit(f"Resume not found: {resume_path}")
    if not TEMPLATE.exists():
        sys.exit(f"Template not found: {TEMPLATE}")

    out_path = ROOT / "user_profiles" / f"{args.name}.json"
    if out_path.exists() and not args.force:
        sys.exit(f"{out_path} already exists. Pass --force to overwrite.")

    profile, derived_info, resume = build_profile(resume_path, args.name)

    out_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {out_path}\n")

    print(f"Derived from the resume ({len(derived_info)} fields):")
    for key, value in derived_info.items():
        shown = value if len(str(value)) <= 46 else str(value)[:43] + "..."
        print(f"    {key:18} {shown}")

    imp = profile["resume_preferences"]["component_importance"]
    print(f"\nImportance tiers from resume order: "
          f"{len(imp['experiences'])} experiences, {len(imp['projects'])} projects")

    rules = profile["resume_preferences"]
    n_exp = len(rules["experiences"]["conditional_inclusion"])
    n_proj = len(rules["projects"]["conditional_inclusion"])
    n_terms = sum(
        len(r["include_if_jd_contains"])
        for section in ("experiences", "projects")
        for r in rules[section]["conditional_inclusion"].values()
    )
    print(f"Conditional triggers derived: {n_exp} experiences, "
          f"{n_proj} projects ({n_terms} terms)")

    missing = [f for f in NEEDS_HUMAN["personal_info"] if f not in derived_info]
    print("\nSTILL NEEDS YOU — these are placeholders, not derived:")
    for field in missing:
        print(f"    personal_info.{field:22} {profile['personal_info'].get(field)!r}")
    for field in NEEDS_HUMAN["job_preferences"]:
        print(f"    job_preferences.{field}")

    # A profile that cannot load is worse than none, so say so now.
    print()
    try:
        from tools.profile import load_profile
        from tools.profile.validation import find_unresolvable_ids

        loaded = load_profile(args.name)
        print("Profile validates against the schema.")

        # Schema validity is not the same as usability: a rule keyed to a
        # component that does not exist loads fine and then never fires.
        # The template used to ship five such IDs.
        ghosts = find_unresolvable_ids(loaded, ResumeParser(str(resume_path),
                                                            skip_embeddings=True))
        if ghosts:
            print()
            print(f"WARNING: {len(ghosts)} rule(s) reference components that "
                  f"do not exist:")
            for problem in ghosts:
                print(f"    {problem}")
        else:
            print("Every profile rule resolves to a real component.")
    except Exception as exc:
        print(f"WARNING: profile does not validate yet: {exc}")
        print("Fill the fields above and re-check.")


if __name__ == "__main__":
    main()

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
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.profile.derivation import (  # noqa: E402
    derive_component_importance,
    derive_personal_info,
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

    return profile, derived_info, resume


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
        load_profile(args.name)
        print("Profile validates against the schema.")
    except Exception as exc:
        print(f"WARNING: profile does not validate yet: {exc}")
        print("Fill the fields above and re-check.")


if __name__ == "__main__":
    main()

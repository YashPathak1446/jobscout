"""
Is this machine ready to run JobScout, and if not, what would fix it?

Roadmap item 8 argued for this over an install script, and the argument has
held up: **an installer's logic goes stale every OS release; a doctor's does
not.** An installer has to know how to put a LaTeX distribution on six
platforms. A doctor only has to know whether one is there, and say the name of
the thing to install if it is not.

It also earns its keep against this project's own history. Three of the last
week's bugs were setup problems that looked like logic problems — a `.env` no
entry point loaded (R41), an Ollama with no model pulled (R42), a rung nobody
had ever run (R44). Every one of them is a line in this report now, and each
took hours to find the first time.

Two rules for every check here:

- **Say what to do, not just what is wrong.** "pdflatex not found" is a
  diagnosis; "install MiKTeX, or run with --no-pdf for .tex files" is a fix.
- **Distinguish broken from absent.** Most of this pipeline is optional. No
  Gemini key is a supported configuration, not a fault, and reporting it as
  one teaches people to ignore the report — which is R47's lesson applied to
  a diagnostic tool.

Usage:
    python -m scripts.doctor
    python -m scripts.doctor --profile yash_pathak

Exit code is 0 unless something is genuinely broken, so CI can call it.

Location: jobscout_v3/scripts/doctor.py
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

ROOT = Path(__file__).parent.parent

OK, WARN, FAIL = "ok", "warn", "fail"

MARKS = {OK: "[ ok ]", WARN: "[warn]", FAIL: "[FAIL]"}

MINIMUM_PYTHON = (3, 10)


class Report:
    """What the doctor found, in the order it looked."""

    def __init__(self):
        self.checks = []

    def add(self, status, name, detail, fix=""):
        self.checks.append({"status": status, "name": name,
                            "detail": detail, "fix": fix})

    @property
    def failures(self):
        return [c for c in self.checks if c["status"] == FAIL]

    @property
    def warnings(self):
        return [c for c in self.checks if c["status"] == WARN]

    def render(self) -> str:
        lines = ["", "JobScout doctor", "=" * 60, ""]
        for check in self.checks:
            lines.append(f"{MARKS[check['status']]}  {check['name']}")
            lines.append(f"        {check['detail']}")
            if check["fix"]:
                lines.append(f"        → {check['fix']}")
            lines.append("")

        lines.append("-" * 60)
        if self.failures:
            lines.append(f"{len(self.failures)} problem(s) will stop a run. "
                         f"{len(self.warnings)} thing(s) would improve it.")
        elif self.warnings:
            lines.append(f"Ready to run. {len(self.warnings)} thing(s) would "
                         f"improve results.")
        else:
            lines.append("Everything checks out.")
        lines.append("")
        return "\n".join(lines)


# --- the checks ---------------------------------------------------------------

def check_python(report):
    version = sys.version_info
    shown = f"{version.major}.{version.minor}.{version.micro}"
    if version >= MINIMUM_PYTHON:
        report.add(OK, "Python", f"{shown}")
    else:
        need = ".".join(str(p) for p in MINIMUM_PYTHON)
        report.add(FAIL, "Python", f"{shown} is too old",
                   f"JobScout needs Python {need} or newer")


def check_dependencies(report):
    """
    Imported rather than read off a version list, because a package that is
    installed and broken is the case worth catching.
    """
    required = {
        "google.genai": "google-genai",
        "dotenv": "python-dotenv",
        "requests": "requests",
        "bs4": "beautifulsoup4",
        "pydantic": "pydantic",
        "pypdf": "pypdf",
        "docx": "python-docx",
        "streamlit": "streamlit",
    }

    missing = []
    for module, package in required.items():
        try:
            __import__(module)
        except Exception:
            missing.append(package)

    if missing:
        report.add(FAIL, "Dependencies", f"missing: {', '.join(missing)}",
                   "pip install -r requirements.txt")
    else:
        report.add(OK, "Dependencies", f"all {len(required)} present")


def check_scoring_backend(report):
    """Scoring needs embeddings from somewhere; local needs no key (R36)."""
    from tools.resume import local_embeddings

    if local_embeddings.is_available():
        report.add(OK, "Scoring", "local embeddings available — no key needed")
    else:
        report.add(WARN, "Scoring", "model2vec is not installed",
                   "pip install model2vec, or set a Gemini key so scoring can "
                   "use the API instead")


def check_rewriting_backend(report):
    """
    Which rung will rewrite bullets, and what that costs.

    `none` is a supported configuration, so it is a warning about quality
    rather than a failure — the run will still produce real resumes in the
    user's own words (R37).
    """
    from agents.orchestrator import backend_status

    status = backend_status()
    backend = status["backend"]

    if backend == "gemini":
        report.add(OK, "Bullet rewriting", "Google Gemini — a key was found")
    elif backend == "openai":
        report.add(OK, "Bullet rewriting", "an OpenAI-compatible key was found")
    elif backend == "ollama":
        # R81 replaced R44's verdict and this line kept repeating it. The
        # README was corrected and the doctor was not — the same fix landing
        # on one of two paths, in the two places that tell a user what to
        # expect. Found by running the doctor out of a TestPyPI install,
        # which is the first time anyone had read this text as a stranger.
        report.add(WARN, "Bullet rewriting",
                   "Ollama, running locally — measured 2026-08-27 on "
                   "llama3.1:8b, where it passed one of three fixture resumes",
                   "a Gemini key gives the results this project measured; the "
                   "no-model floor passed all three")
    else:
        report.add(WARN, "Bullet rewriting",
                   "no model — jobs are still found, scored and matched, but "
                   "your bullets are used exactly as written",
                   "add GOOGLE_API_KEY to .env for tailored bullets, free at "
                   "aistudio.google.com/app/apikey")


def check_env_file(report):
    """
    R41: `.env` was loaded by the agents and by nothing else, so importing a
    PDF from the CLI silently found no key. Worth naming the file directly.
    """
    env = ROOT / ".env"
    if not env.exists():
        report.add(WARN, ".env", "not found",
                   "cp .env.example .env — optional, but it is where keys go")
        return

    try:
        text = env.read_text(encoding="utf-8")
    except OSError as exc:
        report.add(WARN, ".env", f"could not be read: {exc}")
        return

    set_keys = [
        line.split("=", 1)[0].strip()
        for line in text.splitlines()
        if "=" in line and not line.strip().startswith("#")
        and line.split("=", 1)[1].strip()
    ]
    if set_keys:
        report.add(OK, ".env", f"present, {len(set_keys)} value(s) set: "
                              f"{', '.join(sorted(set_keys))}")
    else:
        report.add(WARN, ".env", "present but every value is empty",
                   "fill in GOOGLE_API_KEY, or run without one")


def check_pdflatex(report):
    """R20: no LaTeX engine is a degraded mode, not a failure."""
    from tools.generation.pdf_builder import detect_flavor, find_pdflatex

    binary = find_pdflatex()
    if not binary:
        report.add(WARN, "PDF output", "no LaTeX engine found — you will get "
                                       ".tex files rather than PDFs",
                   "install MiKTeX (Windows) or TeX Live (macOS/Linux)")
        return

    try:
        flavor = detect_flavor(binary)
    except Exception:
        flavor = "unknown"
    report.add(OK, "PDF output", f"{flavor} at {binary}")


def check_profiles(report, wanted=None):
    from tools.profile import list_available_profiles, load_profile

    names = [n for n in list_available_profiles() if n != "template"]
    if not names:
        report.add(WARN, "Profiles", "none yet",
                   "run the app and upload a resume, or "
                   "python scripts/init_profile.py --resume <file> --name <you>")
        return

    to_check = [wanted] if wanted else names
    broken = []
    for name in to_check:
        try:
            load_profile(name)
        except Exception as exc:
            broken.append(f"{name}: {exc}")

    if broken:
        report.add(FAIL, "Profiles", "; ".join(broken)[:200],
                   "rebuild it from your resume, or fix the JSON by hand")
    else:
        report.add(OK, "Profiles", f"{len(to_check)} valid: {', '.join(to_check)}")


def check_master_resume(report, wanted=None):
    """A profile can validate while pointing at a resume that is not there."""
    from tools.profile import list_available_profiles, load_profile

    names = [wanted] if wanted else [
        n for n in list_available_profiles() if n != "template"]
    if not names:
        return

    problems, checked = [], 0
    for name in names:
        try:
            profile = load_profile(name)
        except Exception:
            continue                      # already reported by check_profiles

        path = Path(profile.resume_preferences.master_resume_path)
        if not path.is_absolute():
            path = ROOT / path
        if not path.exists():
            problems.append(f"{name} points at {path.name}, which is missing")
            continue

        try:
            from tools.resume import ResumeParser
            parsed = ResumeParser(str(path), skip_embeddings=True).parsed_resume
            if not (parsed.experiences or parsed.projects):
                problems.append(f"{name}: {path.name} parsed to nothing")
            else:
                checked += 1
        except Exception as exc:
            problems.append(f"{name}: {path.name} would not parse ({exc})")

    if problems:
        report.add(FAIL, "Master resume", "; ".join(problems)[:200],
                   "check master_resume_path in the profile")
    elif checked:
        report.add(OK, "Master resume", f"{checked} parsed cleanly")


def check_job_store(report):
    from agents.orchestrator import board_stats

    try:
        stats = board_stats()
    except Exception as exc:
        report.add(FAIL, "Job store", f"could not be opened: {exc}",
                   "delete data/jobs.db to start a fresh board")
        return

    if not stats["total"]:
        report.add(OK, "Job store", "empty — nothing has been discovered yet")
    else:
        report.add(OK, "Job store",
                   f"{stats['total']} job(s), {stats['scored']} scored, "
                   f"{stats['with_resume']} with a resume")


CHECKS = (check_python, check_dependencies, check_env_file,
          check_scoring_backend, check_rewriting_backend, check_pdflatex,
          check_job_store)


def run(profile: str = None) -> Report:
    """Every check, in order. A check that explodes is itself a finding."""
    report = Report()

    for check in CHECKS:
        try:
            check(report)
        except Exception as exc:
            report.add(FAIL, check.__name__.replace("check_", "").title(),
                       f"the check itself failed: {exc}")

    for check in (check_profiles, check_master_resume):
        try:
            check(report, profile)
        except Exception as exc:
            report.add(FAIL, check.__name__.replace("check_", "").title(),
                       f"the check itself failed: {exc}")

    return report


def main():
    parser = argparse.ArgumentParser(
        description="Check whether this machine can run JobScout.")
    parser.add_argument("--profile", default=None,
                        help="Only check this profile, rather than all of them.")
    args = parser.parse_args()

    report = run(args.profile)

    try:
        print(report.render())
    except UnicodeEncodeError:
        # A console that cannot encode an arrow should still get the report
        # (R29 — the same failure that once ended a successful run).
        print(report.render().encode("ascii", "replace").decode("ascii"))

    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

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
    location, visa_status, work_authorization (us_person,
    needs_sponsorship, holds_clearance)
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
from functools import partial
from pathlib import Path

from tools import paths

sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic import ValidationError  # noqa: E402

from tools.profile.profile_schema import (  # noqa: E402
    UserProfile,
    migrate_work_authorization,
)
from tools.profile.derivation import (  # noqa: E402
    derive_component_importance,
    derive_conditional_triggers,
    derive_personal_info,
    merge_conditional_triggers,
)
from tools.profile.profile_loader import (  # noqa: E402
    BadProfileName, list_available_profiles, profile_file)
from tools.resume.resume_parser import ResumeParser  # noqa: E402

# Ships with the package; it is a starter, not one of the user's profiles.
TEMPLATE = paths.asset("profile_template.json")

# Fields a human must confirm. Listed so the script can report them rather
# than let a placeholder slip into a live run.
#
# The three work-authorization answers are dotted because they are nested,
# and listed separately because each is its own question: one answered and
# two left unknown is a profile the gate will badge, not a finished one (A4).
NEEDS_HUMAN = {
    "personal_info": ["location",
                      "work_authorization.us_person",
                      "work_authorization.needs_sponsorship",
                      "work_authorization.holds_clearance"],
    "job_preferences": ["target_roles", "locations", "exclude_keywords"],
}


# The three work-authorization questions, worded once (A4). Streamlit renders
# from this; the React screen cannot import Python, so it carries a copy and
# `test_about_you.py` fails if any string here is missing from it verbatim.
#
# The wording is load-bearing, and was reviewed as such:
#   - "refugee or asylee": ITAR's "US person" includes them, and a wrong "No"
#     hides jobs they may hold without saying so.
#   - "now or later", and help that opens on the present: readers answer about
#     today unless told otherwise, and an F-1 on OPT does not need sponsorship
#     *today*.
#   - "active ... today": eligibility to obtain a clearance is question 1.
#
# "Prefer not to say" stores "unknown", the same as never answering — the
# gate treats both alike, and the board's badge keeps asking.
WORK_AUTHORIZATION_QUESTIONS = (
    {
        "field": "us_person",
        "question": "Are you a US citizen, green-card holder, or admitted as "
                    "a refugee or asylee?",
        "options": (("yes", "Yes"), ("no", "No"),
                    ("unknown", "Prefer not to say")),
        "help": "Some postings are open only to US persons: ITAR, "
                "export-control and most clearance work.",
    },
    {
        "field": "needs_sponsorship",
        "question": "Will you need visa sponsorship, now or in future?",
        "options": (("yes", "Yes, now or later"), ("no", "No"),
                    ("unknown", "Prefer not to say")),
        "help": "If you're on a work visa today, the answer is yes. F-1 on OPT "
                "or CPT: yes, you'll need it later. H-1B: yes, a transfer is "
                "sponsorship. Green card or citizen: no.",
    },
    {
        "field": "holds_clearance",
        "question": "Do you hold an active security clearance today?",
        "options": (("yes", "Yes"), ("no", "No"),
                    ("unknown", "Prefer not to say")),
        "help": "Active today. Being eligible to get one doesn't count; "
                "postings that only need eligibility are already covered by "
                "question 1.",
    },
)


def build_profile(resume_path: Path, name: str, *, user_id) -> dict:
    parser = ResumeParser(str(resume_path), skip_embeddings=True, user_id=user_id)
    resume = parser.parsed_resume

    profile = json.loads(TEMPLATE.read_text(encoding="utf-8"))

    profile["user_id"] = name
    profile["created"] = date.today().isoformat()
    profile["description"] = f"Profile for {resume.name or name}"

    derived_info = derive_personal_info(resume)
    profile["personal_info"].update(derived_info)

    rp = profile["resume_preferences"]
    # Relative to the **user's home**, which is what reads resolve it against
    # (`paths.stored_path`, from the orchestrator and `_component_rules`
    # below). It was relative to the install directory, and in a checkout
    # those are the same directory, so the mismatch only appeared in a
    # container (R86). Unscoped, the user's home *is* the data home.
    try:
        rel = resume_path.resolve().relative_to(
            paths.user_home(user_id).resolve())
        rp["master_resume_path"] = str(rel).replace("\\", "/")
    except ValueError:
        # Outside the user's home entirely — a temp dir, another drive. Store
        # it absolute; there is no relative spelling that would mean anything.
        # A scoped run refuses to read it (`paths.stored_path`), which is
        # right: a scoped user's resume lives in their own home.
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


def resume_dir(user_id) -> Path:
    """
    Where one user's uploaded and imported resumes live:
    `data/master_resumes/` under their home.

    Was the import-time constant `RESUME_DIR`, which both UIs imported — so
    it was one directory for everybody, decided before anybody had said who
    they were (pilot plan A3). A function is the only shape that can be
    somebody in particular.
    """
    return paths.user_path("data", "master_resumes", user_id=user_id)


def profiles_dir(user_id) -> Path:
    """
    Where one user's profiles are written — through the *loader's* resolver,
    so the write here and the read in `load_profile` cannot come apart (the
    R86 shape: two spellings, one directory, until a container).

    Was `PROFILES`, an import-time constant. Seven sites read or wrote it from
    the repo root; installed, that is site-packages.
    """
    from tools.profile.profile_loader import profiles_dir as _loader_dir
    return _loader_dir(user_id)


def profile_name_problem(name: str):
    """
    Why `name` cannot be a profile name, in words, or None if it can (R111).

    For a UI to say so before reading a resume. The same check `create_profile`
    enforces, so the screen cannot pass a name the save will refuse.
    """
    try:
        profile_file(name, profiles_dir(None))
    except BadProfileName as exc:
        return str(exc)
    return None


def _profile_file(user_id, name: str, must_exist: bool = True) -> Path:
    """
    One user's profile file, with its directory made on the way.

    The `mkdir` was a module-level `PROFILES.mkdir()` until A3: on a fresh
    volume `user_profiles/` did not exist and the first profile write failed
    with FileNotFoundError — never seen in a checkout, where the directory is
    already in git (R86). Per user it has to happen per call, because a new
    user's home is created by their first write.
    """
    where = profiles_dir(user_id)
    # The name is checked before anything is made: a refused name must not
    # leave even an empty directory behind (R111).
    path = profile_file(name, where)
    where.mkdir(parents=True, exist_ok=True)
    if must_exist and not path.exists():
        raise FileNotFoundError(f"No profile named '{name}'.")
    return path


def save_resume(user_id, file_bytes: bytes, filename: str, backend: str = None) -> Path:
    """
    Put an uploaded resume where master resumes live, and return its `.tex`.

    Accepts `.tex`, `.pdf` and `.docx`. Anything that is not already LaTeX is
    read into a structured schema and rendered into the project's template —
    the pipeline downstream only ever sees `.tex`, and the user keeps a real
    file they can edit rather than a hidden intermediate format.

    Extraction is imperfect by nature, which is why R33 requires every
    extracted field to be confirmed before it is used.

    The UI should not decide where resumes belong, or how a PDF becomes a
    resume — both are facts about this project, and keeping them here is what
    lets `app.py` stay a view layer (R25).
    """
    extracted = extract_resume(user_id, file_bytes, filename, backend)
    if extracted["kind"] == "latex":
        return extracted["path"]
    return save_extracted(extracted["schema"], extracted["source"])


def extract_resume(user_id, file_bytes: bytes, filename: str, backend: str = None) -> dict:
    """
    Read an upload far enough to show it, without committing to anything.

    This is the half of importing that happens *before* a person has agreed
    that the extraction is right. R33 requires every extracted field to be
    confirmed before use, and a function that extracts and writes in one call
    leaves nowhere for that to happen — which is exactly why the confirmation
    screen did not exist for as long as it did.

    Returns either:
        {"kind": "latex", "path": Path, "rung": None}
        {"kind": "extracted", "schema": {...}, "source": Path, "rung": str}

    A `.tex` upload skips confirmation deliberately. It is the user's own file
    in the pipeline's own format, so there is nothing a model guessed at.

    `backend` pins the rung; `None` means resolve it the usual way. `rung`
    reports which one actually read the resume, and it is **three states, not
    two** — a rung name, or `None` meaning no model was consulted and none was
    needed. Absent is not the same as `"none"`, which is a rung a person chose.

    Both exist because their absence was a bug. `scripts/acceptance.py` pinned
    the pipeline and not the import, so the row labelled `none` imported
    through Gemini, and nothing anywhere recorded which rung had read the
    resume — so nothing could contradict it (R83).
    """
    from tools.generation import llm_backends
    from tools.resume import resume_import, tex_renderer

    resumes = resume_dir(user_id)
    resumes.mkdir(parents=True, exist_ok=True)
    source = resumes / Path(filename).name
    source.write_bytes(file_bytes)

    if source.suffix.lower() == ".tex":
        return {"kind": "latex", "path": source, "rung": None}

    text = resume_import.extract_text(source)
    if tex_renderer.looks_like_latex(text):
        return {"kind": "latex", "path": source, "rung": None}

    # Resolved here rather than inside `complete_json` so the rung can be
    # reported, and deliberately *below* the two LaTeX returns: a `.tex` upload
    # needs no model, and resolving at the top would have it probing for a
    # local Ollama to answer a question nobody asked.
    #
    # `partial` rather than a wider `to_schema`: that function calls its agent
    # with one positional argument, and three test modules pass one-argument
    # callables. Binding the rung to the callable keeps that contract exactly
    # as it was instead of asking every caller to be updated in step.
    chosen = llm_backends.effective_backend(backend)
    schema = resume_import.to_schema(
        text, agent=partial(llm_backends.complete_json, backend=chosen))

    # Three outcomes, not two.
    #
    # This guard used to be `if not (experiences or projects): raise`, and that
    # made the heuristic floor unreachable. `heuristic_schema` returns
    # `experiences: []` *by design* — splitting roles apart is the judgement a
    # regex cannot make — and keeps the section's raw lines under `_unparsed`
    # so a confirmation screen can show them. `app.py` has had the code to
    # display exactly that since the screen was written, and its test builds
    # the `_unparsed` state by hand because the product could not produce it:
    # with no model the floor always returned zero experiences, so the raise
    # always fired first.
    #
    # The result was that arriving without a key — the configuration a stranger
    # is most likely to arrive in — turned a readable PDF into "could not read
    # any experience", while the same file with a key imported three jobs
    # cleanly. Measured on a six-year Boston resume: contact, education and
    # four skill categories all read fine, and the error threw them away.
    salvaged = {k: v for k, v in (schema.get("_unparsed") or {}).items() if v}
    readable = (schema.get("experiences") or schema.get("projects")
                or salvaged or schema.get("education")
                or (schema.get("contact") or {}).get("email"))

    if not readable:
        raise ValueError(
            f"Could not read any text out of {source.name}. A text-based PDF "
            "works best; a scanned image will not."
        )

    return {"kind": "extracted", "schema": schema, "source": source,
            "rung": chosen}


def save_extracted(schema: dict, source, destination=None) -> Path:
    """
    Render a confirmed schema to the `.tex` the pipeline reads.

    The other half of `extract_resume`. Takes whatever the user corrected
    rather than whatever the model said, which is the entire point of the
    split.
    """
    from tools.resume import tex_renderer

    source = Path(source)
    target = Path(destination) if destination else source.with_suffix(".tex")
    tex_renderer.write(schema, target)
    return target


def import_to_tex(source, destination=None, backend: str = None, *, user_id) -> Path:
    """
    Convert a PDF or DOCX resume into a `.tex`, unconfirmed.

    The CLI path, where there is no screen to confirm on. The UI uses
    `extract_resume` and `save_extracted` instead, so that a misread is caught
    by a person rather than discovered three stages later.
    """
    source = Path(source)
    extracted = extract_resume(user_id, source.read_bytes(), source.name, backend)
    if extracted["kind"] == "latex":
        return extracted["path"]
    return save_extracted(extracted["schema"], extracted["source"], destination)


def _id_problems(user_id, name: str, resume_path=None, parser=None) -> list:
    """
    Rules in the profile just written whose component ID names no component, or
    more than one.

    **Here rather than in `load_profile`, which is what "check at load" would
    literally mean.** The check needs the resume parsed to know which IDs
    exist, and `ResumeParser(skip_embeddings=True)` measures 67 ms on this
    machine. `refresh_board_gate` calls `load_profile` before *every* board
    render, so that is 67 ms of waste per page view for an answer that changes
    only when the profile or the resume does — and `load_profile` is also
    called where no master resume exists, so it would have to degrade to
    silence, which is the failure being fixed.

    `create_profile` is where a profile is *adopted* rather than merely read,
    it is the path both UIs use for an import or a correction, and it is where
    a title edit lands — the edit that orphans a key under Q34's ID scheme. It
    had no check at all before this: the validator's only two callers were the
    `init_profile` CLI's `main()` and the orchestrator at generation, so a
    profile imported through either UI went unchecked until a run started.

    Returned as data the way `needs_you` is, so a UI can show it. Never
    raises — a profile that was written must still be reported on.

    A check that could not run returns **a problem saying so**, not `[]`. An
    empty list is read by every caller as "every rule names one component",
    which is the one thing a failed check does not know — unknown is never a
    value, and a swallowed exception here would restore the silence this
    function exists to end.
    """
    try:
        from tools.profile import load_profile
        from tools.profile.validation import find_id_problems
        from tools.resume.resume_parser import ResumeParser

        if parser is None:
            parser = ResumeParser(str(resume_path), skip_embeddings=True,
                                  user_id=user_id)
        return find_id_problems(load_profile(name, user_id=user_id), parser)
    except Exception as exc:  # pragma: no cover - reporting must not fail
        return [f"component IDs could not be checked ({exc}) — the rules in "
                f"this profile may name components that do not exist"]


class ProfileLimit(Exception):
    """This account already has as many profiles as it may (R109)."""


def profile_limit(user_id):
    """
    How many profiles one account may hold: **one when scoped, no limit
    unscoped.**

    The board has no profile column. It is the user's (R90's partition), and
    every stored score, gate verdict and applied/rejected mark on it was made
    for one resume. A second profile in the same partition is ranked against
    scores computed for the first, and Q53's labels would mix two people's
    judgements. The CLI and local mode keep any number: one person, who knows
    which profile they ran.

    Read by `create_profile`, which enforces it, and by `/api/health`, so the
    wizard can offer "replace" instead of a name field that would 409. One
    function, so the two cannot disagree.
    """
    return None if user_id is None else 1


def create_profile(user_id, resume_path, name: str, force: bool = False) -> dict:
    """
    Build, validate and write a profile in one call.

    `main()` below does the same thing with printing in between; a UI needs
    the outcome as data. Returns what a caller needs to report:

        {profile_path, derived, needs_you, counts}

    Raises FileExistsError when a profile of that name exists and `force` is
    not set, so the caller can offer to overwrite rather than silently clobber.
    """
    resume_path = Path(resume_path)
    out_path = _profile_file(user_id, name, must_exist=False)

    if out_path.exists() and not force:
        raise FileExistsError(f"A profile named '{name}' already exists.")

    limit = profile_limit(user_id)
    if limit is not None:
        others = [n for n in list_available_profiles(user_id=user_id)
                  if n != out_path.stem]
        if len(others) >= limit:
            raise ProfileLimit(
                f"This account already has a profile, '{others[0]}', and holds "
                "one. Upload your new resume to replace it instead.")

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

    profile, derived_info, resume = build_profile(resume_path, name, user_id=user_id)
    out_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")

    rp = profile["resume_preferences"]
    return {
        "profile_path": out_path,
        "backup_path": backup,
        "derived": derived_info,
        "id_problems": _id_problems(user_id, name, resume_path),
        # Lines of the resume the parser could not read (R112). Shown at
        # import, beside id_problems, so nothing is dropped unseen.
        "parse_warnings": list(resume.warnings),
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


def _merge(target: dict, updates: dict) -> dict:
    """
    Recursive dict merge: only the leaf keys given are replaced.

    The non-recursive version of this replaced a whole nested section with
    whatever partial dict a form happened to collect, and `job_preferences.
    locations` is where that bit. The preferences screen collects two of its
    seven fields, so saving it dropped `countries` — which the schema requires
    — and the profile stopped loading at all. The wizard could break a working
    profile just by being walked through.

    That is R30's shape again: a form destroying data it never showed the
    user. The fix belongs here rather than in the caller, because every future
    form that touches a nested section would otherwise have to remember.
    """
    for key, value in (updates or {}).items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = value
    return target


class ProfileInvalid(ValueError):
    """
    A save that would leave a profile the loader refuses (Q44).

    `problems` is one readable line per field, for the screen that asked.
    """

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


def _schema_problems(profile: dict) -> dict:
    """Every schema error in `profile`, keyed by its dotted field path."""
    try:
        UserProfile(**profile)
    except ValidationError as exc:
        return {".".join(str(part) for part in error["loc"]): error["msg"]
                for error in exc.errors()}
    return {}


def update_profile_fields(user_id, name: str, updates: dict) -> Path:
    """
    Merge answers into an existing profile and write it back.

    `updates` is nested by section, e.g.
    ``{"personal_info": {"location": "Irvine, CA"}}``. Only the keys given are
    touched, at any depth, so a form that collects three fields cannot wipe
    the other thirty.

    Kept here rather than in the UI so that knowing a profile is JSON on disk,
    and where, stays out of the view layer (R25).

    Validated before it is written (Q44): a save that introduces a schema
    error raises `ProfileInvalid` and leaves the file as it was. Merging
    without looking once wrote `years_experience: 2.5`, and the profile then
    would not load — R30's outcome by a different route. Only errors the save
    *introduces* refuse it. A profile already invalid somewhere else (a
    legacy file, a hand edit) can still be saved, so the form stays a way to
    fix it rather than a second wall in front of it.
    """
    path = _profile_file(user_id, name)

    profile = json.loads(path.read_text(encoding="utf-8"))
    already = _schema_problems(profile)
    _merge(profile, updates or {})

    # A form that writes `work_authorization` leaves the legacy booleans in
    # the file, ignored but contradicting it for anyone reading the JSON. The
    # migration drops them once an answer exists, so run it on the way out.
    personal = (updates or {}).get("personal_info") or {}
    if "work_authorization" in personal:
        profile["personal_info"] = migrate_work_authorization(
            profile["personal_info"])

    introduced = {field: msg for field, msg in _schema_problems(profile).items()
                  if field not in already}
    if introduced:
        raise ProfileInvalid(f"{field}: {msg}" for field, msg in introduced.items())

    path.write_text(json.dumps(profile, indent=2) + chr(10), encoding="utf-8")
    return path


def read_preferences(user_id, name: str) -> dict:
    """
    The job-preference answers a form needs to show what is already set.

    Without this the preferences screen renders its own defaults every time,
    so a returning user who opens it and saves silently reverts whatever they
    had tuned — the same destruction as above, one layer up. A form that
    cannot read cannot safely write.
    """
    path = _profile_file(user_id, name)

    prefs = json.loads(path.read_text(encoding="utf-8")).get("job_preferences", {})
    locations = prefs.get("locations", {}) or {}
    return {
        "target_roles": prefs.get("target_roles", []) or [],
        "seniority": prefs.get("seniority", []) or [],
        "years_experience": prefs.get("years_experience"),
        "exclude_keywords": prefs.get("exclude_keywords", []) or [],
        "cities": locations.get("cities", []) or [],
        "remote_ok": bool(locations.get("remote_ok", True)),
        # The rest of `locations`, which discovery and the filter both read
        # and no screen ever offered. R40 stopped the form destroying these;
        # this is the half that lets you set them.
        "countries": locations.get("countries", []) or [],
        "states_priority": locations.get("states_priority", []) or [],
        "states_acceptable": locations.get("states_acceptable", []) or [],
        "willing_to_relocate": bool(locations.get("willing_to_relocate", True)),
    }


def read_personal(user_id, name: str) -> dict:
    """
    The answers the "about you" screen asks for, as already stored.

    Same reason as `read_preferences`: a form that renders blanks and then
    saves them overwrites whatever was there. Location and work authorisation
    are the two fields derivation deliberately does not guess (R16), so
    re-entering them is the user's work, and losing them on a revisit wastes
    it twice.
    """
    path = _profile_file(user_id, name)

    raw = json.loads(path.read_text(encoding="utf-8")).get("personal_info", {})
    # Through the same migration the loader applies, so this screen never
    # shows blanks for answers the gate is already acting on (A4). Raw JSON
    # would skip it: `PersonalInfo` is where it runs for everything else.
    personal = migrate_work_authorization(raw)
    return {
        "location": personal.get("location", "") or "",
        "visa_status": personal.get("visa_status", "") or "",
        "work_authorization": personal["work_authorization"],
    }


def read_component_rules(user_id, name: str) -> dict:
    """
    The editor's view of every component, plus what is wrong with its rules.

    `{experiences, projects, id_problems}`. The first two are the screen; see
    `_component_rules`. The third is here rather than only on save because
    **this is the render that lists the rules**, so it is the one place a
    warning about them is actionable — and a warning a user meets only after
    pressing Save is a warning attached to the wrong moment.

    It costs nothing extra: `_component_rules` parses the resume to build the
    screen either way, and the check reuses that parser. Consumers index by
    section name, so the added key reaches nobody iterating.
    """
    rules, parser = _component_rules(user_id, name)
    return {**rules, "id_problems": _id_problems(user_id, name, parser=parser),
            # Again here, not only at import: a profile imported before R112
            # has never been told, and this is the screen a returning user
            # opens.
            "parse_warnings": list(parser.parsed_resume.warnings)}


def _component_rules(user_id, name: str):
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
    path = _profile_file(user_id, name)

    profile = json.loads(path.read_text(encoding="utf-8"))
    rp = profile["resume_preferences"]

    # Through `paths.stored_path`, the resolver the orchestrator uses. This
    # was `data_home() / stored` — a second resolution of one field, which
    # agreed with the first only while there was one user.
    parser = ResumeParser(
        str(paths.stored_path(rp["master_resume_path"], user_id=user_id)),
        skip_embeddings=True, user_id=user_id)
    resume = parser.parsed_resume

    from tools.profile.derivation import merge_importance

    def collect(section, components, label_of):
        tiers = merge_importance(
            rp["component_importance"].get(section, {}),
            parser.derived_importance.get(section, {}),
        )
        rules = rp[section].get("conditional_inclusion", {})
        always = set(rp[section].get("always_include", []))
        never = set(rp[section].get("never_include", []))
        return [
            {
                "id": c.id,
                "label": label_of(c),
                "tier": tiers.get(c.id, "medium"),
                "triggers": list(rules.get(c.id, {}).get("include_if_jd_contains", [])),
                # Read by the parser since it was written — always_include
                # boosts, never_include excludes outright — and editable only
                # by hand until now.
                "always": c.id in always,
                "never": c.id in never,
            }
            for c in components
        ]

    rules = {
        "experiences": collect(
            "experiences", resume.experiences,
            lambda c: f"{c.title} — {c.company}",
        ),
        "projects": collect("projects", resume.projects, lambda c: c.name),
    }
    # The parser comes back with them because `write_component_rules` needs
    # one and this is the call that already built it. Parsing a second time
    # for the ID check would be 67 ms spent re-deriving what is in hand — and
    # a second parse is a second answer, which is how two readers of one
    # resume start disagreeing.
    return rules, parser


def write_component_rules(user_id, name: str, importance: dict, triggers: dict,
                          always: dict = None, never: dict = None) -> dict:
    """
    Save edited tiers and trigger lists back to the profile.

    Only the two maps an editor owns are touched; everything else in the
    profile is left exactly as it was. A component whose trigger list is
    emptied has its rule removed rather than stored empty — an empty rule
    cannot fire and is indistinguishable from one that never matched, which is
    the silence R17 set out to remove.

    Returns `{profile_path, id_problems}`, the same shape `create_profile`
    returns, rather than the bare `Path` it used to — which nothing read.

    **`id_problems` reports; it does not repair.** Writes here are already
    filtered to the IDs on the screen, so this call cannot *introduce* a
    dangling key. What it can do is leave one: R17 deliberately keeps a rule
    for a component the resume no longer has, rather than dropping it silently,
    on the grounds that a rule somebody wrote is worth more than a tidy file.
    That is still the behaviour. The only thing that changes is that saving now
    *says so*, which is the half R17 could not supply on its own — a rule kept
    and never mentioned is indistinguishable from a rule that works.

    Free, as checks go: `_component_rules` below already parses the resume to
    build the screen, and the check reuses that parser rather than spending a
    second 67 ms.
    """
    path = _profile_file(user_id, name)

    profile = json.loads(path.read_text(encoding="utf-8"))
    rp = profile["resume_preferences"]

    # Read the component list once. Resolving section membership per component
    # would re-parse the resume for every id on the screen.
    known, parser = _component_rules(user_id, name)

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

        # always_include and never_include are stored as lists of ids, and the
        # screen hands back a decision per component. Only ids on the screen
        # are touched, so a rule for a component the resume no longer has is
        # left alone rather than silently dropped (R17).
        for field, decisions in (("always_include", always),
                                 ("never_include", never)):
            if decisions is None:
                continue
            current = set(rp[section].get(field, []))
            for comp_id in ids:
                if comp_id not in decisions:
                    continue
                if decisions[comp_id]:
                    current.add(comp_id)
                else:
                    current.discard(comp_id)
            rp[section][field] = sorted(current)

    path.write_text(json.dumps(profile, indent=2) + chr(10), encoding="utf-8")

    # After the write, so what is reported is the state the user just saved
    # rather than the one they arrived with.
    return {"profile_path": path,
            "id_problems": _id_problems(user_id, name, parser=parser)}


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

    # The CLI is the unscoped layout: a developer's checkout, one person.
    out_path = _profile_file(None, args.name, must_exist=False)
    if out_path.exists() and not args.force:
        sys.exit(f"{out_path} already exists. Pass --force to overwrite.")

    profile, derived_info, resume = build_profile(resume_path, args.name, user_id=None)

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
        value = profile["personal_info"]
        for part in field.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        print(f"    personal_info.{field:38} {value!r}")
    for field in NEEDS_HUMAN["job_preferences"]:
        print(f"    job_preferences.{field}")

    # A profile that cannot load is worse than none, so say so now.
    print()
    try:
        from tools.profile import load_profile
        from tools.profile.validation import find_id_problems

        loaded = load_profile(args.name, user_id=None)
        print("Profile validates against the schema.")

        # Schema validity is not the same as usability: a rule keyed to a
        # component that does not exist loads fine and then never fires, and a
        # rule keyed to an ID two components now share fires on whichever was
        # parsed first (Q34). The template used to ship five of the former.
        ghosts = find_id_problems(loaded, ResumeParser(str(resume_path),
                                                       skip_embeddings=True,
                                                       user_id=None))
        if ghosts:
            print()
            print(f"WARNING: {len(ghosts)} rule(s) do not name one real "
                  f"component:")
            for problem in ghosts:
                print(f"    {problem}")
        else:
            print("Every profile rule names exactly one real component.")
    except Exception as exc:
        print(f"WARNING: profile does not validate yet: {exc}")
        print("Fill the fields above and re-check.")


if __name__ == "__main__":
    main()

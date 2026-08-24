"""
JobScout — local Streamlit UI.

**This file is a view layer and nothing else (R25).** It reads answers from
widgets, calls into the pipeline, and renders what comes back. It does no
filtering, ranking, scoring or path-building, and it imports nothing from
`tools/`. `tests/test_ui_contract.py` fails the build if that stops being
true. The hosted tier is planned as React + FastAPI; keeping this boundary
means that port is a re-skin rather than a rewrite.

If you find yourself wanting a resume-parsing detail, a score, or a directory
layout in here, the answer belongs behind one of the two modules imported
below.

Run it with:
    streamlit run app.py

Location: jobscout_v3/app.py
"""

import os

import streamlit as st

from agents.orchestrator import (
    JobScoutOrchestrator,
    available_profiles,
    backend_status,
    board_jobs,
    board_stats,
    job_statuses,
    load_run,
    pdflatex_available,
    previous_runs,
    seniority_levels,
    set_job_status,
)
from scripts.init_profile import (
    create_profile,
    extract_resume,
    read_component_rules,
    read_personal,
    read_preferences,
    save_extracted,
    save_resume,
    update_profile_fields,
    write_component_rules,
)

VISA_OPTIONS = [
    "US Citizen", "Green Card", "F1 OPT", "F1 CPT", "H1B",
    "Other / prefer not to say",
]

ROLE_OPTIONS = [
    "Software Engineer", "Backend Engineer", "Frontend Engineer",
    "Full Stack Engineer", "ML Engineer", "AI Engineer",
    "Data Engineer", "Data Analyst", "DevOps Engineer",
]

EXCLUDE_OPTIONS = [
    "senior", "staff", "principal", "lead",
    "3+ years", "5+ years", "7+ years", "10+ years",
    "PhD required", "security clearance required",
]

TIERS = ["high", "medium", "low"]

STEPS = ["Resume", "About you", "Preferences", "Tuning", "Run"]


# ---------------------------------------------------------------- state ----

def _init_state():
    st.session_state.setdefault("step", 0)
    # The furthest screen reached, so stepping back does not strand the user
    # behind screens they have already completed.
    st.session_state.setdefault("max_step", 0)
    st.session_state.setdefault("profile_name", None)
    st.session_state.setdefault("setup_summary", None)
    st.session_state.setdefault("api_key", "")
    st.session_state.setdefault("results", None)
    # Set when a run stops at the review checkpoint and is waiting to resume.
    st.session_state.setdefault("pending", None)
    # "setup" walks the wizard; "board" is the job board. The board is not a
    # sixth step — R33 decided the app is a board you live in, and a step is
    # something you finish and leave. Setup is the thing you pass through.
    st.session_state.setdefault("view", "setup")
    # Detection asks whether Ollama is up, which is a network call. Cached so
    # it does not run on every keystroke in a text field.
    st.session_state.setdefault("backend", None)
    # An extraction waiting to be confirmed: what the model read, the file it
    # read it from, and what the profile will be called. Nothing is written
    # while this is set (R33).
    st.session_state.setdefault("pending_import", None)


def _goto(step: int):
    st.session_state.step = step
    st.session_state.max_step = max(st.session_state.get("max_step", 0), step)


# ------------------------------------------------------------ screen: 1 ----

def screen_resume():
    # An extraction awaiting confirmation takes over the screen: agreeing with
    # it, or fixing it, is the only sensible next action.
    if st.session_state.pending_import:
        _render_confirm()
        return

    st.subheader("1. Your resume")
    st.caption(
        "Upload your resume as PDF, Word or LaTeX. Everything it already "
        "states is read from it — name, contact links, education, and which "
        "of your projects suit which jobs."
    )

    # A returning user has already done this. Making them re-upload a resume
    # to reach the run screen would be the kind of friction that stops people
    # using a tool they otherwise like.
    existing = available_profiles()
    if existing:
        with st.container(border=True):
            st.markdown("**Already set up?**")
            chosen = st.selectbox("Use an existing profile", existing, key="existing-pick")
            if st.button("Continue with this profile"):
                st.session_state.profile_name = chosen
                st.session_state.setup_summary = None
                _goto(4)
                st.rerun()
        st.caption("Or upload a resume below to start fresh.")

    uploaded = st.file_uploader(
        "Your resume", type=["tex", "pdf", "docx"],
        help="PDF and Word files are read into a LaTeX resume you can keep "
             "and edit. Text-based PDFs work; a scanned image will not.",
    )
    name = st.text_input(
        "Profile name",
        value=st.session_state.profile_name or "",
        placeholder="e.g. jane_doe",
        help="Used for the profile file and generated resume filenames.",
    )

    # Overwriting is never implicit. Building a profile discards every rule the
    # owner tuned by hand, and one profile was already lost that way (R30).
    clash = bool(name) and name in existing
    if clash:
        st.warning(
            f"**{name}** already exists. Rebuilding replaces it completely, "
            "including any rules you tuned by hand. A timestamped backup is "
            "kept, but the live profile is replaced.",
            icon="⚠️",
        )
    confirmed = st.checkbox(f"Yes, replace '{name}'") if clash else False

    if st.button("Read my resume", type="primary",
                 disabled=not (uploaded and name) or (clash and not confirmed)):
        with st.spinner("Reading your resume..."):
            try:
                extracted = extract_resume(uploaded.getvalue(), uploaded.name)
            except Exception as exc:                       # surfaced, not swallowed
                st.error(f"Could not read that resume: {exc}")
                return

        # A `.tex` upload is already in the pipeline's own format, so there is
        # nothing a model guessed at and nothing to confirm.
        if extracted["kind"] == "latex":
            if not _build(extracted["path"], name, confirmed):
                return
            _goto(1)
            st.rerun()

        st.session_state.pending_import = {
            "schema": extracted["schema"],
            "source": str(extracted["source"]),
            "name": name,
            "force": confirmed,
        }
        st.rerun()

    summary = st.session_state.setup_summary
    if summary:
        counts = summary["counts"]
        a, b, c = st.columns(3)
        a.metric("Experiences", counts["experiences"])
        b.metric("Projects", counts["projects"])
        c.metric("Match rules derived", counts["trigger_rules"])

        if summary.get("backup_path"):
            st.caption(f"Previous profile saved as `{os.path.basename(str(summary['backup_path']))}`")

        with st.expander("What was read from your resume"):
            for field, value in summary["derived"].items():
                st.write(f"**{field}** — {value}")


def _build(resume_path, name, force):
    """Build and store a profile, reporting failure on screen. True if it worked."""
    try:
        summary = create_profile(resume_path, name, force=force)
    except FileExistsError:
        st.error(f"A profile named '{name}' already exists.")
        return False
    except Exception as exc:                               # surfaced, not swallowed
        st.error(f"Could not build a profile from that resume: {exc}")
        return False

    st.session_state.profile_name = name
    st.session_state.setup_summary = summary
    return True


def _lines(values) -> str:
    return "\n".join(v for v in (values or []) if v)


def _entry_fields(entry, index, kind, fields):
    """
    One extracted experience or project, editable.

    Returns the corrected entry, or None if the user unticked it. Extraction
    can invent an entry out of a heading it misread, and a screen that only
    allows correction leaves no way to say "this is not a job".
    """
    label = " — ".join(str(entry.get(f) or "") for f, _ in fields[:2]).strip(" —")
    with st.expander(label or f"{kind} {index + 1}", expanded=False):
        keep = st.checkbox("Include this", value=True, key=f"keep-{kind}-{index}")

        corrected = {}
        columns = st.columns(2)
        for position, (field, caption) in enumerate(fields):
            corrected[field] = columns[position % 2].text_input(
                caption, value=str(entry.get(field) or ""),
                key=f"{kind}-{index}-{field}")

        text = st.text_area(
            "Bullets, one per line", value=_lines(entry.get("bullets")),
            height=160, key=f"{kind}-{index}-bullets",
            help="These are used as written unless a model rewrites them for "
                 "a specific job.")
        corrected["bullets"] = [line.strip() for line in text.split("\n") if line.strip()]

    return corrected if keep else None


def _render_confirm():
    """
    Every extracted field, shown for correction before anything is saved (R33).

    Extraction from a PDF or Word file will misread some resumes — R39 found a
    header that yielded the word "GitHub" as a URL and kerning that split
    "WebApp" in two, on a file this project generated itself. A silent misparse
    produces bad resumes until somebody opens one, so nothing is written until
    this screen is agreed with.

    It doubles as the moment the user sees what the system understood about
    them, which is a better first impression than a spinner.
    """
    pending = st.session_state.pending_import
    schema = pending["schema"]

    st.subheader("Is this right?")
    st.caption(
        "This is what was read from your file. Correct anything wrong — it is "
        "used exactly as it stands here. Nothing has been saved yet."
    )

    a, b, c = st.columns(3)
    a.metric("Experiences", len(schema.get("experiences") or []))
    b.metric("Projects", len(schema.get("projects") or []))
    c.metric("Skill groups", len(schema.get("skills") or {}))

    # The floor keeps text it could not split into entries. Showing it is the
    # difference between "we found one job" and "we found one job and could
    # not read this part", which are very different things to be told.
    unparsed = schema.get("_unparsed") or {}
    leftovers = {k: v for k, v in unparsed.items() if v}
    if leftovers:
        st.warning(
            "Some of your resume could not be split into separate entries — "
            "most likely because no model was available to read it. It is "
            "shown below; anything you want kept has to be typed in above.",
            icon="⚠️",
        )
        with st.expander("What could not be read"):
            for section, lines in leftovers.items():
                st.markdown(f"**{section}**")
                st.text("\n".join(lines) if isinstance(lines, list) else str(lines))

    contact = dict(schema.get("contact") or {})
    st.markdown("#### Contact")
    st.caption(
        "A PDF shows link *text*, not link targets, so a URL field holding "
        "the word `GitHub` means the address never made it into the file."
    )
    columns = st.columns(2)
    for position, (field, caption) in enumerate(
            [("name", "Name"), ("email", "Email"), ("phone", "Phone"),
             ("github", "GitHub URL"), ("linkedin", "LinkedIn URL")]):
        contact[field] = columns[position % 2].text_input(
            caption, value=str(contact.get(field) or ""), key=f"contact-{field}")

    st.markdown("#### Education")
    education = []
    for index, entry in enumerate(schema.get("education") or []):
        columns = st.columns(2)
        corrected = {}
        for position, (field, caption) in enumerate(
                [("school", "School"), ("degree", "Degree"),
                 ("location", "Location"), ("dates", "Dates")]):
            corrected[field] = columns[position % 2].text_input(
                caption, value=str(entry.get(field) or ""), key=f"edu-{index}-{field}")
        education.append(corrected)
    if not education:
        st.caption("Nothing was read as education.")

    st.markdown("#### Experience")
    experiences = [
        _entry_fields(entry, index, "experience",
                      [("company", "Company"), ("title", "Title"),
                       ("location", "Location"), ("dates", "Dates")])
        for index, entry in enumerate(schema.get("experiences") or [])
    ]

    st.markdown("#### Projects")
    projects = [
        _entry_fields(entry, index, "project",
                      [("name", "Project"), ("tech", "Built with"),
                       ("dates", "Dates")])
        for index, entry in enumerate(schema.get("projects") or [])
    ]

    st.markdown("#### Skills")
    skills = {}
    for index, (category, values) in enumerate((schema.get("skills") or {}).items()):
        text = st.text_input(category, value=str(values or ""), key=f"skill-{index}")
        if text.strip():
            skills[category] = text.strip()

    corrected = {
        "contact": contact,
        "education": education,
        "experiences": [e for e in experiences if e],
        "projects": [p for p in projects if p],
        "skills": skills,
    }

    st.divider()
    nothing_left = not (corrected["experiences"] or corrected["projects"])
    if nothing_left:
        st.error("Keep at least one experience or project — a resume needs "
                 "something to tailor.")

    back, forward = st.columns([1, 3])
    if back.button("Start over"):
        st.session_state.pending_import = None
        st.rerun()

    if forward.button("This is right — build my profile", type="primary",
                     disabled=nothing_left):
        with st.spinner("Building your profile..."):
            resume_path = save_extracted(corrected, pending["source"])
            if not _build(resume_path, pending["name"], pending["force"]):
                return
        st.session_state.pending_import = None
        _goto(1)
        st.rerun()


# ------------------------------------------------------------ screen: 2 ----

BACKEND_HEADLINES = {
    "gemini": "Bullets will be rewritten by Google Gemini.",
    "openai": "Bullets will be rewritten through your OpenAI-compatible key.",
    "ollama": "Bullets will be rewritten locally by Ollama. Nothing leaves this machine.",
    "none": "Jobs will be scored and the right components picked for each one, "
            "but your bullets will be used exactly as you wrote them.",
}


def _backend_panel():
    """
    Say what will rewrite bullets, and let a key change it (R33).

    The key used to be mandatory here — Continue stayed disabled without one —
    which stopped being true the moment R36 moved embeddings off the API and
    R37 gave rewriting a floor that needs no model at all. Discovery, scoring
    and component selection now work with nothing configured, so demanding a
    key was the UI holding the door shut on a pipeline that had already
    learned to run without it.

    Detected and explained rather than asked: quality does differ between the
    rungs, and most people cannot answer "which model backend?" before they
    have seen the tool work once.
    """
    key = st.text_input(
        "Google Gemini API key (optional)", value=st.session_state.api_key,
        type="password",
        help="Stays on this machine and is passed straight to the pipeline. "
             "Free at aistudio.google.com/app/apikey. Without one, JobScout "
             "still finds and scores jobs and builds a resume per posting.",
    )

    # Re-detect when the answer could have changed, not on every rerun: the
    # check asks the network whether Ollama is up.
    cached = st.session_state.backend
    if cached is None or cached.get("key_used") != key:
        cached = backend_status(key)
        cached["key_used"] = key
        st.session_state.backend = cached

    chosen = cached["backend"]
    headline = BACKEND_HEADLINES.get(chosen, cached["description"])

    with st.container(border=True):
        if chosen == "none":
            st.warning(headline, icon="✍️")
            st.caption(
                "To get tailored bullets, add a Gemini key above, or install "
                "**Ollama** and run `ollama pull llama3.1` for a free local "
                "model that sends nothing anywhere."
            )
        else:
            st.success(headline, icon="✅")
            st.caption(cached["description"])

        if cached["forced"]:
            st.caption(
                f"`LLM_BACKEND` in config.py pins this to **{chosen}**, so "
                "detection is not choosing it."
            )

    return key




def screen_about_you():
    st.subheader("2. About you")
    st.caption(
        "Two things a resume cannot reliably tell us. An address line says "
        "where you live, not where you are allowed to work."
    )

    # Seeded, not blank: saving a blank form over stored answers is the same
    # silent revert the preferences screen had.
    try:
        stored = read_personal(st.session_state.profile_name)
    except Exception:
        stored = {"location": "", "visa_status": ""}

    location = st.text_input("Where are you based?", value=stored["location"],
                             placeholder="City, State")
    visa = st.selectbox(
        "Work authorisation", VISA_OPTIONS,
        index=VISA_OPTIONS.index(stored["visa_status"])
        if stored["visa_status"] in VISA_OPTIONS else 0,
    )

    key = _backend_panel()

    back, forward = st.columns([1, 5])
    if back.button("Back"):
        _goto(0)
        st.rerun()

    if forward.button("Continue", type="primary", disabled=not location):
        st.session_state.api_key = key
        update_profile_fields(st.session_state.profile_name, {
            "personal_info": {
                "location": location,
                "visa_status": visa,
                "us_citizen": visa == "US Citizen",
                "permanent_resident": visa == "Green Card",
            },
        })
        _goto(2)
        st.rerun()


# ------------------------------------------------------------ screen: 3 ----

def screen_preferences():
    st.subheader("3. What are you looking for?")

    # Seeded from the profile, never from this form's own defaults. A
    # returning user who opens this screen and saves would otherwise revert
    # every answer they had tuned, which is the same silent destruction the
    # nested-merge bug caused one layer down.
    try:
        current = read_preferences(st.session_state.profile_name)
    except Exception:
        current = {"target_roles": ["Software Engineer"], "seniority": ["new grad"],
                   "exclude_keywords": [], "cities": [], "remote_ok": True}

    options = ROLE_OPTIONS + [r for r in current["target_roles"] if r not in ROLE_OPTIONS]
    roles = st.multiselect("Target roles", options,
                           default=current["target_roles"] or ["Software Engineer"])

    levels = seniority_levels()
    seniority = st.multiselect(
        "Levels to look at", levels,
        default=[s for s in current["seniority"] if s in levels] or ["new grad"],
        format_func=lambda s: s.title(),
        help="Postings phrase these a dozen ways — 'recent graduate', "
             "'0-2 years', 'Engineer II' — so each level you pick matches "
             "more wordings than its name.",
    )

    cities = st.text_input("Cities (comma separated, optional)",
                           value=", ".join(current["cities"]),
                           placeholder="San Francisco, New York")
    remote_ok = st.checkbox("Remote roles are fine", value=current["remote_ok"])
    excludes = st.multiselect(
        "Skip postings mentioning",
        EXCLUDE_OPTIONS + [e for e in current["exclude_keywords"]
                           if e not in EXCLUDE_OPTIONS],
        default=current["exclude_keywords"],
        help="A hard filter on wording, separate from the levels above. "
             "Excluding 'senior' while asking for senior roles will find you "
             "nothing.",
    )

    back, forward = st.columns([1, 5])
    if back.button("Back"):
        _goto(1)
        st.rerun()

    if forward.button("Save and continue", type="primary",
                     disabled=not (roles and seniority)):
        update_profile_fields(st.session_state.profile_name, {
            "job_preferences": {
                "target_roles": roles,
                "seniority": seniority,
                "exclude_keywords": excludes,
                "locations": {
                    "cities": [c.strip() for c in cities.split(",") if c.strip()],
                    "remote_ok": remote_ok,
                },
            },
        })
        _goto(3)
        st.rerun()


# ------------------------------------------------------------ screen: 4 ----

def screen_tuning():
    st.subheader("4. Tune what gets shown")
    st.caption(
        "Optional. Trigger words are read from each component's tech stack, "
        "which means they cover what you *built with* but not what a posting "
        "*calls it*. A mobile project derives `ionic` and `capacitor`; the job "
        "ad says `android` and `mobile app`. Adding those is the one thing "
        "nobody but you can do."
    )

    try:
        rules = read_component_rules(st.session_state.profile_name)
    except Exception as exc:
        st.error(f"Could not read this profile: {exc}")
        return

    edits_tier, edits_triggers = {}, {}

    for section, heading in (("experiences", "Experience"), ("projects", "Projects")):
        st.markdown(f"#### {heading}")
        for component in rules[section]:
            with st.expander(component["label"], expanded=False):
                edits_tier[component["id"]] = st.radio(
                    "How central is this to your story?",
                    TIERS,
                    index=TIERS.index(component["tier"]) if component["tier"] in TIERS else 1,
                    horizontal=True,
                    key=f"tier-{component['id']}",
                    help="High gets the most bullets. Low is shown only when a "
                         "job specifically calls for it.",
                )
                text = st.text_area(
                    "Show this when a job description mentions",
                    value=", ".join(component["triggers"]),
                    placeholder="android, mobile app, mobile development",
                    key=f"trig-{component['id']}",
                    help="Comma separated. Leave empty for no rule.",
                )
                edits_triggers[component["id"]] = [t for t in text.split(",")]

    back, forward = st.columns([1, 5])
    if back.button("Back"):
        _goto(2)
        st.rerun()

    if forward.button("Save and continue", type="primary"):
        write_component_rules(st.session_state.profile_name, edits_tier, edits_triggers)
        st.success("Saved.")
        _goto(4)
        st.rerun()

    if st.button("Skip this"):
        _goto(4)
        st.rerun()


# ------------------------------------------------------------ screen: 5 ----

def screen_run():
    st.subheader("5. Find jobs and tailor resumes")

    has_latex = pdflatex_available()
    if not has_latex:
        st.info(
            "No LaTeX engine found, so you will get `.tex` files rather than PDFs. "
            "Install **MiKTeX** (Windows) or **TeX Live** (macOS/Linux) and rerun "
            "to get PDFs.",
            icon="ℹ️",
        )

    # A run paused at the review checkpoint takes over the screen: deciding
    # about it is the only sensible next action.
    if st.session_state.pending:
        _render_review(has_latex)
        return

    left, right = st.columns(2)
    max_jobs = left.slider("Jobs to search for", 5, 50, 20, step=5)
    max_resumes = right.slider("Resumes to generate", 1, 10, 3)
    review = st.checkbox(
        "Show me the jobs before writing resumes",
        help="Stops after scoring so you can see what was found. Generation is "
             "the expensive step, so this is where to spend a moment.",
    )

    if st.button("Run", type="primary"):
        _execute(max_jobs, max_resumes, has_latex, review)

    if st.session_state.results is not None:
        _render_results(st.session_state.results, has_latex)


def _execute(max_jobs, max_resumes, has_latex, review):
    orchestrator = JobScoutOrchestrator(
        profile_name=st.session_state.profile_name,
        api_key=st.session_state.api_key,
        max_resumes=max_resumes,
        generate_pdf=has_latex,
        # Checkpoints fall through to a terminal prompt unless answered by
        # callback (R26), which would hang the app. Always answered below.
        checkpoint=review,
    )

    # `checkpoint=True` arms a checkpoint at every stage, so the callback must
    # say *which* one to stop at. Declining indiscriminately halts after
    # Discovery, before anything has been scored, and the review screen then
    # shows nothing.
    state = _run_with_progress(
        orchestrator, max_jobs,
        on_checkpoint=lambda stage, items: stage != "analysis",
    )
    if state is None:
        return

    if review:
        st.session_state.pending = {
            "state": state,
            "enriched": orchestrator.enriched_jobs_file,
            "max_resumes": max_resumes,
        }
    else:
        st.session_state.results = state
    st.rerun()


def _render_review(has_latex):
    pending = st.session_state.pending
    scored = pending["state"].get("analysis_results") or []

    st.markdown(f"**{len(scored)} jobs scored.** Nothing has been written yet.")

    for record in scored[:15]:
        job = record.get("job", {})
        score = record.get("score", {}).get("overall")
        with st.container(border=True):
            st.markdown(f"**{job.get('company', '?')}** — {job.get('title', '?')}")
            bits = [job.get("location", "")]
            if score is not None:
                bits.append(f"{score:.0f}% match")
            st.caption("  ·  ".join(b for b in bits if b))
    if len(scored) > 15:
        st.caption(f"...and {len(scored) - 15} more")

    go, stop = st.columns([2, 1])
    if go.button(f"Write the top {pending['max_resumes']} resumes", type="primary"):
        _resume_generation(has_latex)
    if stop.button("Discard"):
        st.session_state.pending = None
        st.rerun()


def _resume_generation(has_latex):
    """
    Second half of a reviewed run.

    Replays from the enriched jobs the first half already wrote, so Discovery
    and Enrichment do not run twice. JD embeddings are cached (R28), so scoring
    them again costs nothing.
    """
    pending = st.session_state.pending
    orchestrator = JobScoutOrchestrator(
        profile_name=st.session_state.profile_name,
        api_key=st.session_state.api_key,
        max_resumes=pending["max_resumes"],
        generate_pdf=has_latex,
        input_file=pending["enriched"],
        checkpoint=False,
    )

    state = _run_with_progress(orchestrator, 0, on_checkpoint=lambda stage, items: True)
    if state is None:
        return

    st.session_state.pending = None
    st.session_state.results = state
    st.rerun()


def _run_with_progress(orchestrator, max_jobs, on_checkpoint):
    """Drive a run, streaming progress. Returns None if it failed."""
    with st.status("Running the pipeline...", expanded=True) as status:
        bar = st.progress(0.0)
        line = st.empty()

        def on_progress(event):
            bar.progress(event.fraction)
            label = event.stage.capitalize()
            if event.total:
                line.write(f"**{label}** {event.done}/{event.total} — {event.message}")
            else:
                line.write(f"**{label}** — {event.message}")

        try:
            state = orchestrator.run(
                max_jobs=max_jobs,
                on_progress=on_progress,
                on_checkpoint=on_checkpoint,
            )
        except Exception as exc:
            status.update(label="Pipeline failed", state="error")
            st.error(f"{exc}")
            st.caption(
                "A quota error means the free Gemini tier is used up for today. "
                "Anything already written is still in your outputs folder."
            )
            return None

        bar.progress(1.0)
        status.update(label="Done", state="complete")

    return state


def _render_results(state, has_latex):
    results = state.get("generation_results") or []
    analysed = state.get("analysis_results") or []

    if not results:
        st.warning("No resumes were generated. Try widening your preferences.")
        return

    st.success(f"{len(results)} resume(s) generated from {len(analysed)} scored jobs.")
    if st.button("See all your jobs"):
        st.session_state.view = "board"
        st.rerun()

    for item in results:
        job = item.get("job", {})
        score = next(
            (r["score"]["overall"] for r in analysed
             if r.get("job", {}).get("id") == job.get("id")),
            None,
        )

        header = f"{_plain(job.get('company')) or '?'} — {_plain(job.get('title')) or '?'}"
        if score is not None:
            header += f"  ·  {score:.0f}% match"

        with st.container(border=True):
            st.markdown(f"**{header}**")
            meta = [job.get("location", "")]
            if item.get("page_count"):
                meta.append(f"{item['page_count']} page")
            if item.get("status") != "valid":
                meta.append("needs review")
            st.caption("  ·  ".join(m for m in meta if m))

            columns = st.columns(2)
            pdf_path = item.get("pdf_path")
            show_pdf = has_latex and pdf_path
            if show_pdf:
                _download(columns[0], pdf_path, "Download PDF", "application/pdf")
            _download(columns[1] if show_pdf else columns[0],
                      item.get("latex_path"), "Download .tex", "text/plain")

            if job.get("apply_url"):
                st.link_button("Open the posting", job["apply_url"])


def _plain(text) -> str:
    """
    A scraped string, safe to drop inside markdown.

    Job titles come from other people's HTML, and one of the real ones ends in
    a space: `"Software Engineer II, Backend (Furnishing Platform) "`. Inside
    `**...**` a trailing space breaks the closing delimiter, so that row
    rendered its own asterisks. Stripping fixes that case and escaping covers
    the rest — a title with an asterisk or underscore in it would garble the
    same way, and nothing upstream promises it will not.
    """
    cleaned = (text or "").strip()
    for character in ("\\", "*", "_", "`", "[", "]"):
        cleaned = cleaned.replace(character, "\\" + character)
    return cleaned


def _download(column, path, label, mime, unique=""):
    """
    Offer a generated file, or say why it is missing rather than nothing.

    `unique` disambiguates the widget key. Keying on the path alone was enough
    for a run log, where each row is a different resume, and not enough for
    the board, where two postings can point at the same generated file —
    generation names a resume after the company and title, so two openings
    with the same title at the same company overwrite each other. The board is
    the first screen to show both of those rows at once, and Streamlit raised
    a duplicate-key error rather than rendering. Callers pass something that
    identifies the row.
    """
    if not path:
        return
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        column.caption(f"{label}: file missing")
        return

    column.download_button(label, data, file_name=os.path.basename(path),
                           mime=mime, key=f"{label}-{unique or path}")


# ----------------------------------------------------------------- board ----

STATUS_LABELS = {
    "new": "New",
    "seen": "Seen",
    "applied": "Applied",
    "rejected": "Rejected",
    "archived": "Archived",
}


def screen_board(has_latex):
    """
    Every job ever discovered, not just this run's (R33, R35).

    The run screen answers "what did that run do"; this answers "what am I
    working through", which is the question a person actually returns to a job
    tool with. The store keeps score, status and resume paths per posting, so
    a job marked `applied` stays applied across runs that re-find it.
    """
    st.subheader("Your jobs")

    stats = board_stats()
    if not stats["total"]:
        st.info(
            "No jobs yet. Run a search and everything it finds is kept here — "
            "scores, statuses and the resumes written for each posting.",
            icon="🔍",
        )
        return

    a, b, c = st.columns(3)
    a.metric("Jobs found", stats["total"])
    b.metric("Scored", stats["scored"])
    c.metric("With a resume", stats["with_resume"])

    counts = stats["by_status"]
    statuses = job_statuses()

    with st.container(border=True):
        left, middle, right = st.columns([2, 1, 1])
        shown = left.multiselect(
            "Show", statuses,
            default=[s for s in statuses if s != "archived"],
            format_func=lambda s: f"{STATUS_LABELS.get(s, s)} ({counts.get(s, 0)})",
        )
        min_score = middle.slider("Minimum score", 0, 100, 0, step=5)
        only_resumes = right.checkbox("Only with a resume")

    rows = board_jobs(
        status=shown or None,
        min_score=min_score or None,
        has_resume=True if only_resumes else None,
    )

    if not rows:
        st.caption("Nothing matches those filters.")
        return

    st.caption(f"{len(rows)} job(s)")

    for row in rows:
        _board_row(row, statuses, has_latex)


def _board_row(row, statuses, has_latex):
    url = row["url"]
    with st.container(border=True):
        heading, control = st.columns([4, 1])

        title = f"**{_plain(row.get('company')) or '?'} — {_plain(row.get('title')) or '?'}**"
        if row.get("score") is not None:
            title += f"  ·  {row['score']:.0f}% match"
        heading.markdown(title)

        meta = [row.get("location") or "", row.get("source") or ""]
        if row.get("scored_at") is None:
            meta.append("not scored yet")
        heading.caption("  ·  ".join(m for m in meta if m))

        # Writing only on a real change keeps a render from re-recording the
        # status a row already has.
        current = row.get("status") or "new"
        picked = control.selectbox(
            "Status", statuses,
            index=statuses.index(current) if current in statuses else 0,
            format_func=lambda s: STATUS_LABELS.get(s, s),
            key=f"status-{url}", label_visibility="collapsed",
        )
        if picked != current:
            set_job_status(url, picked)
            st.rerun()

        buttons = st.columns(3)
        pdf_path = row.get("resume_pdf")
        if has_latex and pdf_path:
            _download(buttons[0], pdf_path, "PDF", "application/pdf", unique=url)
        if row.get("resume_tex"):
            _download(buttons[1], row["resume_tex"], ".tex", "text/plain", unique=url)
        if url:
            buttons[2].link_button("Open posting", url)


# ------------------------------------------------------------------ main ----

def _sidebar(step):
    st.sidebar.success(f"Profile: **{st.session_state.profile_name}**")

    if st.session_state.view == "board":
        if st.sidebar.button("Back to setup", type="primary"):
            st.session_state.view = "setup"
            st.rerun()
    elif st.sidebar.button("Your jobs", type="primary"):
        st.session_state.view = "board"
        st.rerun()

    st.sidebar.caption("Steps")
    for index, name in enumerate(STEPS):
        if index <= st.session_state.max_step and st.sidebar.button(name, key=f"nav-{index}"):
            _goto(index)
            st.rerun()

    # Resumes outlive the session that made them; session_state does not.
    # Without this, closing the tab loses every download link to files still
    # sitting in outputs/.
    runs = previous_runs()
    if runs:
        with st.sidebar.expander("Previous runs"):
            for run in runs:
                if not run["resumes"]:
                    continue
                if st.button(f"{run['date']} — {run['resumes']} resume(s)",
                             key=f"run-{run['date']}"):
                    st.session_state.results = load_run(run["path"])
                    st.session_state.pending = None
                    _goto(4)
                    st.rerun()


def main():
    st.set_page_config(page_title="JobScout", page_icon="📄", layout="centered")
    _init_state()

    st.title("JobScout")
    st.caption("Find roles at your level and tailor your resume to each one, locally.")

    step = st.session_state.step

    if step > 0 and st.session_state.profile_name:
        _sidebar(step)

    if st.session_state.view == "board":
        screen_board(pdflatex_available())
        return

    st.progress((step + 1) / len(STEPS),
                text=f"Step {step + 1} of {len(STEPS)}: {STEPS[step]}")

    [screen_resume, screen_about_you, screen_preferences,
     screen_tuning, screen_run][step]()


if __name__ == "__main__":
    main()

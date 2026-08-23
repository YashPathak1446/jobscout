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
    load_run,
    pdflatex_available,
    previous_runs,
)
from scripts.init_profile import (
    create_profile,
    read_component_rules,
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


def _goto(step: int):
    st.session_state.step = step
    st.session_state.max_step = max(st.session_state.get("max_step", 0), step)


# ------------------------------------------------------------ screen: 1 ----

def screen_resume():
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

    if st.button("Build my profile", type="primary",
                 disabled=not (uploaded and name) or (clash and not confirmed)):
        with st.spinner("Reading your resume..."):
            resume_path = save_resume(uploaded.getvalue(), uploaded.name)
            try:
                summary = create_profile(resume_path, name, force=confirmed)
            except FileExistsError:
                st.error(f"A profile named '{name}' already exists.")
                return
            except Exception as exc:                       # surfaced, not swallowed
                st.error(f"Could not build a profile from that resume: {exc}")
                return

        st.session_state.profile_name = name
        st.session_state.setup_summary = summary
        _goto(1)
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


# ------------------------------------------------------------ screen: 2 ----

def screen_about_you():
    st.subheader("2. About you")
    st.caption(
        "Two things a resume cannot reliably tell us, plus your API key. "
        "An address line says where you live, not where you are allowed to work."
    )

    key = st.text_input(
        "Google Gemini API key", value=st.session_state.api_key, type="password",
        help="Stays on this machine and is passed straight to the pipeline. "
             "Get one free at aistudio.google.com/app/apikey",
    )
    location = st.text_input("Where are you based?", placeholder="City, State")
    visa = st.selectbox("Work authorisation", VISA_OPTIONS, index=0)

    back, forward = st.columns([1, 5])
    if back.button("Back"):
        _goto(0)
        st.rerun()

    if forward.button("Continue", type="primary", disabled=not (key and location)):
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

    roles = st.multiselect("Target roles", ROLE_OPTIONS, default=["Software Engineer"])
    cities = st.text_input("Cities (comma separated, optional)",
                           placeholder="San Francisco, New York")
    remote_ok = st.checkbox("Remote roles are fine", value=True)
    excludes = st.multiselect(
        "Skip postings mentioning", EXCLUDE_OPTIONS,
        default=["senior", "staff", "principal", "5+ years"],
        help="Filters out roles you are not eligible for as a new grad.",
    )

    back, forward = st.columns([1, 5])
    if back.button("Back"):
        _goto(1)
        st.rerun()

    if forward.button("Save and continue", type="primary", disabled=not roles):
        update_profile_fields(st.session_state.profile_name, {
            "job_preferences": {
                "target_roles": roles,
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

    for item in results:
        job = item.get("job", {})
        score = next(
            (r["score"]["overall"] for r in analysed
             if r.get("job", {}).get("id") == job.get("id")),
            None,
        )

        header = f"{job.get('company', '?')} — {job.get('title', '?')}"
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


def _download(column, path, label, mime):
    """Offer a generated file, or say why it is missing rather than nothing."""
    if not path:
        return
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        column.caption(f"{label}: file missing")
        return

    column.download_button(label, data, file_name=os.path.basename(path),
                           mime=mime, key=f"{label}-{path}")


# ------------------------------------------------------------------ main ----

def _sidebar(step):
    st.sidebar.success(f"Profile: **{st.session_state.profile_name}**")

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
    st.caption("Find new-grad roles and tailor your resume to each one, locally.")

    step = st.session_state.step
    st.progress((step + 1) / len(STEPS),
                text=f"Step {step + 1} of {len(STEPS)}: {STEPS[step]}")

    if step > 0 and st.session_state.profile_name:
        _sidebar(step)

    [screen_resume, screen_about_you, screen_preferences,
     screen_tuning, screen_run][step]()


if __name__ == "__main__":
    main()

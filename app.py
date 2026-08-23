"""
JobScout — local Streamlit UI.

**This file is a view layer and nothing else (R25).** It reads answers from
widgets, calls into the pipeline, and renders what comes back. It does no
filtering, ranking, scoring or path-building, and it imports nothing from
`tools/`. The hosted tier is planned as React + FastAPI; keeping this boundary
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
    pdflatex_available,
)
from scripts.init_profile import (
    create_profile,
    save_resume,
    update_profile_fields,
)

VISA_OPTIONS = [
    "US Citizen",
    "Green Card",
    "F1 OPT",
    "F1 CPT",
    "H1B",
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

STEPS = ["Resume", "About you", "Preferences", "Run"]


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


def _goto(step: int):
    st.session_state.step = step
    st.session_state.max_step = max(st.session_state.get("max_step", 0), step)


# ---------------------------------------------------------- screen: 1/3 ----

def screen_resume():
    st.subheader("1. Your resume")
    st.caption(
        "Upload your master LaTeX resume. Everything the resume already states "
        "is read from it — name, contact links, education, and which of your "
        "projects suit which jobs."
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
                _goto(3)
                st.rerun()
        st.caption("Or upload a resume below to start fresh.")

    uploaded = st.file_uploader("Master resume (.tex)", type=["tex"])
    name = st.text_input(
        "Profile name",
        value=st.session_state.profile_name or "",
        placeholder="e.g. jane_doe",
        help="Used for the profile file and generated resume filenames.",
    )

    # Overwriting is never implicit. Building a profile discards every rule the
    # owner tuned by hand — the JD trigger lists especially, which are the
    # difference between good component selection and generic selection — and
    # nothing else on disk records them. `create_profile` raises
    # FileExistsError precisely so this screen can ask first.
    clash = name and name in existing
    if clash:
        st.warning(
            f"**{name}** already exists. Rebuilding replaces it completely, "
            "including any rules you tuned by hand. This cannot be undone.",
            icon="⚠️",
        )
    confirmed = st.checkbox(f"Yes, replace '{name}'") if clash else False

    build_disabled = not (uploaded and name) or (clash and not confirmed)

    if st.button("Build my profile", type="primary", disabled=build_disabled):
        with st.spinner("Reading your resume..."):
            resume_path = save_resume(uploaded.getvalue(), uploaded.name)
            try:
                summary = create_profile(resume_path, name, force=confirmed)
            except FileExistsError:
                # Only reachable if the profile appeared between render and
                # click. Refusing is still the right answer.
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

        with st.expander("What was read from your resume"):
            for field, value in summary["derived"].items():
                st.write(f"**{field}** — {value}")


# ---------------------------------------------------------- screen: 2/3 ----

def screen_about_you():
    st.subheader("2. About you")
    st.caption(
        "Two things a resume cannot reliably tell us, plus your API key. "
        "An address line says where you live, not where you are allowed to work."
    )

    key = st.text_input(
        "Google Gemini API key",
        value=st.session_state.api_key,
        type="password",
        help="Stays on this machine and is passed straight to the pipeline. "
             "Get one free at aistudio.google.com/app/apikey",
    )
    location = st.text_input("Where are you based?", placeholder="City, State")
    visa = st.selectbox("Work authorisation", VISA_OPTIONS, index=0)

    col_back, col_next = st.columns([1, 5])
    if col_back.button("Back"):
        _goto(0)
        st.rerun()

    if col_next.button("Continue", type="primary", disabled=not (key and location)):
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


# ---------------------------------------------------------- screen: 3/3 ----

def screen_preferences():
    st.subheader("3. What are you looking for?")

    roles = st.multiselect(
        "Target roles", ROLE_OPTIONS, default=["Software Engineer"],
    )
    cities = st.text_input(
        "Cities (comma separated, optional)", placeholder="San Francisco, New York",
    )
    remote_ok = st.checkbox("Remote roles are fine", value=True)
    excludes = st.multiselect(
        "Skip postings mentioning",
        EXCLUDE_OPTIONS,
        default=["senior", "staff", "principal", "5+ years"],
        help="Filters out roles you are not eligible for as a new grad.",
    )

    col_back, col_next = st.columns([1, 5])
    if col_back.button("Back"):
        _goto(1)
        st.rerun()

    if col_next.button("Save and continue", type="primary", disabled=not roles):
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


# ------------------------------------------------------------ screen: run --

def screen_run():
    st.subheader("4. Find jobs and tailor resumes")

    has_latex = pdflatex_available()
    if not has_latex:
        st.info(
            "No LaTeX engine found, so you will get `.tex` files rather than PDFs. "
            "Install **MiKTeX** (Windows) or **TeX Live** (macOS/Linux) and rerun "
            "to get PDFs.",
            icon="ℹ️",
        )

    col_a, col_b = st.columns(2)
    max_jobs = col_a.slider("Jobs to search for", 5, 50, 20, step=5)
    max_resumes = col_b.slider("Resumes to generate", 1, 10, 3)

    if st.button("Run", type="primary"):
        _execute(max_jobs, max_resumes, has_latex)

    if st.session_state.results is not None:
        _render_results(st.session_state.results, has_latex)


def _execute(max_jobs: int, max_resumes: int, has_latex: bool):
    orchestrator = JobScoutOrchestrator(
        profile_name=st.session_state.profile_name,
        api_key=st.session_state.api_key,
        max_resumes=max_resumes,
        generate_pdf=has_latex,
        # Checkpoints are terminal prompts unless a callback answers them
        # (R26). Both belt and braces: disabled here, and answered below.
        checkpoint=False,
    )

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
                on_checkpoint=lambda stage, items: True,
            )
        except Exception as exc:
            status.update(label="Pipeline failed", state="error")
            st.error(f"{exc}")
            st.caption(
                "A quota error means the free Gemini tier is used up for today. "
                "Anything already written is still in your outputs folder."
            )
            return

        bar.progress(1.0)
        status.update(label="Done", state="complete")

    st.session_state.results = state
    st.rerun()


def _render_results(state: dict, has_latex: bool):
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

            cols = st.columns(2)
            pdf_path = item.get("pdf_path")
            if has_latex and pdf_path:
                _download(cols[0], pdf_path, "Download PDF", "application/pdf")
            _download(cols[1] if (has_latex and pdf_path) else cols[0],
                      item.get("latex_path"), "Download .tex", "text/plain")

            if job.get("apply_url"):
                st.link_button("Open the posting", job["apply_url"])


def _download(column, path, label: str, mime: str):
    """Offer a generated file, or say why it is missing rather than nothing."""
    if not path:
        return
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        column.caption(f"{label}: file missing")
        return

    column.download_button(
        label, data, file_name=os.path.basename(path),
        mime=mime, key=f"{label}-{path}",
    )


# ------------------------------------------------------------------ main ----

def main():
    st.set_page_config(page_title="JobScout", page_icon="📄", layout="centered")
    _init_state()

    st.title("JobScout")
    st.caption("Find new-grad roles and tailor your resume to each one, locally.")

    step = st.session_state.step
    st.progress((step + 1) / len(STEPS), text=f"Step {step + 1} of {len(STEPS)}: {STEPS[step]}")

    if step > 0 and st.session_state.profile_name:
        st.sidebar.success(f"Profile: **{st.session_state.profile_name}**")
        st.sidebar.caption("Steps")
        for index, name in enumerate(STEPS):
            if index <= st.session_state.max_step and st.sidebar.button(name, key=f"nav-{index}"):
                _goto(index)
                st.rerun()

    [screen_resume, screen_about_you, screen_preferences, screen_run][step]()


if __name__ == "__main__":
    main()

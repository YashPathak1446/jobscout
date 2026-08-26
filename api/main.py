"""
JobScout — the HTTP boundary.

**This file is a view layer and nothing else, on exactly the terms `app.py`
is (R25).** It reads query parameters, calls into the pipeline, and returns
what comes back as JSON. It does no filtering, ranking, scoring or
path-building, and it imports nothing from `tools/`.
`tests/test_ui_contract.py` fails the build if that stops being true.

R25 chose Streamlit on the condition that the eventual React + FastAPI port
would be a re-skin rather than a rewrite. This is that port's half of the
bargain being collected: every endpoint below is a thin wrapper over a
function `app.py` already calls, and the two UIs are interchangeable views of
the same surface. Nothing in `agents/orchestrator.py` changed to make this
work, which is the evidence the boundary was real.

Local and single-user, by design. There is no auth here because there is no
second user — the hosted tier is a separate project (Q15), and putting a
half-built session layer in now would be the speculative generality R4
rejected.

Run it with:
    uvicorn api.main:app --reload --port 8000
"""

from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agents.orchestrator import (
    available_profiles,
    backend_status,
    board_filters,
    board_job,
    board_jobs,
    board_sorts,
    board_stats,
    board_total,
    ghosted_jobs,
    job_history,
    job_selection,
    job_statuses,
    pdflatex_available,
    previous_runs,
    refresh_board_gate,
    score_bands,
    set_job_status,
)
from scripts.init_profile import (
    create_profile,
    extract_resume,
    read_component_rules,
    read_personal,
    read_preferences,
    save_extracted,
    update_profile_fields,
    write_component_rules,
)

app = FastAPI(title="JobScout", version="1.0.0")

# The Vite dev server runs on a different port, so the browser treats it as a
# different origin. Both are localhost on this machine and there is nothing
# to protect against here; the hosted tier will not use this list.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------- meta ----

@app.get("/api/health")
def health() -> dict:
    """What this machine can do, which the UI has to say out loud (R43)."""
    return {
        "profiles": available_profiles(),
        "backend": backend_status(),
        "pdflatex": pdflatex_available(),
        "statuses": list(job_statuses()),
        "sorts": board_sorts(),
    }


# ------------------------------------------------------------ board ----

@app.get("/api/board")
def board(
    status: Optional[str] = None,
    min_score: Optional[float] = None,
    has_resume: Optional[bool] = None,
    company: Optional[str] = None,
    source: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "best",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_ineligible: bool = False,
) -> dict:
    """
    One page of the board, and the total it is a page of.

    The total ships with the page rather than behind its own endpoint because
    a page cap with no total looks exactly like running out of jobs — the
    thing R65 fixed in the Streamlit board, and which a React rewrite would
    otherwise be free to reintroduce.
    """
    criteria = dict(status=status, min_score=min_score, has_resume=has_resume,
                    company=company, source=source, search=search)
    total = board_total(include_ineligible=include_ineligible, **criteria)

    # How many the gate is holding back under these same filters. R62 excludes
    # them by default and says the screen must state the number — "a filter
    # that removes things without saying so is the shape this project keeps
    # regretting". The count belongs here rather than in the UI because the UI
    # would have to issue a second query to work it out, and a number nobody
    # can be bothered to fetch is a number that stops being shown.
    hidden = 0 if include_ineligible else (
        board_total(include_ineligible=True, **criteria) - total)

    return {
        "jobs": [_without_jd(row)
                 for row in board_jobs(sort=sort, limit=limit, offset=offset,
                                       include_ineligible=include_ineligible,
                                       **criteria)],
        "total": total,
        "hidden": hidden,
        "offset": offset,
        "limit": limit,
    }


def _without_jd(row: dict) -> dict:
    """
    Drop the posting text from a list row.

    Measured: a 50-row page is 336 KB with `full_jd` and 44 KB without, so 87%
    of the board's payload is job descriptions nothing on the list renders.
    This is a transport decision, not a pipeline one — the row is unchanged,
    the field is simply not on the wire until `/api/job` is asked for it. The
    boolean stays so the UI can tell "no description" from "not sent here",
    which is the distinction this codebase keeps collapsing.
    """
    return {**{k: v for k, v in row.items() if k != "full_jd"},
            "has_jd": bool(row.get("full_jd"))}


@app.get("/api/board/stats")
def stats() -> dict:
    return board_stats()


@app.get("/api/board/filters")
def filters() -> dict:
    """Companies and sources with counts, read from the store, not a list here."""
    return board_filters()


@app.get("/api/board/bands")
def bands() -> dict:
    """Quartiles, so a screen can say where a job sits among yours (R67)."""
    return score_bands()


@app.get("/api/board/ghosted")
def ghosted(after_days: Optional[int] = None) -> list:
    return ghosted_jobs(after_days=after_days)


class GateRequest(BaseModel):
    profile: str


@app.post("/api/board/gate")
def gate(request: GateRequest) -> dict:
    """Re-judge the stored rows against a profile. Returns how many moved."""
    return {"rejudged": refresh_board_gate(request.profile)}


# -------------------------------------------------------------- job ----

@app.get("/api/job")
def job(url: str) -> dict:
    """
    One job's detail: why it scored as it did, and everywhere it has been.

    `selection` is the panel R64 built — facts about the posting rather than
    verdicts about the reader — and it is None for a job analysis never
    reached. The UI has to render that difference rather than showing an
    empty panel, because unknown is not the same as nothing to say.
    """
    row = board_job(url)
    if row is None:
        raise HTTPException(status_code=404, detail="No such job")
    return {
        "job": row,
        "selection": job_selection(url),
        "history": job_history(url),
    }


class StatusRequest(BaseModel):
    url: str
    status: str


@app.post("/api/job/status")
def update_status(request: StatusRequest) -> dict:
    if request.status not in job_statuses():
        raise HTTPException(
            status_code=422,
            detail=f"{request.status!r} is not one of {list(job_statuses())}")
    set_job_status(request.url, request.status)
    return {"url": request.url, "status": request.status}


# ------------------------------------------------------- setup: resume ----

# Uploads land here, and the only thing a client is ever given back is a bare
# filename. `extract_resume` returns an absolute path, which would be the
# obvious thing to hand over and take back on the confirm call — and that is a
# client choosing which file the server opens. Names are resolved against this
# directory instead, so the worst a caller can name is a file in it.
RESUME_DIR = Path.cwd() / "data" / "master_resumes"


def _resolve_upload(filename: str) -> Path:
    candidate = (RESUME_DIR / Path(filename).name).resolve()
    if candidate.parent != RESUME_DIR.resolve() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="No such uploaded resume")
    return candidate


@app.post("/api/resume/extract")
async def resume_extract(file: UploadFile = File(...)) -> dict:
    """
    Read an upload far enough to show it, without committing to anything.

    R33's rule is that every extracted field is confirmed before use, which
    only works if extracting and writing are two calls with a person in
    between. A `.tex` skips confirmation because it is already the pipeline's
    own format — there is nothing a model guessed at.
    """
    try:
        extracted = extract_resume(await file.read(), file.filename or "resume")
    except ValueError as exc:
        # A scanned image, or a PDF with no readable experience in it. The
        # message says which; it is written for the person, not the log.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # surfaced, not swallowed
        raise HTTPException(status_code=400,
                            detail=f"Could not read that resume: {exc}") from exc

    if extracted["kind"] == "latex":
        return {"kind": "latex", "filename": Path(extracted["path"]).name}
    return {
        "kind": "extracted",
        "filename": Path(extracted["source"]).name,
        "schema": extracted["schema"],
    }


class ProfileRequest(BaseModel):
    name: str
    filename: str
    force: bool = False
    # Present when the upload needed confirming; absent for a .tex. This is
    # what the person corrected, not what the model said, which is the entire
    # point of the two-call split.
    schema_: Optional[dict[str, Any]] = None

    model_config = {"populate_by_name": True}


@app.post("/api/profile")
def profile_create(request: ProfileRequest) -> dict:
    """
    Build a profile from a confirmed resume.

    Overwriting is never implicit: `create_profile` raises when the name is
    taken and `force` is not set, and one profile was already lost to a
    rebuild that discarded hand-tuned rules (R30). The 409 exists so the UI
    can ask rather than clobber.
    """
    source = _resolve_upload(request.filename)
    resume_path = (save_extracted(request.schema_, source)
                   if request.schema_ else source)
    try:
        return create_profile(resume_path, request.name, force=request.force)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # surfaced, not swallowed
        raise HTTPException(
            status_code=400,
            detail=f"Could not build a profile from that resume: {exc}") from exc


# ------------------------------------------------------ setup: profile ----

@app.get("/api/profile/{name}")
def profile_read(name: str) -> dict:
    """Everything the wizard's forms need, in the shape they need it."""
    try:
        return {
            "personal": read_personal(name),
            "preferences": read_preferences(name),
            "components": read_component_rules(name),
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class ProfileUpdate(BaseModel):
    updates: dict[str, Any]


@app.patch("/api/profile/{name}")
def profile_update(name: str, request: ProfileUpdate) -> dict:
    """
    Save part of a profile without disturbing the rest.

    `update_profile_fields` merges nested sections rather than replacing
    them. That is load-bearing: the preferences screen saves two of
    `locations`' seven fields, and a wholesale replace dropped `countries`,
    which the schema requires — walking the wizard left a profile that would
    not load. A form must not destroy what it never showed (R30).
    """
    try:
        path = update_profile_fields(name, request.updates)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"saved": Path(path).name}


class ComponentRules(BaseModel):
    importance: dict[str, Any]
    triggers: dict[str, Any]


@app.put("/api/profile/{name}/components")
def components_write(name: str, request: ComponentRules) -> dict:
    try:
        write_component_rules(name, request.importance, request.triggers)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"saved": name}


# ------------------------------------------------------------- runs ----

@app.get("/api/runs")
def runs(limit: int = Query(10, ge=1, le=50)) -> list:
    """Past runs, because resumes outlive the session that made them."""
    return previous_runs(limit=limit)


@app.get("/api/file")
def file(path: str):
    """
    Serve a generated resume for download.

    The path comes from a board row rather than from the user, but it arrives
    over HTTP either way, so it is resolved and checked against the outputs
    directory before anything is opened. A local single-user app is still an
    app with an open port on it.
    """
    root = (Path.cwd() / "outputs").resolve()
    target = (Path.cwd() / path).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="No such generated file")
    return FileResponse(target, filename=target.name)

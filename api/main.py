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
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
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

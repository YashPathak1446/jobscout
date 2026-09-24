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

**Two modes (pilot plan A5).** `JOBSCOUT_MODE=local`, the default, is one
person on their own machine: no accounts, and every facade call is the
unscoped user. It serves loopback clients only, and refuses anything else with
a 403 and an ERROR log line — a deploy that lost the flag has to be loud, not
open. `JOBSCOUT_MODE=hosted` needs `JOBSCOUT_SESSION_SECRET` or the import
below refuses to boot, and every `/api` route except signing in names its
caller through a signed session cookie.

**Authorization is by partition, not by predicate.** No route checks that a
job, a run or a file "belongs" to the caller: each one reads the caller's own
stores (A3), where somebody else's job, run or file does not exist. So another
user's identifier gets exactly the 404 a made-up one does, byte for byte, and
`tests/test_authorization.py` holds that. A 403 would be a confirmation that
the thing exists.

`_caller` is how a route learns who is asking, and every `/api` route outside
`OPEN_ROUTES` must depend on it — `test_every_api_route_names_its_caller`
walks the routes and fails on one that does not. Local mode's `None` comes out
of that dependency, never out of a literal at a call site, which is what
`test_hosted_mode_has_no_unscoped_call_site` counts.

The shared-password Basic-auth gate this file carried until A5 is gone. It was
authentication without authorization, and its docstring said it would be
deleted the day accounts landed rather than extended.

Run it with:
    uvicorn api.main:app --reload --port 8000
"""

import ipaddress
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import (Depends, FastAPI, File, Form, HTTPException, Query, Request,
                     UploadFile)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents.orchestrator import (
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    EmailTaken,
    InviteRefused,
    PassphraseRefused,
    RunInProgress,
    RunSizeRefused,
    account_email,
    active_runs,
    available_profiles,
    backend_status,
    board_filters,
    board_job,
    board_jobs,
    board_sorts,
    board_stats,
    board_total,
    check_hosting,
    delete_user_data,
    derived_levels,
    ghosted_jobs,
    hosting_mode,
    job_history,
    job_selection,
    job_statuses,
    pdflatex_available,
    previous_runs,
    redact_keys,
    redeem_invite,
    reap_stale_runs,
    refresh_board_gate,
    score_bands,
    seniority_levels,
    session_user,
    set_job_status,
    sign_in,
    start_error_reporting,
    start_run,
    run_limits,
    run_status,
    user_outputs_root,
    YEARS_EXPERIENCE_MAX,
)
from scripts.init_profile import (
    BadProfileName,
    ProfileInvalid,
    ProfileLimit,
    create_profile,
    extract_resume,
    profile_limit,
    read_component_rules,
    read_personal,
    read_preferences,
    resume_dir,
    save_extracted,
    update_profile_fields,
    write_component_rules,
)

# Refuse to boot an instance that cannot name its callers: `hosted` without a
# session secret, a mode that is not one of the two words, or local mode on a
# hosting platform. At import, so uvicorn exits before it binds.
check_hosting()

log = logging.getLogger("jobscout.api")


def _bound_host(argv=None) -> Optional[str]:
    """The `--host` uvicorn was started with, or None if it was not given."""
    argv = sys.argv if argv is None else argv
    for i, arg in enumerate(argv):
        if arg == "--host" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--host="):
            return arg.split("=", 1)[1]
    return os.getenv("UVICORN_HOST")


def _warn_if_local_mode_is_listening_widely(argv=None) -> bool:
    """
    Local mode bound past loopback — the shipped Dockerfile's `--host 0.0.0.0`
    run without `JOBSCOUT_MODE=hosted` — is said at boot, at ERROR, before
    the first request is refused. Said rather than refused: the middleware
    below is what enforces, and this reads argv, which is a hint about the
    bind and not the bind itself. Returns whether it warned.
    """
    host = _bound_host(argv)
    if check_hosting() != "local" or host is None or _is_loopback(host):
        return False
    log.error("JOBSCOUT_MODE is local but uvicorn is bound to %s. Local mode "
              "has no accounts; every request from another machine will be "
              "refused. If this is a deploy, set JOBSCOUT_MODE=hosted and "
              "JOBSCOUT_SESSION_SECRET.", host)
    return True

# Before the app exists, so Sentry's FastAPI integration sees it built. Off
# unless SENTRY_DSN is set: a checkout and the test suite send nothing (A9).
start_error_reporting()



@asynccontextmanager
async def _lifespan(_app):
    # The startup sweep (R120, Q49). A run a previous process left `queued` or
    # `running` has no worker, and until it is failed it parks its owner's run
    # screen and refuses their next run and their account deletion. At boot,
    # not at import: importing this module (as every test does) must not
    # write to anybody's runs.db.
    reap_stale_runs()
    yield


app = FastAPI(title="JobScout", version="1.0.0", lifespan=_lifespan)

# The Vite dev server runs on a different port, so the browser treats it as a
# different origin. Both are localhost on this machine and there is nothing to
# protect against here.
#
# Deployed, this list is simply unused: the API serves the built React from
# its own origin (see the mount at the bottom of this file), so the browser
# never makes a cross-origin request and CORS never applies. The previous
# comment said "the hosted tier will not use this list", which was right about
# the list and wrong about why — it read as though something would replace it,
# when in fact same-origin serving makes it moot. What actually needed
# replacing was the protection it was accidentally providing.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def _validation_refused(request: Request, exc: RequestValidationError):
    """
    FastAPI's 422, without the request echoed back (R117).

    Its default puts each failing field's `input` in the response, and a
    missing field's input is the *whole body*, so a run request without a
    `profile` would have sent its `api_key` back in an error message. The
    location and the reason are kept; the values are not.
    """
    errors = [{k: v for k, v in error.items() if k in ("type", "loc", "msg")}
              for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})


# Liveness only. Deliberately says nothing about the machine — `/api/health`
# lists profile names, which is a fact about a person, and a health check runs
# unauthenticated by definition.
LIVENESS = "/healthz"


def _is_loopback(host: Optional[str]) -> bool:
    # Starlette's TestClient reports its peer as the literal "testclient",
    # which no TCP connection can: a real peer is always an address.
    if host is None or host == "testclient":
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def _from_elsewhere(request: Request) -> Optional[str]:
    """The first non-loopback address this request came from, or None."""
    peer = request.client.host if request.client else None
    if not _is_loopback(peer):
        return peer
    # A reverse proxy on this machine makes every peer loopback, and says who
    # it was forwarding for. Uvicorn already rewrites the peer from these when
    # the proxy is loopback; checking them again costs nothing.
    forwarded = request.headers.get("x-forwarded-for", "")
    for hop in (part.strip() for part in forwarded.split(",")):
        if hop and not _is_loopback(hop):
            return hop
    return None


_warn_if_local_mode_is_listening_widely()


@app.middleware("http")
async def local_mode_serves_this_machine_only(request: Request, call_next):
    """
    Local mode has no accounts and one unscoped user, which is correct on a
    laptop and an open instance anywhere else. The mode is one environment
    variable, and a deploy that drops it would otherwise come up silently
    serving every caller one directory.

    So in local mode a request from a non-loopback peer is refused, on every
    path including `/healthz` and the static build, and logged at ERROR every
    time. A platform health check then fails the deploy, which is the point:
    noisy, not open. There is no switch to allow it — a person who wants the
    app reachable from another machine wants hosted mode, which has a door.
    """
    if hosting_mode() == "local":
        stranger = _from_elsewhere(request)
        if stranger is not None:
            log.error(
                "Refused %s %s from %s: JOBSCOUT_MODE is local, which has no "
                "accounts and serves loopback only. If this instance is "
                "deployed, set JOBSCOUT_MODE=hosted and JOBSCOUT_SESSION_SECRET.",
                request.method, request.url.path, stranger)
            return Response(
                status_code=403,
                content="This JobScout instance is in local mode and serves "
                        "this machine only.",
                media_type="text/plain")
    return await call_next(request)


def _caller(request: Request) -> Optional[str]:
    """
    Whose data this request is served from.

    Local mode: `None`, the unscoped layout — one person, no accounts.
    Hosted: the user id the session cookie names, or a 401. Absent, tampered,
    expired, signed under another secret, or for a deleted account all get the
    same 401 with the same body: which one it was is not the caller's business.
    """
    if hosting_mode() == "local":
        return None
    user = session_user(request.cookies.get(SESSION_COOKIE, ""))
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return user


# The only `/api` routes a caller reaches without being signed in: finding out
# whether you are, signing in, signing out, and redeeming an invite.
OPEN_ROUTES = {("GET", "/api/session"), ("POST", "/api/session"),
               ("DELETE", "/api/session"), ("POST", "/api/account")}


@app.get(LIVENESS)
def healthz() -> dict:
    """Is the process up. Nothing else, on purpose."""
    return {"ok": True}


# ---------------------------------------------------------- session ----
#
# Invite-only (plan decision 2): `scripts/admin.py invite` prints a code, the
# friend redeems it here with an email and a passphrase, and is signed in.
# There is no public signup and no reset flow — the admin script is the reset.

def _no_accounts_here() -> None:
    raise HTTPException(status_code=404,
                        detail="This instance runs in local mode and has no accounts.")


def _set_session(response: Response, token: str) -> None:
    # HttpOnly: no script reads it. Secure: never over plain HTTP (browsers
    # treat localhost as secure, so a local hosted-mode run still works).
    # SameSite=Strict: no other site's page can make a request that carries
    # it, which is this app's CSRF defence — there is no token to forget.
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL_SECONDS,
                        httponly=True, secure=True, samesite="strict", path="/")


class SignIn(BaseModel):
    email: str
    passphrase: str


class Redeem(BaseModel):
    invite_code: str
    email: str
    passphrase: str


@app.get("/api/session")
def session_read(request: Request) -> dict:
    """
    Which mode this is, and who is signed in. Answers without a session,
    because the screen that asks is the one deciding whether to show sign-in.

    `user` is None for "nobody", never absent: the screen has to tell "not
    signed in" from "not asked yet".
    """
    mode = hosting_mode()
    if mode == "local":
        return {"mode": mode, "user": None}
    user = session_user(request.cookies.get(SESSION_COOKIE, ""))
    return {"mode": mode,
            "user": {"email": account_email(user)} if user else None}


@app.post("/api/session")
def session_create(request: SignIn, response: Response) -> dict:
    """Sign in. One answer for an unknown email and a wrong passphrase."""
    if hosting_mode() == "local":
        _no_accounts_here()
    token = sign_in(request.email, request.passphrase)
    if token is None:
        raise HTTPException(status_code=401,
                            detail="That email and passphrase do not match an account.")
    _set_session(response, token)
    return {"signed_in": True}


def _clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True,
                           samesite="strict")


@app.delete("/api/session")
def session_delete(response: Response) -> dict:
    """Sign out. Works without a valid session: forgetting one is always allowed."""
    _clear_session(response)
    return {"signed_in": False}


@app.post("/api/account")
def account_create(request: Redeem, response: Response) -> dict:
    """
    Redeem an invite: attach an email and a passphrase, and sign in.

    A code that never existed and one already used are the same 404 — which
    of the two is a fact about somebody else's invite.
    """
    if hosting_mode() == "local":
        _no_accounts_here()
    try:
        token = redeem_invite(request.invite_code, request.email, request.passphrase)
    except InviteRefused as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EmailTaken as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (PassphraseRefused, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _set_session(response, token)
    return {"signed_in": True}


@app.delete("/api/account")
def account_delete(response: Response,
                   user: Optional[str] = Depends(_caller)) -> dict:
    """
    Delete the caller's account and everything under it (pilot plan A6), and
    return what went: `{"account", "files", "bytes", "areas"}`. Not a soft
    delete, and not undoable.

    409 while a run is in progress — its worker would write into the tree
    after it was removed. Local mode has no account to delete: its data is the
    checkout, and this route will not touch it.
    """
    if hosting_mode() == "local":
        _no_accounts_here()
    try:
        removed = delete_user_data(user)
    except RunInProgress as exc:
        raise HTTPException(
            status_code=409,
            detail="A run is still in progress. Wait for it to finish, "
                   "then delete your account.") from exc
    _clear_session(response)
    return {key: removed[key] for key in ("account", "files", "bytes", "areas")}


# ------------------------------------------------------------- meta ----

@app.get("/api/health")
def health(user: Optional[str] = Depends(_caller)) -> dict:
    """What this machine can do, which the UI has to say out loud (R43)."""
    return {
        "profiles": available_profiles(user),
        # How many this account may hold: 1 hosted, None local (R109). The
        # wizard offers "replace" rather than a name field that would 409.
        "profile_limit": profile_limit(user),
        # The bounds `start_run` enforces (R110), so the run screen's inputs
        # stop where the server would refuse.
        "run_limits": run_limits(),
        "backend": backend_status(),
        "pdflatex": pdflatex_available(),
        "statuses": list(job_statuses()),
        "sorts": board_sorts(),
    }


@app.get("/api/levels")
def levels(years: Optional[int] = Query(None, ge=0, le=YEARS_EXPERIENCE_MAX),
           user: Optional[str] = Depends(_caller)) -> dict:
    """
    Every seniority level, and the ones a number of years implies (R68).

    `years` is optional and `None` is not zero: a profile that has never been
    asked has no answer, and zero years is the claim "new graduate". The
    caller gets `derived: []` for an unanswered profile and has to render that
    as a question rather than as a level.
    """
    return {
        "all": seniority_levels(),
        "derived": derived_levels(years) if years is not None else [],
    }


class BackendRequest(BaseModel):
    # Optional: the pipeline runs with nothing configured. R37 gave rewriting
    # a floor and R36 moved embeddings off the API, so demanding a key would
    # be the UI holding the door shut on a pipeline that runs without one.
    key: str = ""


@app.post("/api/backend")
def backend(request: BackendRequest, user: Optional[str] = Depends(_caller)) -> dict:
    """
    What will rewrite bullets if this key is used, and what that costs.

    A POST with the key in the body rather than a GET with it in the query
    string: a URL is logged, cached and kept in history, and this is a
    credential. It is passed straight through to detection and never stored —
    the hosted tier is where key handling becomes a real design problem (Q15),
    and inventing half of it here would be worse than not having it.

    Detection touches the network (it asks whether Ollama is up), so the
    caller should ask when the answer could have changed, not per keystroke.
    """
    return backend_status(request.key)


# One answer for a profile that is not yours, wherever it might be. The loader's
# own message names the directory it looked in, which is the server's layout.
NO_SUCH_PROFILE = "No such profile"


def _own_profile(user, name: str) -> None:
    """
    404 before doing anything with a profile the caller does not have.

    Without this, a run for a missing profile started a thread that failed a
    minute later, and a re-judge of one quietly reported zero rows moved.
    Neither leaked anything, but both answered 200 about a profile that is
    not the caller's to name.
    """
    if name not in available_profiles(user):
        raise HTTPException(status_code=404, detail=NO_SUCH_PROFILE)


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
    user: Optional[str] = Depends(_caller),
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
    total = board_total(user, include_ineligible=include_ineligible, **criteria)

    # How many the gate is holding back under these same filters. R62 excludes
    # them by default and says the screen must state the number — "a filter
    # that removes things without saying so is the shape this project keeps
    # regretting". The count belongs here rather than in the UI because the UI
    # would have to issue a second query to work it out, and a number nobody
    # can be bothered to fetch is a number that stops being shown.
    hidden = 0 if include_ineligible else (
        board_total(user, include_ineligible=True, **criteria) - total)

    # Shown, but not confirmed (A4): a requirement met by a question the
    # profile has not answered, or a posting that could not be read. Counted
    # under the same filters as `hidden`, for the same reason — each row
    # carries its own badge, and a badge you would have to page through to
    # tally is not a count.
    unconfirmed = board_total(user, unconfirmed=True, **criteria)

    # Of those, the postings whose description could not be read (R131).
    # "best" sorts them below every readable job, so the screen says how many
    # it moved down.
    unreadable = board_total(user, unreadable=True, **criteria)

    return {
        "jobs": [_without_jd(row)
                 for row in board_jobs(user, sort=sort, limit=limit, offset=offset,
                                       include_ineligible=include_ineligible,
                                       **criteria)],
        "total": total,
        "hidden": hidden,
        "unconfirmed": unconfirmed,
        "unreadable": unreadable,
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
def stats(user: Optional[str] = Depends(_caller)) -> dict:
    return board_stats(user)


@app.get("/api/board/filters")
def filters(user: Optional[str] = Depends(_caller)) -> dict:
    """Companies and sources with counts, read from the store, not a list here."""
    return board_filters(user)


@app.get("/api/board/bands")
def bands(user: Optional[str] = Depends(_caller)) -> dict:
    """Quartiles, so a screen can say where a job sits among yours (R67)."""
    return score_bands(user)


@app.get("/api/board/ghosted")
def ghosted(after_days: Optional[int] = None, user: Optional[str] = Depends(_caller)) -> list:
    return ghosted_jobs(user, after_days=after_days)


class GateRequest(BaseModel):
    profile: str


@app.post("/api/board/gate")
def gate(request: GateRequest, user: Optional[str] = Depends(_caller)) -> dict:
    """Re-judge the stored rows against a profile. Returns how many moved."""
    _own_profile(user, request.profile)
    return {"rejudged": refresh_board_gate(user, request.profile)}


# -------------------------------------------------------------- job ----

@app.get("/api/job")
def job(url: str, user: Optional[str] = Depends(_caller)) -> dict:
    """
    One job's detail: why it scored as it did, and everywhere it has been.

    `selection` is the panel R64 built — facts about the posting rather than
    verdicts about the reader — and it is None for a job analysis never
    reached. The UI has to render that difference rather than showing an
    empty panel, because unknown is not the same as nothing to say.
    """
    row = board_job(user, url)
    if row is None:
        raise HTTPException(status_code=404, detail="No such job")
    return {
        "job": row,
        "selection": job_selection(user, url),
        "history": job_history(user, url),
    }


class StatusRequest(BaseModel):
    url: str
    status: str


@app.post("/api/job/status")
def update_status(request: StatusRequest, user: Optional[str] = Depends(_caller)) -> dict:
    if request.status not in job_statuses():
        raise HTTPException(
            status_code=422,
            detail=f"{request.status!r} is not one of {list(job_statuses())}")
    # The same 404 `/api/job` gives: a job that is not on your board is not
    # found, whether it is on nobody's or on somebody else's (A5).
    if not set_job_status(user, request.url, request.status):
        raise HTTPException(status_code=404, detail="No such job")
    return {"url": request.url, "status": request.status}


# ------------------------------------------------------- setup: resume ----

# Uploads land here, and the only thing a client is ever given back is a bare
# filename. `extract_resume` returns an absolute path, which would be the
# obvious thing to hand over and take back on the confirm call — and that is a
# client choosing which file the server opens. Names are resolved against this
# directory instead, so the worst a caller can name is a file in it.
#
# `resume_dir` is imported from `scripts.init_profile` — the module that
# *writes* the upload — rather than recomputed here. It was
# `Path.cwd() / "data" / "master_resumes"`, which is the same directory in a
# checkout and `/app/data/master_resumes` in the container, while the writer
# used `/data/data/master_resumes`. The wizard's confirm step 404'd on a file
# it had just uploaded (R89). R86 fixed four sites of this shape; this was the
# fifth, and the only one the acceptance run cannot reach, because the harness
# calls `create_profile` directly and never walks `POST /api/profile`.


def _resolve_upload(user_id, filename: str) -> Path:
    # Per user since A3: the worst a caller can name is a file in *their own*
    # upload directory.
    uploads = resume_dir(user_id).resolve()
    candidate = (uploads / Path(filename).name).resolve()
    if candidate.parent != uploads or not candidate.is_file():
        raise HTTPException(status_code=404, detail="No such uploaded resume")
    return candidate


@app.post("/api/resume/extract")
async def resume_extract(file: UploadFile = File(...), api_key: str = Form(""),
                         user: Optional[str] = Depends(_caller)) -> dict:
    """
    Read an upload far enough to show it, without committing to anything.

    R33's rule is that every extracted field is confirmed before use, which
    only works if extracting and writing are two calls with a person in
    between. A `.tex` skips confirmation because it is already the pipeline's
    own format — there is nothing a model guessed at.

    `api_key` is the key the browser saved (R117), a form field beside the
    file: a hosted import reads no key from the environment (R113), so this is
    how a PDF or Word upload gets a model instead of the pattern reader. It is
    used for this request and forgotten, and scrubbed from any error here.
    """
    try:
        extracted = extract_resume(user, await file.read(), file.filename or "resume",
                                   gemini_key=api_key or None)
    except ValueError as exc:
        # A scanned image, a PDF with no readable experience in it, or a key
        # that cannot be sent (R101). The message says which; it is written
        # for the person, not the log. `from None` in both: the cause is not
        # chained, because its text may hold the key and the key is no longer
        # in use once `extract_resume` has returned.
        raise HTTPException(status_code=422,
                            detail=redact_keys(str(exc), api_key)) from None
    except Exception as exc:  # surfaced, not swallowed
        raise HTTPException(
            status_code=400,
            detail=redact_keys(f"Could not read that resume: {exc}", api_key),
        ) from None

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
def profile_create(request: ProfileRequest, user: Optional[str] = Depends(_caller)) -> dict:
    """
    Build a profile from a confirmed resume.

    Overwriting is never implicit: `create_profile` raises when the name is
    taken and `force` is not set, and one profile was already lost to a
    rebuild that discarded hand-tuned rules (R30). The 409 exists so the UI
    can ask rather than clobber.
    """
    source = _resolve_upload(user, request.filename)
    resume_path = (save_extracted(request.schema_, source)
                   if request.schema_ else source)
    try:
        return create_profile(user, resume_path, request.name, force=request.force)
    except (FileExistsError, ProfileLimit) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BadProfileName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # surfaced, not swallowed
        raise HTTPException(
            status_code=400,
            detail=f"Could not build a profile from that resume: {exc}") from exc


# ------------------------------------------------------ setup: profile ----

@app.get("/api/profile/{name}")
def profile_read(name: str, user: Optional[str] = Depends(_caller)) -> dict:
    """Everything the wizard's forms need, in the shape they need it."""
    try:
        return {
            "personal": read_personal(user, name),
            "preferences": read_preferences(user, name),
            "components": read_component_rules(user, name),
        }
    except (FileNotFoundError, BadProfileName) as exc:
        # A name that cannot be a profile is one that does not exist (R111).
        raise HTTPException(status_code=404, detail=NO_SUCH_PROFILE) from exc
    except ValueError as exc:
        # A stored resume path that resolves outside this account (R108).
        # Refused in words, not as a 500.
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class ProfileUpdate(BaseModel):
    updates: dict[str, Any]


# Everything `PATCH /api/profile/{name}` may write: exactly what the two
# screens that call it save. That is Preferences (`job_preferences`) and
# About you (`personal_info`). A dict is a section whose own keys are checked;
# `True` is a leaf, whose value the schema validates on save.
#
# An allow-list, not a denylist, for the payload test's reason: the route used
# to merge any dict it was sent. So a hand-built request could set
# `agent_preferences.max_jobs_to_generate` (run cost, A10), the scoring
# threshold (Q63), or `resume_preferences.master_resume_path`, which a
# relative `..` walked into another user's partition. A field reaches this
# list when a screen starts saving it, in the same change.
PROFILE_PATCHABLE: dict[str, Any] = {
    "job_preferences": {
        "target_roles": True,
        "years_experience": True,
        "seniority": True,
        "exclude_keywords": True,
        "locations": {
            "cities": True,
            "remote_ok": True,
            "countries": True,
            "states_priority": True,
            "states_acceptable": True,
            "willing_to_relocate": True,
        },
    },
    "personal_info": {
        "location": True,
        "work_authorization": {
            "us_person": True,
            "needs_sponsorship": True,
            "holds_clearance": True,
        },
    },
}


def _unpatchable(updates: Any, allowed: dict, prefix: str = "") -> list[str]:
    """Every dotted path in `updates` that `allowed` does not name."""
    if not isinstance(updates, dict):
        return [prefix.rstrip(".") or "updates"]
    refused = []
    for key, value in updates.items():
        rule = allowed.get(key)
        if rule is None:
            refused.append(f"{prefix}{key}")
        elif isinstance(rule, dict):
            refused += _unpatchable(value, rule, f"{prefix}{key}.")
    return refused


@app.patch("/api/profile/{name}")
def profile_update(name: str, request: ProfileUpdate, user: Optional[str] = Depends(_caller)) -> dict:
    """
    Save part of a profile without disturbing the rest.

    `update_profile_fields` merges nested sections rather than replacing
    them. That is load-bearing: the preferences screen saves two of
    `locations`' seven fields, and a wholesale replace dropped `countries`,
    which the schema requires — walking the wizard left a profile that would
    not load. A form must not destroy what it never showed (R30).

    Only the fields in `PROFILE_PATCHABLE` are written. Anything else is a 400
    naming each refused field, and nothing is written.
    """
    refused = _unpatchable(request.updates, PROFILE_PATCHABLE)
    if refused:
        raise HTTPException(
            status_code=400,
            detail="These fields cannot be changed here: " + ", ".join(refused))
    try:
        path = update_profile_fields(user, name, request.updates)
    except (FileNotFoundError, BadProfileName) as exc:
        # A name that cannot be a profile is one that does not exist (R111).
        raise HTTPException(status_code=404, detail=NO_SUCH_PROFILE) from exc
    except ProfileInvalid as exc:
        # Nothing was written. A string detail, not FastAPI's error list, so
        # the screen can show it as it is (Q44).
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Re-judge the board against what was just saved (A4). About-you's three
    # answers and Preferences' years, seniority and countries all feed the
    # gate's fingerprint, and the React board has no way to ask for this
    # itself — `GET /api/board` names no profile, and nothing in the client
    # called `POST /api/board/gate`. So a badge saying "you have not said
    # whether you hold a clearance" outlived the answer. Here, rather than in
    # each screen, so no screen can forget. Cheap: only rows whose
    # fingerprint changed are touched, and a failure logs rather than failing
    # the save.
    return {"saved": Path(path).name,
            "rejudged": refresh_board_gate(user, name)}


class ComponentRules(BaseModel):
    importance: dict[str, Any]
    triggers: dict[str, Any]
    # `always_include` boosts and `never_include` excludes outright. Both have
    # been read by the parser since they were written and were editable only
    # by hand until the tuning screen existed — so leaving them off here would
    # have made this endpoint the one path that silently cannot set them.
    always: dict[str, bool] = {}
    never: dict[str, bool] = {}


@app.put("/api/profile/{name}/components")
def components_write(name: str, request: ComponentRules,
                     user: Optional[str] = Depends(_caller)) -> dict:
    """
    Save the tuning screen's edits.

    `id_problems` rides back with the confirmation because this is the one
    screen that can show a person *which* of their rules is broken next to the
    rule itself. The write never drops a rule keyed to a component the resume
    no longer has (R17); it now says that it kept one.
    """
    try:
        saved = write_component_rules(user, name, request.importance, request.triggers,
                                      request.always, request.never)
    except (FileNotFoundError, BadProfileName) as exc:
        # A name that cannot be a profile is one that does not exist (R111).
        raise HTTPException(status_code=404, detail=NO_SUCH_PROFILE) from exc
    return {"saved": name, "id_problems": saved["id_problems"]}


# ------------------------------------------------------------- runs ----

class RunRequest(BaseModel):
    profile: str
    # Not stored anywhere. It reaches the pipeline for this run and is
    # forgotten; a run with no key is a supported configuration, not an error.
    api_key: str = ""
    # Which rung rewrites bullets, for this run only. Same rule as the key:
    # it reaches the pipeline and is forgotten. `""` means "no opinion", and
    # the profile or detection then decides — which is not the same as
    # "auto", an opinion that detection should decide.
    backend: str = ""
    max_jobs: int = 20
    max_resumes: int = 3
    generate_pdf: bool = True


@app.post("/api/run")
def run_start(request: RunRequest, user: Optional[str] = Depends(_caller)) -> dict:
    """
    Begin a run in the background and hand back its id at once (R51).

    The pipeline takes minutes. Progress goes to `data/runs.db` rather than to
    this response, because the browser that asked may be gone by the time it
    ends — which is the whole point: a reloaded page can find the run again.
    """
    _own_profile(user, request.profile)
    try:
        run_id = start_run(
            user,
            request.profile,
            api_key=request.api_key,
            max_jobs=request.max_jobs,
            max_resumes=request.max_resumes,
            generate_pdf=request.generate_pdf,
            backend=request.backend or None,
        )
    except RunSizeRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RunInProgress as exc:
        # One run per user (R120). 409: the request is fine, the moment is not.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run_id": run_id}


@app.get("/api/run/{run_id}")
def run_progress(run_id: str, user: Optional[str] = Depends(_caller)) -> dict:
    """
    Where a run has got to, or 404 if there is no such run.

    404, not an empty object: "this run does not exist" and "this run has no
    progress yet" are different answers, and a UI given the second for the
    first would spin forever on a run that never started.
    """
    status = run_status(user, run_id)
    if status is None:
        raise HTTPException(status_code=404, detail="No such run")
    return status


@app.get("/api/run")
def runs_active(user: Optional[str] = Depends(_caller)) -> dict:
    """
    What is still going, read from disk.

    A reloaded page has no memory of starting anything, so the answer cannot
    come from anything the browser holds.
    """
    return {"active": active_runs(user)}


@app.get("/api/runs")
def runs(limit: int = Query(10, ge=1, le=50), user: Optional[str] = Depends(_caller)) -> list:
    """Past runs, because resumes outlive the session that made them."""
    return previous_runs(user, limit=limit)


@app.get("/api/file")
def file(path: str, user: Optional[str] = Depends(_caller)):
    """
    Serve a generated resume for download.

    The path comes from a board row rather than from the user, but it arrives
    over HTTP either way, so it is resolved and checked against the outputs
    directory before anything is opened. A local single-user app is still an
    app with an open port on it.
    """
    # `user_outputs_root()` rather than `Path.cwd() / "outputs"`, and the two are
    # only the same thing on a laptop. In a container the working directory is
    # an image layer and the outputs live on the volume, so resolving against
    # cwd would have containment-checked downloads against a directory the
    # runs never wrote to — every file a 404, with the guard looking correct.
    #
    # It is also the twin of the resolution in `JobScoutOrchestrator`, and a
    # writer and a reader computing the same root separately is how this
    # codebase loses a week. One function, two callers, and a test that they
    # agree.
    #
    # **Contained in the caller's root, not everybody's** (A3). The partition
    # and this guard are one change: partition first and a guard over the
    # shared root still permits cross-user download; tighten first and every
    # download 404s. The caller is the session's since A5.
    root = user_outputs_root(user).resolve()
    target = (root.parent / path).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="No such generated file")
    return FileResponse(target, filename=target.name)


# ------------------------------------------------------------- the app ----
#
# The built React, served from this origin.
#
# **Mounted last, and that is load-bearing.** A mount at "/" matches every
# path, so FastAPI resolves it only after the routes declared above — put it
# any earlier and it swallows `/api/*` and the frontend talks to a 404.
#
# `web/dist` is a build artifact, so it is absent in a checkout that has not
# run `npm run build` and absent from the wheel entirely. Missing is a normal
# state, not an error: the dev loop serves the frontend from Vite on 5173 and
# only ever calls this process for `/api`. Hosted, the Dockerfile builds it in.
#
# `html=True` serves `index.html` for `/`. There is no client-side router, so
# no deep-link fallback is needed — and inventing one would mean answering 200
# to every mistyped API path, which is the kind of helpfulness that hides a
# bug for a week.
WEB_DIST = Path(os.getenv("JOBSCOUT_WEB_DIST")
                or Path(__file__).parent.parent / "web" / "dist")

if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")

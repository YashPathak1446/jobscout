"""
JobScout V3 Orchestrator - Main Entry Point

Coordinates all agents in the job application pipeline:
1. Discovery Agent - Find relevant jobs
2. Enrichment Agent - Scrape full job descriptions
3. Analysis Agent - Score & select resume components
4. Generation Agent - Create tailored resumes

Features:
- Human checkpoints (review before proceeding)
- Progress tracking (save state between steps)
- Summary generation (markdown report)
- Error handling (graceful recovery)

Location: jobscout_v3/agents/orchestrator.py
"""

import os
import sys
import json
import logging
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
from typing import Callable, List, Dict, Optional

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, skip

# Add project root to path (parent of agents/)
sys.path.insert(0, str(Path(__file__).parent.parent))

# `redact_keys` is re-exported for the API's error responses (R117).
from config import key_in_use, redact_keys  # noqa: F401
# The API's error reporting, off unless SENTRY_DSN is set (A9, R119).
from tools.error_reporting import start_error_reporting  # noqa: F401
from tools.paths import outputs_root, stored_path
from tools.profile import load_profile
# Re-exported for both views: the largest `years_experience` the schema takes,
# which `/api/levels` and the Streamlit input bound themselves by (Q44).
from tools.profile.profile_schema import YEARS_EXPERIENCE_MAX  # noqa: F401
from tools.resume import ResumeParser
from agents import DiscoveryAgent, EnrichmentAgent, AnalysisAgent, GenerationAgent

logger = logging.getLogger(__name__)


def _console_print(*args, **kwargs) -> None:
    """
    print(), but a console that cannot encode a character loses the character
    rather than the run.

    `main()` reconfigures stdout to UTF-8 for the CLI, which covers the CLI
    and nothing else. Called as a library — from the Streamlit app, a test, a
    notebook — the orchestrator inherits whatever encoding the host has, and
    on Windows that is cp1252. The failure that exposed this is the worst
    shape available: discovery, enrichment, analysis and generation all
    succeed, the resumes are on disk, the API quota is spent, and then the run
    raises UnicodeEncodeError printing a party emoji in the completion banner.

    A library must not mutate the host's stdout, so the encoding is handled
    per call instead.
    """
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        cleaned = [
            str(a).encode(encoding, errors="replace").decode(encoding)
            for a in args
        ]
        print(*cleaned, **kwargs)


def user_outputs_root(user_id) -> Path:
    """
    Where this user's generated resumes go (pilot plan A3).

    The facade's answer to "whose outputs directory", exported so `/api/file`
    can contain a download inside the *caller's* root rather than inside
    everybody's. `None` is the unscoped layout, which is `outputs/` at the
    checkout root, exactly as before.
    """
    return outputs_root(user_id=user_id)


def master_resume_path(user_id, stored: str) -> str:
    """
    Resolve a profile's `master_resume_path` for the user it belongs to.

    A facade over `tools.paths.stored_path`, which `init_profile`'s editor
    reads through too — the second of two resolutions of this one field,
    and two resolutions of one field is how R86 happened.
    """
    return str(stored_path(stored, user_id=user_id))


def previous_runs(user_id, output_dir: str = "outputs", limit: int = 10) -> list:
    """
    Past runs, newest first, as {date, path, jobs, resumes}.

    Generated resumes live on disk long after the session that made them, but
    a Streamlit `session_state` does not survive a browser reload — so a user
    who closed the tab lost every download link to files that were still
    sitting in `outputs/`. This lets the UI find them again.

    Runs that cannot be read are skipped rather than raised on: a half-written
    state file from an interrupted run should cost that one row, not the
    screen.
    """
    import json as _json

    base = outputs_root(output_dir, user_id=user_id)
    if not base.is_dir():
        return []

    runs = []
    for directory in sorted(base.iterdir(), reverse=True):
        state_file = directory / "state.json"
        if not directory.is_dir() or not state_file.is_file():
            continue
        try:
            state = _json.loads(state_file.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue

        runs.append({
            "date": directory.name,
            "path": str(directory),
            "jobs": len(state.get("analysis_results") or []),
            "resumes": len(state.get("generation_results") or []),
        })
        if len(runs) >= limit:
            break

    return runs


def load_run(user_id, path: str) -> dict:
    """
    The saved state of one past run, in the shape `run()` returns.

    `path` comes from `previous_runs` — but it arrives as a string, so it is
    contained inside this user's outputs before it is opened. Otherwise the
    listing is scoped and the read is not, which is the pair A3 exists to
    stop splitting.
    """
    import json as _json

    root = user_outputs_root(user_id).resolve()
    run = Path(path).resolve()
    if root not in run.parents:
        raise ValueError(f"not one of this user's runs: {path!r}")
    return _json.loads((run / "state.json").read_text(encoding="utf-8"))


def pdflatex_available() -> bool:
    """
    Is a LaTeX engine installed? R20's results screen branches on this.

    A facade so the UI does not import from `tools/` (R25). Cheap enough to
    call per render — `find_pdflatex` checks PATH then a handful of known
    install directories.
    """
    from tools.generation.pdf_builder import find_pdflatex
    return find_pdflatex() is not None


def available_profiles(user_id) -> list:
    """Names of this user's profiles. Facade, for the same reason as above."""
    from tools.profile import list_available_profiles
    return list_available_profiles(user_id=user_id)


# ------------------------------------------------------------------------
# The board's facades (R33)
#
# R33 decided the app is a persistent job board rather than a run log, and
# R35 built the store that makes that possible. These are the three things a
# board does — list, count, and record what the user decided — exposed so the
# view layer never learns that any of it is SQLite (R25).
# ------------------------------------------------------------------------

def _board(user_id):
    """
    This user's board. Every facade below opens it through here, so there is
    one place that says whose — and `JobStore` no longer has a default to
    fall back to if a facade forgot.
    """
    from tools.jobs.job_store import JobStore, db_path
    return JobStore(db_path(user_id))


def job_statuses() -> tuple:
    """What a user is allowed to say about a job."""
    from tools.jobs.job_store import STATUSES
    return STATUSES


def board_jobs(user_id, status=None, min_score=None, has_resume=None, company=None,
               source=None, search=None, sort="best", limit=50, offset=0,
               include_ineligible=False) -> list:
    """
    The board's rows: every job ever discovered, ordered as asked.

    Unscored jobs sort to the bottom rather than as if they scored zero, which
    matters because discovery reaches thousands of roles (R34, R46) and
    analysis only looks at the top slice of them.

    Every filter here already existed in the store and none of them had ever
    been offered to a screen. `limit` defaults small because it is now paged —
    see `board_total`, without which a page cap looks exactly like running out
    of jobs.

    Jobs the gates would hide are excluded by default (R62). Not deleted and
    not silently dropped: `include_ineligible=True` returns them, and the
    screen says how many there are, because a filter that removes things
    without saying so is the shape this project keeps regretting.
    """
    store = _board(user_id)
    try:
        return store.query(status=status, min_score=min_score,
                           has_resume=has_resume, company=company,
                           source=source, search=search, sort=sort,
                           limit=limit, offset=offset,
                           eligible=None if include_ineligible else True)
    finally:
        store.close()


def board_total(user_id, status=None, min_score=None, has_resume=None, company=None,
                source=None, search=None, include_ineligible=False,
                unconfirmed=False, unreadable=False) -> int:
    """
    How many jobs match, ignoring the page window.

    `unconfirmed=True` counts only the shown jobs the gate could not decide
    (A4): a requirement met by a question you have not answered, or a posting
    that could not be read. The board states that number next to the hidden
    one, because a badge you have to scroll to find is not a count.

    `unreadable=True` counts only the shown jobs whose description could not
    be read (R131), a subset of `unconfirmed`. The default sort puts them
    last, and moving jobs down a board without saying how many is the same
    silent subtraction R62 forbids.
    """
    store = _board(user_id)
    try:
        return store.count(status=status, min_score=min_score,
                           has_resume=has_resume, company=company,
                           source=source, search=search,
                           eligible=None if include_ineligible else True,
                           unconfirmed=unconfirmed, unreadable=unreadable)
    finally:
        store.close()


def refresh_board_gate(user_id, profile_name: str) -> int:
    """
    Bring every stored verdict up to date with the current gates (R62).

    Cheap to call before each render: a row is re-judged only when the gate's
    own code or the profile fields it reads have changed, so after the first
    pass this matches nothing. Returns how many rows were re-judged.

    Non-fatal. A board that cannot re-judge should show what it has rather than
    refuse to render, so a failure here is logged and the stale verdicts stand.
    """
    from tools.jobs.job_filter import gate_fingerprint, gate_verdict

    try:
        profile = load_profile(profile_name, user_id=user_id)
    except Exception as exc:
        logger.warning(f"Board gate not refreshed: {exc}")
        return 0

    store = None
    try:
        store = _board(user_id)
        return store.refresh_gate(
            gate_fingerprint(profile),
            lambda row: gate_verdict(row, profile),
        )
    except Exception as exc:
        logger.warning(f"Board gate not refreshed: {exc}")
        return 0
    finally:
        if store is not None:
            store.close()


def board_filters(user_id) -> dict:
    """
    The companies and sources worth offering, with counts, commonest first.

    Read from the store so a board that has just learned a new ATS offers it
    without anyone editing a list in the view layer.
    """
    store = _board(user_id)
    try:
        return store.facets()
    finally:
        store.close()


def ghosted_jobs(user_id, after_days=None) -> list:
    """
    Applied to, and silent since — computed, never clicked.

    Ghosting is not a decision anyone makes; it is what happens to a job while
    nobody does anything. A stored status would go stale the moment a reply
    arrived, and would need the user to notice the anniversary themselves,
    which is the work a log is supposed to do for them.
    """
    from tools.jobs.job_store import GHOSTED_AFTER_DAYS

    store = _board(user_id)
    try:
        # `if after_days is None`, not `or` — a threshold of 0 days is a
        # legitimate ask ("everything I have applied to and not heard about")
        # and `0 or 28` silently answers a different question.
        window = GHOSTED_AFTER_DAYS if after_days is None else after_days
        return store.ghosted(window)
    finally:
        store.close()


def job_history(user_id, url: str) -> list:
    """Every status one job has held, oldest first."""
    store = _board(user_id)
    try:
        return store.history(url)
    finally:
        store.close()


def board_job(user_id, url: str):
    """
    One stored job in full, posting text included, or None.

    The list facades deliberately hand back every column, which is right for a
    view that renders a table and wrong for one rendering fifty rows over
    HTTP — a 50-row page is 336 KB with the descriptions and 44 KB without.
    So the HTTP boundary drops `full_jd` from list rows and asks here for the
    one job a reader actually opened. Streamlit never needed this because it
    renders in-process; a second view is what made the difference visible.
    """
    store = _board(user_id)
    try:
        return store.get(url)
    finally:
        store.close()


def job_selection(user_id, url: str):
    """
    Why one job's resume contains what it contains, or None (R57).

    The sentence is attached here rather than in the view because forming it
    needs `selection_report.describe`, and `app.py` may not import from
    `tools/` — `test_ui_contract` fails the build if it does. The view gets
    text and numbers and decides only how they look.
    """
    from tools.resume.selection_report import describe

    store = _board(user_id)
    try:
        report = store.selection(url)
    finally:
        store.close()

    if not report or not report.get("picked"):
        return None

    for entry in report["picked"]:
        entry["sentence"] = describe(entry)
    return report


def _registry(user_id):
    """This user's run registry. See `_board`: one place that says whose."""
    from tools.jobs.run_registry import RunRegistry, db_path
    return RunRegistry(db_path(user_id))


# Which runs this process has a live worker for (R120). An id goes in before
# its thread starts and comes out in the worker's `finally`, so "in the set"
# is "a thread of ours is on it". `_RUNS_LOCK` makes claim-then-add one step
# as far as the reaper can see: without it, a listing between the row landing
# and the id going in would reap a run that is about to start.
_PROCESS = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
_LIVE_RUNS: set = set()
_RUNS_LOCK = threading.Lock()

# A live worker touches `heartbeat_at` every HEARTBEAT seconds, from a timer
# of its own, because a progress tick can be minutes apart (discovery ticks
# at its start and end only, Q49). Another process's run is presumed dead
# after STALE of silence: four missed beats, so a busy machine is not enough.
RUN_HEARTBEAT_SECONDS = 30
RUN_STALE_SECONDS = 120


def _reap(registry, every_foreign: bool = False) -> list:
    """Fail this registry's runs that no worker is on. See `RunRegistry.reap`."""
    with _RUNS_LOCK:
        return registry.reap(_PROCESS, set(_LIVE_RUNS), RUN_STALE_SECONDS,
                             every_foreign=every_foreign)


def _readable_count(enriched_jobs) -> int:
    """Enriched jobs whose description could be read (R124)."""
    return sum(1 for job in enriched_jobs if job.get("scraped_successfully"))


def reap_stale_runs() -> int:
    """
    The startup sweep: every partition's dead runs marked failed (R120, Q49).

    Called once when the API boots. Walks every `runs.db` that exists, the
    unscoped one and each user's, because a sweep of one registry clears
    nobody else's run. Hosted, one process serves every run, so at boot every
    active row is dead and fails at once. Local, Streamlit may be a second
    process with a run going in the same `runs.db`, so its rows are judged by
    heartbeat instead. Returns how many runs it failed.
    """
    from tools.jobs.run_registry import RunRegistry, every_db_path

    hosted = hosting_mode() == "hosted"
    reaped = 0
    for path in every_db_path():
        # One unreadable registry must not keep the instance from booting for
        # everybody else. Logged at ERROR, so Sentry sees it (R119).
        try:
            with RunRegistry(path) as registry:
                reaped += len(_reap(registry, every_foreign=hosted))
        except Exception:
            logger.exception("Could not sweep %s for interrupted runs", path)
    if reaped:
        logger.warning("Marked %d interrupted run(s) failed at startup", reaped)
    return reaped


# How large a run a UI may ask for (R110), inclusive. `start_run` refuses
# anything outside, so every UI gets the same bound whatever its widget
# allows. `/api/health` hands this to the React run screen and Streamlit's
# sliders read it. The CLI calls `JobScoutOrchestrator.run` directly and is
# not bounded: it is a developer's own machine and quota.
#
# 50 and 10 are Streamlit's existing slider ranges; React allowed 100. Each
# job is a scrape and an embedding. Each resume is LLM calls on the user's
# key plus one `pdflatex` compile, the heaviest server CPU per unit (A10).
RUN_LIMITS = {"max_jobs": (1, 50), "max_resumes": (1, 10)}


class RunSizeRefused(ValueError):
    """A run asked for more (or less) than `RUN_LIMITS` allows."""


def run_limits() -> dict:
    """`RUN_LIMITS` as the UIs want it: {field: {"min": a, "max": b}}."""
    return {field: {"min": lo, "max": hi} for field, (lo, hi) in RUN_LIMITS.items()}


def _check_run_size(**sizes) -> None:
    for field, value in sizes.items():
        lo, hi = RUN_LIMITS[field]
        # `bool` is an `int` in Python; `True` is not a job count.
        if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
            raise RunSizeRefused(f"{field} must be a whole number from {lo} to {hi}; "
                                 f"got {value!r}.")


def start_run(user_id, profile_name, api_key="", max_jobs=20, max_resumes=3,
              generate_pdf=True, output_dir="outputs", backend=None) -> str:
    """
    Begin a run in the background and return its id immediately (R33).

    The pipeline takes minutes, and until now it ran inside the request that
    asked for it — so the browser had to stay open and a reload lost both the
    progress bar and any way of knowing whether the run was still going.

    Progress goes to `data/runs.db` rather than to the caller, because the
    caller may not exist by the time the run ends. Poll `run_status(id)`.

    Checkpoints are deliberately not offered here. A background run has nobody
    to ask, and R26's checkpoint resolves through a callback that would block
    the worker forever waiting for a browser that may have closed. Reviewing
    before generation stays a foreground feature.

    `user_id` reaches the worker **as a closure variable**, not through a
    `ContextVar`: context variables do not follow a `threading.Thread`, so the
    worker would resolve to whoever the default was and write a resume into a
    stranger's outputs with no error anywhere (pilot plan A3).

    One run per user (R120): a second start while one is going raises
    `RunInProgress`, and the API turns that into a 409.
    """
    # Before the registry row, so a refused run leaves no trace (R110).
    _check_run_size(max_jobs=max_jobs, max_resumes=max_resumes)

    # The row is recorded on a connection that closes here, and the worker
    # opens its own. Before, this one connection was handed to the thread and
    # closed only in the worker's `finally`, so a thread that never ran (a
    # test that stubs it, or a failed `start()`) left it open for good. On
    # Windows an open SQLite file cannot be deleted, so the test's temporary
    # home failed to clean up (WinError 32), and Python 3.13 warned about
    # the unclosed database at exit. A connection's life is now the life of
    # whoever uses it.
    from tools.jobs import event_log

    # One run per user (R120). A dead run in the way is reaped first, so a
    # restart never leaves somebody refused by a run nothing is doing.
    from tools.jobs.run_registry import RunAlreadyActive

    with _registry(user_id) as registry:
        _reap(registry)
        with _RUNS_LOCK:
            try:
                run_id = registry.claim(profile_name, _PROCESS)
            except RunAlreadyActive as exc:
                raise RunInProgress(
                    "You already have a run in progress"
                    f" (started {exc.run['started_at'][:16].replace('T', ' ')} UTC,"
                    f" profile {exc.run['profile']}). Wait for it to finish,"
                    " then start another.") from exc
            _LIVE_RUNS.add(run_id)
    # With the registry row, not in the worker: a run the thread never starts
    # was still asked for, and "started, never finished" is what says so (A8).
    event_log.record(user_id, "run_started")

    def worker():
        # The key is scrubbed from every log line and run record for as long
        # as the run holds it (R117).
        try:
            with key_in_use(api_key):
                _run_worker()
        finally:
            with _RUNS_LOCK:
                _LIVE_RUNS.discard(run_id)

    def _run_worker():
        registry = _registry(user_id)
        stop = threading.Event()

        def beat():
            while not stop.wait(RUN_HEARTBEAT_SECONDS):
                registry.heartbeat(run_id)

        beating = threading.Thread(target=beat, name=f"jobscout-beat-{run_id}",
                                   daemon=True)
        # Outside the `try` below, whose `finally` joins this thread; so a
        # failed start closes the registry here instead.
        try:
            beating.start()
        except BaseException:
            registry.close()
            raise
        try:
            orchestrator = JobScoutOrchestrator(
                profile_name=profile_name,
                user_id=user_id,
                api_key=api_key or None,
                output_dir=output_dir,
                max_resumes=max_resumes,
                generate_pdf=generate_pdf,
                checkpoint=False,
                backend=backend,
            )
            state = orchestrator.run(
                max_jobs=max_jobs,
                on_progress=lambda tick: registry.progress(
                    run_id, tick.stage, tick.done, tick.total, tick.message),
            )
            results = (state or {}).get("generation_results") or []
            registry.finish(run_id, {
                # `discovered` and `enriched` are here so a run that produced
                # nothing can say *which* nothing. "Found no jobs at all",
                # "found jobs and none scored high enough" and "matched jobs
                # and wrote no resumes" are three different problems, and the
                # user can act on the first two. Without these the screen can
                # only report zero and call it success — which is what it did,
                # on the last screen a first-time user sees.
                "discovered": len((state or {}).get("discovered_jobs") or []),
                # With a readable description, as the report counts (R124).
                "enriched": _readable_count((state or {}).get("enriched_jobs") or []),
                "analysed": len((state or {}).get("analysis_results") or []),
                "generated": len(results),
                "valid": sum(1 for r in results if r.get("status") == "valid"),
                # The bar a job had to clear, so the screen can name the number
                # rather than telling somebody to go and find it.
                "threshold": getattr(
                    getattr(orchestrator.profile, "agent_preferences", None),
                    "scoring_threshold", None),
                # Carried out of the run so a reloaded page can say why the
                # bullets are the user's own without reopening state.json.
                "degraded": sorted({r["degraded"] for r in results
                                    if r.get("degraded")}),
                # Why resumes have no PDF, carried out the same way (R116),
                # so the run screen can say so instead of counting them valid.
                "pdf_problems": sorted({r["pdf_problem"] for r in results
                                        if r.get("pdf_problem")}),
            }, output_dir=getattr(orchestrator, "output_path", ""))
            # One per resume, then the run (R118). A `failed` resume was not
            # generated, so it has no event; the run is still `ok`.
            for result in results:
                if result.get("status") in ("valid", "needs_review"):
                    event_log.record(user_id, "resume_generated", result["status"])
            event_log.record(user_id, "run_finished", "ok")
        except Exception as exc:                      # the worker owns nothing else
            logger.exception("Background run failed")
            registry.fail(run_id, f"{type(exc).__name__}: {exc}")
            # The class name only: the message can hold a URL, a line of a job
            # description, or (scrubbed, but still) where a key was.
            event_log.record(user_id, "run_finished",
                             f"failed:{type(exc).__name__}")
        finally:
            stop.set()
            beating.join()
            registry.close()

    # Daemon, so a stuck run cannot keep the interpreter alive after the
    # server is told to stop.
    try:
        threading.Thread(target=worker, name=f"jobscout-run-{run_id}",
                         daemon=True).start()
    except BaseException:
        with _RUNS_LOCK:
            _LIVE_RUNS.discard(run_id)
        raise
    return run_id


def run_status(user_id, run_id: str):
    """
    Where a background run has got to, or None if there is no such run.

    None too for somebody else's run: the id is looked up in this user's
    registry, where another person's run does not exist.
    """
    registry = _registry(user_id)
    try:
        return registry.get(run_id)
    finally:
        registry.close()


def active_runs(user_id) -> list:
    """
    Runs still going, read from disk.

    What a reloaded page asks: it has no memory of starting anything, so the
    answer cannot come from session state.
    """
    registry = _registry(user_id)
    try:
        _reap(registry)            # a listing never shows a dead run (R120)
        return registry.active()
    finally:
        registry.close()


def recent_runs(user_id, limit: int = 10) -> list:
    """The last few runs, newest first, whatever became of them."""
    registry = _registry(user_id)
    try:
        _reap(registry)
        return registry.recent(limit)
    finally:
        registry.close()


def score_bands(user_id) -> dict:
    """
    Where your scored jobs' quartiles fall, for labelling a match.

    The score is normalised against a window much wider than real data uses —
    95 scored jobs spanned 44 to 59 on a 0-100 scale — so the raw number reads
    as "about 53" whatever it is. This lets a screen say where one job sits
    among yours without changing the number the pipeline gates on.
    """
    store = _board(user_id)
    try:
        return store.score_bands()
    finally:
        store.close()


def board_sorts() -> list:
    """The orderings the board may ask for. The view never builds SQL."""
    from tools.jobs.job_store import JobStore
    return list(JobStore.SORTS)


def board_stats(user_id) -> dict:
    """Totals for the board's header. Returns zeros if no run has happened."""
    store = _board(user_id)
    try:
        return store.stats()
    finally:
        store.close()


def set_job_status(user_id, url: str, status: str) -> bool:
    """
    Record what the user decided about one job. Raises on a bad status.

    False when the job is not on this user's board, and nothing is written —
    the route turns that into the same 404 `/api/job` gives (A5).
    """
    from tools.jobs import event_log

    store = _board(user_id)
    try:
        changed = store.set_status(url, status)
    finally:
        store.close()
    # Only a mark that landed, and only the two A8 counts (R118). A job that
    # is not on this board changed nothing, so it is not an event either.
    if changed and status in ("applied", "rejected"):
        event_log.record(user_id, "job_marked", status)
    return changed


def seniority_levels() -> list:
    """
    The levels a profile can ask for, entry-level first.

    R34 made the seniority gate read the profile instead of a constant, which
    only helps if something lets a user set it. The list lives with the
    synonym map that has to understand it, not in the form.
    """
    from tools.jobs.job_filter import SENIORITY_SYNONYMS
    return list(SENIORITY_SYNONYMS.keys())


def derived_levels(years) -> list:
    """
    The seniority levels a given number of years implies (R68).

    A facade so the wizard can show what it derived without importing from
    `tools/` (R25) — the screen displays the answer, it does not compute it.
    """
    from tools.jobs.job_filter import derive_levels
    return derive_levels(years)


def backend_status(gemini_key: str = "", backend: str = None,
                   profile=None) -> dict:
    """
    What will rewrite bullets on the next run, and what that costs.

    R33: detected, then explained — not silent, because output quality differs
    materially between rungs, and not a mandatory choice screen, because most
    people do not yet know enough to answer one. Returns the chosen rung, a
    line describing it, and whether each rung is currently reachable, so the
    UI can show what it would take to move up.

    Detection touches the network (it asks whether Ollama is up), so a caller
    rendering on every keystroke should cache it.
    """
    from config import (OLLAMA_API_URL, OLLAMA_MODEL, OPENAI_MODEL,
                        gemini_key_problem, resolve_api_key, resolve_backend)
    from tools.generation import llm_backends

    # `resolve_api_key` is the single place that decides what "no key passed"
    # means (R22); asking the environment directly here would be a second
    # answer to the same question. `resolve_backend` is the same rule for the
    # rung — this read `LLM_BACKEND` off the module, which was one of four
    # places answering the same question independently.
    key = resolve_api_key(gemini_key or None)
    # A key that cannot be sent is not a key (R101). Detection must not choose
    # Gemini on it, and the panel must say what is wrong with it rather than
    # "add a key", because there is one.
    key_problem = gemini_key_problem(key)
    if key_problem:
        key = ""
    openai_key = llm_backends.env_openai_key()
    ollama_up = llm_backends.ollama_is_running(OLLAMA_API_URL)

    configured = resolve_backend(backend, profile)
    if configured in ("auto", ""):
        chosen = llm_backends.detect(gemini_key=key, openai_key=openai_key,
                                     ollama_url=OLLAMA_API_URL)
        forced = False
    else:
        chosen = configured
        forced = True

    model = {"ollama": OLLAMA_MODEL, "openai": OPENAI_MODEL}.get(chosen, "")
    return {
        "backend": chosen,
        "forced": forced,
        "description": llm_backends.describe(chosen, model),
        "key_problem": key_problem,
        "available": {
            "gemini": bool(key),
            "openai": bool(openai_key),
            "ollama": ollama_up,
            "none": True,
        },
    }


# ------------------------------------------------------------------------
# Who is asking (pilot plan A5)
#
# The API may not import `tools.accounts`, so the door is opened through here
# like everything else. The mode, the secret and the store all live in that
# module; these only name what a view is allowed to ask of it.
# ------------------------------------------------------------------------

from tools.accounts import (  # noqa: E402, F401  re-exported for the view layer
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    EmailTaken,
    HostingMisconfigured,
    InviteRefused,
    PassphraseRefused,
)


def hosting_mode() -> str:
    """`local` (one unscoped user, no accounts) or `hosted`. Raises otherwise."""
    from tools.accounts import hosting_mode as mode
    return mode()


def check_hosting() -> str:
    """Refuse to boot an instance that cannot name its callers. Returns the mode."""
    from tools.accounts import check_boot
    return check_boot()


def session_user(token: str):
    """The user id a session cookie names, or None if it names nobody."""
    from tools.accounts import session_user as resolve
    return resolve(token)


def sign_in(email: str, passphrase: str):
    """A session cookie value for these credentials, or None."""
    from tools.accounts import authenticate, issue_session
    user_id = authenticate(email, passphrase)
    return issue_session(user_id) if user_id else None


def redeem_invite(code: str, email: str, passphrase: str) -> str:
    """
    Claim an invite and return a session cookie value for the new account.

    Raises `InviteRefused`, `EmailTaken` or `PassphraseRefused` (a
    `ValueError`, as is a malformed email), each with a message for the person.
    """
    from tools.accounts import issue_session, redeem
    from tools.jobs import event_log

    user_id = redeem(code, email, passphrase)
    # Once per account: a reset is redeemed here too, and re-opens an account
    # rather than creating one (A8).
    event_log.record(user_id, "account_created", once=True)
    return issue_session(user_id)


def account_email(user_id) -> Optional[str]:
    """The email an account signs in with, for the screen that says who you are."""
    from tools.accounts import email_of
    return email_of(user_id)


def invite_account() -> tuple:
    """A new unredeemed account: `(user_id, code)`. For `scripts/admin.py`."""
    from tools.accounts import invite
    return invite()


def find_account(who: str) -> Optional[str]:
    """The user id `who` names, a user id or an email, or None. For the operator."""
    from tools.accounts import find
    return find(who)


def list_accounts() -> list:
    """Every account: `user_id`, `email` (None until redeemed) and `created_at`."""
    from tools.accounts import list_accounts as listing
    return listing()


def pilot_events() -> list:
    """
    Every account's A8 event counts, for `scripts/admin.py events` (R118).

    One entry per account, redeemed or not, with its email, its counts by
    event (and reason), and whether it met the pilot's success criterion in
    its first week: `True`, `False`, or `None` when there is no creation
    event to count from. Each partition is read on its own; nothing here
    merges one user's rows into another's.
    """
    from tools.accounts import list_accounts as listing
    from tools.jobs import event_log

    return [{"user_id": account["user_id"], "email": account["email"],
             **event_log.summarise(event_log.read(account["user_id"]))}
            for account in listing()]


def reset_passphrase(user_id: str) -> str:
    """
    A one-time code that re-invites this account, ending every session it has
    (Q45). The friend redeems it as they did their invite. Raises `KeyError`
    for an id with no account.
    """
    from tools.accounts import reset
    return reset(user_id)


class RunInProgress(RuntimeError):
    """
    Refused because the user has a run the registry calls live: a deletion
    (A6), or a second run while one is going (R120).
    """


def delete_user_data(user_id: str, *, ignore_active_runs: bool = False) -> dict:
    """
    Remove everything this instance holds for one user, and say what (A6).

    The account row, which ends every session at once, and then the whole of
    `users/<user_id>/`: profiles, master resumes, outputs, `jobs.db`,
    `runs.db` and every cache. Not a soft delete. Returns
    `{"user_id", "account": rows, "files", "bytes", "areas"}`, all zero for a
    user with nothing here, so a caller can tell "deleted" from "was never
    there" — the same rule as a filter that must say how many it removed.

    **The one deletion path.** `DELETE /api/account` and `scripts/admin.py
    delete-user` both call this; a second path would be the twin-path bug
    pointed at the one thing that must be provably complete, and
    `test_no_byte_of_a_deleted_user_survives` walks the data home after it.

    **Refused while a run is live** (`RunInProgress`): a worker thread would
    keep writing into the tree after it was removed and leave the residue this
    exists to prevent. The registry never clears a run a crashed process left
    `running`, so the operator can pass `ignore_active_runs` after checking
    the server is not in fact running it. The API never does.

    Order: the row first, so no new request is served as this user, then the
    tree. If the tree fails half-way the error propagates and a second call
    finishes it — both steps are idempotent. The A8 event log lives under
    `users/<id>/data/events.db` (R118), so the tree is where its rows go too.

    Not covered, and stated so "deleted" never means more than it does: Fly
    volume snapshots and anything outside the data home (logs, Sentry).
    `None` is refused: the unscoped home is the whole checkout.
    """
    from tools import paths
    from tools.accounts import delete
    from tools.jobs import run_registry

    if user_id is None:
        raise ValueError("refusing to delete the unscoped data home")
    # Asked of the file only if it exists: opening the registry creates it,
    # and a deletion that recreated the tree it came to remove is a bad joke.
    if not ignore_active_runs and run_registry.db_path(user_id).is_file():
        live = active_runs(user_id)
        if live:
            raise RunInProgress(
                f"{len(live)} run(s) still in progress: "
                + ", ".join(run["id"] for run in live))
    account = delete(user_id)
    removed = paths.remove_user_home(user_id)
    return {"user_id": user_id, "account": account, **removed}


class _CheckpointStop(Exception):
    """Raised when a checkpoint declines to continue. Caught inside run()."""


@dataclass
class StageProgress:
    """
    One progress tick from the pipeline.

    The pipeline runs for minutes and used to report only by logging, which a
    terminal shows live and a UI cannot consume at all. Callers now pass
    `on_progress` and receive these; the CLI prints them and Streamlit renders
    them, without either side knowing what the other does.

    `total` is 0 for stages that cannot know their size up front (discovery
    does not know how many jobs exist until it has looked).
    """
    stage: str          # discovery | enrichment | analysis | generation | summary
    done: int
    total: int
    message: str = ""

    @property
    def fraction(self) -> float:
        """0.0-1.0, or 0.0 when the total is unknown. Safe to feed a progress bar."""
        if not self.total:
            return 0.0
        return min(1.0, self.done / self.total)


class JobScoutOrchestrator:
    """
    Main orchestrator for JobScout V3 pipeline.
    
    Coordinates all agents and provides:
    - Progress tracking
    - Human checkpoints
    - State persistence
    - Summary generation
    """
    
    def __init__(
        self,
        profile_name: str,
        output_dir: str = "outputs",
        *,
        user_id,
        checkpoint: bool = False,
        mock_mode: bool = False,
        mock_generation: bool = False,
        mock_embeddings: bool = False,
        input_file: Optional[str] = None,
        max_resumes: Optional[int] = None,
        generate_pdf: bool = True,
        api_key: str = None,
        backend: str = None,
        use_cache: bool = True,
    ):
        """
        Initialize orchestrator.

        Args:
            profile_name: Name of profile to load
            user_id: Whose data this run reads and writes — profile, master
                resume, board, caches, outputs. `None` is the unscoped layout
                the CLI uses. Keyword-only and required: an orchestrator that
                forgot to say whose would otherwise write somebody's resume
                into whichever home was the default.
            output_dir: Base output directory
            checkpoint: If True, pause for human review between stages
            mock_mode: If True, use mock data for entire pipeline
            mock_generation: If True, use mock for generation only
            mock_embeddings: If True, use mock embeddings for analysis
            input_file: Path to enriched_jobs.json - skips Discovery + Enrichment,
                runs Analysis + Generation directly on cached enriched data.
                Useful for diagnosing scoring/selection without re-scraping.
            max_resumes: Cap on resumes generated per run (the funnel cut). When
                set, only the top-K jobs by analysis score get resumes. Defaults
                to profile.agent_preferences.max_jobs_to_generate.
            generate_pdf: If True, compile each generated .tex to PDF. Degrades
                to .tex-only when no pdflatex is installed.
            api_key: Explicit Gemini key, threaded to every agent that calls the
                API. None falls back to the environment, which is what the CLI
                wants; a UI collecting a key from a user passes it here and it
                never touches os.environ.
            backend: An explicitly chosen rung for this run — the `--backend`
                flag or a run request. Outranks the environment and the
                profile; None means "no opinion" and lets those decide.
            use_cache: If False, every model call is made fresh. A measurement
                is the caller that most needs this, and until R80 the flag
                existed only on the generation agent's own `main()` — so the
                entry point every real run uses could not be told to skip the
                cache at all.
        """
        self.profile_name = profile_name
        self.user_id = user_id
        self.api_key = api_key
        self.backend = backend
        self.use_cache = use_cache
        self._on_progress = None
        self._on_checkpoint = None
        self.checkpoint = checkpoint
        self.mock_mode = mock_mode
        self.mock_generation = mock_generation
        self.mock_embeddings = mock_embeddings or mock_mode
        self.input_file = input_file
        self.max_resumes = max_resumes
        self.generate_pdf = generate_pdf
        
        # Load profile
        logger.info(f"📋 Loading profile: {profile_name}")
        self.profile = load_profile(profile_name, user_id=user_id)
        logger.info(f"✅ Loaded profile: {self.profile.personal_info.name}")
        
        # Setup output directory
        self.timestamp = datetime.now().strftime("%Y-%m-%d")
        # Anchored at the data home, not the working directory: in a container
        # those differ, and the difference is every generated PDF.
        self.output_path = outputs_root(output_dir, user_id=user_id) / self.timestamp
        self.output_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"📁 Output directory: {self.output_path}")
        
        # State tracking
        self.state = {
            'profile': profile_name,
            'timestamp': self.timestamp,
            'discovered_jobs': [],
            'enriched_jobs': [],
            'analysis_results': [],
            # Jobs analysis could not score and why (R97); None until it runs.
            'scoring': None,
            # Scored under the bar, stored and marked on the board (R106).
            'below_bar': [],
            'generation_results': [],
        }
        
        # Resume path, anchored at this user's home — see `master_resume_path`
        # for why the anchor is the data and never the code (R86).
        resume_path = master_resume_path(
            user_id, self.profile.resume_preferences.master_resume_path)
        self.resume_path = resume_path

        logger.info(f"📄 Resume: {resume_path}")
        self._refuse_an_empty_resume(resume_path)

    @staticmethod
    def _refuse_an_empty_resume(resume_path: str) -> None:
        """
        Stop before the run rather than after it, if there is nothing to tailor.

        A master with no experiences and no projects is not a degraded resume,
        it is not a resume — and the pipeline used to accept one, discover
        jobs, score them, and write a file holding an education line and an
        empty Experience heading. Priya Raghunathan got 574 bytes with no
        `\\begin{document}` in it, under a headline saying a resume had been
        written.

        Nothing along the way was wrong. Import produced what it could, the
        renderer omitted the sections that were empty, generation filled the
        two it owns. The product still handed somebody a file that is not a
        resume, so the refusal belongs here, before the API calls, where the
        message can name the cause.
        """
        from tools.resume.latex_parser import parse_latex_resume
        from tools.resume import tex_renderer

        try:
            text = Path(resume_path).read_text(encoding="utf-8", errors="replace")
            parsed = parse_latex_resume(resume_path)
        except Exception:
            # Parsing is the pipeline's own job further down and it reports
            # its failures properly. This guard only answers one question, so
            # it must not become the thing that breaks a run it cannot judge.
            return

        # "This file is not a LaTeX resume" and "this resume has no work on
        # it" are different failures, and `parse_latex_resume` answers both
        # with an empty parse. Telling somebody their resume has no experience
        # when the real problem is that the file is not a resume would be this
        # same bug wearing the fix's clothes, so only a file that *is* one gets
        # judged here; anything else goes to the parser, which says so
        # properly.
        if not tex_renderer.looks_like_latex(text):
            return

        if parsed.experiences or parsed.projects:
            return

        raise ValueError(
            f"{Path(resume_path).name} has no experience and no projects, so "
            "there is nothing to tailor. If you imported a PDF or Word file, "
            "some of it could not be read into separate entries — go back to "
            "the resume step and add them, or edit the .tex directly."
        )
    
    def run(
        self,
        max_jobs: int = 20,
        on_progress: Optional[Callable[[StageProgress], None]] = None,
        on_checkpoint: Optional[Callable[[str, list], bool]] = None,
    ) -> Dict:
        """
        Run the full pipeline.

        Args:
            max_jobs: Maximum number of jobs to process
            on_progress: Called with a StageProgress on every tick. Optional —
                omitting it keeps the previous logging-only behaviour.
            on_checkpoint: Called as (stage, items) when a checkpoint is
                configured; return True to continue, False to stop. Omitting it
                falls back to the terminal prompt, which is correct for the CLI
                and would hang any UI, since it reads stdin.

        Returns:
            Final state dict with all results
        """
        self._on_progress = on_progress
        self._on_checkpoint = on_checkpoint
        logger.info("=" * 80)
        logger.info("🚀 STARTING JOBSCOUT V3 PIPELINE")
        logger.info("=" * 80)
        logger.info(f"Profile: {self.profile.personal_info.name}")
        logger.info(f"Max jobs: {max_jobs}")
        logger.info(f"Checkpoints: {'Enabled' if self.checkpoint else 'Disabled'}")
        logger.info(f"Mock mode: {self.mock_mode}")
        logger.info(f"Mock embeddings: {self.mock_embeddings}")
        logger.info(f"Mock generation: {self.mock_generation}")
        logger.info("")
        
        try:
            if self.input_file:
                # Replay mode — load enriched jobs from disk, skip Discovery + Enrichment
                self._load_enriched_from_file()
            else:
                # Stage 1: Discovery
                self._run_discovery(max_jobs)

                # Discovery is where rows enter the board, and a row no gate
                # has judged reads as shown (`job_store._VERDICT`). Streamlit
                # re-judges before every render; the React board cannot — its
                # GET names no profile — so until this, a board a React user
                # only ever saw was never judged at all: every row eligible,
                # no badge, no count. Here rather than at the end of the run
                # so a checkpoint stop or a failed generation still leaves a
                # judged board. Non-fatal by `refresh_board_gate`'s contract.
                refresh_board_gate(self.user_id, self.profile_name)

                # Stage 2: Enrichment
                self._run_enrichment()

            # Stage 3: Analysis
            self._run_analysis()

            # Stage 4: Generation
            self._run_generation()
            
            # Generate summary
            self._generate_summary()
            
            # Final report
            self._print_final_report()
            
            return self.state
            
        except _CheckpointStop:
            logger.info("Pipeline stopped at a checkpoint")
            self._save_state()
            return self.state

        except KeyboardInterrupt:
            logger.warning("\n\n⚠️  Pipeline interrupted by user")
            self._save_state()
            logger.info(f"💾 State saved to: {self.output_path / 'state.json'}")
            raise
        except Exception as e:
            logger.error(f"\n\n❌ Pipeline failed: {e}")
            import traceback
            traceback.print_exc()
            self._save_state()
            raise
    
    @property
    def enriched_jobs_file(self) -> str:
        """
        Where this run wrote its enriched jobs.

        A caller that stopped at a checkpoint needs this to resume without
        re-scraping: pass it back as `input_file` and Discovery and Enrichment
        are skipped. Exposed as a property so the UI does not have to know the
        orchestrator's directory layout (R25).
        """
        return str(self.output_path / "enriched_jobs.json")

    # =====================================================================
    # PROGRESS AND CHECKPOINTS
    # =====================================================================

    def _emit(self, stage: str, done: int, total: int, message: str = ""):
        """
        Report a progress tick, if anyone is listening.

        A caller's callback is not allowed to take the pipeline down with it:
        a UI that raises while rendering a progress bar should cost a missing
        bar, not a lost run that has already spent API quota.
        """
        if not self._on_progress:
            return
        try:
            self._on_progress(StageProgress(stage, done, total, message))
        except Exception as exc:
            logger.debug(f"progress callback raised, ignoring: {exc}")

    def _request_checkpoint(self, stage: str, items: list) -> bool:
        """
        Ask whether to continue past a checkpoint. True means continue.

        With a callback, the decision belongs to the caller — a UI resolves it
        from a button without anything blocking. Without one, this falls back
        to the terminal prompt the CLI has always used. That fallback reads
        stdin, so a UI must pass a callback or disable checkpoints; it cannot
        simply ignore this.
        """
        if self._on_checkpoint:
            return bool(self._on_checkpoint(stage, items))

        if stage == "analysis":
            return self._checkpoint_review_analysis(items)
        return self._checkpoint_review_jobs(items, stage)

    # =====================================================================
    # PIPELINE STAGES
    # =====================================================================

    def _run_discovery(self, max_jobs: int):
        """Stage 1: Discover jobs."""
        logger.info("=" * 80)
        logger.info("🔍 STAGE 1: DISCOVERY")
        logger.info("=" * 80)
        
        self._emit("discovery", 0, 0, "searching job sources")

        agent = DiscoveryAgent(self.profile, mock_mode=self.mock_mode,
                               user_id=self.user_id)
        jobs = agent.discover_jobs(max_jobs=max_jobs)

        self._emit("discovery", len(jobs), len(jobs), f"found {len(jobs)} jobs")
        
        self.state['discovered_jobs'] = jobs
        logger.info(f"✅ Discovered {len(jobs)} jobs")
        
        if self.checkpoint and jobs:
            if not self._request_checkpoint("discovery", jobs):
                raise _CheckpointStop()
        
        self._save_state()
    
    def _run_enrichment(self):
        """Stage 2: Enrich jobs with full JDs."""
        logger.info("\n" + "=" * 80)
        logger.info("📝 STAGE 2: ENRICHMENT")
        logger.info("=" * 80)
        
        jobs = self.state['discovered_jobs']
        if not jobs:
            logger.warning("⚠️  No jobs to enrich")
            return
        
        # Enrichment respects mock_mode. When real scraping is
        # implemented, this will use Greenhouse/Lever/Ashby scrapers.
        self._emit("enrichment", 0, len(jobs), "fetching job descriptions")

        agent = EnrichmentAgent(mock_mode=self.mock_mode, user_id=self.user_id)
        enriched = agent.enrich_jobs(jobs)

        self._emit("enrichment", len(enriched), len(jobs), f"enriched {len(enriched)} jobs")
        
        self.state['enriched_jobs'] = enriched
        logger.info(f"✅ Enriched {len(enriched)} jobs")
        
        # Save enriched jobs
        enriched_path = self.output_path / "enriched_jobs.json"
        with open(enriched_path, 'w', encoding='utf-8') as f:
            json.dump(enriched, f, indent=2, default=str)
        logger.info(f"💾 Saved to: {enriched_path}")
        
        if self.checkpoint and enriched:
            if not self._request_checkpoint("enrichment", enriched):
                raise _CheckpointStop()
        
        self._save_state()

    def _load_enriched_from_file(self):
        """
        Replay mode — load already-enriched jobs from a previous run.

        Skips Discovery + Enrichment entirely. Useful for re-running
        Analysis + Generation against the same JDs without re-scraping
        (saves Gemini quota during diagnosis).
        """
        import json as _json

        logger.info("=" * 80)
        logger.info(f"📂 REPLAY MODE — loading enriched jobs from file")
        logger.info("=" * 80)
        logger.info(f"Input file: {self.input_file}")

        path = Path(self.input_file)
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {self.input_file}")

        with open(path, 'r', encoding='utf-8') as f:
            data = _json.load(f)

        # File can be either a list of enriched jobs or a dict with 'enriched_jobs' key
        if isinstance(data, dict) and 'enriched_jobs' in data:
            enriched = data['enriched_jobs']
        elif isinstance(data, list):
            enriched = data
        else:
            raise ValueError(
                "Input file must be a list of enriched jobs or have an 'enriched_jobs' key"
            )

        self.state['enriched_jobs'] = enriched
        # Also populate discovered_jobs for summary purposes
        self.state['discovered_jobs'] = [
            {
                'title': j.get('title', ''),
                'company': j.get('company', ''),
                'apply_url': j.get('apply_url', ''),
                'location': j.get('location', ''),
                'source': j.get('source', 'replay'),
            }
            for j in enriched
        ]

        logger.info(f"✅ Loaded {len(enriched)} enriched jobs from {self.input_file}")
        logger.info("⏩ Skipping Discovery + Enrichment stages")

        self._save_state()

    def _apply_body_gate(self, jobs):
        """
        Drop jobs whose *body* rules this profile out, before scoring them.

        Discovery's filter reads the title, deliberately: it runs before
        enrichment so it needs no JD, which is what protects the scraping
        budget. The cost is that a clean title can hide a disqualifying body,
        and in one real run three of eight generated resumes went to postings
        that excluded the candidate in their second paragraph — including one
        whose title advertised "ALL LEVELS" while the body said it was "not
        intended for ... new graduate ... applicants".

        Here rather than in discovery because it needs the JD, and after
        enrichment rather than during it because enrichment is scraping: this
        pass costs no model call and no request, so it can run on everything.

        Non-fatal by construction. A job that survives is scored as before; a
        job that does not is logged with the reason, because a filter that
        silently removes things is the shape this project keeps regretting.

        The verdict is `judge_body`'s, the same function the board's gate
        uses (Q39), so the two cannot disagree about the same text. Only
        `hidden` drops. An undecidable job — a scrape that failed (R61), or a
        requirement met by a question the profile has not answered (A4) — is
        kept and scored, and counted here rather than passed silently.
        """
        from tools.jobs.job_filter import HIDDEN, UNDECIDABLE, judge_body

        kept, dropped, undecided = [], [], []
        for job in jobs or []:
            verdict = judge_body(
                job.get("full_jd", ""), self.profile,
                readable=job.get("scraped_successfully") is not False)
            if verdict.state == HIDDEN:
                dropped.append((job, verdict.reason))
                continue
            if verdict.state == UNDECIDABLE:
                undecided.append((job, verdict.reason))
            kept.append(job)

        if dropped:
            logger.info(f"🚫 Body gate dropped {len(dropped)} of {len(jobs)} "
                        f"job(s) whose description rules you out:")
            for job, reason in dropped:
                logger.info(f"   {job.get('company', '?')} — "
                            f"{str(job.get('title', ''))[:48]}")
                logger.info(f"      {reason}")
        if undecided:
            logger.info(f"❔ Body gate could not decide {len(undecided)} of "
                        f"{len(jobs)} job(s); kept, and marked on the board:")
            for job, reason in undecided:
                logger.info(f"   {job.get('company', '?')} — "
                            f"{str(job.get('title', ''))[:48]}")
                logger.info(f"      {reason}")

        return kept

    def _run_analysis(self):
        """Stage 3: Analyze jobs and select components."""
        logger.info("\n" + "=" * 80)
        logger.info("📊 STAGE 3: ANALYSIS")
        logger.info("=" * 80)
        
        jobs = self._apply_body_gate(self.state['enriched_jobs'])
        if not jobs:
            logger.warning("⚠️  No jobs to analyze")
            return
        
        agent = AnalysisAgent(
            self.profile,
            str(self.resume_path),
            mock_embeddings=self.mock_embeddings,
            api_key=self.api_key,
            user_id=self.user_id,
        )
        results = agent.analyze_jobs(
            jobs,
            on_progress=lambda d, n, msg: self._emit("analysis", d, n, msg),
        )
        
        self.state['analysis_results'] = results
        self.state['scoring'] = getattr(agent, "scoring", None)
        below_bar = getattr(agent, "below_bar", None) or []
        self.state['below_bar'] = [
            {"url": b["job"].get("apply_url"), "title": b["job"].get("title"),
             "company": b["job"].get("company"), "score": b["score"]}
            for b in below_bar]
        logger.info(f"✅ Analyzed {len(results)} jobs passing threshold")

        self._store_scores(results, below_bar,
                           bar=(self.state['scoring'] or {}).get('bar'))
        
        # Save analysis results
        analysis_path = self.output_path / "analysis_results.json"
        with open(analysis_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"💾 Saved to: {analysis_path}")
        
        if self.checkpoint and results:
            if not self._request_checkpoint("analysis", results):
                raise _CheckpointStop()
        
        self._save_state()
    
    @staticmethod
    def _split_unreadable(results):
        """
        Separate jobs whose description was never actually read (R61).

        Returns (readable, unreadable). A job is unreadable when enrichment
        set `scraped_successfully` false — it still has whatever short
        description discovery found, which is honest but thin.

        Absent flags count as readable, so a replayed run or a hand-built
        fixture from before this existed behaves as it always did.
        """
        readable, unreadable = [], []
        for result in results or []:
            job = result.get('job', {}) if isinstance(result, dict) else {}
            if job.get('scraped_successfully') is False:
                unreadable.append(result)
            else:
                readable.append(result)
        return readable, unreadable

    def _resume_cap(self) -> int:
        """
        How many resumes this run writes: `--max-resumes` or the run request,
        falling back to `agent_preferences.max_jobs_to_generate` only when none
        was given (the CLI without the flag).

        `is None`, not `or`. With `or`, a request for 0 silently became the
        profile's number: 10 by default, and settable over PATCH until R107
        (R110). The UIs always pass one, bounded by `start_run`.
        """
        if self.max_resumes is not None:
            return self.max_resumes
        return self.profile.agent_preferences.max_jobs_to_generate

    def _run_generation(self):
        """Stage 4: Generate tailored resumes for the top-K best-fit jobs."""
        logger.info("\n" + "=" * 80)
        logger.info("📝 STAGE 4: GENERATION")
        logger.info("=" * 80)

        analysis_results = self.state['analysis_results']
        if not analysis_results:
            logger.warning("⚠️  No jobs to generate resumes for")
            return

        # FUNNEL: rank by overall fit score (descending) and slice to top-K.
        # Generation is the expensive stage (1-2 Gemini calls per resume), so
        # we pay for it only on the highest-scoring jobs. K is set per-run via
        max_resumes = self._resume_cap()

        # A resume tailored to a posting nobody could read is tailored to
        # nothing (R61). Enrichment marks a job it could not scrape, and this
        # is the first thing that has ever read the mark — the flag was
        # written since the agent existed and consulted by no one, which is
        # how a fabricated JD reached eight resumes.
        #
        # Scoring such a job is still fine: a short description is thin, not
        # false, and the job belongs on the board. Spending a model call to
        # tailor against it is not.
        analysis_results, unreadable = self._split_unreadable(analysis_results)
        if unreadable:
            logger.info(f"📄 {len(unreadable)} job(s) kept on the board but not "
                        f"given a resume — no description could be read:")
            for result in unreadable[:5]:
                job = result.get('job', {})
                logger.info(f"      {job.get('company', '?')} — "
                            f"{str(job.get('title', ''))[:48]}")

        if not analysis_results:
            logger.warning("⚠️  No jobs with a readable description to generate for")
            return

        ranked = sorted(
            analysis_results,
            key=lambda r: r.get('score', {}).get('overall', 0),
            reverse=True,
        )

        if len(ranked) > max_resumes:
            kept = ranked[:max_resumes]
            dropped = ranked[max_resumes:]
            logger.info(
                f"🔻 Funnel: {len(ranked)} jobs passed analysis → "
                f"generating top {max_resumes} by score"
            )
            logger.info(f"   Kept (top {max_resumes}):")
            for r in kept:
                score = r.get('score', {}).get('overall', 0)
                title = r.get('job', {}).get('title', '?')
                company = r.get('job', {}).get('company', '?')
                logger.info(f"      {score:5.1f}%  {title} @ {company}")
            logger.info(f"   Dropped (below funnel cut):")
            for r in dropped:
                score = r.get('score', {}).get('overall', 0)
                title = r.get('job', {}).get('title', '?')
                company = r.get('job', {}).get('company', '?')
                logger.info(f"      {score:5.1f}%  {title} @ {company}")
            generation_input = kept
        else:
            logger.info(
                f"📋 All {len(ranked)} analyzed jobs proceed to generation "
                f"(under cap of {max_resumes})"
            )
            generation_input = ranked

        mock_gen = self.mock_mode or self.mock_generation

        # Generation Agent gets its own ResumeParser with skip_embeddings
        # since it only needs parsed resume data, not scoring.
        gen_parser = ResumeParser(str(self.resume_path), skip_embeddings=True,
                                  api_key=self.api_key, user_id=self.user_id)

        # A profile rule keyed to a component that no longer exists is ignored
        # silently at scoring time — it looks exactly like a rule that simply
        # did not match. A rule keyed to a component ID that two components now
        # share is worse: it fires, on whichever was parsed first (Q34). Say so
        # once per run instead of neither.
        from tools.profile.validation import warn_id_problems
        warn_id_problems(self.profile, gen_parser, context=self.profile_name)

        agent = GenerationAgent(
            self.profile,
            gen_parser,
            mock_mode=mock_gen,
            generate_pdf=self.generate_pdf,
            api_key=self.api_key,
            backend=self.backend,
            use_cache=self.use_cache,
        )

        # Pass output_dir (not output_path) — generation agent adds
        # its own date subdirectory via generate_resumes().
        results = agent.generate_resumes(
            generation_input,
            output_dir=str(self.output_path.parent),
            on_progress=lambda d, n, msg: self._emit("generation", d, n, msg),
        )

        self._emit("generation", len(results), len(results), f"wrote {len(results)} resumes")

        self.state['generation_results'] = results

        # What this run actually used, written into the run rather than said
        # once to a terminal. `configured` is the rung `detect()` chose;
        # `used` is what wrote each resume, and the two differ whenever a
        # model was asked and did not answer.
        #
        # This exists because two passes over the same profile were compared
        # against each other and one of them was not the rung it was labelled
        # with — `detect()` prefers a local Ollama over nothing, so "no key"
        # is not "no model" on a machine where Ollama is installed. A run that
        # does not record its own rung cannot be compared with another later.
        used = {}
        for record in results:
            used[record.get("rung") or "unknown"] = (
                used.get(record.get("rung") or "unknown", 0) + 1)
        self.state['backend'] = {
            'configured': getattr(agent, 'llm_backend', 'unknown'),
            'used': used,
        }
        logger.info(f"✍️  Rungs used: {used or 'none — no resumes written'}")

        self._store_resumes(results)

        valid = sum(1 for r in results if r.get('status') == 'valid')
        review = sum(1 for r in results if r.get('status') == 'needs_review')
        failed = sum(1 for r in results if r.get('status') == 'failed')
        pdfs = sum(1 for r in results if r.get('pdf_path'))
        logger.info(f"✅ Generation: {valid} valid, {review} needs review, {failed} failed")
        if self.generate_pdf:
            logger.info(f"📄 PDFs compiled: {pdfs}")

        self._save_state()
    
    # =====================================================================
    # CHECKPOINTS
    # =====================================================================

    def _checkpoint_review_jobs(self, jobs: List, stage: str):
        """Pause for human review of discovered/enriched jobs. True to continue."""
        _console_print("\n" + "=" * 80)
        _console_print(f"🔍 CHECKPOINT: Review {stage.upper()} results")
        _console_print("=" * 80)
        
        _console_print(f"\nFound {len(jobs)} jobs:\n")
        
        for i, job in enumerate(jobs[:10], 1):
            if hasattr(job, 'title'):
                _console_print(f"{i}. [{job.source}] {job.title} @ {job.company}")
                _console_print(f"   Location: {job.location}")
                if job.salary_min:
                    _console_print(f"   Salary: ${job.salary_min:,.0f} - ${job.salary_max:,.0f}")
            else:
                _console_print(f"{i}. [{job.get('source', 'unknown')}] {job['title']} @ {job['company']}")
                _console_print(f"   Location: {job['location']}")
                if 'salary_min' in job and job['salary_min']:
                    _console_print(f"   Salary: ${job['salary_min']:,.0f} - ${job['salary_max']:,.0f}")
            _console_print()
        
        if len(jobs) > 10:
            _console_print(f"... and {len(jobs) - 10} more\n")
        
        response = input("Continue to next stage? (y/n): ").strip().lower()
        return response == 'y'
    
    def _checkpoint_review_analysis(self, results: List[Dict]):
        """Pause for human review of analysis results. True to continue."""
        _console_print("\n" + "=" * 80)
        _console_print("📊 CHECKPOINT: Review ANALYSIS results")
        _console_print("=" * 80)
        
        _console_print(f"\n{len(results)} jobs passed threshold:\n")
        
        for i, result in enumerate(results[:5], 1):
            job = result['job']
            score = result['score']
            selected = result['selected_components']
            
            _console_print(f"{i}. [{score['overall']:.1f}%] {job['title']} @ {job['company']}")
            _console_print(f"   Location: {job['location']}")
            _console_print(f"   Selected: {len(selected['experiences'])} exp, {len(selected['projects'])} proj")
            _console_print(f"   Top exp: {', '.join(selected['experiences'][:2])}")
            _console_print()
        
        if len(results) > 5:
            _console_print(f"... and {len(results) - 5} more\n")
        
        response = input("Continue to generation? (y/n): ").strip().lower()
        return response == 'y'
    
    # =====================================================================
    # JOB STORE
    # =====================================================================

    def _store_scores(self, results, below_bar=(), bar=None) -> None:
        """
        Write scores back to the durable store, with the bar they met or missed.

        Analysis is the only stage that forms an opinion about a job, and
        without this the board has nothing to rank by. Failing here must not
        cost the run — the scores are already in `state` and on disk.

        Jobs under the bar are written too (R106). They used to be dropped, so
        the board showed "Not scored" for a job analysis had scored 39.9, and
        discovery treated it as unprocessed, re-analysing it every run in a
        slot a new posting could have had.

        `bar` is the threshold analysis applied, passed in from its result,
        not read from the profile: the profile holds the *current* threshold,
        and a store row records what the job was judged against.
        """
        self._update_store(
            lambda store: [
                store.set_score(r["job"]["apply_url"], r["score"]["overall"],
                                selection=r.get("selection_report"), bar=bar)
                for r in results or []
                if r.get("job", {}).get("apply_url")
            ] + [
                store.set_score(b["job"]["apply_url"], b["score"], bar=bar)
                for b in below_bar or ()
                if b.get("job", {}).get("apply_url")
            ],
            "scores",
        )

    def _store_resumes(self, results) -> None:
        """Point each stored job at the resume written for it."""
        self._update_store(
            lambda store: [
                store.attach_resume(
                    r["job"]["apply_url"],
                    tex_path=r.get("latex_path"),
                    pdf_path=r.get("pdf_path"),
                )
                for r in results or []
                if r.get("job", {}).get("apply_url")
            ],
            "resume paths",
        )

    def _update_store(self, work, what: str) -> None:
        try:
            from tools.jobs.job_store import JobStore, db_path

            store = JobStore(db_path(self.user_id))
            try:
                work(store)
            finally:
                store.close()
        except Exception as exc:
            logger.warning(f"Could not write {what} to the job store: {exc}")

    # =====================================================================
    # STATE & REPORTING
    # =====================================================================

    def _save_state(self):
        """Save current state to JSON."""
        state_path = self.output_path / "state.json"
        try:
            with open(state_path, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"⚠️  Failed to save state: {e}")
    
    def _generate_summary(self):
        """Generate markdown summary report."""
        logger.info("\n" + "=" * 80)
        logger.info("📄 GENERATING SUMMARY")
        logger.info("=" * 80)
        
        summary_path = self.output_path / "summary.md"
        
        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write(f"# JobScout V3 - Pipeline Summary\n\n")
            f.write(f"**Profile:** {self.profile.personal_info.name}\n")
            f.write(f"**Date:** {self.state['timestamp']}\n")
            f.write(f"**Email:** {self.profile.personal_info.email}\n\n")

            # Which rung wrote the bullets, at the top, where somebody
            # comparing two runs will see it before reading either. A pass
            # that does not say this cannot be compared with another pass.
            backend = self.state.get('backend') or {}
            if backend:
                used = backend.get('used') or {}
                f.write(f"**Bullets written by:** "
                        + (", ".join(f"{rung} ({n})"
                                     for rung, n in sorted(used.items()))
                           or "nothing — no resumes were written")
                        + f"  ·  backend selected: `{backend.get('configured')}`\n\n")

            f.write("---\n\n")
            
            # Discovery summary
            f.write("## 🔍 Discovery\n\n")
            jobs = self.state['discovered_jobs']
            f.write(f"**Jobs found:** {len(jobs)}\n\n")
            
            if jobs:
                f.write("### Top Jobs:\n\n")
                for i, job in enumerate(jobs[:10], 1):
                    if hasattr(job, 'title'):
                        f.write(f"{i}. **{job.title}** @ **{job.company}**\n")
                        f.write(f"   - Location: {job.location}\n")
                        f.write(f"   - Source: {job.source}\n")
                        if job.salary_min:
                            f.write(f"   - Salary: ${job.salary_min:,.0f} - ${job.salary_max:,.0f}\n")
                        f.write(f"   - URL: {job.apply_url}\n\n")
                    else:
                        f.write(f"{i}. **{job['title']}** @ **{job['company']}**\n")
                        f.write(f"   - Location: {job['location']}\n")
                        f.write(f"   - Source: {job.get('source', 'unknown')}\n")
                        if 'salary_min' in job and job['salary_min']:
                            f.write(f"   - Salary: ${job['salary_min']:,.0f} - ${job['salary_max']:,.0f}\n")
                        f.write(f"   - URL: {job.get('apply_url', 'N/A')}\n\n")
            
            f.write("\n---\n\n")
            
            # Analysis summary
            f.write("## 📊 Analysis\n\n")
            results = self.state['analysis_results']
            f.write(f"**Jobs analyzed:** {len(self.state['enriched_jobs'])}\n")
            f.write(f"**Jobs passing threshold:** {len(results)}\n")
            f.write(f"**Threshold:** {self.profile.agent_preferences.scoring_threshold}%\n\n")
            for line in self._scoring_lines():
                f.write(f"> ⚠️  {line}\n")
            
            if results:
                f.write("### Top Matches:\n\n")
                for i, result in enumerate(results[:10], 1):
                    job = result['job']
                    score = result['score']
                    selected = result['selected_components']
                    
                    f.write(f"{i}. **[{score['overall']:.1f}%] {job['title']}** @ **{job['company']}**\n")
                    f.write(f"   - Location: {job['location']}\n")
                    f.write(f"   - Selected: {len(selected['experiences'])} experiences, {len(selected['projects'])} projects\n")
                    f.write(f"   - Top experiences: {', '.join(selected['experiences'][:2])}\n")
                    f.write(f"   - Top projects: {', '.join(selected['projects'][:2])}\n\n")
            
            f.write("\n---\n\n")
            
            # Generation summary
            f.write("## 📝 Generation\n\n")
            gen_results = self.state['generation_results']
            
            valid = sum(1 for r in gen_results if r.get('status') == 'valid')
            review = sum(1 for r in gen_results if r.get('status') == 'needs_review')
            failed = sum(1 for r in gen_results if r.get('status') == 'failed')
            
            f.write(f"**Valid:** {valid}\n")
            f.write(f"**Needs review:** {review}\n")
            f.write(f"**Failed:** {failed}\n\n")

            # A run whose model never answered still produces resumes, in the
            # user's own words. That is a good floor and a bad surprise, so
            # the summary says it happened and why (R47).
            # Resumes whose compile was tried and failed (R116). Each is in
            # needs_review with its .tex, and has no PDF to submit.
            no_pdf = [r for r in gen_results if r.get("pdf_problem")]
            if no_pdf:
                f.write(f"> ⚠️  **No PDF for {len(no_pdf)} of {len(gen_results)} "
                        f"resume(s).** Each is kept as .tex in needs_review.\n>\n")
                for reason in sorted({r["pdf_problem"] for r in no_pdf}):
                    f.write(f"> - {reason}\n")
                f.write("\n")

            degraded = [r for r in gen_results if r.get("degraded")]
            if degraded:
                f.write(f"> ⚠️  **Bullets were not rewritten** for "
                        f"{len(degraded)} of {len(gen_results)} resume(s). "
                        f"Your own bullets were used instead, correctly "
                        f"selected for each job.\n>\n")
                for reason in sorted({r["degraded"] for r in degraded}):
                    f.write(f"> - {reason}\n")
                f.write("\n")
            
            if gen_results:
                f.write("### Generated Files:\n\n")
                for i, result in enumerate(gen_results, 1):
                    job = result['job']
                    validation = result.get('validation', {})
                    
                    if result.get('status') == 'valid':
                        status = "✅"
                    elif result.get('status') == 'needs_review':
                        status = "⚠️"
                    else:
                        status = "❌"
                    
                    f.write(f"{i}. {status} **{job['company']}** - {job['title']}\n")
                    
                    if result.get('latex_path'):
                        f.write(f"   - File: `{Path(result['latex_path']).name}`\n")

                    if result.get('pdf_path'):
                        f.write(f"   - PDF: `{Path(result['pdf_path']).name}`\n")
                    
                    if validation.get('errors'):
                        f.write(f"   - Errors: {len(validation['errors'])}\n")
                    f.write("\n")
            
            f.write("\n---\n\n")
            f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        logger.info(f"✅ Summary saved: {summary_path}")
    
    def _scoring_lines(self) -> list:
        """
        What the summary and the console say about jobs that went unscored.

        Empty when every job was scored on real embeddings. Otherwise it says
        how many were dropped and the failure kinds, because "34 not scored"
        with no reason is what made the Gemini comparison unreadable (R97).
        """
        scoring = self.state.get('scoring') or {}
        lines = []
        if scoring.get('mock'):
            lines.append("Scores use MOCK embeddings: the resume could not be embedded.")
        if scoring.get('unscored'):
            lines.append(f"Jobs not scored: {scoring['unscored']} "
                         f"({scoring.get('description', 'reason unknown')})")
        elif (scoring.get('embeddings') or {}).get('recovered'):
            lines.append(f"Embeddings: {scoring.get('description')}")

        below = self.state.get('below_bar') or []
        if below:
            # The bar analysis applied, from its own result, not the profile's
            # current threshold (R106).
            bar = scoring.get('bar')
            lines.append(
                f"Below your bar{f' of {bar}' if bar is not None else ''}: "
                f"{len(below)} job(s) scored under it. They are on your board, "
                f"marked, with their scores, and no resume was written for them.")

        # The window guard (R99). Any clipped job is reported, with counts, so
        # 1 of 40 reads differently from 40 of 40. It is the event that says
        # the fitted window has gone stale for a new kind of resume (Q53).
        window = scoring.get('window') or {}
        clipped = window.get('at_floor', 0) + window.get('at_ceiling', 0)
        if clipped:
            lines.append(
                f"Scoring window hit: {window['at_ceiling']} of {window['scored']} "
                f"jobs at the ceiling and {window['at_floor']} at the floor "
                f"({window['backend']}, {window['model']}, raw "
                f"{window['floor']:.4f}-{window['ceiling']:.4f}). The embedding "
                f"half cannot rank those jobs, so keyword count orders them. "
                f"If this resume differs from the ones the window was fit on, "
                f"the window needs refitting (Q53).")
        return lines

    def _print_final_report(self):
        """Print final report to console."""
        _console_print("\n\n")
        _console_print("=" * 80)
        _console_print("🎉 PIPELINE COMPLETE!")
        _console_print("=" * 80)
        _console_print()
        _console_print(f"Profile: {self.profile.personal_info.name}")
        _console_print(f"Output directory: {self.output_path}")
        _console_print()
        _console_print("📊 Results:")
        _console_print(f"  Jobs discovered: {len(self.state['discovered_jobs'])}")
        # Readable only (R124). This counted every job enrichment returned, so
        # a run whose page scrapes all failed still said "5 of 5 enriched".
        # The rest are kept and scored, and said, not subtracted in silence.
        enriched = self.state['enriched_jobs'] or []
        readable = _readable_count(enriched)
        kept = len(enriched) - readable
        _console_print(f"  Jobs enriched: {readable}"
                       + (f" ({kept} more kept without a readable description)"
                          if kept else ""))
        _console_print(f"  Jobs analyzed: {len(self.state['analysis_results'])}")
        for line in self._scoring_lines():
            _console_print(f"  {line}")
        
        gen = self.state['generation_results']
        valid = sum(1 for r in gen if r.get('status') == 'valid')
        review = sum(1 for r in gen if r.get('status') == 'needs_review')
        failed = sum(1 for r in gen if r.get('status') == 'failed')
        _console_print(f"  Resumes: {valid} valid, {review} needs review, {failed} failed")
        _console_print()
        
        _console_print("📁 Output files:")
        _console_print(f"  Summary:  {self.output_path / 'summary.md'}")
        _console_print(f"  Analysis: {self.output_path / 'analysis_results.json'}")
        _console_print(f"  Resumes:  {self.output_path / '*.tex'}")
        _console_print()
        
        if gen:
            _console_print("📄 Generated resumes:")
            for result in gen[:10]:
                job = result['job']
                status = result.get('status', 'unknown')
                icon = "✅" if status == "valid" else ("⚠️" if status == "needs_review" else "❌")
                _console_print(f"  {icon} {job['company']} - {job['title']}")
            
            if len(gen) > 10:
                _console_print(f"  ... and {len(gen) - 10} more")
        
        _console_print()
        _console_print("=" * 80)
        _console_print()


def main():
    """CLI entry point."""
    import argparse

    # On Windows, the default console encoding (cp1252) can't render emojis
    # used in the orchestrator's progress output. Force UTF-8 with 'replace'
    # so unencodable characters become '?' rather than crashing the pipeline.
    # No-op on platforms where stdout is already UTF-8 or non-reconfigurable.
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass
    
    parser = argparse.ArgumentParser(
        description="JobScout V3 - Multi-agent job application pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full mock pipeline (zero API calls)
  python -m agents.orchestrator --profile yash_pathak --max-jobs 5 --mock
  
  # Real discovery + mock embeddings + real generation
  python -m agents.orchestrator --profile yash_pathak --max-jobs 5 --mock-embeddings
  
  # Full pipeline with checkpoints
  python -m agents.orchestrator --profile yash_pathak --max-jobs 10 --checkpoint
  
  # Real pipeline, mock generation only
  python -m agents.orchestrator --profile yash_pathak --max-jobs 10 --mock-generation
        """
    )
    
    parser.add_argument(
        "--profile",
        default="yash_pathak",
        help="Profile name (default: yash_pathak)"
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=10,
        help="Maximum jobs to discover and analyze (default: 10). The full "
             "pipeline runs Discovery → Enrichment → Analysis on this many jobs."
    )
    parser.add_argument(
        "--max-resumes",
        type=int,
        default=None,
        help="Maximum resumes to generate (the funnel cut). After analysis, "
             "only the top-K jobs by score get resumes. Defaults to profile's "
             "agent_preferences.max_jobs_to_generate."
    )

    parser.add_argument(
        "--output",
        default="outputs",
        help="Output directory (default: outputs/)"
    )
    parser.add_argument(
        "--checkpoint",
        action="store_true",
        help="Enable human checkpoints between stages"
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock mode for entire pipeline (zero API calls)"
    )
    parser.add_argument(
        "--mock-generation",
        action="store_true",
        help="Use mock for generation only"
    )
    parser.add_argument(
        "--mock-embeddings",
        action="store_true",
        help="Use mock embeddings for analysis (saves embedding API calls)"
    )
    parser.add_argument(
        "--no-pdf",
        action="store_true",
        help="Write .tex only, skip pdflatex compilation"
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "gemini", "openai", "ollama", "none"],
        default=None,
        help="Which rung rewrites bullets, overriding JOBSCOUT_LLM_BACKEND, "
             "the profile and detection. 'auto' defers to detection. Omit it "
             "for no opinion, which is not the same thing."
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Make every model call fresh. A cached reply carries the model "
             "that wrote it, so a measurement that counts cache hits as model "
             "answers is fiction."
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Path to enriched_jobs.json from a previous run. Skips Discovery + "
             "Enrichment and runs Analysis + Generation directly on the cached "
             "JDs. Useful for diagnosing scoring without burning API quota."
    )
    
    args = parser.parse_args()
    
    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(levelname)s:%(name)s:%(message)s'
    )
    
    # Run orchestrator
    orchestrator = JobScoutOrchestrator(
        profile_name=args.profile,
        # The CLI is the unscoped layout, always: a developer's checkout, the
        # frozen baselines, `--input` replays. There is no user to name.
        user_id=None,
        output_dir=args.output,
        checkpoint=args.checkpoint,
        mock_mode=args.mock,
        mock_generation=args.mock_generation,
        mock_embeddings=args.mock_embeddings,
        input_file=args.input,
        max_resumes=args.max_resumes,
        generate_pdf=not args.no_pdf,
        backend=args.backend,
        use_cache=not args.no_cache,
    )
    
    orchestrator.run(max_jobs=args.max_jobs)


if __name__ == "__main__":
    main()
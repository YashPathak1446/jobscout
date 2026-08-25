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

from tools.profile import load_profile
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


def previous_runs(output_dir: str = "outputs", limit: int = 10) -> list:
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

    base = Path(output_dir)
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


def load_run(path: str) -> dict:
    """The saved state of one past run, in the shape `run()` returns."""
    import json as _json
    return _json.loads((Path(path) / "state.json").read_text(encoding="utf-8"))


def pdflatex_available() -> bool:
    """
    Is a LaTeX engine installed? R20's results screen branches on this.

    A facade so the UI does not import from `tools/` (R25). Cheap enough to
    call per render — `find_pdflatex` checks PATH then a handful of known
    install directories.
    """
    from tools.generation.pdf_builder import find_pdflatex
    return find_pdflatex() is not None


def available_profiles() -> list:
    """Names of profiles that exist. Facade, for the same reason as above."""
    from tools.profile import list_available_profiles
    return list_available_profiles()


# ------------------------------------------------------------------------
# The board's facades (R33)
#
# R33 decided the app is a persistent job board rather than a run log, and
# R35 built the store that makes that possible. These are the three things a
# board does — list, count, and record what the user decided — exposed so the
# view layer never learns that any of it is SQLite (R25).
# ------------------------------------------------------------------------

def job_statuses() -> tuple:
    """What a user is allowed to say about a job."""
    from tools.jobs.job_store import STATUSES
    return STATUSES


def board_jobs(status=None, min_score=None, has_resume=None, company=None,
               source=None, search=None, sort="best", limit=50, offset=0) -> list:
    """
    The board's rows: every job ever discovered, ordered as asked.

    Unscored jobs sort to the bottom rather than as if they scored zero, which
    matters because discovery reaches thousands of roles (R34, R46) and
    analysis only looks at the top slice of them.

    Every filter here already existed in the store and none of them had ever
    been offered to a screen. `limit` defaults small because it is now paged —
    see `board_total`, without which a page cap looks exactly like running out
    of jobs.
    """
    from tools.jobs.job_store import JobStore

    store = JobStore()
    try:
        return store.query(status=status, min_score=min_score,
                           has_resume=has_resume, company=company,
                           source=source, search=search, sort=sort,
                           limit=limit, offset=offset)
    finally:
        store.close()


def board_total(status=None, min_score=None, has_resume=None, company=None,
                source=None, search=None) -> int:
    """How many jobs match, ignoring the page window."""
    from tools.jobs.job_store import JobStore

    store = JobStore()
    try:
        return store.count(status=status, min_score=min_score,
                           has_resume=has_resume, company=company,
                           source=source, search=search)
    finally:
        store.close()


def board_filters() -> dict:
    """
    The companies and sources worth offering, with counts, commonest first.

    Read from the store so a board that has just learned a new ATS offers it
    without anyone editing a list in the view layer.
    """
    from tools.jobs.job_store import JobStore

    store = JobStore()
    try:
        return store.facets()
    finally:
        store.close()


def ghosted_jobs(after_days=None) -> list:
    """
    Applied to, and silent since — computed, never clicked.

    Ghosting is not a decision anyone makes; it is what happens to a job while
    nobody does anything. A stored status would go stale the moment a reply
    arrived, and would need the user to notice the anniversary themselves,
    which is the work a log is supposed to do for them.
    """
    from tools.jobs.job_store import GHOSTED_AFTER_DAYS, JobStore

    store = JobStore()
    try:
        # `if after_days is None`, not `or` — a threshold of 0 days is a
        # legitimate ask ("everything I have applied to and not heard about")
        # and `0 or 28` silently answers a different question.
        window = GHOSTED_AFTER_DAYS if after_days is None else after_days
        return store.ghosted(window)
    finally:
        store.close()


def job_history(url: str) -> list:
    """Every status one job has held, oldest first."""
    from tools.jobs.job_store import JobStore

    store = JobStore()
    try:
        return store.history(url)
    finally:
        store.close()


def start_run(profile_name, api_key="", max_jobs=20, max_resumes=3,
              generate_pdf=True, output_dir="outputs") -> str:
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
    """
    import threading

    from tools.jobs.run_registry import RunRegistry

    registry = RunRegistry()
    run_id = registry.create(profile_name)

    def worker():
        try:
            orchestrator = JobScoutOrchestrator(
                profile_name=profile_name,
                api_key=api_key or None,
                output_dir=output_dir,
                max_resumes=max_resumes,
                generate_pdf=generate_pdf,
                checkpoint=False,
            )
            state = orchestrator.run(
                max_jobs=max_jobs,
                on_progress=lambda tick: registry.progress(
                    run_id, tick.stage, tick.done, tick.total, tick.message),
            )
            results = (state or {}).get("generation_results") or []
            registry.finish(run_id, {
                "analysed": len((state or {}).get("analysis_results") or []),
                "generated": len(results),
                "valid": sum(1 for r in results if r.get("status") == "valid"),
                # Carried out of the run so a reloaded page can say why the
                # bullets are the user's own without reopening state.json.
                "degraded": sorted({r["degraded"] for r in results
                                    if r.get("degraded")}),
            }, output_dir=getattr(orchestrator, "output_path", ""))
        except Exception as exc:                      # the worker owns nothing else
            logger.exception("Background run failed")
            registry.fail(run_id, f"{type(exc).__name__}: {exc}")
        finally:
            registry.close()

    # Daemon, so a stuck run cannot keep the interpreter alive after the
    # server is told to stop.
    threading.Thread(target=worker, name=f"jobscout-run-{run_id}",
                     daemon=True).start()
    return run_id


def run_status(run_id: str):
    """Where a background run has got to, or None if there is no such run."""
    from tools.jobs.run_registry import RunRegistry

    registry = RunRegistry()
    try:
        return registry.get(run_id)
    finally:
        registry.close()


def active_runs() -> list:
    """
    Runs still going, read from disk.

    What a reloaded page asks: it has no memory of starting anything, so the
    answer cannot come from session state.
    """
    from tools.jobs.run_registry import RunRegistry

    registry = RunRegistry()
    try:
        return registry.active()
    finally:
        registry.close()


def recent_runs(limit: int = 10) -> list:
    """The last few runs, newest first, whatever became of them."""
    from tools.jobs.run_registry import RunRegistry

    registry = RunRegistry()
    try:
        return registry.recent(limit)
    finally:
        registry.close()


def score_bands() -> dict:
    """
    Where your scored jobs' quartiles fall, for labelling a match.

    The score is normalised against a window much wider than real data uses —
    95 scored jobs spanned 44 to 59 on a 0-100 scale — so the raw number reads
    as "about 53" whatever it is. This lets a screen say where one job sits
    among yours without changing the number the pipeline gates on.
    """
    from tools.jobs.job_store import JobStore

    store = JobStore()
    try:
        return store.score_bands()
    finally:
        store.close()


def board_sorts() -> list:
    """The orderings the board may ask for. The view never builds SQL."""
    from tools.jobs.job_store import JobStore
    return list(JobStore.SORTS)


def board_stats() -> dict:
    """Totals for the board's header. Returns zeros if no run has happened."""
    from tools.jobs.job_store import JobStore

    store = JobStore()
    try:
        return store.stats()
    finally:
        store.close()


def set_job_status(url: str, status: str) -> None:
    """Record what the user decided about one job. Raises on a bad status."""
    from tools.jobs.job_store import JobStore

    store = JobStore()
    try:
        store.set_status(url, status)
    finally:
        store.close()


def seniority_levels() -> list:
    """
    The levels a profile can ask for, entry-level first.

    R34 made the seniority gate read the profile instead of a constant, which
    only helps if something lets a user set it. The list lives with the
    synonym map that has to understand it, not in the form.
    """
    from tools.jobs.job_filter import SENIORITY_SYNONYMS
    return list(SENIORITY_SYNONYMS.keys())


def backend_status(gemini_key: str = "") -> dict:
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
    from config import (LLM_BACKEND, OLLAMA_API_URL, OLLAMA_MODEL,
                        OPENAI_MODEL, resolve_api_key)
    from tools.generation import llm_backends

    # `resolve_api_key` is the single place that decides what "no key passed"
    # means (R22); asking the environment directly here would be a second
    # answer to the same question.
    key = resolve_api_key(gemini_key or None)
    openai_key = llm_backends.env_openai_key()
    ollama_up = llm_backends.ollama_is_running(OLLAMA_API_URL)

    configured = (LLM_BACKEND or "auto").lower()
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
        "available": {
            "gemini": bool(key),
            "openai": bool(openai_key),
            "ollama": ollama_up,
            "none": True,
        },
    }


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
        checkpoint: bool = False,
        mock_mode: bool = False,
        mock_generation: bool = False,
        mock_embeddings: bool = False,
        input_file: Optional[str] = None,
        max_resumes: Optional[int] = None,
        generate_pdf: bool = True,
        api_key: str = None,
    ):
        """
        Initialize orchestrator.

        Args:
            profile_name: Name of profile to load
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
        """
        self.profile_name = profile_name
        self.api_key = api_key
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
        self.profile = load_profile(profile_name)
        logger.info(f"✅ Loaded profile: {self.profile.personal_info.name}")
        
        # Setup output directory
        self.timestamp = datetime.now().strftime("%Y-%m-%d")
        self.output_path = Path(output_dir) / self.timestamp
        self.output_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"📁 Output directory: {self.output_path}")
        
        # State tracking
        self.state = {
            'profile': profile_name,
            'timestamp': self.timestamp,
            'discovered_jobs': [],
            'enriched_jobs': [],
            'analysis_results': [],
            'generation_results': [],
        }
        
        # Resume path (resolved relative to project root)
        resume_path = self.profile.resume_preferences.master_resume_path
        if not Path(resume_path).is_absolute():
            resume_path = str(Path(__file__).parent.parent / resume_path)
        self.resume_path = resume_path
        
        logger.info(f"📄 Resume: {resume_path}")
    
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

        agent = DiscoveryAgent(self.profile, mock_mode=self.mock_mode)
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

        agent = EnrichmentAgent(mock_mode=self.mock_mode)
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

    def _run_analysis(self):
        """Stage 3: Analyze jobs and select components."""
        logger.info("\n" + "=" * 80)
        logger.info("📊 STAGE 3: ANALYSIS")
        logger.info("=" * 80)
        
        jobs = self.state['enriched_jobs']
        if not jobs:
            logger.warning("⚠️  No jobs to analyze")
            return
        
        agent = AnalysisAgent(
            self.profile,
            str(self.resume_path),
            mock_embeddings=self.mock_embeddings,
            api_key=self.api_key,
        )
        results = agent.analyze_jobs(
            jobs,
            on_progress=lambda d, n, msg: self._emit("analysis", d, n, msg),
        )
        
        self.state['analysis_results'] = results
        logger.info(f"✅ Analyzed {len(results)} jobs passing threshold")

        self._store_scores(results)
        
        # Save analysis results
        analysis_path = self.output_path / "analysis_results.json"
        with open(analysis_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"💾 Saved to: {analysis_path}")
        
        if self.checkpoint and results:
            if not self._request_checkpoint("analysis", results):
                raise _CheckpointStop()
        
        self._save_state()
    
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
        # --max-resumes, falling back to profile.agent_preferences.max_jobs_to_generate.
        max_resumes = self.max_resumes or self.profile.agent_preferences.max_jobs_to_generate
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
                                  api_key=self.api_key)

        # A profile rule keyed to a component that no longer exists is ignored
        # silently at scoring time — it looks exactly like a rule that simply
        # did not match. Say so once per run instead.
        from tools.profile.validation import warn_unresolvable_ids
        warn_unresolvable_ids(self.profile, gen_parser, context=self.profile_name)

        agent = GenerationAgent(
            self.profile,
            gen_parser,
            mock_mode=mock_gen,
            generate_pdf=self.generate_pdf,
            api_key=self.api_key,
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

    def _store_scores(self, results) -> None:
        """
        Write scores back to the durable store.

        Analysis is the only stage that forms an opinion about a job, and
        without this the board has nothing to rank by. Failing here must not
        cost the run — the scores are already in `state` and on disk.
        """
        self._update_store(
            lambda store: [
                store.set_score(r["job"]["apply_url"], r["score"]["overall"])
                for r in results or []
                if r.get("job", {}).get("apply_url")
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
            from tools.jobs.job_store import JobStore

            store = JobStore()
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
        _console_print(f"  Jobs enriched: {len(self.state['enriched_jobs'])}")
        _console_print(f"  Jobs analyzed: {len(self.state['analysis_results'])}")
        
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
        output_dir=args.output,
        checkpoint=args.checkpoint,
        mock_mode=args.mock,
        mock_generation=args.mock_generation,
        mock_embeddings=args.mock_embeddings,
        input_file=args.input,
        max_resumes=args.max_resumes,
        generate_pdf=not args.no_pdf,
    )
    
    orchestrator.run(max_jobs=args.max_jobs)


if __name__ == "__main__":
    main()
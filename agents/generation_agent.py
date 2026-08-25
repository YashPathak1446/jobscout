"""
Generation Agent - Tailor Resumes for Each Job

Takes analysis results and generates tailored resumes:
1. Loads selected components from Analysis Agent
2. Calls Gemini to tailor bullets (or uses mock)
3. Validates output
4. Generates LaTeX files
5. Optionally compiles to PDF

Location: jobscout_v3/agents/generation_agent.py
"""

import hashlib
import os
import sys
import logging
from pathlib import Path
from typing import List, Dict
import json
from datetime import datetime
import re

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.cache.rate_limiter import retry_with_backoff, RateLimitError
from tools.cache.llm_cache import LLMCache
from config import (
    GENERATION_MODELS,
    LLM_CACHE_DIR,
    LLM_CACHE_ENABLED,
    classify_api_error,
    resolve_api_key,
)

from tools.profile import load_profile, UserProfile
from tools.resume import ResumeParser
from tools.generation import build_generic_tailoring_prompt, build_validation_repair_prompt, validate_resume_output
from tools.generation.bullet_fit import fit_bullet, FitResult
from tools.generation.pdf_builder import compile_pdf, detect_flavor, find_pdflatex

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# A master bullet is written to be complete, not to fit a line: this resume's
# run to about 500 characters where the model path rewrites them to 140-280.
# So a verbatim bullet occupies roughly twice the space, and using the model
# path's bullet count verbatim overflows onto a second page — measured, 13
# bullets rendering to 2 pages and seven of them unable to compress.
#
# The one-page rule is the invariant and bullet count is the only lever left
# when the text cannot be rewritten, so the no-model rung takes fewer bullets
# and keeps them whole. Chosen by rendering, not by taste.
VERBATIM_BULLET_SCALE = 0.5


def _scaled(count: int, scale: float) -> int:
    """At least one bullet, however hard the budget is squeezed."""
    import math
    return max(1, int(math.floor(count * scale)))


class GenerationAgent:
    """
    Resume Generation Agent - Tailors resumes for each job.
    
    The agent:
    1. Loads analysis results with selected components
    2. For each job, tailors bullets using Gemini (or mock)
    3. Validates output (bullet counts, character limits, metrics)
    4. Generates LaTeX files with tailored content
    5. Saves to outputs directory
    """
    
    def __init__(self, profile: UserProfile, resume_parser: ResumeParser,
                 mock_mode: bool = False, use_cache: bool = True,
                 generate_pdf: bool = True, api_key: str = None):
        """
        Initialize Generation Agent.

        Args:
            profile: User profile with formatting preferences
            resume_parser: ResumeParser with master resume
            mock_mode: If True, use mock tailoring (no Gemini API calls)
            use_cache: If False, bypass the LLM response cache and force
                       fresh API calls (wired to the --no-cache CLI flag)
            generate_pdf: If True, compile each written .tex to PDF. Silently
                          degrades to .tex-only when no pdflatex is installed.
            api_key: Explicit Gemini key. None falls back to the environment.
        """
        self.profile = profile
        self.resume_parser = resume_parser
        self.mock_mode = mock_mode
        self.api_key = api_key

        self.last_model_used = None

        # Resolve pdflatex once per run, not once per resume: find_pdflatex
        # walks the filesystem and detect_flavor spawns a subprocess, and
        # neither answer changes mid-batch.
        self.generate_pdf = generate_pdf
        self._pdflatex = find_pdflatex() if generate_pdf else None
        self._pdflatex_flavor = detect_flavor(self._pdflatex) if self._pdflatex else None

        logger.info("📝 Initializing Generation Agent...")
        logger.info(f"Profile: {profile.personal_info.name}")
        logger.info(f"Mock mode: {mock_mode}")

        if not generate_pdf:
            logger.info("PDF: disabled (--no-pdf)")
        elif self._pdflatex:
            logger.info(f"PDF: {self._pdflatex_flavor} at {self._pdflatex}")
        else:
            logger.warning(
                "⚠️  PDF: pdflatex not found — writing .tex only. "
                "Install MiKTeX (Windows) or TeX Live to get PDFs."
            )

        # Catch a missing key up front. Without this, a keyless run goes down
        # the real path, _call_gemini_json raises, and _gemini_tailor's bare
        # except silently degrades to mock — producing needs_review files with
        # no visible cause.
        # Which rung of the ladder this run is on. Previously a missing Gemini
        # key meant "mock mode", which wrote placeholder text — a silent
        # downgrade to something nobody wants. Now the absence of a key picks
        # the best backend that *is* available, and says so.
        self.llm_backend = self._resolve_backend(api_key) if not mock_mode else "mock"

        # Built after the rung is resolved, because the rung is part of the
        # key: a cached Ollama reply must never be served to a run asking
        # Gemini, which is how a llama3.1 answer was once read as a Gemini
        # regression (R45).
        self.llm_cache = LLMCache(
            cache_dir=LLM_CACHE_DIR,
            enabled=LLM_CACHE_ENABLED and use_cache,
            backend=self.llm_backend,
        )
        logger.info(f"Cache: {'enabled' if self.llm_cache.enabled else 'disabled'}")

        logger.info("✅ Ready to generate resumes")
    
    
    def _escape_latex(self, text: str, already_latex: bool = False) -> str:
        """
        Escape LaTeX metacharacters — unless the text is already LaTeX.

        `already_latex` exists for the no-model rung. Model output is prose
        and must be escaped; the user's own master bullets are valid LaTeX
        already, and escaping them turns a math span such as ~503ms into
        visible backslash-and-dollar markup in the rendered PDF.

        Found by reading a PDF, not by any test: both paths compiled, both
        produced one page, and only one of them was readable.
        """
        if already_latex:
            return text or ""

        return self._escape_latex_impl(text)

    def _escape_latex_impl(self, text: str) -> str:
        """
        Escape special LaTeX characters using a single-pass regex.

        `<` and `>` are the subtle ones and were missing until R53. They are
        not *errors* in LaTeX — nothing warns, the file compiles, the PDF is
        one page — but in the default OT1 font encoding a bare `<` renders as
        an inverted exclamation mark. "p99 query latency of <5ms" shipped as
        "p99 query latency of ¡5ms" in three resumes before anyone opened the
        PDF and read it.

        That is why they are easy to miss: every other character here fails
        loudly. `%` eats the line, `&` breaks alignment, `#` is a parameter.
        These two fail silently and only in the render, so no test that checks
        compilation or page count can see them. Found by a human reading the
        output.
        """
        if not text:
            return ""
        replacements = {
            '&': r'\&',
            '%': r'\%',
            '$': r'\$',
            '#': r'\#',
            '_': r'\_',
            '{': r'\{',
            '}': r'\}',
            '~': r'\textasciitilde{}',
            '^': r'\textasciicircum{}',
            '\\': r'\textbackslash{}',
            '<': r'\textless{}',
            '>': r'\textgreater{}',
        }
        pattern = re.compile('|'.join(re.escape(key) for key in replacements.keys()))
        return pattern.sub(lambda match: replacements[match.group()], str(text))
    
    def generate_resumes(self, analysis_results: List[Dict], output_dir: str = "outputs",
                         on_progress=None) -> List[Dict]:
        """
        Generate tailored resumes for analyzed jobs.

        Valid outputs are saved directly under outputs/YYYY-MM-DD/.
        Invalid-but-generated outputs are saved under outputs/YYYY-MM-DD/needs_review/.
        Failed generations are reported but not saved.
        """
        logger.info(f"📝 Generating resumes for {len(analysis_results)} jobs...")

        timestamp = datetime.now().strftime("%Y-%m-%d")
        output_path = Path(output_dir) / timestamp
        review_path = output_path / "needs_review"

        output_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"📁 Output directory: {output_path}")

        results = []

        for i, analysis in enumerate(analysis_results, 1):
            job = analysis["job"]
            if on_progress:
                on_progress(i - 1, len(analysis_results),
                            f"{job.get('company', '?')} - {job.get('title', '?')}")
            selected = analysis["selected_components"]

            job_title = job["title"]
            company = job["company"]

            logger.info(f"📄 Generating {i}/{len(analysis_results)}: {job_title} @ {company}")

            try:
                # Compute bullet budgets (used for real Gemini and final validation)
                # Computed on every rung. These decide which components appear
                # and how many bullets each gets, which is selection work, not
                # rewriting work — a run with no model still needs them, and
                # skipping them is why keyless runs used to overflow the page
                # and land in needs_review.
                bullet_budgets = self._compute_bullet_budgets(analysis)
                if self.mock_mode or self.llm_backend == "none":
                    # Fewer bullets, kept whole. Scaling inside the tailor
                    # alone would leave validation expecting the model path's
                    # count and reporting every component as short — the
                    # budget is the contract, so it is what gets scaled.
                    bullet_budgets = self._scale_budgets(
                        bullet_budgets, VERBATIM_BULLET_SCALE)
                budgeted_components = bullet_budgets.get(
                    "budgeted_components", selected
                )

                tailored = self._tailor_resume(
                    job=job,
                    selected_components=budgeted_components,
                    analysis=analysis,
                    bullet_budgets=bullet_budgets,
                )

                if not tailored:
                    logger.error("   ❌ Tailoring failed")

                    results.append({
                        "job": job,
                        "status": "failed",
                        "latex_path": None,
                        "pdf_path": None,
                        "page_count": 0,
                        "validation": {
                            "valid": False,
                            "errors": ["Tailoring failed: no tailored content returned"],
                            "warnings": [],
                        },
                        "tailored_content": None,
                    })

                    continue

                validation = validate_resume_output(
                    tailored, master_resume_text=self._master_resume_text(),
                    bullet_budgets=bullet_budgets,
                    master_bullets=self._master_bullets(budgeted_components))
                self._validate_selected_ids(tailored, budgeted_components, validation)

                filename = self._generate_filename(
                    company, job_title, job.get("apply_url", ""))

                if validation.valid:
                    status = "valid"
                    latex_path = output_path / f"{filename}.tex"
                    logger.info("   ✅ Validation passed")
                else:
                    status = "needs_review"
                    review_path.mkdir(parents=True, exist_ok=True)
                    latex_path = review_path / f"{filename}.tex"

                    logger.warning(f"   ⚠️  Validation failed: {len(validation.errors)} errors")
                    if validation.errors:
                        logger.warning(f"   First error: {validation.errors[0]}")
                    logger.warning(f"   📁 Saving to needs_review/: {latex_path.name}")

                self._generate_latex_file(
                    tailored=tailored,
                    output_path=latex_path,
                    job=job,
                )

                if status == "valid":
                    logger.info(f"   ✅ Saved: {latex_path.name}")
                else:
                    logger.info(f"   ⚠️  Saved for review: {latex_path.name}")

                # Compile needs_review files too — a rendered PDF is usually
                # the fastest way to see what's wrong with one.
                pdf_result = self._compile_to_pdf(latex_path)
                pdf_path = pdf_result.pdf_path if pdf_result and pdf_result.success else None
                page_count = pdf_result.pages if pdf_result else 0

                # Page count is the one quality gate that can't be checked
                # before rendering. A 2-page new-grad resume is a real defect,
                # and content validation has no way to see it.
                if status == "valid" and page_count > 1:
                    logger.warning(
                        f"   ⚠️  Renders to {page_count} pages, expected 1 — "
                        f"demoting to needs_review"
                    )
                    status = "needs_review"
                    validation.add_error(
                        f"Resume renders to {page_count} pages; a new-grad "
                        f"resume must fit on one. Reduce bullet budget or "
                        f"drop a component."
                    )
                    latex_path, pdf_path = self._demote_to_review(
                        latex_path, pdf_path, review_path
                    )

                results.append({
                    "job": job,
                    "status": status,
                    "latex_path": str(latex_path),
                    "pdf_path": str(pdf_path) if pdf_path else None,
                    "page_count": page_count,
                    # Present only when the model path was meant to run and
                    # did not. A resume built from your own bullets is a fine
                    # outcome when you chose it and a thing you would want to
                    # know about when you did not (R47).
                    "degraded": tailored.get("_verbatim_reason"),
                    "validation": {
                        "valid": validation.valid,
                        "errors": validation.errors,
                        "warnings": validation.warnings,
                    },
                    "tailored_content": tailored,
                })

            except Exception as e:
                logger.error(f"   ❌ Generation failed: {e}")

                results.append({
                    "job": job,
                    "status": "failed",
                    "latex_path": None,
                    "pdf_path": None,
                    "page_count": 0,
                    "validation": {
                        "valid": False,
                        "errors": [str(e)],
                        "warnings": [],
                    },
                    "tailored_content": None,
                })

                import traceback
                traceback.print_exc()

        valid_count = sum(1 for r in results if r["status"] == "valid")
        review_count = sum(1 for r in results if r["status"] == "needs_review")
        failed_count = sum(1 for r in results if r["status"] == "failed")
        files_written = sum(1 for r in results if r.get("latex_path"))
        pdf_count = sum(1 for r in results if r.get("pdf_path"))

        logger.info(
            f"✅ Generation complete: "
            f"{valid_count} valid, {review_count} needs review, "
            f"{failed_count} failed, {files_written} files written"
        )

        if self.generate_pdf and self._pdflatex:
            logger.info(f"📄 PDFs compiled: {pdf_count}/{files_written}")

        return results

    def _compile_to_pdf(self, latex_path: Path):
        """
        Compile one written .tex to PDF, returning the PdfResult or None.

        A compile failure is logged and swallowed. The .tex is the real
        deliverable of this stage — losing a whole batch because one resume
        tripped over a LaTeX escape would be a bad trade.
        """
        if not self.generate_pdf or not self._pdflatex:
            return None

        result = compile_pdf(
            latex_path,
            binary=self._pdflatex,
            flavor=self._pdflatex_flavor,
        )

        if result.success:
            pages = f"{result.pages} page{'s' if result.pages != 1 else ''}"
            logger.info(f"   📄 PDF: {result.pdf_path.name} ({pages})")
            return result

        logger.warning(f"   ⚠️  PDF failed for {latex_path.name}: {result.error}")
        if result.log_excerpt:
            first_line = result.log_excerpt.splitlines()[0]
            logger.warning(f"      LaTeX said: {first_line}")

        return result

    def _demote_to_review(self, latex_path: Path, pdf_path, review_path: Path):
        """
        Move an already-written .tex (and its .pdf) into needs_review/.

        Used when a resume passes content validation but fails a check that
        can only be made after rendering — currently just page count. The
        files are written before we can compile them, so this moves rather
        than redirects.
        """
        review_path.mkdir(parents=True, exist_ok=True)

        new_latex = review_path / latex_path.name
        latex_path.replace(new_latex)

        new_pdf = None
        if pdf_path:
            pdf_path = Path(pdf_path)
            if pdf_path.exists():
                new_pdf = review_path / pdf_path.name
                pdf_path.replace(new_pdf)

        return new_latex, new_pdf


    # =========================================================================
    # BULLET LENGTH FITTING (deterministic post-LLM compression)
    # =========================================================================

    def _master_resume_text(self) -> str:
        """
        The master resume as text, for the invented-metric check.

        Cached: validation runs per job, sometimes twice with the repair loop,
        and this is the same file every time.

        Its absence is why that check never ran. `validate_resume_output` takes
        `master_resume_text` and skips the metric checks when it is empty, and
        no call site had ever passed it — so the guard was written, shipped and
        dead for as long as it existed (R31 and R41 are the same story).
        """
        if getattr(self, "_master_text_cache", None) is None:
            try:
                with open(self.resume_parser.resume_path, encoding="utf-8") as handle:
                    self._master_text_cache = handle.read()
            except OSError as exc:
                logger.warning(f"   Could not read master resume for validation: {exc}")
                self._master_text_cache = ""
        return self._master_text_cache

    def _master_bullets(self, selected: Dict) -> Dict:
        """
        The source bullets behind each selected component, keyed by id (R58).

        `_master_resume_text` hands validation the whole file, which is right
        for asking "does this number appear anywhere in my resume" and useless
        for asking "did *this* component's numbers survive its rewrite" — every
        figure is somewhere in the file by definition.
        """
        bullets = {}
        for key, lookup in (("experiences", self.resume_parser.get_experience_by_id),
                            ("projects", self.resume_parser.get_project_by_id)):
            for component_id in (selected or {}).get(key, []) or []:
                component = lookup(component_id)
                if component and getattr(component, "bullets", None):
                    bullets[component.id] = list(component.bullets)
        return bullets

    def _restore_factual_fields(self, tailored: Dict) -> Dict:
        """
        Take company, title, dates and location back from the master resume.

        These are records, not writing. The prompt asks the model to echo them
        unchanged and it has no reason to alter them — but "no reason to" is
        not a guarantee, and the LaTeX builder reads them straight out of the
        model's reply. llama3.1:8b returned `"dates": "Summer 2022"` for work
        done June–Oct 2025 (R44); one successful parse and that date was on a
        resume.

        The model still chooses *which* components appear and rewrites their
        bullets. It just no longer supplies any field whose correct value is
        already known, which removes the whole class rather than detecting it
        afterwards. Anything whose id cannot be matched is left alone — an
        unknown id is a different failure, and `_validate_selected_ids`
        already reports it.

        Mutates `tailored` in place. Returns the same dict.
        """
        lookups = (
            ("experiences", self.resume_parser.get_experience_by_id,
             ("company", "title", "location", "dates")),
            ("projects", self.resume_parser.get_project_by_id,
             ("name", "tech", "dates")),
        )

        if not isinstance(tailored, dict):
            return tailored

        restored = 0
        for section, lookup, fields in lookups:
            for component in tailored.get(section) or []:
                # This runs before validation, so it has to survive anything a
                # model can emit. llama3.1:8b returned a list of strings where
                # the schema says objects — valid JSON, wrong shape — and an
                # unguarded .get() turned a resume that should have been
                # rejected into a crashed run. Malformed input is validation's
                # to report, not this function's to trip over.
                if not isinstance(component, dict):
                    continue
                source = lookup(component.get("id", ""))
                if source is None:
                    continue
                for field in fields:
                    truth = getattr(source, field, None)
                    if truth is None:
                        continue
                    if component.get(field) != truth:
                        component[field] = truth
                        restored += 1

        if restored:
            logger.info(f"   🔒 Restored {restored} factual field(s) from your resume")

        return tailored

    def _apply_bullet_fitting(self, tailored: Dict) -> Dict:
        """
        Normalise a model's reply: restore the facts, then fit the bullets.

        The LLM produces content; this step handles everything deterministic
        that follows. Bullets that overshoot a good zone get compressed, and
        fields the model had no business rewriting are taken back from the
        master resume first.

        The restore lives here rather than at the five call sites because
        every path that post-processes model output already comes through
        this one function, and a guard that can be skipped by adding a sixth
        path is the kind that eventually is.

        Provider-agnostic — works the same regardless of which LLM produced
        the text. Mutates `tailored` in place. Returns the same dict.
        """
        self._restore_factual_fields(tailored)

        adjusted = 0
        unchanged = 0
        flagged = 0

        for exp in tailored.get('experiences', []):
            # A model can return a list of strings where the schema says
            # objects — valid JSON, wrong contract. Skipping here lets
            # validation report that as errors and route the resume to
            # needs_review, which is what the rest of this pipeline does with
            # bad model output. Crashing the run is the one response that
            # loses the other jobs too.
            if not isinstance(exp, dict):
                continue
            new_bullets = []
            for b in exp.get('bullets', []):
                if not isinstance(b, str):
                    new_bullets.append(b)
                    continue
                result = fit_bullet(b, 'experience')
                new_bullets.append(result.text)
                if result.needs_review:
                    flagged += 1
                elif result.target_zone == 'unchanged':
                    unchanged += 1
                else:
                    adjusted += 1
            exp['bullets'] = new_bullets

        for proj in tailored.get('projects', []):
            if not isinstance(proj, dict):
                continue
            new_bullets = []
            for b in proj.get('bullets', []):
                if not isinstance(b, str):
                    new_bullets.append(b)
                    continue
                result = fit_bullet(b, 'project')
                new_bullets.append(result.text)
                if result.needs_review:
                    flagged += 1
                elif result.target_zone == 'unchanged':
                    unchanged += 1
                else:
                    adjusted += 1
            proj['bullets'] = new_bullets

        total = adjusted + unchanged + flagged
        if total > 0:
            logger.info(
                f"   📏 Bullet fit: {unchanged} unchanged, "
                f"{adjusted} compressed, {flagged} couldn't fit cleanly"
            )

        return tailored

    # =========================================================================
    # BULLET BUDGET COMPUTATION
    # =========================================================================

    def _compute_bullet_budgets(self, analysis: Dict) -> Dict:
        """
        Compute per-component bullet budgets using importance tiers + JD scores.

        Algorithm:
        1. Resolve selected component IDs to canonical parser IDs.
        2. Get user importance tier per component from profile.
        3. Compute allocation priority = importance_weight + jd_score.
        4. Decide whether to use 3 or 4 projects (depth vs breadth).
        5. Allocate bullets within global budget using blended priority.
        6. Low-importance components are capped at 1 bullet.

        This is fully dynamic — it uses only component counts, JD scores,
        and user-defined importance tiers. No component names are hardcoded.
        """
        selected = analysis.get("selected_components", {})
        score_data = analysis.get("score", {})

        exp_scores = score_data.get("experience_scores", {})
        proj_scores = score_data.get("project_scores", {})

        # The composite the selector actually ranked on: embedding + keyword +
        # conditional + importance + always. `project_scores` above is raw
        # embedding similarity alone, which is why it must not be used to
        # decide what to *drop* — see Q18. Selection already published this.
        breakdown = selected.get("score_breakdown") or {}
        composite_scores = {
            cid: entry.get("final", 0.0)
            for cid, entry in breakdown.items()
            if isinstance(entry, dict)
        }

        # How well a component fits *this JD*, with the user's own importance
        # preference removed: embedding + keyword + conditional + always.
        # Allocation adds the importance tier back as its own weight, so
        # leaving the term in would count importance twice (Q20).
        jd_fit = {
            cid: entry.get("final", 0.0) - entry.get("importance", 0.0)
            for cid, entry in breakdown.items()
            if isinstance(entry, dict)
        }
        conditional_scores = {
            cid: entry.get("conditional", 0.0)
            for cid, entry in breakdown.items()
            if isinstance(entry, dict)
        }

        # Resolve selected IDs to canonical parser IDs
        selected_exp_ids = [
            self._resolve_to_canonical_exp(eid)
            for eid in selected.get("experiences", [])
        ]
        selected_proj_ids = [
            self._resolve_to_canonical_proj(pid)
            for pid in selected.get("projects", [])
        ]

        # Get importance tiers from profile (resolve aliases defensively)
        # Same merge as Analysis uses: resume-order defaults underneath, the
        # profile's explicit tiers on top. Budget allocation and component
        # selection must agree on importance or they pull in opposite
        # directions.
        from tools.profile.derivation import merge_importance

        imp = self.profile.resume_preferences.component_importance
        derived = getattr(self.resume_parser, "derived_importance", {})
        exp_importance = self._resolve_importance_map(
            merge_importance(imp.experiences, derived.get("experiences", {})), "exp"
        )
        proj_importance = self._resolve_importance_map(
            merge_importance(imp.projects, derived.get("projects", {})), "proj"
        )

        # --- Dynamic project count decision ---
        # If using all selected projects would force the lowest-importance
        # project to 1 bullet while a higher-importance project could use it,
        # drop the weakest project and give remaining ones more depth.
        selected_proj_ids = self._decide_project_count(
            selected_proj_ids, proj_scores, proj_importance,
            proj_composite=composite_scores,
        )

        num_exp = len(selected_exp_ids)
        num_proj = len(selected_proj_ids)

        # --- Global bullet budgets from component counts ---
        exp_budget_table = {1: 3, 2: 5, 3: 6, 4: 7}
        proj_budget_table = {1: 3, 2: 5, 3: 6, 4: 7}

        total_exp_budget = exp_budget_table.get(num_exp, num_exp * 2)
        total_proj_budget = proj_budget_table.get(num_proj, num_proj * 2)

        # Per-component caps based on importance
        # High importance → can get up to 3 bullets
        # Low importance → capped at 1 bullet regardless of budget
        exp_budgets = self._allocate_with_importance(
            component_ids=selected_exp_ids,
            scores=jd_fit or exp_scores,
            importance=self._promote_on_evidence(
                selected_exp_ids, exp_importance, conditional_scores),
            total_budget=total_exp_budget,
            global_max=3,
        )

        proj_budgets = self._allocate_with_importance(
            component_ids=selected_proj_ids,
            scores=jd_fit or proj_scores,
            importance=self._promote_on_evidence(
                selected_proj_ids, proj_importance, conditional_scores),
            total_budget=total_proj_budget,
            global_max=2 if num_proj >= 4 else 3,
        )

        actual_exp_total = sum(exp_budgets.values())
        actual_proj_total = sum(proj_budgets.values())

        budgets = {
            "experiences": exp_budgets,
            "projects": proj_budgets,
            "totals": {
                "experiences": actual_exp_total,
                "projects": actual_proj_total,
                "overall": actual_exp_total + actual_proj_total,
            },
            # Filtered component lists after dynamic project drop.
            # Generation MUST use these everywhere downstream instead of
            # the original selected_components from Analysis.
            "budgeted_components": {
                "experiences": selected_exp_ids,
                "projects": selected_proj_ids,  # already trimmed by _decide_project_count
                "skills": selected.get("skills", []),
            },
        }

        logger.info(
            f"   📊 Bullet budget: {actual_exp_total} exp + "
            f"{actual_proj_total} proj = {actual_exp_total + actual_proj_total} total"
        )
        for cid, count in exp_budgets.items():
            imp_tier = exp_importance.get(cid, "medium")
            short_id = cid.replace("exp_", "")[:22]
            logger.info(f"      exp  {short_id} [{imp_tier}]: {count} bullets")
        for cid, count in proj_budgets.items():
            imp_tier = proj_importance.get(cid, "medium")
            short_id = cid.replace("proj_", "")[:22]
            logger.info(f"      proj {short_id} [{imp_tier}]: {count} bullets")

        return budgets

    # ── Importance tier weights ──────────────────────────────────────────────
    _IMPORTANCE_WEIGHTS = {"high": 2.0, "medium": 1.0, "low": 0.0}
    _LOW_MAX_BULLETS = 1  # Low-importance components never exceed this

    # Two independent trigger matches (R14 scores 0.07 each) is the point at
    # which JD evidence outweighs the user's own "not central to my story"
    # tier for the purposes of depth. One incidental match must not qualify —
    # that was exactly R14's complaint about all-or-nothing scoring.
    _STRONG_CONDITIONAL = 0.14

    def _resolve_importance_map(
        self,
        raw_map: Dict[str, str],
        prefix: str,
    ) -> Dict[str, str]:
        """
        Resolve alias-based importance map to canonical parser IDs.

        e.g. {"exp_sorenson": "high"} → {"exp_sorenson_communications": "high"}

        Unknown aliases are kept as-is (won't match any component, harmless).
        """
        resolved = {}
        for raw_id, tier in raw_map.items():
            tier = tier.lower().strip()
            if tier not in self._IMPORTANCE_WEIGHTS:
                logger.warning(f"   ⚠️  Unknown importance tier '{tier}' for {raw_id}, treating as medium")
                tier = "medium"

            if prefix == "exp":
                comp = self.resume_parser.get_experience_by_id(raw_id)
            else:
                comp = self.resume_parser.get_project_by_id(raw_id)

            canonical = comp.id if comp else raw_id
            resolved[canonical] = tier

        return resolved

    def _decide_project_count(
        self,
        proj_ids: List[str],
        proj_scores: Dict[str, float],
        proj_importance: Dict[str, str],
        proj_composite: Dict[str, float] = None,
    ) -> List[str]:
        """
        Decide whether to use fewer projects for more depth.

        Rule: if we have 4+ projects and the lowest-ranked project is
        low importance AND dropping it would free a bullet for a
        higher-importance project, drop it.

        This gives the user depth on strong projects rather than
        spreading thin across 4 shallow ones.

        **Rank on the composite, not on the embedding (Q18).** This used to
        score `importance_weight + embedding_similarity`, which is not the
        number selection ranked on and cannot see why a project was chosen. A
        project picked for strong JD-specific evidence — the case R14's
        per-hit triggers exist to create — is exactly the one that scores
        badly on embedding alone, so the stage reliably discarded the most
        relevant project. On a Ramp Android role the mobile project earned the
        full 0.20 conditional bonus and the highest composite of any project,
        0.91, and was dropped for embedding 0.58 and a `low` tier.

        The composite already contains the importance term, so it is used on
        its own; adding `_IMPORTANCE_WEIGHTS` back would count importance
        twice. `proj_scores` remains the fallback for an analysis payload
        written before selection published a breakdown.

        Returns the (possibly shorter) list of project IDs to use.
        """
        if len(proj_ids) < 4:
            return proj_ids  # Nothing to drop

        def priority(pid):
            if proj_composite and pid in proj_composite:
                return proj_composite[pid]
            imp_tier = proj_importance.get(pid, "medium")
            imp_weight = self._IMPORTANCE_WEIGHTS.get(imp_tier, 1.0)
            return imp_weight + proj_scores.get(pid, 0.0)

        ranked = sorted(proj_ids, key=priority, reverse=True)
        weakest = ranked[-1]
        weakest_tier = proj_importance.get(weakest, "medium")

        # Only drop if: weakest is low importance
        # AND at least one other project is high importance (would benefit)
        has_high = any(
            proj_importance.get(pid, "medium") == "high"
            for pid in ranked[:-1]
        )

        if weakest_tier == "low" and has_high:
            logger.info(
                f"   📐 Dropped lowest-priority project for depth: "
                f"{weakest.replace('proj_', '')}"
            )
            return [pid for pid in proj_ids if pid != weakest]

        return proj_ids

    def _promote_on_evidence(
        self,
        component_ids: List[str],
        importance: Dict[str, str],
        conditional_scores: Dict[str, float],
    ) -> Dict[str, str]:
        """
        Lift a `low` tier to `medium` when this JD argued strongly for it.

        An importance tier is a statement about the *user*: "this is not
        central to my story". A conditional trigger firing two or more times is
        the system observing that *this particular employer disagrees*. Those
        are different claims, and the second is about the job in front of you.

        Without this, eligibility alone changes nothing. A `low` component
        ranks on `_IMPORTANCE_WEIGHTS['low']` = 0.0 against 1.0 and 2.0, so it
        sits last and the others absorb every spare bullet before it is
        reached. Measured: making low components merely eligible moved zero
        allocations; promoting the tier moved two, both with the full or
        near-full conditional bonus (Q20).

        Promotion is capped at `medium` deliberately. The evidence says "this
        matters here", not "this is your strongest work".
        """
        promoted = dict(importance)

        for cid in component_ids:
            if (importance.get(cid, "medium") == "low"
                    and conditional_scores.get(cid, 0.0) >= self._STRONG_CONDITIONAL):
                promoted[cid] = "medium"
                logger.info(
                    f"   ⬆️  {cid.replace('proj_', '').replace('exp_', '')[:34]} "
                    f"promoted low→medium for depth (JD evidence "
                    f"{conditional_scores[cid]:.2f})"
                )

        return promoted

    def _allocate_with_importance(
        self,
        component_ids: List[str],
        scores: Dict[str, float],
        importance: Dict[str, str],
        total_budget: int,
        global_max: int,
    ) -> Dict[str, int]:
        """
        Allocate bullets using blended importance + JD fit priority.

        `scores` is JD fit — the composite with the importance term removed —
        not raw embedding similarity, and not the full composite. The tier
        weight below is the importance signal; including it in `scores` too
        would count it twice (Q20). Tiers may already have been promoted by
        `_promote_on_evidence`.

        Priority = importance_weight + jd_fit
          high   = 2.0
          medium = 1.0
          low    = 0.0

        Low-importance components are hard-capped at _LOW_MAX_BULLETS (1).
        High/medium components share remaining budget by priority rank.

        Steps:
        1. Give every component 1 bullet.
        2. Hard-cap low-importance components at 1 (no extras).
        3. Distribute remaining budget to high/medium by priority rank.
        4. Respect global_max per component.
        """
        if not component_ids:
            return {}

        # Compute blended priority scores
        def blended_priority(cid):
            imp_tier = importance.get(cid, "medium")
            imp_weight = self._IMPORTANCE_WEIGHTS.get(imp_tier, 1.0)
            jd_score = scores.get(cid, 0.0)
            return imp_weight + jd_score

        # Start everyone at 1
        allocation = {cid: 1 for cid in component_ids}

        # Low-importance components are frozen at 1 — no extras
        eligible = [
            cid for cid in component_ids
            if importance.get(cid, "medium") != "low"
        ]

        # Remaining budget after giving 1 to everyone
        remaining = total_budget - len(component_ids)

        # Sort eligible by blended priority
        ranked_eligible = sorted(eligible, key=blended_priority, reverse=True)

        # Round-robin: give 1 extra bullet at a time to highest priority
        while remaining > 0:
            gave_any = False
            for cid in ranked_eligible:
                if remaining <= 0:
                    break
                if allocation[cid] < global_max:
                    allocation[cid] += 1
                    remaining -= 1
                    gave_any = True
            if not gave_any:
                break  # All eligible at max

        return allocation

    def _resolve_to_canonical_exp(self, exp_id: str) -> str:
        """Resolve an experience ID alias to its canonical parser ID."""
        exp = self.resume_parser.get_experience_by_id(exp_id)
        return exp.id if exp else exp_id

    def _resolve_to_canonical_proj(self, proj_id: str) -> str:
        """Resolve a project ID alias to its canonical parser ID."""
        proj = self.resume_parser.get_project_by_id(proj_id)
        return proj.id if proj else proj_id

    # =========================================================================
    # RESUME TAILORING
    # =========================================================================

    def _tailor_resume(self, job: Dict, selected_components: Dict, analysis: Dict, bullet_budgets: Dict = None) -> Dict:
        """
        Tailor resume bullets for a specific job.
        
        Args:
            job: Job dict with full_jd
            selected_components: Selected experiences, projects, skills
            analysis: Full analysis dict
            bullet_budgets: Pre-computed bullet budgets (None for mock mode)
            
        Returns:
            Dict with tailored experiences and projects
        """
        if self.mock_mode or self.llm_backend == "none":
            # `downgrade_reason` is empty when `none` was genuinely chosen,
            # which is the case that should stay quiet.
            return self._verbatim_tailor(
                job, selected_components, bullet_budgets,
                reason=getattr(self, "downgrade_reason", ""))
        if self.llm_backend in ("openai", "ollama"):
            return self._chat_tailor(job, selected_components, bullet_budgets)
        return self._gemini_tailor(job, selected_components, bullet_budgets)
    
    def _build_selected_experience_text(self, selected: Dict) -> str:
        """
        Build structured prompt context for selected experiences.

        Includes all metadata Gemini is expected to preserve:
        id, title, company, location, dates, and source bullets.
        """
        sections = []

        for exp_id in selected.get('experiences', []):
            exp = self.resume_parser.get_experience_by_id(exp_id)

            if not exp:
                logger.warning(f"   ⚠️  Selected experience not found: {exp_id}")
                continue

            bullets = "\n".join(f"- {bullet}" for bullet in exp.bullets)

            sections.append(
                f"""EXPERIENCE COMPONENT
ID: {exp.id}
Title: {exp.title}
Company: {exp.company}
Location: {exp.location}
Dates: {exp.dates}

Source bullets:
{bullets}
"""
            )

        return "\n\n".join(sections)

    def _build_selected_project_text(self, selected: Dict) -> str:
        """
        Build structured prompt context for selected projects.

        Includes all metadata Gemini is expected to preserve:
        id, name, url, tech, dates, and source bullets.
        """
        sections = []

        for proj_id in selected.get('projects', []):
            proj = self.resume_parser.get_project_by_id(proj_id)

            if not proj:
                logger.warning(f"   ⚠️  Selected project not found: {proj_id}")
                continue

            bullets = "\n".join(f"- {bullet}" for bullet in proj.bullets)
            url = proj.url or ""

            sections.append(
                f"""PROJECT COMPONENT
ID: {proj.id}
Name: {proj.name}
URL: {url}
Tech: {proj.tech}
Dates: {proj.dates}

Source bullets:
{bullets}
"""
            )

        return "\n\n".join(sections)

    def _strip_json_markdown(self, response_text: str) -> str:
        """Remove markdown fences if Gemini wraps JSON in ```json blocks."""
        text = response_text.strip()

        if text.startswith("```json"):
            text = text[len("```json"):].strip()
        elif text.startswith("```"):
            text = text[len("```"):].strip()

        if text.endswith("```"):
            text = text[:-3].strip()

        return text


    def _call_gemini_json(self, prompt: str) -> Dict:
        """
        Call Gemini with model fallback chain and parse the response as JSON.

        Checks the prompt-hash cache first. On a miss, tries models from
        config.GENERATION_MODELS in order — free-tier quota is per-model, so
        each fallback adds real capacity.

        Error handling distinguishes four cases (see config.classify_api_error):
        quota and retired models fall through to the next entry, transient
        failures retry before falling through, and anything else raises.
        """
        from google import genai

        cached = self.llm_cache.get(prompt)
        if cached is not None:
            self.last_model_used = "cache"
            return cached

        client = genai.Client(api_key=resolve_api_key(self.api_key))

        last_error = None
        retired_models = []

        for model in GENERATION_MODELS:
            def make_api_call(m=model):
                return client.models.generate_content(model=m, contents=prompt)

            try:
                response = retry_with_backoff(
                    make_api_call,
                    max_retries=1,   # 1 retry per model, then fall back
                    base_delay=2.0,
                )

                response_text = response.text.strip()
                logger.info(f"   📡 Model: {model}")
                logger.debug(f"   📝 Raw response length: {len(response_text)} chars")

                cleaned_text = self._strip_json_markdown(response_text)
                parsed = json.loads(cleaned_text)

                # Only cache after a successful parse — caching an unparseable
                # response would pin the failure across every future run.
                self.llm_cache.set(prompt, parsed, model)
                self.last_model_used = model

                return parsed

            except json.JSONDecodeError as e:
                # The model answered, it just didn't answer in JSON. Retrying a
                # different model is reasonable; caching is not.
                logger.warning(f"   ⚠️  {model} returned unparseable JSON: {e}")
                last_error = e
                continue

            except Exception as e:
                kind = classify_api_error(e)

                if kind == 'retired':
                    logger.error(
                        f"   ☠️  {model} is retired (404). Update GENERATION_MODELS "
                        f"in config.py — run scripts/check_models.py to see what's live."
                    )
                    retired_models.append(model)
                    last_error = e
                    continue

                if kind == 'quota':
                    logger.warning(f"   ⚠️  {model} quota exhausted, trying next model...")
                    last_error = e
                    continue

                if kind == 'transient':
                    logger.warning(f"   ⚠️  {model} unavailable (503/500), trying next model...")
                    last_error = e
                    continue

                # 'fatal' — bad key, malformed request, a real bug. Falling
                # through would mask it behind a misleading quota message.
                raise

        if retired_models:
            raise RateLimitError(
                f"All models exhausted. RETIRED MODELS IN CONFIG: "
                f"{', '.join(retired_models)} — run scripts/check_models.py and update "
                f"GENERATION_MODELS in config.py. Last error: {last_error}"
            )

        raise RateLimitError(
            f"All models exhausted ({', '.join(GENERATION_MODELS)}). "
            f"Wait for quota reset or upgrade to paid tier. "
            f"Last error: {last_error}"
        )

    def _log_tailored_counts(self, tailored: Dict, selected: Dict) -> None:
        """Log expected vs actual Gemini output counts."""
        exp_count = len(tailored.get('experiences', []))
        proj_count = len(tailored.get('projects', []))

        expected_exp = len(selected.get('experiences', []))
        expected_proj = len(selected.get('projects', []))

        logger.info(f"   ✅ Gemini returned: {exp_count} experiences, {proj_count} projects")

        if exp_count != expected_exp:
            logger.warning(f"   ⚠️  Expected {expected_exp} experiences but got {exp_count}")
        if proj_count != expected_proj:
            logger.warning(f"   ⚠️  Expected {expected_proj} projects but got {proj_count}")

        if exp_count > 0:
            exp_ids = [exp.get('id') or exp.get('title', 'Unknown')
                       for exp in tailored.get('experiences', []) if isinstance(exp, dict)]
            logger.debug(f"   📋 Experiences: {', '.join(exp_ids)}")

        if proj_count > 0:
            proj_ids = [proj.get('id') or proj.get('name', 'Unknown')
                        for proj in tailored.get('projects', []) if isinstance(proj, dict)]
            logger.debug(f"   📋 Projects: {', '.join(proj_ids)}")

    def _resolve_backend(self, api_key) -> str:
        """
        Pick a rung, say which one out loud (R33), and remember if we fell.

        A rung that was configured and could not be used is downgraded to
        `none` here, which makes the rest of the run indistinguishable from a
        deliberately keyless one. That is A4's shape surviving inside R42's
        fix: the log warned, and the *result* recorded nothing, so the summary
        and the UI stayed silent about a backend the user had asked for.

        `self.downgrade_reason` carries it to `_verbatim_tailor`.
        """
        from config import LLM_BACKEND, OLLAMA_API_URL, OLLAMA_MODEL, OPENAI_MODEL
        from tools.generation import llm_backends

        choice = (LLM_BACKEND or "auto").lower()
        if choice == "auto":
            choice = llm_backends.detect(
                gemini_key=resolve_api_key(api_key),
                openai_key=llm_backends.env_openai_key(),
                ollama_url=OLLAMA_API_URL,
            )

        # Resolved once, here, rather than per job: it is a network call, and
        # the answer cannot change mid-run in any way worth chasing. Asking
        # what Ollama actually has is what stops the log promising a model
        # that was never pulled.
        if choice == "ollama":
            self.ollama_model = llm_backends.resolve_ollama_model(
                OLLAMA_API_URL, OLLAMA_MODEL)
            if not self.ollama_model:
                self.downgrade_reason = (
                    "Ollama was selected but has no model pulled — "
                    "run `ollama pull llama3.1`, or any model you prefer")
                logger.warning(f"   {self.downgrade_reason}")
                choice = "none"

        model = {"ollama": getattr(self, "ollama_model", ""),
                 "openai": OPENAI_MODEL}.get(choice, "")
        logger.info(f"✍️  Bullets: {llm_backends.describe(choice, model)}")
        if choice == "none":
            logger.info("   Add a Gemini key, or run Ollama, to have bullets "
                        "rewritten for each job.")
        return choice

    def _scale_budgets(self, budgets: Dict, scale: float) -> Dict:
        """
        Fewer bullets, for a rung that cannot shorten them.

        Returns a copy: the caller's dict is also what validation reads, and
        mutating it in place would make the two disagree in a way that is
        tedious to trace.
        """
        scaled = dict(budgets)
        for section in ("experiences", "projects"):
            scaled[section] = {
                cid: _scaled(count, scale)
                for cid, count in (budgets.get(section) or {}).items()
            }
        totals = {
            "experiences": sum(scaled["experiences"].values()),
            "projects": sum(scaled["projects"].values()),
        }
        totals["overall"] = totals["experiences"] + totals["projects"]
        scaled["totals"] = totals
        return scaled

    def _verbatim_tailor(self, job: Dict, selected: Dict,
                         bullet_budgets: Dict = None, reason: str = "") -> Dict:
        """
        A resume with no model involved: your own bullets, correctly chosen.

        `reason` says *why* there was no model, and it is not decoration. This
        floor is reached two ways that produce byte-identical output: because
        you chose to run without one, and because the one you configured did
        not answer. Until R47 both logged the same line, so a broken key and a
        deliberate keyless run looked the same from the outside — which is how
        an unloaded `.env` shipped a resume with zero experiences (R41).

        This is the floor of the ladder and it is genuinely useful, which is
        why it is no longer called "mock". Component selection, the project
        drop and the bullet budget are all deterministic and all still happen
        — only the rewriting is missing. What comes out is a real resume
        targeted at the job, written in the user's own words.

        The bullets are trimmed to the budget and run through the same
        deterministic fitter the model path uses (R6), so the result fits a
        page instead of overflowing it.
        """
        if reason:
            logger.warning(f"   Using your bullets as written — {reason}")
        else:
            logger.info("   Using your bullets as written (no model configured)")

        budgets = (bullet_budgets or {})
        exp_budget = budgets.get("experiences", {})
        proj_budget = budgets.get("projects", {})

        tailored = {"experiences": [], "projects": []}
        # Carried on the payload rather than returned alongside it, because
        # every caller of this already threads a single dict through fitting,
        # validation and the result record. An out-of-band value would be
        # dropped by the first one that forgot it.
        if reason:
            tailored["_verbatim_reason"] = reason

        for exp_id in selected.get("experiences", []):
            exp = self.resume_parser.get_experience_by_id(exp_id)
            if not exp:
                continue
            keep = exp_budget.get(exp.id, len(exp.bullets))
            tailored["experiences"].append({
                "id": exp.id, "title": exp.title, "company": exp.company,
                "dates": exp.dates, "location": exp.location,
                "bullets": list(exp.bullets)[:keep],
                # Straight from the user's .tex, so already valid LaTeX.
                "_already_latex": True,
            })

        for proj_id in selected.get("projects", []):
            proj = self.resume_parser.get_project_by_id(proj_id)
            if not proj:
                continue
            keep = proj_budget.get(proj.id, len(proj.bullets))
            tailored["projects"].append({
                "id": proj.id, "name": proj.name, "url": proj.url,
                "tech": proj.tech, "dates": proj.dates,
                "bullets": list(proj.bullets)[:keep],
                "_already_latex": True,
            })

        return self._apply_bullet_fitting(tailored)

    def _chat_tailor(self, job: Dict, selected: Dict,
                     bullet_budgets: Dict = None) -> Dict:
        """
        Rewrite through any OpenAI-compatible endpoint, Ollama included.

        Reuses the Gemini prompt verbatim. It was tuned against Gemini and a
        smaller model will follow it less exactly — that is the known cost of
        this rung, and the validation and repair loop downstream is what
        catches the difference.

        A failure here falls back to the verbatim rung rather than aborting.
        A resume in the user's own words beats no resume.
        """
        from config import (OLLAMA_BASE_URL, OLLAMA_MODEL,
                            OPENAI_BASE_URL, OPENAI_MODEL)
        from tools.generation import llm_backends

        if self.llm_backend == "ollama":
            base_url, key = OLLAMA_BASE_URL, None
            model = getattr(self, "ollama_model", "") or OLLAMA_MODEL
        else:
            base_url, model = OPENAI_BASE_URL, OPENAI_MODEL
            key = llm_backends.env_openai_key()

        # The same prompt the Gemini path uses. Tuned against Gemini, which is
        # this rung's known cost: a smaller model follows it less exactly, and
        # the validation loop downstream is what catches the difference.
        prompt = build_generic_tailoring_prompt(
            parsed_resume=self.resume_parser.parsed_resume,
            jd_text=job["full_jd"],
            selected_exp_text=self._build_selected_experience_text(selected),
            selected_proj_text=self._build_selected_project_text(selected),
            num_experiences=len(selected.get("experiences", [])),
            num_projects=len(selected.get("projects", [])),
            bullet_budgets=bullet_budgets,
        )

        cached = self.llm_cache.get(prompt)
        if cached is not None:
            self.last_model_used = "cache"
            return self._apply_bullet_fitting(cached)

        try:
            parsed = llm_backends.call_chat_json(prompt, base_url, model, key)
        except Exception as exc:
            logger.warning(f"   {self.llm_backend} rewriting failed ({exc}); "
                           "falling back to your bullets as written")
            return self._verbatim_tailor(
                job, selected, bullet_budgets,
                reason=f"the {self.llm_backend} backend failed ({exc})")

        self.last_model_used = model
        self.llm_cache.set(prompt, parsed, model)
        return self._apply_bullet_fitting(parsed)

    def _mock_tailor(self, job: Dict, selected: Dict) -> Dict:
        """
        Mock tailoring - just returns original bullets.
        
        For testing without Gemini API calls.
        """
        logger.info("   🧪 Using mock tailoring")
        
        tailored = {
            'experiences': [],
            'projects': [],
        }
        
        # Get experiences
        for exp_id in selected['experiences']:
            exp = self.resume_parser.get_experience_by_id(exp_id)
            if exp:
                tailored['experiences'].append({
                    'id': exp.id,
                    'title': exp.title,
                    'company': exp.company,
                    'dates': exp.dates,
                    'location': exp.location,
                    'bullets': exp.bullets,  # Use original bullets
                })
        
        # Get projects
        for proj_id in selected['projects']:
            proj = self.resume_parser.get_project_by_id(proj_id)
            if proj:
                tailored['projects'].append({
                    'id': proj.id,
                    'name': proj.name,
                    'url': proj.url,
                    'tech': proj.tech,
                    'dates': proj.dates,
                    'bullets': proj.bullets,  # Use original bullets
                })
        
        return tailored
    
    def _gemini_tailor(self, job: Dict, selected: Dict, bullet_budgets: Dict = None) -> Dict:
        """
        Real tailoring using Gemini API.

        Builds structured prompt context with IDs/full metadata, calls Gemini,
        validates the response, and makes one narrow repair attempt if needed.
        """
        logger.info("   🤖 Using Gemini tailoring")

        exp_text = self._build_selected_experience_text(selected)
        proj_text = self._build_selected_project_text(selected)

        num_experiences = len(selected.get('experiences', []))
        num_projects = len(selected.get('projects', []))

        prompt = build_generic_tailoring_prompt(
            parsed_resume=self.resume_parser.parsed_resume,
            jd_text=job['full_jd'],
            selected_exp_text=exp_text,
            selected_proj_text=proj_text,
            num_experiences=num_experiences,
            num_projects=num_projects,
            bullet_budgets=bullet_budgets,
        )

        try:
            tailored = self._call_gemini_json(prompt)
            self._log_tailored_counts(tailored, selected)

            # Deterministic length fitting — LLM produces content, this handles precision.
            tailored = self._apply_bullet_fitting(tailored)

            validation = validate_resume_output(tailored, master_resume_text=self._master_resume_text(),
                                            bullet_budgets=bullet_budgets,
                                            master_bullets=self._master_bullets(selected))
            self._validate_selected_ids(tailored, selected, validation)

            if validation.valid:
                logger.info("   ✅ Gemini output passed validation")
                return tailored

            logger.warning(f"   ⚠️  Gemini output failed validation: {len(validation.errors)} errors")
            if validation.errors:
                logger.warning(f"   First error: {validation.errors[0]}")

            error_feedback = self._format_validation_errors(validation)
            repair_prompt = build_validation_repair_prompt(
                previous_json=tailored,
                error_feedback=error_feedback,
                num_experiences=num_experiences,
                num_projects=num_projects,
                bullet_budgets=bullet_budgets,
            )

            logger.info("   🔧 Attempting Gemini validation repair")
            repaired = self._call_gemini_json(repair_prompt)
            self._log_tailored_counts(repaired, selected)

            # Fit the repair output too
            repaired = self._apply_bullet_fitting(repaired)

            repair_validation = validate_resume_output(repaired, master_resume_text=self._master_resume_text(),
                                                   bullet_budgets=bullet_budgets,
                                                   master_bullets=self._master_bullets(selected))
            self._validate_selected_ids(repaired, selected, repair_validation)

            if repair_validation.valid:
                logger.info("   ✅ Gemini repair passed validation")
                return repaired

            logger.warning(f"   ⚠️  Gemini repair still failed: {len(repair_validation.errors)} errors")
            if repair_validation.errors:
                logger.warning(f"   First repair error: {repair_validation.errors[0]}")

            # Return repaired content anyway; generate_resumes() will classify it
            # as valid or needs_review using the final validation gate.
            return repaired

        except Exception as e:
            # The verbatim floor, not `_mock_tailor`. R37 built the floor and
            # said why it is "no longer called mock": it produces a real
            # resume in the user's own words, correctly selected. This path
            # was never moved over, so a genuine Gemini outage told the user
            # their run had gone to "mock tailoring" — which sounds like test
            # output and gives them nothing to act on.
            logger.error(f"   ❌ Gemini API error: {e}")
            return self._verbatim_tailor(
                job, selected, bullet_budgets,
                reason=f"Gemini could not be reached ({e})")

    def _generate_filename(self, company: str, title: str, apply_url: str = "") -> str:
        """
        A safe, readable, *unique* filename for one posting's resume.

        Company plus the first three title words is readable and not unique.
        Affirm posts "Software Engineer I, Fullstack (Servicing International)"
        in several countries; every one of them produced the same name, so the
        last one written won and the others' stored paths pointed at a resume
        tailored to a different job description. The job board is what made it
        visible, by showing those rows side by side.

        So the apply URL — already the job store's primary key — contributes a
        short suffix. Hashed rather than slugged because a URL is long and
        ugly, and stable rather than sequential because the same posting
        re-discovered should overwrite its own resume instead of accumulating
        near-duplicates beside it.
        """
        # Clean company name
        company_clean = company.replace(" ", "_").replace(",", "").replace(".", "")

        # Clean title - take first few words
        title_words = title.split()[:3]
        title_clean = "_".join(title_words).replace(",", "").replace(".", "")

        # Combine
        name = self.profile.personal_info.name.replace(" ", "_")
        filename = f"{name}_{company_clean}_{title_clean}"

        # Remove any non-alphanumeric except underscore
        filename = "".join(c for c in filename if c.isalnum() or c == "_")

        # Eight hex characters: unique across far more postings than discovery
        # can reach, and short enough to keep the readable part readable.
        if apply_url:
            digest = hashlib.sha256(apply_url.encode("utf-8")).hexdigest()[:8]
            filename = f"{filename}_{digest}"

        return filename
    
    def _strip_coursework(self, latex_text: str) -> str:
        """
        Remove the Relevant Coursework bullet from the education section.

        Strips the \\resumeItemListStart...\\resumeItemListEnd block inside
        the education subheading, which typically contains only the
        coursework bullet. The education degree/school heading is preserved.

        This is a deterministic layout optimisation — no LLM involved.
        """
        # Match the entire coursework block:
        #   \resumeItemListStart
        #     \resumeItem{\textbf{Relevant Coursework:} ...}
        #   \resumeItemListEnd
        pattern = (
            r'\s*\\resumeItemListStart\s*'
            r'\\resumeItem\{\\textbf\{Relevant Coursework[^}]*\}[^}]*\}\s*'
            r'\\resumeItemListEnd'
        )
        stripped = re.sub(pattern, '', latex_text, count=1)

        if stripped != latex_text:
            logger.debug("   Stripped Relevant Coursework from education section")

        return stripped

    def _generate_latex_file(self, tailored: Dict, output_path: Path, job: Dict):
        """
        Generate LaTeX file from tailored content.

        Builds resume using ONLY selected components with tailored bullets while
        preserving the master resume header, education, skills, and footer.
        """
        # Get master resume template
        with open(self.resume_parser.resume_path, 'r', encoding='utf-8') as f:
            master_latex = f.read()

        # Keep everything before Experience section
        header_end = master_latex.find('%-----------EXPERIENCE-----------')
        if header_end == -1:
            header_end = master_latex.find('\\section{Experience}')

        # Keep everything from Technical Skills onward
        skills_start = master_latex.find('%-----------PROGRAMMING SKILLS-----------')
        if skills_start == -1:
            skills_start = master_latex.find('\\section{Technical Skills}')

        # Start with header + education from master resume
        header_section = master_latex[:header_end] if header_end != -1 else ""

        # Remove Relevant Coursework from generated resumes.
        # For users with internships and projects, coursework is the
        # lowest-value section and the space is better used for
        # experience/project bullets. This is a deterministic layout
        # decision, not user-specific — any resume with enough
        # experience benefits from reclaiming this space.
        header_section = self._strip_coursework(header_section)

        latex_content = header_section

        # -------------------------
        # Experience section
        # -------------------------
        latex_content += """%-----------EXPERIENCE-----------
    \\section{Experience}
    \\resumeSubHeadingListStart

    """

        for exp in tailored.get('experiences', []):
            # needs_review resumes are still written to disk, so this runs on
            # output validation has already rejected. Skip what it cannot
            # render rather than losing the whole file.
            if not isinstance(exp, dict):
                continue
            verbatim = bool(exp.get('_already_latex'))
            title = self._escape_latex(exp.get('title', 'Unknown Title'))
            company = self._escape_latex(exp.get('company', 'Unknown Company'))
            dates = self._escape_latex(exp.get('dates', 'Dates'))
            location = self._escape_latex(exp.get('location', ''))
            bullets = exp.get('bullets', [])

            latex_content += f"""    \\resumeSubheading
                {{{company}}}{{{dates}}}
                {{{title}}}{{{location}}}
                \\resumeItemListStart
            """

            for bullet in bullets:
                escaped_bullet = self._escape_latex(bullet, already_latex=verbatim)
                latex_content += f"        \\resumeItem{{{escaped_bullet}}}\n"

            latex_content += "      \\resumeItemListEnd\n\n"

        # Close Experience section before starting Projects
        latex_content += "  \\resumeSubHeadingListEnd\n\n\n"

        # -------------------------
        # Projects section
        # -------------------------
        latex_content += """%-----------PROJECTS-----------
    \\section{Projects}
    \\resumeSubHeadingListStart

    """

        for proj in tailored.get('projects', []):
            if not isinstance(proj, dict):
                continue
            verbatim = bool(proj.get('_already_latex'))
            name = self._escape_latex(proj.get('name', 'Unknown Project'))
            tech = self._escape_latex(proj.get('tech', ''))
            dates = self._escape_latex(proj.get('dates', ''))
            bullets = proj.get('bullets', [])

            # Mock tailoring uses "url"; Gemini may return "link".
            # Support both so links don't disappear.
            link = proj.get('url') or proj.get('link') or ''

            if link:
                proj_heading = f"\\textbf{{\\href{{{link}}}{{\\underline{{{name}}}}}}} $|$ \\emph{{{tech}}}"
            else:
                proj_heading = f"\\textbf{{{name}}} $|$ \\emph{{{tech}}}"

            latex_content += f"""    \\resumeProjectHeading
        {{{proj_heading}}}{{{dates}}}
        \\resumeItemListStart
    """

            for bullet in bullets:
                escaped_bullet = self._escape_latex(bullet, already_latex=verbatim)
                latex_content += f"        \\resumeItem{{{escaped_bullet}}}\n"

            latex_content += "      \\resumeItemListEnd\n\n"

        # Close Projects section before adding Skills/footer
        latex_content += "  \\resumeSubHeadingListEnd\n\n\n"

        # -------------------------
        # Technical Skills section
        # -------------------------
        # Generate skills deterministically from parsed master resume,
        # compacted to max_skill_categories from the profile.
        # JD-relevant skills are prioritised within each category.
        jd_text = job.get('full_jd', job.get('short_description', ''))
        latex_content += self._build_skills_section(
            master_latex, jd_text=jd_text, on_page=tailored)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(latex_content)
            

    def _build_skills_section(self, master_latex: str, jd_text: str = "",
                              on_page: dict = None) -> str:
        """
        Build a JD-aware Technical Skills section.

        Reads all skill categories from the parsed master resume, then
        for each category selects skills in JD-relevance order:
        1. Skills that appear in the JD text come first.
        2. Remaining skills fill until the line-length cap is reached.
        3. Categories with zero JD matches are deprioritised.
        4. Total categories capped to max_skill_categories from profile.

        Each category line is capped to MAX_SKILL_LINE_CHARS so it
        never wraps to a second line in the LaTeX template.

        No LLM is involved. No skills are invented.
        """
        # Maximum rendered characters per skill line (label + ": " + values).
        # Calibrated from Jake's Resume template at standard margins.
        MAX_SKILL_LINE_CHARS = 100

        parsed = self.resume_parser.parsed_resume
        categories = parsed.skills.categories if parsed.skills else {}

        if not categories:
            # Fallback: copy skills section verbatim from master
            skills_start = master_latex.find('%-----------PROGRAMMING SKILLS-----------')
            if skills_start == -1:
                skills_start = master_latex.find('\\section{Technical Skills}')
            if skills_start != -1:
                return master_latex[skills_start:]
            return "%-------------------------------------------\n\\end{document}\n"

        max_cats = getattr(
            self.profile.resume_preferences.formatting,
            'max_skill_categories',
            4,
        )

        jd_lower = jd_text.lower() if jd_text else ""
        shown, elsewhere = self._skill_evidence(on_page)
        breadth = self._skill_breadth()

        # Clean category values and split into individual skills
        parsed_categories = []
        for label, raw_value in categories.items():
            clean_val = re.sub(r'[\s}\\]+$', '', raw_value.strip().rstrip('}').rstrip('\\').strip()).strip()
            if not clean_val:
                continue
            # Split on ", " but keep parenthetical groups together
            # e.g., "SQL (PostgreSQL, MySQL)" stays as one skill
            skills = self._split_skills(clean_val)
            parsed_categories.append((label, skills))

        # Score and select skills per category
        selected_categories = []
        for label, skills in parsed_categories:
            selected = self._select_skills_for_jd(
                label=label,
                skills=skills,
                jd_lower=jd_lower,
                max_line_chars=MAX_SKILL_LINE_CHARS,
                shown=shown,
                elsewhere=elsewhere,
                breadth=breadth,
            )
            jd_match_count = sum(
                1 for s in selected
                if self._skill_in_jd(s, jd_lower)
            )
            selected_categories.append((label, selected, jd_match_count))

        # Sort: categories with more JD matches first, but keep
        # "Languages" always first regardless of match count
        languages_cat = None
        rest_cats = []
        for label, skills, matches in selected_categories:
            if label.lower().startswith("language"):
                languages_cat = (label, skills, matches)
            else:
                rest_cats.append((label, skills, matches))

        # Sort rest by JD match count descending
        rest_cats.sort(key=lambda x: x[2], reverse=True)

        # Reassemble and cap to max categories
        ordered = []
        if languages_cat:
            ordered.append(languages_cat)
        ordered.extend(rest_cats)
        ordered = ordered[:max_cats]

        # Drop categories with zero skills selected
        ordered = [(l, s, m) for l, s, m in ordered if s]

        # Build LaTeX
        lines = []
        lines.append("%-----------PROGRAMMING SKILLS-----------")
        lines.append("\\section{Technical Skills}")
        lines.append(" \\begin{itemize}[leftmargin=0.15in, label={}]")
        lines.append("    \\small{\\item{")

        for i, (label, skills, _) in enumerate(ordered):
            escaped_label = label.replace("&", "\\&")
            value = ", ".join(skills)
            separator = " \\\\" if i < len(ordered) - 1 else ""
            lines.append(f"     \\textbf{{{escaped_label}}}{{: {value}}}{separator}")

        lines.append("    }}")
        lines.append(" \\end{itemize}")
        lines.append("")
        lines.append("%-------------------------------------------")
        lines.append("\\end{document}")
        lines.append("")

        return "\n".join(lines)

    def _split_skills(self, skills_str: str) -> List[str]:
        """
        Split a comma-separated skills string into individual skills,
        keeping parenthetical groups together.

        "Python, SQL (PostgreSQL, MySQL), Docker" →
        ["Python", "SQL (PostgreSQL, MySQL)", "Docker"]
        """
        skills = []
        current = ""
        depth = 0

        for char in skills_str:
            if char == '(':
                depth += 1
                current += char
            elif char == ')':
                depth -= 1
                current += char
            elif char == ',' and depth == 0:
                stripped = current.strip()
                if stripped:
                    skills.append(stripped)
                current = ""
            else:
                current += char

        stripped = current.strip()
        if stripped:
            skills.append(stripped)

        return skills

    def _component_keywords(self, components) -> set:
        """Every keyword and tech term the given components carry, lowercased."""
        terms = set()
        for component in components or []:
            for keyword in getattr(component, "keywords", None) or []:
                terms.add(str(keyword).lower())
            tech = getattr(component, "tech", "") or ""
            for part in re.split(r"[,/]", tech):
                part = part.strip().lower()
                if part:
                    terms.add(part)
        return terms

    def _skill_breadth(self) -> dict:
        """How many components use each term. Breadth of use, not depth."""
        parsed = self.resume_parser.parsed_resume
        counts = {}
        for component in list(parsed.experiences) + list(parsed.projects):
            for term in self._component_keywords([component]):
                counts[term] = counts.get(term, 0) + 1
        return counts

    def _skill_evidence(self, on_page) -> tuple:
        """
        Which skills this page evidences, and which belong to work left off it.

        Returns (shown, elsewhere). A term in `shown` is demonstrated by a
        bullet the reader can see. A term in `elsewhere` belongs to a component
        of this resume's owner that did not make this particular resume — so
        listing it advertises work the page does not show.

        Terms in neither set are general: the master's skills section names
        them and no single component owns them. Pandas and NumPy are that, and
        they are not weakened by it.
        """
        parsed = self.resume_parser.parsed_resume
        all_components = list(parsed.experiences) + list(parsed.projects)

        ids_on_page = set()
        for section in ("experiences", "projects"):
            for entry in (on_page or {}).get(section) or []:
                if isinstance(entry, dict) and entry.get("id"):
                    ids_on_page.add(entry["id"])

        shown_components = [c for c in all_components if c.id in ids_on_page]
        shown = self._component_keywords(shown_components)
        everywhere = self._component_keywords(all_components)
        return shown, everywhere - shown

    def _skill_in_jd(self, skill: str, jd_lower: str) -> bool:
        """
        Check if a skill appears in the JD text.

        Handles parenthetical skills by checking both the main skill
        and the sub-skills: "SQL (PostgreSQL, MySQL)" matches if
        "sql", "postgresql", or "mysql" appears in the JD.
        """
        if not jd_lower:
            return False

        skill_lower = skill.lower()

        # Check the full skill string
        # Strip parenthetical for main check
        main_skill = re.sub(r'\s*\([^)]*\)', '', skill_lower).strip()
        if main_skill and main_skill in jd_lower:
            return True

        # Check sub-skills inside parentheses
        paren_match = re.search(r'\(([^)]+)\)', skill_lower)
        if paren_match:
            sub_skills = [s.strip() for s in paren_match.group(1).split(',')]
            for sub in sub_skills:
                if sub and sub in jd_lower:
                    return True

        # Check the full string as-is (for things like "CI/CD", "REST API")
        if skill_lower in jd_lower:
            return True

        return False

    def _select_skills_for_jd(
        self,
        label: str,
        skills: List[str],
        jd_lower: str,
        max_line_chars: int,
        shown: set = None,
        elsewhere: set = None,
        breadth: dict = None,
    ) -> List[str]:
        """
        Select skills for one category, in order of what backs them.

        1. Skills the job description asks for.
        2. Skills a bullet on this page demonstrates.
        3. Skills no single component owns — the general ones.
        4. Skills whose only evidence is a component left off this resume.

        Tier 4 is R59, and the run of 2026-08-25 is why. `OpenAI Gym` comes
        from one reinforcement-learning project. It appeared on the Scale AI
        and Experian resumes, neither of which includes that project, and was
        **absent from the Elastic resume, the only one that does** — the
        selection was exactly inverted. A recruiter reading Scale AI's skills
        line finds nothing about RL anywhere on the page.

        Before this, tiers 2-4 did not exist: everything that did not match the
        JD filled in the order the master resume happens to list it, and that
        order clusters `stable-baselines3, OpenAI Gym, MineRL` ahead of
        `Pandas, NumPy`.

        The cap then made it worse. Filling *skips* an item that does not fit
        and keeps going, so a short low-priority skill leapfrogs a long
        high-priority one — `stable-baselines3` (17 chars) did not fit, and
        `OpenAI Gym` (10) took the slot. The skip is kept, because stopping at
        the first miss wastes the rest of the line, but it means the ordering
        below is what decides the outcome rather than a tiebreak.
        """
        shown = shown or set()
        elsewhere = elsewhere or set()
        breadth = breadth or {}

        def tier(skill: str) -> int:
            if self._skill_in_jd(skill, jd_lower):
                return 0
            terms = self._skill_terms(skill)
            if terms & shown:
                return 1
            if terms & elsewhere:
                return 3
            return 2

        def rank(skill: str) -> tuple:
            level = tier(skill)
            if level < 3:
                # Stable within a tier: the master's own order is a real
                # signal about what its author considers central, and nothing
                # beats it except evidence.
                return (level, 0)

            # Inside tier 3, how many components use the term at all. A skill
            # one absent project owns is a weaker claim than one that runs
            # through several — and without this the tier is decided by the
            # master's listing order, which clusters the whole reinforcement
            # -learning stack together and hands it the last slot.
            #
            # Measured: without it, `MineRL` displaced `NumPy` on the
            # Databricks resume, trading one absent project's library for a
            # library used across four.
            terms = self._skill_terms(skill)
            return (level, -max((breadth.get(t, 0) for t in terms), default=0))

        ordered = sorted(skills, key=rank)

        # Build the line incrementally, respecting the char cap
        selected = []
        label_overhead = len(label) + len(": ")  # "Cloud & Infrastructure: "

        def current_line_length():
            if not selected:
                return label_overhead
            return label_overhead + len(", ".join(selected))

        for skill in ordered:
            test_len = current_line_length()
            if selected:
                test_len += len(", ") + len(skill)
            else:
                test_len += len(skill)
            if test_len <= max_line_chars:
                selected.append(skill)

        return selected

    @staticmethod
    def _skill_terms(skill: str) -> set:
        """
        A skill as the terms a component keyword list might name it by.

        "SQL (MySQL, PostgreSQL)" has to match a component that knows only
        `mysql`, and "AWS (EC2, S3, Lambda)" one that knows only `s3`.
        """
        lower = skill.lower().strip()
        terms = {lower}

        main = re.sub(r"\s*\([^)]*\)", "", lower).strip()
        if main:
            terms.add(main)

        inner = re.search(r"\(([^)]*)\)", lower)
        if inner:
            for part in inner.group(1).split(","):
                part = part.strip()
                if part:
                    terms.add(part)

        return {t for t in terms if t}

    def _validate_selected_ids(self, tailored: Dict, selected: Dict, validation) -> None:
        """
        Ensure generated output preserves the exact selected component IDs.

        The selected IDs may be short aliases from analysis_results.json.
        Resolve them through ResumeParser first, then compare against the
        canonical IDs used in the tailored output.
        """
        expected_exp_ids = self._resolve_expected_experience_ids(selected)
        expected_proj_ids = self._resolve_expected_project_ids(selected)

        # Non-dict entries are a contract violation `validate_resume_output`
        # already reports; this check is about *which* ids came back, and it
        # should not be the thing that crashes on a malformed one.
        actual_exp_ids = [
            exp.get("id")
            for exp in tailored.get("experiences", []) if isinstance(exp, dict)
        ]

        actual_proj_ids = [
            proj.get("id")
            for proj in tailored.get("projects", []) if isinstance(proj, dict)
        ]

        self._validate_id_list(
            label="Experience",
            expected_ids=expected_exp_ids,
            actual_ids=actual_exp_ids,
            validation=validation,
        )

        self._validate_id_list(
            label="Project",
            expected_ids=expected_proj_ids,
            actual_ids=actual_proj_ids,
            validation=validation,
        )


    def _resolve_expected_experience_ids(self, selected: Dict) -> List[str]:
        """
        Resolve selected experience aliases into canonical resume parser IDs.
        """
        resolved_ids = []

        for exp_id in selected.get("experiences", []):
            exp = self.resume_parser.get_experience_by_id(exp_id)

            if exp:
                resolved_ids.append(exp.id)
            else:
                resolved_ids.append(exp_id)

        return resolved_ids


    def _resolve_expected_project_ids(self, selected: Dict) -> List[str]:
        """
        Resolve selected project aliases into canonical resume parser IDs.
        """
        resolved_ids = []

        for proj_id in selected.get("projects", []):
            proj = self.resume_parser.get_project_by_id(proj_id)

            if proj:
                resolved_ids.append(proj.id)
            else:
                resolved_ids.append(proj_id)

        return resolved_ids


    def _validate_id_list(
        self,
        label: str,
        expected_ids: List[str],
        actual_ids: List[str],
        validation,
    ) -> None:
        """
        Validate exact ID preservation for one component type.
        """
        if actual_ids != expected_ids:
            validation.add_error(
                f"{label} IDs do not match selected components.\n"
                f"    Expected: {expected_ids}\n"
                f"    Actual:   {actual_ids}"
            )

        missing_ids = [component_id for component_id in expected_ids if component_id not in actual_ids]
        unexpected_ids = [component_id for component_id in actual_ids if component_id not in expected_ids]

        duplicate_ids = []
        seen = set()
        for component_id in actual_ids:
            if component_id in seen and component_id not in duplicate_ids:
                duplicate_ids.append(component_id)
            seen.add(component_id)

        if missing_ids:
            validation.add_error(
                f"{label} output is missing selected IDs: {missing_ids}"
            )

        if unexpected_ids:
            validation.add_error(
                f"{label} output contains unselected or unknown IDs: {unexpected_ids}"
            )

        if duplicate_ids:
            validation.add_error(
                f"{label} output contains duplicate IDs: {duplicate_ids}"
            )

        if any(component_id is None or component_id == "" for component_id in actual_ids):
            validation.add_error(
                f"{label} output contains missing/empty id fields: {actual_ids}"
            )
    
    
    def _format_validation_errors(self, validation, max_errors: int = 10) -> str:
        """
        Convert validation errors into concise feedback for Gemini repair.
        """
        errors = validation.errors[:max_errors]

        if not errors:
            return "No specific validation errors were provided."

        return "\n".join(f"{i + 1}. {error}" for i, error in enumerate(errors))


def main():
    """CLI for testing Generation Agent."""
    import argparse
    
    parser = argparse.ArgumentParser(description="JobScout V3 - Generation Agent")
    parser.add_argument(
        "--profile",
        default="yash_pathak",
        help="Profile name (default: yash_pathak)"
    )
    parser.add_argument(
        "--resume",
        help="Path to master resume .tex file"
    )
    parser.add_argument(
        "--input",
        default="analysis_results.json",
        help="JSON file with analysis results (default: analysis_results.json)"
    )   
    parser.add_argument(
        "--run-pipeline",
        action="store_true",
        help="Run discovery, enrichment, and analysis before generation. By default, generation uses --input."
    )
    parser.add_argument(
        "--output",
        default="outputs",
        help="Output directory for resumes (default: outputs/)"
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=5,
        help="Maximum jobs to generate resumes for (default: 5)"
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock mode for entire pipeline"
    )
    parser.add_argument(
        "--mock-generation",
        action="store_true",
        help="Use mock for generation only (keep real discovery/analysis)"
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass the LLM response cache (forces fresh API calls)"
    )
    parser.add_argument(
        "--no-pdf",
        action="store_true",
        help="Write .tex only, skip pdflatex compilation"
    )

    args = parser.parse_args()
    
    # Load profile
    print(f"📋 Loading profile: {args.profile}")
    profile = load_profile(args.profile)
    print(f"✅ Profile loaded: {profile.personal_info.name}\n")
    
    # Determine resume path
    if args.resume:
        resume_path = args.resume
    else:
        resume_path = profile.resume_preferences.master_resume_path
        if not resume_path.startswith('/'):
            resume_path = Path(__file__).parent.parent / resume_path
    
    print(f"📄 Using resume: {resume_path}\n")
    
    # Load resume parser
    print("📊 Loading resume parser...")
    # If using --input, skip embedding computation (saves 25 API calls)
    resume_parser = ResumeParser(str(resume_path), skip_embeddings=True)
    print()
    
    # Get analysis results
    if args.run_pipeline:
        # Import these only when the full pipeline is explicitly requested.
        from agents.discovery_agent import DiscoveryAgent
        from agents.enrichment_agent import EnrichmentAgent
        from agents.analysis_agent import AnalysisAgent

        print("🔍 Running Discovery Agent...")
        discovery = DiscoveryAgent(profile, mock_mode=args.mock)
        jobs = discovery.discover_jobs(max_jobs=args.max_jobs)
        print(f"✅ Found {len(jobs)} jobs\n")

        print("📝 Running Enrichment Agent...")
        enrichment = EnrichmentAgent(mock_mode=args.mock)
        enriched_jobs = enrichment.enrich_jobs(jobs)
        print(f"✅ Enriched {len(enriched_jobs)} jobs\n")

        print("📊 Running Analysis Agent...")
        analysis = AnalysisAgent(profile, str(resume_path))
        analysis_results = analysis.analyze_jobs(enriched_jobs[:args.max_jobs])
        print(f"✅ Analyzed {len(analysis_results)} jobs\n")

    else:
        # Default: generation-only mode from cached analysis results.
        input_path = Path(args.input)

        if not input_path.exists():
            raise FileNotFoundError(
                f"Analysis input file not found: {input_path}. "
                "Run analysis first to create analysis_results.json, "
                "pass --input path/to/results.json, or use --run-pipeline explicitly."
            )

        print(f"📂 Loading analysis results from {input_path}")
        with open(input_path, 'r', encoding='utf-8') as f:
            analysis_results = json.load(f)

        print(f"✅ Loaded {len(analysis_results)} analysis results\n")
    
    # Generate resumes
    print("📝 Running Generation Agent...")
    mock_gen = args.mock or args.mock_generation
    generator = GenerationAgent(profile, resume_parser,
                            mock_mode=mock_gen, use_cache=not args.no_cache,
                            generate_pdf=not args.no_pdf)
    results = generator.generate_resumes(
        analysis_results[:args.max_jobs],
        output_dir=args.output
    )
    
    print()
    print("=" * 80)
    print("GENERATION COMPLETE")
    print("=" * 80)

    valid_count = sum(1 for r in results if r.get("status") == "valid")
    review_count = sum(1 for r in results if r.get("status") == "needs_review")
    failed_count = sum(1 for r in results if r.get("status") == "failed")
    files_written = sum(1 for r in results if r.get("latex_path"))
    pdf_count = sum(1 for r in results if r.get("pdf_path"))

    dated_output_dir = Path(args.output) / datetime.now().strftime("%Y-%m-%d")

    print(f"Valid resumes: {valid_count}")
    print(f"Needs review: {review_count}")
    print(f"Failed: {failed_count}")
    print(f"Files written: {files_written}")
    print(f"PDFs compiled: {pdf_count}")
    print(f"Output directory: {dated_output_dir}")
    print()

    if review_count > 0:
        print(f"Needs-review files: {dated_output_dir / 'needs_review'}")
        print()

    if results:
        print("📄 Generation Results:\n")

        for i, result in enumerate(results, 1):
            job = result["job"]
            validation = result["validation"]
            status = result.get("status")

            if status == "valid":
                icon = "✅"
                label = "Valid"
            elif status == "needs_review":
                icon = "⚠️"
                label = "Needs review"
            else:
                icon = "❌"
                label = "Failed"

            print(f"{i}. {icon} {job['company']} - {job['title']}")
            print(f"   Status: {label}")

            if result.get("latex_path"):
                print(f"   File: {Path(result['latex_path']).name}")

            if result.get("pdf_path"):
                print(f"   PDF: {Path(result['pdf_path']).name}")

            if validation.get("errors"):
                print(f"   Errors: {len(validation['errors'])}")
                print(f"   First error: {validation['errors'][0]}")

            if validation.get("warnings"):
                print(f"   Warnings: {len(validation['warnings'])}")

            print()


if __name__ == "__main__":
    main()
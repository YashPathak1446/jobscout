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
)

from tools.profile import load_profile, UserProfile
from tools.resume import ResumeParser
from tools.generation import build_generic_tailoring_prompt, build_validation_repair_prompt, validate_resume_output
from tools.generation.bullet_fit import fit_bullet, FitResult

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


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
    
    # Drop-in replacement for GenerationAgent.__init__ in agents/generation_agent.py
# Replace from "def __init__" down to (but not including) "def _escape_latex".

    def __init__(self, profile: UserProfile, resume_parser: ResumeParser,
                 mock_mode: bool = False, use_cache: bool = True):
        """
        Initialize Generation Agent.

        Args:
            profile: User profile with formatting preferences
            resume_parser: ResumeParser with master resume
            mock_mode: If True, use mock tailoring (no Gemini API calls)
            use_cache: If False, bypass the LLM response cache and force
                       fresh API calls (wired to the --no-cache CLI flag)
        """
        self.profile = profile
        self.resume_parser = resume_parser
        self.mock_mode = mock_mode

        self.llm_cache = LLMCache(
            cache_dir=LLM_CACHE_DIR,
            enabled=LLM_CACHE_ENABLED and use_cache,
        )
        self.last_model_used = None

        logger.info("📝 Initializing Generation Agent...")
        logger.info(f"Profile: {profile.personal_info.name}")
        logger.info(f"Mock mode: {mock_mode}")
        logger.info(f"Cache: {'enabled' if self.llm_cache.enabled else 'disabled'}")

        # Catch a missing key up front. Without this, a keyless run goes down
        # the real path, _call_gemini_json raises, and _gemini_tailor's bare
        # except silently degrades to mock — producing needs_review files with
        # no visible cause.
        if not mock_mode and not os.getenv("GOOGLE_API_KEY"):
            logger.warning("⚠️  GOOGLE_API_KEY not set, will use mock mode")
            self.mock_mode = True

        logger.info("✅ Ready to generate resumes")
    
    
    def _escape_latex(self, text: str) -> str:
        """Escape special LaTeX characters using a single-pass regex."""
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
        }
        pattern = re.compile('|'.join(re.escape(key) for key in replacements.keys()))
        return pattern.sub(lambda match: replacements[match.group()], str(text))
    
    def generate_resumes(self, analysis_results: List[Dict], output_dir: str = "outputs") -> List[Dict]:
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
            selected = analysis["selected_components"]

            job_title = job["title"]
            company = job["company"]

            logger.info(f"📄 Generating {i}/{len(analysis_results)}: {job_title} @ {company}")

            try:
                # Compute bullet budgets (used for real Gemini and final validation)
                bullet_budgets = None
                budgeted_components = selected  # default: use all selected
                if not self.mock_mode:
                    bullet_budgets = self._compute_bullet_budgets(analysis)
                    # Use the filtered component list (after any project drops)
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
                        "validation": {
                            "valid": False,
                            "errors": ["Tailoring failed: no tailored content returned"],
                            "warnings": [],
                        },
                        "tailored_content": None,
                    })

                    continue

                validation = validate_resume_output(tailored, bullet_budgets=bullet_budgets)
                self._validate_selected_ids(tailored, budgeted_components, validation)

                filename = self._generate_filename(company, job_title)

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

                results.append({
                    "job": job,
                    "status": status,
                    "latex_path": str(latex_path),
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

        logger.info(
            f"✅ Generation complete: "
            f"{valid_count} valid, {review_count} needs review, "
            f"{failed_count} failed, {files_written} files written"
        )

        return results
    
    # =========================================================================
    # BULLET LENGTH FITTING (deterministic post-LLM compression)
    # =========================================================================

    def _apply_bullet_fitting(self, tailored: Dict) -> Dict:
        """
        Run every bullet through the deterministic fit function.

        The LLM produces content; this step handles length precision. Bullets
        that overshoot a good zone get compressed deterministically. Provider-
        agnostic — works the same regardless of which LLM produced the text.

        Mutates `tailored` in place. Returns the same dict.
        """
        adjusted = 0
        unchanged = 0
        flagged = 0

        for exp in tailored.get('experiences', []):
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
        imp = self.profile.resume_preferences.component_importance
        exp_importance = self._resolve_importance_map(imp.experiences, "exp")
        proj_importance = self._resolve_importance_map(imp.projects, "proj")

        # --- Dynamic project count decision ---
        # If using all selected projects would force the lowest-importance
        # project to 1 bullet while a higher-importance project could use it,
        # drop the weakest project and give remaining ones more depth.
        selected_proj_ids = self._decide_project_count(
            selected_proj_ids, proj_scores, proj_importance
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
            scores=exp_scores,
            importance=exp_importance,
            total_budget=total_exp_budget,
            global_max=3,
        )

        proj_budgets = self._allocate_with_importance(
            component_ids=selected_proj_ids,
            scores=proj_scores,
            importance=proj_importance,
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
    ) -> List[str]:
        """
        Decide whether to use fewer projects for more depth.

        Rule: if we have 4+ projects and the lowest-ranked project is
        low importance AND dropping it would free a bullet for a
        higher-importance project, drop it.

        This gives the user depth on strong projects rather than
        spreading thin across 4 shallow ones.

        Returns the (possibly shorter) list of project IDs to use.
        """
        if len(proj_ids) < 4:
            return proj_ids  # Nothing to drop

        # Rank projects by allocation priority (importance + score)
        def priority(pid):
            imp_tier = proj_importance.get(pid, "medium")
            imp_weight = self._IMPORTANCE_WEIGHTS.get(imp_tier, 1.0)
            score = proj_scores.get(pid, 0.0)
            return imp_weight + score

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

    def _allocate_with_importance(
        self,
        component_ids: List[str],
        scores: Dict[str, float],
        importance: Dict[str, str],
        total_budget: int,
        global_max: int,
    ) -> Dict[str, int]:
        """
        Allocate bullets using blended importance + JD score priority.

        Priority = importance_weight + jd_score
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
        if self.mock_mode:
            return self._mock_tailor(job, selected_components)
        else:
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

        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

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
            exp_ids = [exp.get('id') or exp.get('title', 'Unknown') for exp in tailored.get('experiences', [])]
            logger.debug(f"   📋 Experiences: {', '.join(exp_ids)}")

        if proj_count > 0:
            proj_ids = [proj.get('id') or proj.get('name', 'Unknown') for proj in tailored.get('projects', [])]
            logger.debug(f"   📋 Projects: {', '.join(proj_ids)}")

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

            validation = validate_resume_output(tailored, bullet_budgets=bullet_budgets)
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

            repair_validation = validate_resume_output(repaired, bullet_budgets=bullet_budgets)
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
            logger.error(f"   ❌ Gemini API error: {e}")
            logger.warning("   ⚠️  Falling back to mock tailoring")
            return self._mock_tailor(job, selected)

    def _generate_filename(self, company: str, title: str) -> str:
        """Generate safe filename from company and title."""
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
                escaped_bullet = self._escape_latex(bullet)
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
                escaped_bullet = self._escape_latex(bullet)
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
        latex_content += self._build_skills_section(master_latex, jd_text=jd_text)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(latex_content)
            

    def _build_skills_section(self, master_latex: str, jd_text: str = "") -> str:
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
    ) -> List[str]:
        """
        Select skills for one category, prioritising JD matches.

        1. JD-matching skills come first.
        2. Non-matching skills fill remaining space.
        3. Total line length (label + ": " + values) is capped.
        """
        # Partition into JD matches and non-matches
        jd_matches = [s for s in skills if self._skill_in_jd(s, jd_lower)]
        non_matches = [s for s in skills if not self._skill_in_jd(s, jd_lower)]

        # Build the line incrementally, respecting the char cap
        selected = []
        label_overhead = len(label) + len(": ")  # "Cloud & Infrastructure: "

        def current_line_length():
            if not selected:
                return label_overhead
            return label_overhead + len(", ".join(selected))

        # Add JD matches first
        for skill in jd_matches:
            test_len = current_line_length()
            if selected:
                test_len += len(", ") + len(skill)
            else:
                test_len += len(skill)
            if test_len <= max_line_chars:
                selected.append(skill)

        # Fill with non-matches
        for skill in non_matches:
            test_len = current_line_length()
            if selected:
                test_len += len(", ") + len(skill)
            else:
                test_len += len(skill)
            if test_len <= max_line_chars:
                selected.append(skill)

        return selected

    def _validate_selected_ids(self, tailored: Dict, selected: Dict, validation) -> None:
        """
        Ensure generated output preserves the exact selected component IDs.

        The selected IDs may be short aliases from analysis_results.json.
        Resolve them through ResumeParser first, then compare against the
        canonical IDs used in the tailored output.
        """
        expected_exp_ids = self._resolve_expected_experience_ids(selected)
        expected_proj_ids = self._resolve_expected_project_ids(selected)

        actual_exp_ids = [
            exp.get("id")
            for exp in tailored.get("experiences", [])
        ]

        actual_proj_ids = [
            proj.get("id")
            for proj in tailored.get("projects", [])
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
                            mock_mode=mock_gen, use_cache=not args.no_cache)
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

    dated_output_dir = Path(args.output) / datetime.now().strftime("%Y-%m-%d")

    print(f"Valid resumes: {valid_count}")
    print(f"Needs review: {review_count}")
    print(f"Failed: {failed_count}")
    print(f"Files written: {files_written}")
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

            if validation.get("errors"):
                print(f"   Errors: {len(validation['errors'])}")
                print(f"   First error: {validation['errors'][0]}")

            if validation.get("warnings"):
                print(f"   Warnings: {len(validation['warnings'])}")

            print()


if __name__ == "__main__":
    main()
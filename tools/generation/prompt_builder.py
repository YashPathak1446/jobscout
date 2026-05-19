import json

"""
Generic Resume Tailoring Prompt Builder

Builds prompts dynamically based on ANY resume structure.
No hardcoded companies, metrics, or user-specific rules.

Location: jobscout/tools/prompt_builder.py
"""


def build_generic_tailoring_prompt(
    parsed_resume,
    jd_text: str,
    selected_exp_text: str,
    selected_proj_text: str,
    num_experiences: int,
    num_projects: int,
    bullet_budgets: dict = None,
) -> str:
    prompt = f"""
You are a resume bullet rewriting engine.

Your job is NOT to select resume content.
Your job is ONLY to rewrite the already-selected resume components so they are concise, truthful, and aligned with the job description.

=============================================================
CORE TASK
=============================================================

You will receive:
1. A job description
2. {num_experiences} pre-selected experience component(s)
3. {num_projects} pre-selected project component(s)
4. Candidate skills from the master resume

You must return:
- EXACTLY {num_experiences} experience component(s)
- EXACTLY {num_projects} project component(s)
- The same components that were provided in the input
- Rewritten bullets only

The component selection has already been completed by another system.
Do NOT add, remove, merge, rename, reorder, or replace any experience or project.

=============================================================
NON-NEGOTIABLE RULES
=============================================================

1. Include every provided experience.
2. Include every provided project.
3. Preserve each component's metadata exactly:
   - id, if provided
   - title
   - company
   - location
   - dates
   - project name
   - project URL
   - tech stack

4. Do not invent facts.
5. Do not invent metrics.
6. Do not invent technologies.
7. Do not invent companies, products, users, scale, performance numbers, or business impact.
8. Use only information present in the provided resume components.
9. You may rewrite, shorten, reorder, or combine facts from bullets within the SAME component only.
10. Do not move facts between different experiences or projects.

=============================================================
JOB DESCRIPTION ALIGNMENT
=============================================================

Use the job description to decide which source bullets and phrases are most relevant.

You may:
- Emphasize truthful skills that match the JD
- Reorder bullets within a component by relevance
- Use JD-aligned language when it accurately reflects the source resume
- Condense long bullets while keeping the strongest technical signal

You may NOT:
- Add a JD keyword unless it is already supported by the source resume
- Exaggerate impact
- Convert coursework or projects into professional experience
- Claim production scale unless the source bullet supports it
- Add tools just because they appear in the JD

=============================================================
BULLET COUNT RULES
=============================================================

{_build_bullet_budget_section(bullet_budgets, num_experiences, num_projects)}

=============================================================
BULLET LENGTH RULES — STRICT
=============================================================

EVERY bullet must land in one of two valid zones. Lengths between the
zones produce orphan lines on the rendered page and are rejected.

VALID ZONE 1 — TWO FULL LINES (preferred — use this for most bullets):
- 180 to 213 characters
- A complete sentence with action + technical detail + outcome
- Use the master content fully. Multiple clauses are good.
- Example (198 chars):
  "Architected serverless dual-Lambda fan-out cutting pipeline runtime
  from 10 minutes to 30 seconds with Terraform-managed API Gateway and
  CloudWatch alarms across mission-critical workflows."

VALID ZONE 2 — ONE LINE (fallback — use only when content is genuinely sparse):
- 60 to 110 characters
- One tight, complete idea
- Use only when the master bullet truly has nothing more to say
- Example (52 chars): "Optimized read throughput 3x via MySQL replication."

INVALID — NEVER PRODUCE:
- 111 to 179 chars (wraps to 2 lines, line 2 almost empty — looks bad)
- 214 to 282 chars (wraps to 3 lines, line 3 almost empty — looks bad)
- Over 316 chars (overflow)

DEFAULT TO TWO FULL LINES. If the master content has multiple ideas,
metrics, or technical details, you should be writing 180-213 char bullets.
Only fall back to 1-line bullets when the master content is a single
tight idea that would be padded by stretching it longer.

Important:
- Strong specific facts > padded prose
- Do not invent metrics, tools, or claims to fill space
- Preserve all metrics from the master text exactly
- Mirror the JD's terminology where the master content allows

=============================================================
METRIC AND FACT PRESERVATION
=============================================================

Preserve exact numbers and metrics when you use them.

Examples of values that must remain exact:
- 10 minutes
- 30 seconds
- 36M+
- 100K
- 99.9%
- 92%
- 40%
- 60%
- sub-100ms
- p95
- 80k+ records
- 21,000 req/s
- $10M

You may abbreviate units only when meaning stays identical:
- minutes → min
- seconds → sec
- milliseconds → ms

Do not change the numeric value.
Do not round up.
Do not make weak numbers sound stronger.

=============================================================
WRITING STYLE
=============================================================

Good bullets should:
- Start with a strong action verb
- Be specific
- Mention relevant tools when truthful
- Show impact when the source supports it
- End cleanly, preferably on the metric or outcome
- Avoid vague phrases like "worked on", "helped with", "responsible for"

Avoid:
- Successfully
- Effectively
- Efficiently
- Various
- Several
- In order to
- Which resulted in
- By utilizing
- Cutting-edge
- Robust, unless technically meaningful
- Seamless, unless technically meaningful

Compression examples:
- "in order to" → "to"
- "which resulted in" → "achieving"
- "by utilizing" → "using"
- "minutes" → "min"
- "seconds" → "sec"

=============================================================
OUTPUT FORMAT
=============================================================

Return ONLY valid JSON.
Do not include markdown fences.
Do not include explanations.
Do not include comments.
Do not include extra text before or after the JSON.

The JSON must follow this structure exactly:

{{
  "experiences": [
    {{
      "id": "preserve input id if provided",
      "title": "preserve exact title from input",
      "company": "preserve exact company from input",
      "location": "preserve exact location from input",
      "dates": "preserve exact dates from input",
      "bullets": [
        "Rewritten bullet 1",
        "Rewritten bullet 2",
        "Rewritten bullet 3"
      ]
    }}
  ],
  "projects": [
    {{
      "id": "preserve input id if provided",
      "name": "preserve exact project name from input",
      "url": "preserve exact URL from input",
      "tech": "preserve exact tech stack from input",
      "dates": "preserve exact dates from input",
      "bullets": [
        "Rewritten bullet 1",
        "Rewritten bullet 2"
      ]
    }}
  ]
}}

If an input component does not include an id, omit the id field for that component.
If a project does not include a URL, use an empty string for "url".

=============================================================
JOB DESCRIPTION
=============================================================
{jd_text[:5000]}

=============================================================
PRE-SELECTED EXPERIENCES
=============================================================
{selected_exp_text}

=============================================================
PRE-SELECTED PROJECTS
=============================================================
{selected_proj_text}

=============================================================
CANDIDATE SKILLS FROM MASTER RESUME
=============================================================
{" | ".join(parsed_resume.skills.categories.values()) if parsed_resume.skills and parsed_resume.skills.categories else "No skills listed"}

=============================================================
FINAL CHECK BEFORE RESPONDING
=============================================================

Before returning JSON, verify silently:

1. Did you return exactly {num_experiences} experiences?
2. Did you return exactly {num_projects} projects?
3. Did each component get exactly the requested number of bullets?
4. Did you preserve all component metadata?
5. Did you avoid inventing metrics, tools, or claims?
6. Is every bullet either 60-110 chars (1 line) OR 180-213 chars (2 full lines)?
7. Did you DEFAULT to 2-line bullets where the master content supported it?
8. Did you ZERO bullets land in the orphan zones (111-179 or 214-282)?
9. Is the response valid JSON only?

Return the JSON now.
"""
    return prompt


def _build_bullet_budget_section(
    bullet_budgets: dict,
    num_experiences: int,
    num_projects: int,
) -> str:
    """
    Build the bullet count instructions for the prompt.

    If bullet_budgets is provided, generates exact per-component budgets.
    Otherwise falls back to generic rules.

    This function is fully dynamic — it uses component IDs and counts
    from the budget dict, never hardcoded names.
    """
    if not bullet_budgets:
        # Fallback: generic rules when no budget is computed
        return f"""For each EXPERIENCE:
- Return 2-3 bullets
- Prefer 2 bullets unless the experience is highly relevant

For each PROJECT:
- Return 1-2 bullets
- Use 2 bullets only for the most JD-relevant projects

Do not pad with weak bullets just to hit a count.
Total bullets across all experiences and projects should not exceed 13."""

    exp_budgets = bullet_budgets.get("experiences", {})
    proj_budgets = bullet_budgets.get("projects", {})
    totals = bullet_budgets.get("totals", {})

    lines = []
    lines.append("EXACT BULLET BUDGETS")
    lines.append("")
    lines.append("You MUST return exactly the specified number of bullets for each component.")
    lines.append("Do not return more or fewer bullets than specified.")
    lines.append("If a component has a 1-bullet budget, write the single strongest JD-relevant bullet.")
    lines.append("Do not pad with weak bullets. Do not remove components.")
    lines.append("")

    if exp_budgets:
        lines.append("Experiences:")
        for comp_id, count in exp_budgets.items():
            lines.append(f"- {comp_id}: exactly {count} bullet(s)")
        lines.append(f"- Total experience bullets: exactly {totals.get('experiences', '?')}")
        lines.append("")

    if proj_budgets:
        lines.append("Projects:")
        for comp_id, count in proj_budgets.items():
            lines.append(f"- {comp_id}: exactly {count} bullet(s)")
        lines.append(f"- Total project bullets: exactly {totals.get('projects', '?')}")
        lines.append("")

    lines.append(f"TOTAL BULLET BUDGET: exactly {totals.get('overall', '?')} bullets")
    lines.append("Do not exceed this total under any circumstances.")

    return "\n".join(lines)


def build_validation_repair_prompt(
    previous_json: dict,
    error_feedback: str,
    num_experiences: int,
    num_projects: int,
    bullet_budgets: dict = None,
) -> str:
    budget_section = _build_bullet_budget_section(
        bullet_budgets, num_experiences, num_projects
    )

    prompt = f"""
You are repairing a resume JSON output that failed validation.

Your task is ONLY to fix the validation errors listed below.
Do not improve, rewrite, reorder, or modify anything else.

=============================================================
VALIDATION ERRORS TO FIX
=============================================================
{error_feedback}

=============================================================
STRICT REPAIR RULES
=============================================================

1. Return exactly {num_experiences} experiences.
2. Return exactly {num_projects} projects.
3. Preserve all component metadata exactly:
   - id
   - title
   - company
   - location
   - dates
   - name
   - url
   - tech

4. Only modify bullets that caused validation errors.
5. Do not modify bullets that already passed validation.
6. Do not add new metrics.
7. Do not remove existing metrics unless absolutely required to meet length limits.
8. Do not invent tools, technologies, companies, or outcomes.
9. Do not remove components.
10. Do not add components.
11. Do not merge components.
12. Do not reorder components.

=============================================================
BULLET BUDGET
=============================================================

{budget_section}

If a component has too many bullets, remove the weakest or least JD-relevant bullets first.
If a component has too few bullets, split or rewrite from source facts without inventing new claims.
Preserve all components. Shrink bullet counts within components, never remove components.

=============================================================
BULLET LENGTH RULES — STRICT
=============================================================

Every bullet must land in one of two valid zones:

VALID — TWO FULL LINES (preferred):  180 to 213 characters
VALID — ONE LINE (fallback):          60 to 110 characters

INVALID — produces an orphan line:
- 111 to 179 chars  (line 2 mostly empty)
- 214 to 282 chars  (line 3 mostly empty)
- Over 316 chars    (overflow)

If a bullet in your previous response landed in an orphan zone, you must
fix it by EXPANDING to the 180-213 range (preferred) OR compressing to
≤110 chars. Use the master content fully to support 2-line bullets.

If a bullet was over 213 chars (or over 316 for experiences):
- Drop the weakest clause
- Remove filler words
- Preserve all metrics exactly
- Keep the strongest action + outcome

=============================================================
PREVIOUS JSON TO REPAIR
=============================================================
{json.dumps(previous_json, indent=2)}

=============================================================
OUTPUT FORMAT
=============================================================

Return ONLY valid JSON.
No markdown.
No explanations.
No comments.
No text before or after the JSON.

Return the repaired JSON now.
"""
    return prompt
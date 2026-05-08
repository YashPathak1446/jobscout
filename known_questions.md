# JobScout V3 — Known Questions

This doc tracks open architectural and design questions that have come up during
development. The goal is twofold:

1. **Nothing gets lost.** Questions raised mid-development don't disappear when
   we pivot to other work.
2. **Don't keep re-litigating.** Once a decision is made, it gets recorded
   here as resolved so we don't re-debate it three sessions later.

Every entry should answer: what's the question, why does it matter, what are
the options, and what (if anything) have we decided.

---

## How to use this doc

- **Active** — open questions we should think about before the next architectural decision
- **Resolved** — answered or decided, kept for posterity with the resolution
- **Out of scope** — explicit non-goals so we don't accidentally chase them

When a new question comes up mid-conversation, add it to **Active**. When we
make a decision, move it to **Resolved** with a short rationale and the date.
When we explicitly decide *not* to do something, put it in **Out of scope**.

---

# Active questions

## Q1. How does the profile generalize when there are different users?

**Status:** Partially answered, awaiting Phase 1 (auto-derivation refactor).

The current `yash_pathak.json` is hand-tuned with conditional triggers,
importance tiers, exclude keywords, etc. — none of which a real user would
write themselves.

The plan is for most fields to be **derived from the master resume** (tech
stack → conditional triggers, resume order → default importance, header
parsing → personal info), and only a small set of genuinely-personal fields
to come from a UI form (locations, visa status, target roles, exclude
keywords with sensible defaults).

The detailed taxonomy is in `migration_plan.md`. The implementation is
gated on Phase 1 (Step 7 in the master plan).

**Open sub-questions:**
- Should `component_importance` default to "high → medium → low" based on
  resume order? (Most people put their strongest project first.)
- Should `target_roles` be a multi-select (curated list, easier to filter)
  or free-form (more flexible)?
- For users with multiple resumes (different role types), how do we handle
  one-profile-per-resume vs. one-profile-with-multiple-resumes? Defer to
  Phase 5 (multi-user product).

---

## Q2. How do we handle PDF and DOCX as input formats?

**Status:** Open. Architectural commitment needed before Phase 2.

Current parser depends on LaTeX structure (`\emph{...}` for tech stack,
`\resumeProjectHeading{...}` for project headers). PDF and DOCX inputs lose
this structure — they produce plain text where tech stack might be
"Angular, TypeScript, Node.js" after a pipe character, in parentheses, or
not separated at all.

**Three options:**
- **Option A — Convert non-LaTeX to LaTeX.** LLM extracts structure from
  PDF/DOCX, converts to LaTeX, rest of pipeline unchanged. Costs tokens,
  prone to mis-extraction.
- **Option B — Switch trigger derivation to bullet-keyword extraction.**
  Throw away the `\emph{...}` shortcut, scan bullet text for known tech
  keywords. Works on any plain text. Bullets carry more semantic signal
  than the tech-stack header anyway.
- **Option C — Hybrid.** Use structured tech-stack if available (LaTeX),
  fall back to bullet extraction otherwise (PDF/DOCX). Two code paths.

**Tentative direction:** Option B. Multi-user is the goal, and a tiered
"works great for LaTeX, mediocre for PDF" UX creates regret later. Bullets
also carry richer signal than headers.

**Open sub-questions:**
- Where does the canonical `TECH_KEYWORDS` set live? Currently hardcoded
  in `resume_parser.py`. Should it auto-populate from each user's tech
  skills section?
- Difficult PDFs (two-column layouts, image-based text, weird fonts) need
  LLM-based extraction as fallback. When do we add that?

---

## Q3. How do bullet character limits actually work given the "fill the line" rule?

**Status:** Approximation in place (280/140 hard cap), proper solution
deferred to Step 14 (page-aware bullet allocation).

The Medium article's "Fill Bullet Lines All The Way" rule is fundamentally
a packing problem — bullets shouldn't have 2-3 words orphaned on line 2,
and the page should be filled efficiently. A character cap is a bad proxy
because different bullets render to different line counts depending on
word width, font metrics, and template.

**Current approach:** Hard cap at 280 chars (experiences) and 140 chars
(projects). This is an approximation that will produce orphan-line bullets
sometimes.

**Better approach (Step 12):** Replace hard cap with target zones:
- Single-line zone (≤ ~140 chars for experiences, ≤ ~100 for projects)
- Orphan-risk zone (~141-199 chars) — AVOID
- Two-lines-well-filled zone (~200-280 chars)
- Overflow zone (> 280 chars) — AVOID

**Best approach (Step 14):** Use real PDF rendering (pdflatex) to measure
actual line counts and line-2 word counts. Validator becomes mechanical
once Step 8 (PDF generation) is in place.

**Open sub-questions:**
- How do zone thresholds calibrate to your specific resume template? Need
  to render real bullets and measure.
- When the page is over-full, how does the system decide what to drop?
  (Currently bullet-budget allocator is count-based, not length-based.)

---

## Q4. Should we integrate Claude API for generation alongside Gemini?

**Status:** Investigation pending. Not on the critical path.

Claude Max gives chat access but not API credits — API is billed
separately at console.anthropic.com. Adding Claude to the pipeline would
be a pure quality/reliability play.

**Where Claude could plug in:**
- Embedding (Analysis): no — Claude has no public embedding API. Keep Gemini.
- Bullet tailoring (Generation): plausible — Claude Sonnet handles strict
  multi-rule prompts better than Gemini Flash, especially for the
  Golden Rules enforcement work in Step 11.
- Future: JD requirement extraction, cover letters, bullet quality grading.

**Cost math at current volumes:** Sonnet 4.6 = ~$0.024 per resume. At 10
resumes/day = ~$7/month. Cheap enough that cost isn't the deciding factor.

**Tentative direction:** Defer to Step 8.5 (multi-provider LLM
abstraction). Refactor generation calls behind a provider-agnostic
`tailor_with_llm()` interface. Add Claude as a third fallback after Gemini
2.5 → 2.0. When Step 11 (Golden Rules) lands, configure the main tailor
call to use Claude Sonnet (better instruction-following) and the cheaper
repair call to use Gemini Flash.

**Open sub-questions:**
- Is Claude's output meaningfully better on a few representative examples?
  Worth a 30-min investigation with the $5 free credits before committing
  to integration work.
- Multi-provider fallback chain order: prefer cost (Gemini → Claude) or
  prefer quality (Claude → Gemini)?

---

## Q5. How do we keep Gemini reliable when it 503s mid-run?

**Status:** Mostly handled, edge cases remain.

The current fallback chain is `gemini-2.5-flash → gemini-2.0-flash → mock`.
Mock fallback produces invalid output that fails validation, so the resume
ends up in `needs_review/` rather than the final outputs directory.

**Current behavior:** Pipeline doesn't crash on Gemini 503, but the
affected resume is unusable until you re-run.

**Open sub-questions:**
- Should the fallback include another real LLM (Claude) so we don't lose
  output to transient Gemini issues? See Q4.
- Should we add automatic retry with exponential backoff before falling
  back to a different provider?
- Should `needs_review/` resumes be auto-retried on the next pipeline run?

---

## Q6. How does the system handle very long master bullets?

**Status:** Working but fragile.

Your new master resume has bullets up to ~500 chars. Gemini compresses
these well (compression is easier than expansion), but occasionally drops
metrics during compression. The repair loop catches some of this but not
all.

**Open sub-questions:**
- Should the prompt explicitly list "preserve these metrics: [...]" with
  the metrics extracted from the master bullet? Would make compression
  more reliable.
- When the master bullet exceeds the validation cap, who's responsible
  for compression — the LLM (current) or a deterministic preprocessor?
- Does Step 11 (Golden Rules enforcement) need a "preserve quantitative
  data" rule on top of the article's nine rules?

---

## Q7. How do we ensure JD keyword matching against an 80+ entry tech skills section?

**Status:** Open. Bottleneck is the parser's `TECH_KEYWORDS` set.

The new resume has ~80 specific tools across 7 skill categories
(Languages, Backend, Frontend, Cloud, Databases, AI/ML, Dev Tools). When
the JD-side keyword extractor scans a JD for matches, it's bottlenecked
by what's in the hardcoded `TECH_KEYWORDS` set in `resume_parser.py`.

If a tool like "MineRL" or "Jasypt" or "EdgeShark" isn't in the set, JDs
mentioning those tools won't generate a keyword match — even though they
are in your resume.

**Tentative direction:** When Step 7 (auto-derivation) lands, the parser
should also auto-populate `TECH_KEYWORDS` from the user's tech-skills
section. Each user's skills become the keyword vocabulary the system
looks for in JDs.

**Open sub-questions:**
- Should the keyword set be per-user or shared/global? (Per-user is
  technically correct, global is simpler and may produce broader matches.)
- How do we handle ambiguous keywords like "Go" (language vs. preposition)
  or "C" (language vs. letter)? Current code uses word boundaries which
  helps somewhat.
- Should we use embedding similarity for "near-miss" matches (e.g., JD
  says "K8s", resume says "Kubernetes")? Adds complexity but catches more.

---

## Q8. How do output formats work (PDF, DOCX) once we add them?

**Status:** Phase 3 work. Architecturally clear.

PDF generation via `pdflatex` subprocess is well-understood. After each
`.tex` is written by Generation, run `pdflatex` and produce a `.pdf`
alongside. Requires LaTeX installed locally (MiKTeX on Windows, TeX Live
elsewhere) or a Docker container for the eventual web app.

DOCX output is much harder — needs a separate template system built with
`python-docx`, and a different prompt structure since LaTeX commands
(`\textbf{}`, `\emph{}`) don't translate. Probably not worth the effort
for v1.

**Tentative direction:** PDF in Step 8. DOCX deferred indefinitely until
a real user asks for it.

**Open sub-questions:**
- Where does pdflatex run for the eventual web app? Containerized
  server-side seems like the obvious answer.
- Should we ship a Dockerfile with the repo so users don't need to install
  LaTeX locally?

---

# Resolved questions

## R1. Should we use a synthetic john_doe profile for the public repo?

**Decision:** No (May 2026).

Originally proposed as a way to keep personal data out of the public
repo. Decided not to bother because:
1. The repo was already public with personal data committed
2. The example doesn't help current usage
3. Real privacy comes from `git filter-repo` history rewrite when the
   project goes public-public, not synthetic example files

The example pattern would be useful if/when the project becomes a real
product with multiple contributors. Not worth the maintenance burden now.

---

## R2. Should we hand-tune `exclude_keywords` to filter out wrong-fit jobs?

**Decision:** Defer until UI work. Keep current minimal list (May 2026).

We considered adding things like `"II"`, `"III"`, `"test engineer"`,
`"embedded"`, `"Salesforce"`, `"DevOps engineer"`, etc. to filter out
mismatched jobs early.

Decided against because:
1. Many of these (Salesforce, DevOps, SRE) are ambiguous — sometimes
   they're great jobs, sometimes they're wrong-fit
2. Hardcoding catered specifically to current-Yash based on a small
   sample (3 wrong-fit jobs out of 5)
3. The right place to handle this is the UI form, not hand-edited JSON
4. Step 3 (funnel filtering by score) handles the same problem more
   robustly — wrong-fit jobs naturally score lower in Analysis

The `exclude_keywords` list will be a UI checkbox group eventually, with
sensible defaults (`"senior"`, `"5+ years"`, `"PhD required"`,
`"security clearance"`) and user override.

---

## R3. Do we need Claude API integration in the current pipeline?

**Decision:** No, defer to Step 8.5 (May 2026).

Current Gemini setup is working. The repair loop handles validation
failures. The bottleneck is Discovery (wrong jobs) and output format
(no PDF), not generation quality.

Adding Claude would be valuable later for:
- Step 8.5: multi-provider fallback (reliability)
- Step 11: Golden Rules enforcement (quality on strict multi-rule prompts)

Worth a 30-min investigation with $5 free API credits before committing
to integration work.

---

# Out of scope

## OOS1. DOCX output format

We're not building DOCX output unless a real user requests it. PDF covers
99% of use cases. DOCX adds significant complexity (separate template
system, different prompt structure, no LaTeX command translation) for
marginal benefit.

## OOS2. LinkedIn scraping (without paid service)

LinkedIn aggressively blocks scraping. We're not building bespoke
anti-bot logic. When LinkedIn becomes a discovery source, it'll be
through a paid service (Bright Data, ScrapingBee, RapidAPI, or similar).

## OOS3. Resume design / formatting customization

The system uses one LaTeX template (`jakes_resume`). We're not building
a template-picker, font-customizer, or color-themer. The Medium article
explicitly excludes formatting concerns ("Most students have decent
resume formatting"). Stay focused on content quality.

## OOS4. Auto-applying to jobs

Generating a resume is the deliverable. The system does not submit
applications, log into job portals, or fill out application forms.
Those involve credentialing, captchas, ToS issues, and per-employer
custom flows that are outside this project's scope.

---

# Meta: maintaining this doc

- Add new questions to **Active** as they come up
- When making a decision, move the question to **Resolved** with rationale + date
- When deciding something is *not* a goal, put it in **Out of scope**
- Don't delete entries — kept for posterity / future re-evaluation
- Review **Active** at the start of each new working session to remember context
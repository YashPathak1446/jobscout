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

**Status:** Largely answered (see R6). Page-aware allocation still deferred.

The original question — "how do we enforce orphan-line avoidance without
forcing the LLM to be a calculator" — has been answered architecturally
by R6 (deterministic post-LLM compression). The validator now uses zones
(line-1, line-2, line-3) instead of single hard caps, and the bullet-fit
pipeline compresses overshoots into the nearest good zone.

What remains open is **page-aware allocation** — given a known set of
bullets and their rendered line counts, how does the system decide how
many bullets per component to fit on a 1-page resume? Currently the
budget allocator is count-based (e.g. "this experience gets 3 bullets")
without knowing how many lines those bullets will occupy.

This becomes solvable once PDF generation is in place (Step 8). With
pdflatex available, we can measure actual rendered line counts and adjust
budgets to fit the page.

**Unblocked by R8 (August 2026).** PDF generation now runs in-pipeline, so
rendered output is measurable for the first time.

**Measured headroom** (trial compiles that append synthetic 2-line bullets
until the page spills):

| Resume | Components | Bullets | Headroom |
|---|---|---|---|
| IDT | 3 exp, 3 proj | 12 | **2 bullets** |
| Julius AI | 3 exp, 4 proj | 13 | **0 — at capacity** |

So under-fill is real but resume-dependent, not systematic. The allocator
hits its own budget tables exactly (6 exp / 7 proj) — there is no allocation
bug. The tables are simply conservative in the 3-project case.

*Correction:* an earlier eyeball estimate in this doc claimed the Julius AI
page was ~85% full with an inch of dead space. That was wrong — it has zero
headroom. Screenshots are not a measurement.

**Method note, worth keeping.** `\pagetotal / \pagegoal` read out of the .log
is *not* a reliable fill metric. It reported 99.1% for the IDT resume that
had room for two more bullets, because the template's vertical glue is
stretchable and TeX absorbs the difference. Only a trial compile that
actually spills tells the truth. Any future page-aware allocator has to
measure, not predict.

**Half-solved by R9.** The inverse failure — a resume rendering to two pages
— is now caught and demoted to needs_review. Filling headroom when it exists
is still open.

Remaining options for filling it:
- **Over-ask and trim.** Ask the LLM for ~2 extra bullets, then drop the
  lowest-priority ones via trial compiles until it fits one page. Follows
  R6's split (LLM writes content, Python handles fitting) and costs extra
  output tokens rather than extra API calls.
- **Predict from a calibrated line model.** Rejected for now — the glue
  finding above shows prediction is unreliable here.

Deferred until live-run data across more resumes shows how often headroom
actually appears.

**Open sub-questions:**
- Should `SUBSTANTIVE_MIN = 60` be raised for experiences? Some compressed
  experience bullets at exactly 60 chars feel skeletal.
- When compression can't reach a good zone (rare — see R6 caveats), should
  we add an "expand from master content" step, or accept needs_review?
  Decided: accept needs_review for now. Expansion risks invention.

---

## Q4. Should we integrate Claude API for generation alongside Gemini?

**Status:** More urgent than before. Q5's quota issue makes Claude
fallback meaningfully valuable, not just nice-to-have.

Claude Max gives chat access but not API credits — API is billed
separately at console.anthropic.com.

**Where Claude could plug in:**
- Embedding (Analysis): no — Claude has no public embedding API. Keep Gemini.
- Bullet tailoring (Generation): plausible — Claude Sonnet handles strict
  multi-rule prompts well. Less critical now that R6 removed strict-numerical
  constraints from the LLM's job, but still useful for quality.
- **Fallback for quota exhaustion:** when Gemini 2.5 and 2.0 are both
  rate-limited, current behavior is "fall back to mock and fail." Adding
  Claude as a third fallback would mean the resume gets generated anyway.

**Cost math at current volumes:** Sonnet 4.6 = ~$0.024 per resume. At 10
resumes/day = ~$7/month. Cheap enough that cost isn't the deciding factor.

**Tentative direction:** Defer to Step 8.5 (multi-provider LLM
abstraction). Refactor generation calls behind a provider-agnostic
`tailor_with_llm()` interface. Add Claude as a third fallback after Gemini
2.5 → 2.0. Quality-vs-cost ordering decided per-call.

**Open sub-questions:**
- Is Claude's output meaningfully better on a few representative examples?
  Worth a 30-min investigation with the $5 free credits before committing
  to integration work.
- Multi-provider fallback chain order: prefer cost (Gemini → Claude) or
  prefer quality (Claude → Gemini)?
- Should the fallback be silent (just use Claude when Gemini 429s) or
  surface to the user ("Gemini quota out, used Claude for this resume")?

---

## Q5. How do we keep Gemini reliable when it 503s or runs out of quota?

**Status:** Mostly handled at the failure-mode level, but quota
exhaustion is a real production issue we've now hit.

The current fallback chain is `gemini-2.5-flash → gemini-2.0-flash → mock`.
Mock fallback produces invalid output that fails validation, so the resume
ends up in `needs_review/` rather than the final outputs directory.

**What we've observed:**
- **503 errors** (May 2026): Gemini service hiccups happen mid-pipeline.
  Pipeline doesn't crash — it falls through to the next model, then mock.
  Resume goes to needs_review.
- **429 errors / quota exhaustion** (May 2026): Free-tier Gemini has daily
  caps. During heavy development sessions, we exhaust the cap mid-run.
  Both 2.5 and 2.0 share quota, so both fall through to mock together.

**Current behavior:** Pipeline doesn't crash on either failure mode,
but the affected resumes are unusable until quota resets or service
recovers. With the `--input` replay flag, you can rerun Generation later
without paying for Discovery/Enrichment/Analysis again.

**Open sub-questions:**
- Should the fallback include another real LLM (Claude) so we don't lose
  output to transient or quota issues? See Q4.
- Should we add automatic retry with longer exponential backoff before
  falling back to a different provider? Current retry waits ~30-60s
  which isn't enough for quota recovery (resets daily).
- Should `needs_review/` resumes be auto-retried on the next pipeline run?
  Could be a `--retry-needs-review` flag.
- Should we surface a "quota nearly exhausted" warning before starting
  Generation, so the user can choose to defer? Hard to predict cleanly
  without an explicit quota-check API call.

---

## Q6. How does the system handle very long master bullets?

**Status:** Working but fragile.

The new master resume has bullets up to ~500 chars. Gemini compresses
these well (compression is easier than expansion), but occasionally drops
metrics during compression. The repair loop catches some of this but not
all. The R6 bullet-fit pipeline runs after the LLM and can compress
further deterministically if needed.

**Open sub-questions:**
- Should the prompt explicitly list "preserve these metrics: [...]" with
  the metrics extracted from the master bullet? Would make compression
  more reliable.
- When the master bullet exceeds the validation cap, who's responsible
  for compression — the LLM (current) or a deterministic preprocessor?
  Currently both run; LLM goes first, fitter cleans up. Mostly works.
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

## Q8b. Where does pdflatex run once this is a web app?

**Status:** Open, but not urgent — local compilation works (R8).

R8 solved PDF generation for the local CLI by shelling out to a locally
installed pdflatex. That doesn't survive the move to a hosted app: you can't
ask a web user to install MiKTeX.

**Options:**
- **Containerized server-side.** Ship a Dockerfile with TeX Live installed,
  compile in the container. Obvious answer, but a full TeX Live image is
  ~4GB (`texlive-latex-extra` trims it to roughly 1GB).
- **A LaTeX-as-a-service API.** Removes the ops burden, adds a dependency
  and a per-compile cost.
- **Client-side WASM** (e.g. SwiftLaTeX). No server cost, but a large
  initial download and a narrower package set.

**Tentative direction:** containerized, with a trimmed TeX Live. Defer until
there's an actual deployment target.

**Open sub-questions:**
- Should we ship a Dockerfile now so contributors don't need local LaTeX,
  even before there's a web app?

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

**Validated by R7 (May 2026):** with a wider discovery pool, DICK'S
"SE II" — the case that motivated this discussion — naturally fell to #6
in the funnel instead of winning a top-3 slot. The mechanism works.

---

## R3. Do we need Claude API integration in the current pipeline?

**Decision:** No immediate need, but raised priority after Q5 quota issues
(May 2026). Defer to Step 8.5.

Current Gemini setup is working when quota is available. The repair loop
handles validation failures. The architectural bottleneck is reliability
(Q5), which Claude as a third fallback would meaningfully improve.

Adding Claude would be valuable for:
- Step 8.5: multi-provider fallback (reliability when Gemini 429s — now
  a real-world issue, not just hypothetical)
- Step 11: Golden Rules enforcement (quality on strict multi-rule prompts)

Worth a 30-min investigation with $5 free API credits before committing
to integration work.

---

## R4. Sync profile component IDs to new master resume

**Decision:** Done (May 2026).

After resume rewrite produced new project IDs, profile referenced 6
ghost IDs and was missing 4 new ones. Hand-fixed:
- Renamed jobscout, image_to_3d, sleeptracker_mobile to match parser output
- Removed deleted projects (breast_cancer, checkers, classification_diabetes)
- Added jobscout_multi_agent_resume_tailoring (high),
  ml_based_antibiotic_resistance_predictio (medium with bio/ML triggers)
- Fixed always_include aliases (exp_sorenson → exp_sorenson_communications)

Verified with mock pipeline: zero "Could not resolve" warnings,
JobScout now scores with imp=0.15 instead of 0.05.

Note: this hand-edit is exactly what auto-derivation (Phase 1, Step 7
in master plan) is meant to eliminate. When Phase 1 lands, this kind
of manual sync goes away.

---

## R5. Should we add `--max-resumes` to control which jobs get resumes?

**Decision:** Done (May 2026).

Added `--max-resumes N` CLI flag. After Analysis, jobs are sorted by
overall score and only the top-K reach Generation. K defaults to
`profile.agent_preferences.max_jobs_to_generate` (10).

Rationale: Generation is the expensive stage (1-2 Gemini calls per
resume). Wrong-fit jobs that sneak past Discovery filtering used to
still get resumes; now they don't unless they score in the top-K.

Caveat: Score-based funnel ranks by JD-resume fit, not applicability.
A wrong-fit job (e.g., "SE II" requiring 1+ years) can still score
high if its tech stack matches your resume. Real fix is larger
discovery pool (R7) so good-fit jobs outrank these, plus eventual
UI-driven exclude_keywords (deferred per R2).

---

## R6. How should bullet length compliance work?

**Decision:** Done (May 2026). Deterministic post-LLM compression, not
strict LLM prompting.

We went through multiple approaches in one session:
1. **Original:** Single hard cap (280 chars experiences, 140 chars projects).
   Allowed orphan-line bullets where line 2 had ~6 chars used. Looked bad.
2. **Detour 1 — zone validator only:** Added orphan-zone detection. LLM
   was asked to "compress to ≤110 OR expand to 180-213." Gemini Flash
   couldn't comply precisely (missed by 7-13 chars consistently).
3. **Detour 2 — prompt-only fix:** Rip out the fitter and just ask
   harder. Resulted in 0/3 valid (Gemini overshot to 228-270 chars,
   the model is bad at numerical ranges regardless of prompt clarity).
4. **Final design:** Separate content generation (LLM) from length
   compliance (deterministic Python). LLM writes good bullets; a
   compression library (`bullet_compress.py`) applies safe transformations
   in priority order until the bullet lands in a valid zone.

**Implementation:**
- `tools/generation/bullet_compress.py` — 4-tier library: whitespace
  cleanup, verbose-phrase substitutions, conservative article drops,
  trailing-clause drop. All pure functions.
- `tools/generation/bullet_fit.py` — picks target zone based on current
  zone, calls compress with that target.
- `validation.py` — zone-based validation with surgical error messages
  for any bullet that still misses after fitting.
- `prompt_builder.py` — prompt asks for 2-line bullets by default,
  1-line fallback for sparse content. Doesn't demand precise char counts.
- `generation_agent.py` — runs `_apply_bullet_fitting` after each LLM
  call (main + repair).

**Verified:** When Gemini responds (i.e., not 429'd), the system produces
valid resumes. Fitter catches LLM overshoots (228→206 chars) and
undershoots (compress 145→82 to line-1). Provider-agnostic — works
regardless of which LLM produced the text.

**Caveats:**
- Very short master content (e.g. tutor.com bullets at ~80 chars) can't
  expand to 2 lines without inventing. Those flow to needs_review.
- Compression dictionary is hand-curated; covers common patterns but
  not all. Expandable when needed.

---

## R7. Should Discovery scrape a wider candidate pool?

**Decision:** Done (May 2026).

Old behavior: Discovery short-circuited as soon as `len(self.all_jobs) >=
max_jobs` (the CLI flag, usually 10-20). This meant Discovery and
Generation were bottlenecked by the same constraint, and the funnel
(R5) had almost nothing to work with.

New behavior: Discovery scrapes up to **200 candidates** (hardcoded
`DISCOVERY_POOL_TARGET`), filters by profile criteria, ranks the pool,
then slices to `max_jobs` at the very end.

**Changes:**
- `search_github_newgrad`: `max_results` bumped from 50 to 200
- `discovery_agent`: pool target replaces the old max_jobs gate
- Adzuna/Serper internal gates bumped 50 → 200
- `search_github_newgrad`: parses "posted X days ago" from markdown
  (`0d`, `5d`, `2 days ago`, `1 month ago`) into a real timestamp
- `discovery_agent` ranking: recency-adjusted score =
  `base_score - min(days_old, 14) * 0.5`. Recent jobs win ties; older
  jobs get a small penalty (capped so a great old job still beats a
  mediocre new one).

**Verified end-to-end (May 2026):**
- GitHub returned 724 candidates (was 452 — even the underlying source
  has more we weren't reading)
- 192 passed filtering
- Top-3 funnel picks were all genuinely good fits (Neuberger, CVector,
  Etched — full-stack Python new-grad roles)
- DICK'S "SE II" — the wrong-fit job that previously won a top-3 slot —
  fell to #6, validating R2's bet that funnel + bigger pool removes the
  need for hand-tuned exclude_keywords

Generation didn't complete during the test run due to Gemini quota
exhaustion (Q5), but the one Gemini call that succeeded (Neuberger)
behaved as expected with the fitter from R6.

---

## R8. Should Generation compile PDFs, and how?

**Decision:** Done (August 2026). In-pipeline `pdflatex` subprocess, with a
graceful skip when no LaTeX toolchain exists.

Answers the PDF half of the old Q8. DOCX stays out of scope (OOS1).

**Implementation:**
- `tools/generation/pdf_builder.py` — standalone compile layer. Returns a
  `PdfResult` with status `ok` / `skipped` / `failed` / `timeout`, and never
  raises, so one bad resume can't kill a batch.
- `find_pdflatex()` checks PATH, then the default install dirs. This turned
  out to matter: MiKTeX's per-user install puts the binary in
  `%LOCALAPPDATA%\Programs\MiKTeX\miktex\bin\x64` and leaves it off PATH.
- MiKTeX gets `--enable-installer`, because a Basic install lacks `titlesec`
  and `marvosym` and would otherwise open a GUI prompt and hang the
  subprocess until the timeout.
- Reruns only when the log asks (`Rerun to get...`), latexmk-style. hyperref
  writes its `.out` bookmark file during pass one, so pass one emits a PDF
  with no outline. Capped at 2 passes.
- Aux files (`.aux`, `.log`, `.out`, ...) are cleaned up after each compile.
- `--no-pdf` on both the orchestrator and generation-agent CLIs.
- needs_review files get compiled too — a rendered PDF is usually the
  fastest way to see what's wrong with one.

**Verified (August 2026), MiKTeX 25.12:**
- Both real Aug-20 resumes compile clean: 1 page, `%PDF-1.5`, ~110KB, 1.2s
  for two passes. Visual check of the Julius AI resume confirms the template
  renders correctly — header links live, all sections intact.
- Mock pipeline: 3/3 compiled, no aux litter.
- Pre-install, the same code path logged a warning and wrote `.tex` only —
  the degradation path works, which is what makes this safe to leave on by
  default.

**Still open (moved to Q8b):** where pdflatex runs for the eventual web app,
and whether to ship a Dockerfile.

---

## R9. Should generation enforce a one-page limit?

**Decision:** Yes. Done (August 2026).

Until PDF generation landed (R8) there was no way to know how many pages a
resume rendered to. Validation is content-based — bullet counts, character
zones, metric preservation — and none of that sees layout. A two-page
new-grad resume would have shipped silently as "valid".

**Implementation:**
- `PdfResult.pages`, read from the log's "Output written ... (N pages)" line.
  Whitespace is flattened before matching because pdflatex hard-wraps the log
  at ~79 columns and routinely splits that line in half.
- After compiling, a resume that validated clean but renders to more than one
  page is demoted to needs_review, with an explicit validation error saying
  so. `_demote_to_review()` moves both the .tex and the .pdf, since both are
  already written by the time we can measure them.
- Resumes already heading to needs_review are left alone — no point demoting
  twice.

**Verified:** a known-good resume reports `pages=1`; the same resume with one
synthetic bullet appended reports `pages=2`. The move helper was tested for
both the with-PDF and no-PDF cases.

**Note:** mock-mode resumes render to two pages, because mock tailoring
ignores the bullet budgets entirely. That's a mock artifact, not a
regression — they already fail content validation for other reasons.

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
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

# Roadmap — what is left, in order

Rewritten 2026-08-21 after deciding the product shape: **a local app where
each user brings their own Gemini API key.** That decision reorders
everything below, so it is recorded first.

## The decision, and why

Free-tier Gemini quota is per key, not per user. A hosted app routes every
user's generation through one key; twenty active users would exhaust the
daily cap before noon, and the LLM cache cannot help because every user's
prompts contain their own resume. R10 solved dev-time quota burn and does
nothing for concurrent strangers. Against a zero-spend constraint, that rules
out hosting on our key.

The tempting middle option — a hosted app where users paste their key — is
the worst choice available. It keeps every multi-tenant namespacing problem
from Q15 *and* adds custody of other people's API credentials, which is a
security posture a solo maintainer should not want.

Local-first dissolves three problems at once:
- **Q15 items 1–3 evaporate.** One user per instance means the single-file
  embedding cache, the global job cache and the date-only output paths stop
  colliding. No `user_id` threading needed.
- **Q8b evaporates.** pdflatex is on the user's machine.
- **Key custody evaporates.** The key lives in their `.env`, never ours.

This also answers Q15's tenancy question: **single-tenant per instance.** A
hosted paid tier later becomes an addition rather than a rewrite — the
pipeline is identical, only the key's origin changes.

## 0. Baseline durability — DONE (2026-08-21)

Every scoring claim in this doc rests on
`baselines/2026-08-21-pre-step7/`, which is gitignored and existed on one
machine. That is R12's lesson repeating: something load-bearing, invisible
from inside the repo.

Content still stays out of git — it holds employer names and whole resumes.
What is committed is a manifest of checksums and record counts, so a lost or
altered baseline is **detectable rather than silent**, plus
`scripts/baseline.py` to write, verify and archive one. `verify` exits
non-zero, so it can gate a measurement run. See `baselines/README.md`.

## 1. Fix the template ghost rule, and check for its whole class — DONE (2026-08-21)

**Done — see R17.** It was five ghost IDs in the template, not one, and two
of them sat in `always_include`, the +0.30 term. `find_unresolvable_ids()`
now checks every ID-keyed field through the parser's own resolution, called
from the orchestrator and from `init_profile.py`. A correction came with it:
Q14's claim that `exp_outlier` and `exp_tutor` never fired was wrong — they
resolve by prefix matching. And `rarely_include` turned out to be dead code
entirely, which is now Q16.

The original entry follows.

### Original

`user_profiles/template.json` ships a `conditional_inclusion` rule keyed to
`exp_healthcare_company` — a component that exists in nobody's resume. Since
`init_profile.py` copies the template wholesale, **every bootstrapped profile
inherits a dead rule.**

This is the third instance of one bug: a rule keyed to a component ID that
does not resolve, silently never firing. The others are `exp_outlier` and
`exp_tutor` in the live profile (see Q14). Three occurrences means the fix is
not another one-time correction — **add a validation that every
`conditional_inclusion`, `rarely_include`, `always_include` and
`never_include` key resolves to a real parsed component**, and warn loudly
when one does not. A rule that cannot fire should never be silent.

*Why first:* it is in the onboarding path, so it affects every future user,
and it is cheap. Bugs that scale with users outrank bugs that affect one.

## 2. The verification run — DONE (2026-08-22)

Replayed the frozen baseline through current code (20 JDs analysed, top 3
generated), then read the PDFs.

**The instrument is validated end to end.** The live run changed exactly
**8/20** selections — the same eight JDs, with the same swaps, that the
offline reconstruction predicted. Analytical measurement and real behaviour
agree completely, which is what makes the rest of the roadmap's
measure-first approach trustworthy.

**Output is sound.** Three resumes, all one page, none demoted to
needs_review, all with PDFs.

**The swaps hold up.** Samsara dropping a UX-redesign project from a backend
resume is the clear win R14 was aimed at. The Palantir case looked
questionable on a skim — the incoming RunKeeper project's bullet reads
frontend-flavoured — but the numbers say otherwise: it won on embedding
(0.597 vs 0.576) *and* keyword (0.25 vs 0.13) with **zero** trigger hits,
while Spotify's single incidental `typescript` match no longer carries it.
That is precisely the behaviour R14 was built for.

**One marginal case.** Ramp (Mobile Engineer, Android) swapped
`spotify_music_browser` for `search_engine` on a **0.017** margin, decided by
the keyword term against the embedding's preference. The mobile project is
correctly retained with a full 3-hit bonus. Defensible, but a coin flip.

**Two findings the metrics could not have surfaced** — see the Q3 addition
below and Q17.

## 3. Fix the `java` / `javascript` substring bug — DONE (2026-08-22)

**Done — see R18.** The `java`/`javascript` case was the least of it: the
JD-side extractor had no word boundaries at all, so `ai` matched "email" and
"training", `rag` matched "coverage" and "storage", and `go` matched
"government" — in essentially every JD. Measured at 6/20 selections changed.
A fresh baseline is due after item 5.

The original entry follows.

### Original

`_extract_keywords` matches by substring above three characters, so every
JavaScript mention also credits Java.

*Why before item 5, and why the earlier reasoning for that was wrong.* It was
argued that trigger derivation would be "built on a broken matcher". That is
not true: triggers are matched by `_trigger_matches`, which applies word
boundaries — `\bjava\b` does not match "javascript". Verified directly.

The real risk is narrower and worse. If derivation *harvests* candidate
triggers through `_extract_keywords`, a JavaScript project acquires `java` in
its trigger list, and that trigger then matches Java JDs with perfect
word-boundary correctness. Nothing downstream looks wrong. The bug would
corrupt the derived vocabulary, not the matching.

Two ways out: fix the bug first, or harvest from the tech stack by
comma-split so `_extract_keywords` never enters the path. The second makes
this optional for item 5 — but the keyword score term is still wrong on its
own merits, so it wants fixing either way, with the usual measurement.

## 4. Give the tests a home (Q12) — DONE (2026-08-22)

**Done — see R19.** `tests/`, stdlib unittest, 58 tests covering keyword
matching, bullet compression and fitting, profile derivation, and PDF
compilation. No new dependency, and no LaTeX needed to run it.

The original entry follows.

### Original

Minimal, not a suite: move the existing `pdf_builder` self-check into
`tests/` and add `bullet_compress` and `bullet_fit`, which are pure and
deterministic.

*Why above the scoring changes rather than below:* the previous version of
this roadmap said "everything above changes scoring, which is exactly when a
regression net earns its keep" while scheduling tests underneath three
scoring changes. That argument does not survive its own placement.

## 5. Derive `conditional_inclusion` — the product blocker

The last DERIVED field still hand-authored, and the only item here that
stands between the current state and something usable by someone else.

R14 measured that removing conditionals changes **12/20** selections. A
bootstrapped user gets an empty conditional map, so they receive meaningfully
worse component selection than the hand-tuned profile does, with no way to
fix it short of writing JSON they would never write. **Shipping a UI before
this means shipping a product that works well for exactly one person.**

Implement `migration_plan.md`'s algorithm as written and measure it. R14
unblocked it: under all-or-nothing scoring, derived triggers like `angular`
would have fired on every JD and destroyed the term's ability to
discriminate. Under hit-count scoring, three matching stack terms earn the
full bonus and a passing mention earns 0.07 — which is the behaviour wanted.

## 6. Make the API key injectable

`os.getenv("GOOGLE_API_KEY")` is read at five sites, including inside
`_call_gemini_json` and the embedding scorer.

*Why before the UI:* fine for a CLI, wrong the moment a UI collects the key
from a user. Threading it through as a parameter is small now and invasive
once a UI exists — the same argument as R11's cache guard.

## 7. Decide the pdflatex distribution story — before designing screens

Asking a non-technical user to install MiKTeX is probably fatal to adoption.
The options are bundling a TeX distribution, falling back to `.tex`-only
downloads, or an Overleaf handoff.

*Why ahead of the UI rather than after:* this is not a fallback to bolt onto
a finished results screen. If a meaningful share of users have no LaTeX, the
download UX is `.tex` plus a handoff — **a different screen**, not a disabled
button. Deciding after item 8 means redesigning it.

Note `find_pdflatex()` already exists (R8) and detects this reliably.

## 8. The UI

Three screens for an MVP, not the six `migration_plan.md` sketches: resume
upload (`init_profile.py` does the work), key entry plus the fields
derivation deliberately skips (location, visa status), and job preferences.
The importance editor can wait, since R15 derives defaults.

Then run, stream progress, show scored jobs, offer downloads. Mostly a
wrapper over the existing orchestrator.

**Surface failures.** Quota exhaustion, missing key, absent LaTeX all
currently log and degrade — invisible in a browser tab. This is where
`classify_api_error`'s four buckets earn their keep.

**A `doctor` command is worth more than an install script.** Checks Python
version, dependencies, key present and valid, pdflatex present, profile
validates, resume exists. `check_models.py` is already half of one and
`find_pdflatex()` is the other half. An installer's logic goes stale every OS
release; a doctor's does not. It also gives item 7's detection a home.

## Deferred — not blocking a working product

- **Derive `rarely_include`** from the importance map. Small; folds naturally
  into item 1's validation work.
- **INTERNAL cleanup** — five profile fields that should be code constants.
  Every one removed is one less thing in a new user's profile.
- **Q9** — `gemini-embedding-001` is past its shutdown date and still
  serving. R11 made the cache model-aware, so the dangerous part is handled.
- **Q10** — clearance-gated employers. Needs investigation before
  implementation; it is not yet known whether the JD stated the restriction.
- **Q3** — page headroom. Measurable, but wants live-run data on how often
  headroom appears before spending LLM output on bullets that may be trimmed.
- **Q2** — PDF and DOCX resume input. Large, and the architectural choice is
  still open.
- **USER-INPUT fields** — six that need a UI before they stop being
  hand-edited JSON. Item 8 covers three of them.

## Not scheduled

**Q6** — long master bullets. Working but fragile, no recent failure.
Building a metric-preservation checker before seeing a failure on
gemini-3.5-flash is the speculative work this doc otherwise avoids.

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
- ~~Should `component_importance` default to "high → medium → low" based on
  resume order?~~ **Answered yes, August 2026 — see R15.** The hunch held:
  importance decreases monotonically with position, 17 of 18 components. The
  boundaries (top-2 high, next-4 medium) were picked by measurement.
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

**The allocation shape, not just the total (found 2026-08-22).** Reading
real output surfaced something the headroom measurements missed. Both
verified resumes allocate **3/2/1 bullets across experiences and 2/2/2/1
across projects** — the last item in each section always gets one. And both
pages have **zero headroom**, so this is not wasted space; it is how the
budget is divided.

The effect is a one-line tail. Uber's fourth project (Diagnosify) and
Palantir's (RunKeeper Tweet Analyzer) each contribute a single bullet at the
bottom of the page, reading as filler rather than evidence. The open question
is whether a fourth project earning one line beats a third project earning
two, or a fuller experience section. That is a different question from "is
there headroom" and probably a more valuable one, since it applies even when
the page is full.

**Open sub-questions:**
- Should `SUBSTANTIVE_MIN = 60` be raised for experiences? Some compressed
  experience bullets at exactly 60 chars feel skeletal.
- When compression can't reach a good zone (rare — see R6 caveats), should
  we add an "expand from master content" step, or accept needs_review?
  Decided: accept needs_review for now. Expansion risks invention.

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

**Status:** Mechanism shipped (August 2026). Two sub-questions still open.

`build_tech_vocabulary()` unions the curated `TECH_KEYWORDS` base with every
tool in the user's own skills section — 91 → 135 for this resume, picking up
all 45 skills that were previously invisible to JD matching (Figma, Ionic,
Capacitor, Jasypt, EdgeShark, Biopython among them). Union rather than
replace, which answers the "per-user or global?" sub-question below: both.
Component keywords are recomputed against the augmented vocabulary so the
two sides of the comparison use the same words.

**Measured effect on selection: zero.** Against the frozen 20-JD baseline
the expansion changed no selections, and JD keyword matches rose only +0.5
per JD on average. These are new-grad backend and full-stack roles that
simply do not mention the added tooling. The gap was real and is now closed,
but it will only move outcomes on mobile- or design-adjacent JDs. Recorded
here so nobody re-opens this expecting a scoring win.

**A regression shipped and was fixed (August 2026).** The first version of
this change recomputed component keywords from `tech + bullets`, while the
parser builds them from `title + company + bullets` for experiences and
`name + tech + bullets` for projects. Narrow but real: `exp_101gen_ai` and
`exp_ai_ensured` lost the keyword `ai`, which appears only in the employer
name and never in a bullet. Both sites now call the shared
`keyword_source_text()`, so the two definitions cannot drift again — the
duplication was the actual defect, the lost keyword only its symptom.

Re-measured afterwards with the exact instrument: the vocabulary expansion
still changes **0/20** selections. The original null result holds.

**Still open:**
- `_extract_keywords` matches by substring above 3 characters, so **`java`
  matches inside `javascript`**. Every JavaScript mention credits Java.
  Fixing it means word boundaries everywhere — a broad scoring change, see
  Q14.
- Near-miss matching ("K8s" vs "Kubernetes") is still unaddressed.

Original entry follows.

**Status (original):** Open. Bottleneck is the parser's `TECH_KEYWORDS` set.

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

## Q9. When do we migrate off gemini-embedding-001?

**Status:** Open. Not urgent, but on borrowed time.

`gemini-embedding-001` passed its listed shutdown date of 2026-07-14 and is
**still serving** — confirmed by live probe on 2026-08-20. Google's
deprecation page states listed dates are the *earliest possible* retirement
dates and that they notify before pulling an endpoint. So there's no
emergency, but there's no guarantee either, and R10's lesson applies in
reverse: the listing said one thing and reality said another.

`gemini-embedding-2` is GA and visible under the current key.
`tools/resume/embedding_scorer.py` is the only call site.

*Correction (August 2026):* this entry originally said `EMBEDDING_MODEL` in
`config.py` was "already the single point of change". It wasn't — the call
site hardcoded `"gemini-embedding-001"` and never read the constant, so
editing `config.py` would have changed nothing while looking like it had.
Fixed alongside R11; the constant is now actually wired through.

**Why this isn't a one-line swap:**
- A different embedding model almost certainly means different vector
  dimensions, invalidating every cached embedding.
- Full cache rebuild is 18+ resume components plus every JD — a real quota
  hit in one session.
- Similarity scores shift, so the tuned `scoring_threshold` and the
  component-selection behaviour both need re-validation. Analysis output
  could change meaningfully, and that propagates into which jobs get resumes.

**Open sub-questions:**
- ~~Should the embedding cache key include the model name?~~ **Done
  (August 2026)** — see R11. Added ahead of the migration rather than during
  it, since a cross-model cache hit is a silent correctness bug, not an
  error.
- Migrate proactively, or wait until 001 actually 404s? Waiting means the
  pipeline breaks mid-run at an unpredictable time. Proactive means spending
  quota and re-validating scoring on our own schedule.
- Can we compare 001 vs 2 rankings on the same JD set before committing?
  Needs both embedded, which doubles the cost of the test.

---

## Q10. Should Discovery filter out clearance-gated employers?

**Status:** Open. Surfaced 2026-08-20.

A generation run replaying May analysis put "Associate Software Engineer" at
Innovative Defense Technologies (IDT) in the top 2. IDT is a defense
contractor; roles there are near-universally gated on US citizenship and
often an active security clearance.

`job_preferences.citizenship_restrictions` exists for exactly this and did
not catch it. Unknown which is true:
- The JD stated the restriction and the filter didn't match the phrasing
- The restriction was buried somewhere Enrichment didn't scrape
- The JD genuinely doesn't state it — common, since it's implied by the
  employer

The third case is the interesting one, because no amount of JD keyword
filtering solves it. It needs employer-level knowledge, not JD-level.

**Open sub-questions:**
- Is an employer denylist (defense primes, cleared-work contractors) the
  right mechanism, or does that overfit to one user's visa status?
- This is profile-derived in the Q1/Step 7 sense — a user's visa status
  should drive it automatically rather than being hand-listed per user.
- **Related, and worth not losing:** R2 bet that a wider pool plus funnel
  filtering removes the need for hand-tuned `exclude_keywords`. That bet held
  for wrong-*level* jobs — a senior role scores low against a new-grad
  profile, which is why DICK'S SE II fell out on its own. It does **not**
  hold for wrong-*eligibility* jobs, because a clearance-gated role can be a
  genuinely excellent semantic match and score high on merit. Different
  failure class, needs a different mechanism.

---

## Q14. Step 7 — what is built, and where to pick up

**Status:** In progress. This entry is the resume point for the next
session; read it before starting anything else in Step 7.

**Decided already (do not re-litigate):**
- Conditional triggers are **not** redundant with embeddings. Measured by
  ablation on the frozen 20-JD baseline: removing the conditional term
  changes **12/20** selections. The decision rule was "delete if <=2".
  Deleting is off the table.
- Triggers cannot be derived from `component.keywords`. Overlap with the
  hand-written triggers is **3 terms out of ~104**; nine of eleven
  components overlap by zero. Auto keywords describe what a project is
  *built with*; triggers describe what kind of job it is *evidence for*.
  Deriving from the former would also neutralise the mechanism — generic
  terms fire for every JD, so the +0.20 stops discriminating.

**The open decision — the firing rule.** Simulated against the baseline
using the real matcher (`_normalize_jd_for_matching` + `_trigger_matches`;
recorded 26 fires, recomputed 26, all agreeing):

| rule | fires | multi-hit share | selections changed | spot checks |
|---|---|---|---|---|
| current (any 1 hit) | 26 | 15% | — | 4/5 |
| min2 (>=2 hits) | 4 | 100% | 11/20 | 5/5 |
| scaled (+0.07/hit, cap 0.20) | 26 | 15% | 8/20 | 5/5 |
| off | 0 | — | 12/20 | 4/5 |

**85% of fires (22/26) come from a single incidental keyword** — a JD saying
"rapid prototyping" grants the UberEats UX project the same +0.20 as a
genuinely on-topic match. Both fixes clear all five spot checks.
**Recommendation: `scaled`.** Less disruptive than `min2`, and it avoids a
structural bias — `min2` favours components with longer trigger lists, since
14 keywords reach two hits far more easily than 7.

**~~Blocking everything downstream: the measurement gap.~~ CLOSED
(August 2026).** The reconstruction now reproduces **20/20** selections and
**360/360** keyword terms exactly. The cause was the `comp_text` handed to
`_keyword_match_score`: the real call passes `title company bullets` for
experiences and `name bullets` — *without* tech — for projects, while the
reconstruction used `tech + bullets` for both. Tie-breaking in `_pick_top`
was never involved. The instrument is now exact, and every measurement below
was taken with it.

**Remaining Step 7 work, in order:**
1. ~~Close the reconstruction gap.~~ Done — see above.
2. ~~Apply the firing-rule change and measure it.~~ Done — see R14.
   Shipped `scaled`; 8/20 selections changed, matching simulation.
3. ~~`component_importance` derived from resume order.~~ Done — see R15.
   top-2 high / next-4 medium, as a default the profile overrides.
4. ~~Personal info derived from the resume header.~~ Done — see R16.
   Derived at profile-creation time via `scripts/init_profile.py`, since it
   is stable and changes no runtime output.
5. Trigger vocabulary derivation — only now genuinely unblocked, since R14
   settled what kind of vocabulary is useful: terms specific enough that a
   real match produces several hits, not one.

**Smaller items found and deliberately not changed:**
- `_extract_keywords` uses substring matching above 3 characters, so
  **`java` matches inside `javascript`** — every JavaScript mention also
  credits Java. Fixing it means word boundaries for all keywords, which
  moves scoring broadly and needs its own measured change.
- `rarely_include` keys `exp_outlier` and `exp_tutor` **do not resolve** to
  real component IDs (`exp_outlier_ai`, `exp_tutor_com`). Those rules have
  never fired. Fixing the aliases *starts* them firing, so it is a scoring
  change to opt into, not a typo fix to slip in.

**Baseline:** `baselines/2026-08-21-pre-step7/` — 20 enriched JDs, 20
analysis records, 3 generated resumes. Gitignored. Every Step 7 change is
measured against this, or it is not measured.

**Already shipped in Step 7:** per-user keyword vocabulary (Q7) — see the
Q7 entry. Measured effect on selection: **zero** on this baseline. Correct
fix, no observable impact on new-grad backend JDs.

---

## Q15. Does any of this survive multiple users?

**Status:** Open, and worth answering before Phase 3 rather than during it.

Prompted by the question "will these changes eventually lead to the
multi-user migration plan?". Mostly yes on direction, with concrete blockers
that are cheap now and expensive later. Audited 2026-08-21 against the code,
not from memory.

**Pointing the right way:**
- The per-user keyword vocabulary (Q7) is exactly the DERIVED pattern from
  `migration_plan.md` — the vocabulary now comes from the user's own resume
  instead of a global hardcoded list. That generalises to any user with no
  code change.
- R11's model-aware embedding cache prevents a whole class of silent
  cross-contamination bug that gets much worse with more users.
- PDF generation, the one-page gate, and the discovery fixes are all
  user-agnostic infrastructure.

**Blockers, specific:**

1. **The embedding cache is one file for one resume.**
   `EmbeddingCache` writes `cache/resume_embeddings.json`, keyed only on the
   resume hash. Two users means whoever runs second overwrites the first.
   It degrades safely rather than corrupting — `get()` sees a hash mismatch
   and returns None — but the result is a permanent 0% hit rate and ~19
   re-embeddings per user per run. Needs per-user namespacing.

2. **`job_cache.json` is likewise a single global file.**

3. **Output directories are keyed on date alone.** `outputs/<YYYY-MM-DD>/`.
   Resume filenames embed the candidate's name so those will not collide,
   but `state.json`, `summary.md`, `analysis_results.json` and
   `enriched_jobs.json` are fixed names in that directory — two users on the
   same day overwrite each other's run metadata.

4. **One API key, shared quota.** R10's per-model chain adds capacity but
   does nothing about concurrency. Quota is per key, so users compete.

5. **`pdflatex` is a local binary.** Already tracked as Q8b.

6. **Conditional triggers are still hand-authored** — the single largest
   onboarding blocker, and Q14 shows the mechanism needs fixing before it
   can be automated.

7. **The LLM cache is content-addressed on prompt text**, so keys will not
   collide between users (resume content is in the prompt). But the store is
   shared, meaning one user's generated bullets are readable by another
   user's process. A privacy boundary, not a correctness one.

**Cheap now, expensive later.** Items 1–3 are all the same shape: a
hardcoded path that assumes one user. Threading a `user_id` through the
cache and output paths is a small change today and a migration later. Worth
doing opportunistically the next time any of those files is touched, rather
than as its own project.

**Open sub-question:** is the target actually multi-tenant (one deployment,
many users, shared caches namespaced by user) or single-tenant-per-instance
(each user gets their own container and the current layout is fine)? That
choice decides whether items 1–3 are blockers or non-issues, and it is not
recorded anywhere yet. `migration_plan.md` assumes the former without
saying so.

---

## Q16. `rarely_include` is computed and thrown away

**Status:** Open. Found 2026-08-21 while building R17's validation.

`get_experience_selection_rules()` computes `result['rarely']` on every call,
matching triggers against the JD exactly as it does for `conditional`. Nothing
reads it. The only consumers anywhere are two `print` statements in
`profile_loader.py`'s summary printer — scoring never sees it.

So `rarely_include` is a profile feature that does nothing. The live profile
populates it with two entries (`exp_outlier`, `exp_tutor`), both of which
resolve correctly to real components, and both of which have no effect
whatsoever.

**Why it matters now rather than as trivia:** the roadmap is heading toward a
UI. Building a form field for a setting that has no effect is worse than not
building it, and a user who sets it would reasonably expect something to
happen.

**The options:**
- **Wire it up.** Presumably a negative counterpart to `conditional` — a
  penalty when the rule does *not* fire, or a hard demotion when it does. The
  intended semantics were never written down, which is part of why it was
  never finished.
- **Delete it.** `migration_plan.md` lists it under DERIVED debt ("needs
  derivation from importance map"), which suggests the intent was for low
  importance to express the same idea. If `component_importance` already
  covers "rarely show this", the field is redundant and should go rather than
  be resurrected.

**Leaning delete**, because R15 now derives importance automatically and
`low` already means what `rarely_include` was reaching for. But that is a
product decision about what the profile should express, not a bug to fix
quietly, so it stays open.

**Note:** `projects.high_priority` is a near-relative — still read, but only
for explanation text, never for scoring. See R17.

---

## Q17. Embeddings reward vocabulary overlap, not role type

**Status:** Open. Surfaced 2026-08-22 by the item-2 verification run.

On the Uber *Software Engineer I* resume, the third experience slot went to
**tutor.com** — a tutoring role — beating **AI Ensured**, an AI Engineer
internship, by **0.033**. The entire margin is embedding similarity (0.656 vs
0.623); keyword, conditional and importance terms are identical for both.

The cause is visible in the bullet. tutor.com reads *"tutoring in Python and
Java, resolving code bugs, teaching data structures, algorithms, and
object-oriented programming"* — dense with exactly the vocabulary a
software-engineering JD uses. The embedding correctly reports high textual
similarity. It has no way to encode that one is engineering work and the
other is teaching *about* engineering.

This is not caused by R14 or R15 (experience selection was unchanged in all
20 JDs) and it is not obviously wrong — tutor.com is current and ongoing,
AI Ensured was a three-month stint, and a human might well choose the same.
The problem is that it should be a *choice* rather than an artifact of a
0.033 distance.

**Options:**
- **Let importance decide it.** Both are `low` in the hand-tuned profile and
  would both be `medium` under R15's derived tiers, so importance currently
  breaks no ties. Giving tutoring an explicit `low` would settle it — but
  that is hand-tuning, the thing Step 7 exists to remove.
- **Derive a role-type signal** from the title (Intern / Engineer / Tutor /
  Teaching Assistant) and weight it. Generalises across users, and is the
  kind of thing an onboarding UI could confirm rather than ask.
- **Accept it.** A near-tie between two weak third-choice experiences is a
  low-stakes outcome, and the resume is not wrong.

**Worth noting for the app:** this is the sort of decision a user would want
to override, which argues for surfacing "why was this chosen" and an
include/exclude toggle in the UI rather than solving it purely in scoring.

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

**Decision:** No (May 2026). Superseded by OOS5 (August 2026) — Claude
integration is out of scope entirely on the no-spend constraint.

Step 8.5 shipped without it. The reliability problem this entry expected
Claude to solve was addressed by the model chain repoint and the prompt-hash
response cache instead — see R10. The "$5 free credits" investigation below
was never run and is now moot.

The rest of this entry is kept as written, for the record.

Current Gemini setup is working when quota is available. The repair loop
handles validation failures. The architectural bottleneck is reliability
(Q5), which Claude as a third fallback would meaningfully improve.

Adding Claude would be valuable for:
- Step 8.5: multi-provider fallback (reliability when Gemini 429s — now
  a real-world issue, not just hypothetical)
- Step 11: Golden Rules enforcement (quality on strict multi-rule prompts)
  (Also blocked by the no-spend constraint — see OOS5.)

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

## R10. How do we keep Gemini reliable when it 503s or runs out of quota?

**Decision:** Done (August 2026). Step 8.5, zero-cost version — no second
provider.

Three months elapsed between the May 21 commit and this work. In that window
Google retired two of the models the pipeline depended on, and Q5's
documented failure mode silently changed shape into something worse.

**What was actually broken:**
- `gemini-2.0-flash` shut down June 1 2026. It was the second link in the
  fallback chain, so the chain had effectively been a chain of one since June.
- Worse than a dead link: `_call_gemini_json` only continued on quota errors
  and re-raised everything else. A 404 from the retired model turned "2.5
  hit quota" from a soft fall-through-to-mock into a **hard raise**. Q5's
  claim that "the pipeline doesn't crash on either failure mode" had stopped
  being true.
- `retry_with_backoff` re-raises anything that isn't a rate-limit error, so
  503s propagated instantly with no retry — despite Q5 recording 503 handling
  as working.
- Q5's claim that 2.5 and 2.0 "share quota" was also wrong. Free-tier quota
  is per-model, which is what makes a fallback chain worth having at all.

**What changed:**
- Chain repointed to `gemini-3.5-flash → gemini-3.1-flash-lite →
  gemini-flash-lite-latest`. The floating `-latest` alias is deliberately
  last: it silently re-points to new models, so output can shift between runs
  for reasons invisible in a diff. Acceptable as a safety net, not as a primary.
- Model list moved into `config.py`. Google retired a model out from under
  this project twice in one year; the list belongs in exactly one place.
- `classify_api_error()` buckets four ways instead of two — quota / retired /
  transient / fatal. Retired and transient fall through to the next model;
  fatal still raises immediately so a bad key or malformed request isn't
  masked behind a misleading quota message.
- Retired models name themselves in the final exception, so the next
  retirement costs a log line instead of a debugging session.
- `scripts/check_models.py` probes live endpoints under the current API key.

**Prompt-hash response cache (`tools/cache/llm_cache.py`):**
The real fix for quota exhaustion as actually experienced. The quota was
never dying from 10 resumes at 2–4 requests each — it was dying from
re-running the same jobs all session during development. Keyed on prompt text
only, not prompt+model, so a chain fall-through still hits cache; the
producing model is recorded in the payload. `--no-cache` bypasses it, which
matters when iterating on `prompt_builder.py`, where a stale hit would mask
the change you just made.

**Verified end-to-end (2026-08-20), 2 jobs from replayed May analysis:**
- Both valid, 0 needs_review, `gemini-3.5-flash` on both, no fall-through
- Re-run: 2 cache hits, **zero** `generateContent` requests
- `--no-cache`: cache disabled, 2 fresh API calls, output regenerated
- Bullet quality on 3.5-flash beat 2.5-flash in May — 12 unchanged /
  0 compressed on job 1, i.e. the model hit the length zones unaided

**Lesson worth keeping: `models.list()` is not authoritative.**
`gemini-2.5-flash-lite` appeared in the listing with full `generateContent`
support and 404s on a real call. It was in the first proposed chain and would
have shipped as a dead second link, rediscovered at the next quota
exhaustion. Google's own deprecation page also still listed it as alive until
October 16. Only a live probe tells the truth — re-run
`scripts/check_models.py` before any chain change.

**Also still true from Q5, carried forward:**
- `--retry-needs-review` is not built. It's worth more now than when Q5
  raised it, because R9 sends resumes to needs_review for a mechanical,
  fixable reason (page overflow) rather than a content failure.
- A "quota nearly exhausted" pre-flight warning is still unbuilt and still
  hard to do cleanly without an explicit quota-check API call. Lower value
  now that the cache removes most dev-time burn.

**Note:** `gemini-2.5-flash` has an announced shutdown of 2026-10-16 and is
no longer in the chain. `gemini-3.6-flash`, `gemini-3.7-flash`, and
`gemini-3-flash-preview` all probed alive but are unproven on this workload —
promoting one over 3.5-flash needs evidence, not novelty.

---

## R11. Should the embedding cache key include the model name?

**Decision:** Yes. Done (August 2026), ahead of the Q9 migration rather than
during it.

The cache keyed entries on text alone. Switching `EMBEDDING_MODEL` would
therefore have served vectors produced by the *old* model for text that was
already cached, silently mixing two vector spaces in one similarity
computation. That is not an error — it is a plausible-looking ranking that
is quietly wrong, and it would have surfaced as "scoring got weird after the
migration" with no obvious cause.

Cheap to add now, expensive to debug later. Entries written by the previous
scheme are ignored rather than deleted, so the change is reversible.

**Found while implementing:** the call site hardcoded
`model="gemini-embedding-001"` and never read `config.EMBEDDING_MODEL`. The
constant existed but was decorative — a migration would have edited it,
observed no change, and gone looking in the wrong place. Now wired through,
which is what makes the cache guard meaningful in the first place.

`EMBEDDING_DIMENSIONS = 768` is pinned at the call site, so vectors stay the
same width across models. Worth being explicit that this does *not* make
them comparable: same width, different space. Width was never the reason the
guard is needed.

**Implementation:** `EmbeddingCache(model=...)` takes the model as a
constructor argument rather than importing config, matching `llm_cache.py`.
The stored payload gains `embedding_model`; `get()` returns None when it
differs from the current model, or when it's absent (a pre-R11 entry).
Passing `model=None` keeps the old behaviour, so the guard is opt-in.

The existing on-disk cache was backfilled with `gemini-embedding-001` — the
value the call site hardcoded, so it is known with certainty — which avoids
re-embedding 19 components for no reason on the next run.

**Contrast with the LLM cache, which deliberately omits the model from its
key (see R10).** The reasoning is opposite, not inconsistent: for generation,
a fall-through to the next model in the chain *should* hit the cache, because
any model in the chain is an acceptable producer of that bullet. For
embeddings, a cross-model hit is a correctness bug, because vectors from
different models are not comparable.

---

## R12. Why was `tools/cache/llm_cache.py` missing from the repo?

**Decision:** Fixed (August 2026). `.gitignore` patterns for generated
directories must be anchored with a leading slash.

`.gitignore` contained a bare `cache/`, intended for the run-generated
`cache/` directory at the repo root. A pattern without a leading slash
matches at *any* depth, so it also matched `tools/cache/` — a source
directory.

The four modules already tracked there kept working, because gitignore does
not affect files git is already tracking. But `llm_cache.py`, added in the
Aug 20 commit, was silently never staged. `git status` never showed it.
`generation_agent.py` imports it at line 34.

**Consequence:** every fresh clone of the public repo raised
`ModuleNotFoundError: No module named 'tools.cache.llm_cache'` on any run.
The project was broken for everyone except the author, who had the file on
disk, for as long as the commit was public. Confirmed by cloning the repo
into a temp directory and importing the module.

**Fix:** `/cache/` and `/.cache/`, anchored to the repo root, plus committing
the missing file.

**Lesson worth keeping:** a working tree is not evidence that a repo works.
Anything that changes what is or isn't tracked — a new ignore rule, a
restructure, a history rewrite — deserves a throwaway clone and an import
check. This one cost nothing to find once looked for, and was invisible from
inside the working copy.

---

## R13. Discovery parsed the "↳" continuation glyph as a company name

**Decision:** Fixed (August 2026).

The jobright-ai and speedyapply tables name the employer in the first row and
put a "↳" in the rows beneath it when one company posts several roles.
`search_github_newgrad` read the cell literally, so the glyph became the
company and flowed all the way to output — `**↳** - Software Engineer, New
Grad` in the summary, and `Yash_Pathak__Software_Engineer_New.tex` (note the
empty company slot) as the filename. Two of twenty jobs in the Aug 21 run.

**Fix:** track the last real employer per source table and substitute it when
a cell is a continuation marker. `last_company` is updated *before* the
filters run, so a row dropped for being non-US still establishes the employer
for the rows beneath it. A continuation with nothing above it is dropped
rather than emitted with a glyph.

**The part that nearly broke something else.** The dedup key was
`company::title`. Resolving the glyph made that key collide for genuinely
distinct postings — one employer listing the same role in two cities
previously differed *only* by the unresolved glyph. Measured against a live
400-listing scrape: **75 postings, 19% of the pool, would have been silently
dropped** by the fix on its own. Location is now part of the key, which still
dedups the same posting across both source repos.

Worth generalising: a fix that makes two fields more correct can make a key
built from those fields less unique. Anywhere a derived identity is
assembled from parsed values, correcting the parse is a change to the key.

**Verified against live data:** 400 listings, zero with a glyph or empty
company. Continuations resolve into real employers — Albertsons 17, Amazon
16, AWS 13, SpaceX 11, Palantir 11. Marker detection passes 10/10, including
a false-positive guard ("Arrow Electronics" must not match).

**Sub-questions from Q11, answered:**
- The location column does *not* use continuation glyphs — 0 of 400 listings
  had a glyph or an empty location.
- Markers handled: "↳" (U+21B3), "⤷" (U+2937), ditto marks, "same", "same as
  above".
- A continuation row that can't resolve an employer is dropped at Discovery,
  rather than flowing through with a placeholder.

---

## R14. Conditional triggers fired on a single incidental keyword

**Decision:** Done (August 2026). Partial credit by hit count, replacing
all-or-nothing.

A conditional match was worth a flat **+0.20** the moment *any* one trigger
appeared anywhere in the JD. Measured on the frozen 20-JD baseline, **22 of
26 fires (85%) came from a single keyword**, and those single keywords were
usually incidental:

| fired | on | matched |
|---|---|---|
| UberEats UX redesign | Uber, Palantir backend roles | `prototyping` |
| UberEats UX redesign | Confido, Warp, Samsara | `user experience` |
| Sleep-tracker app | backend JDs mentioning the company has an app | `native app` |

A JD saying "rapid prototyping" gave a UX project the same bonus as a
genuinely on-topic match. Only Ramp's *Mobile Engineer, Android* looked
right — and notably it hit three triggers, not one.

**What changed:** the rules now report `conditional_hits` (distinct triggers
matched per component), and the score is `min(0.07 * hits, 0.20)`. Three
hits still earns the full bonus; one earns a nudge.

**Why scaled rather than a >=2 threshold.** Both cleared every spot check in
simulation, but `min2` structurally favours components with longer trigger
lists — 14 keywords reach two hits far more easily than 7 — which would have
made trigger-list length a scoring input. Scaling degrades gracefully and
changed fewer selections (8/20 vs 11/20).

**Verified:** the shipped implementation changes 8/20 selections, exactly as
simulated. Hit counts on the live path are what the design predicts — Ramp's
mobile project scores 3 hits (full 0.20) while Uber's and Samsara's
incidental matches score 1 (0.07). Samsara no longer carries a UX redesign
into a backend resume; Ramp keeps its mobile project.

**Method note.** This was measured with a reconstruction that reproduces the
recorded baseline exactly — 20/20 selections and 360/360 keyword terms. An
earlier version reproduced only 16/20 and would not have resolved an effect
this size reliably. See Q14.

---

## R15. Should `component_importance` be derived from resume order?

**Decision:** Yes. Done (August 2026). Derived as a default; explicit profile
tiers still win.

Q1 posed this as a hunch — "most people put their strongest project first".
It tested well. Against this project's hand-tuned profile, importance is
**monotonically decreasing with resume position**, with exactly one exception
in 18 components (`proj_ml_based_antibiotic_resistance_predictio`, marked
medium while sitting among the lows at position 9).

**The rule was chosen by measurement, not taste.** Candidates were scored on
two axes: agreement with the hand-tuned tiers, and how much they perturbed
selection on the frozen 20-JD baseline.

| rule | tier agreement | selections changed |
|---|---|---|
| **top-2 high, next-4 medium** | **14/18** | **4/20** |
| top-2 high, next-2 medium | 13/18 | 15/20 |
| top-2 high, next-6 medium | 12/18 | 6/20 |
| top-1 high, next-3 medium | 11/18 | 13/20 |
| top-3 high, next-3 medium | 13/18 | 16/20 |

Top-2/next-4 wins on both, and the two axes moving together is the reason to
trust the rule rather than either number alone. All four disagreements are
the derived rule being *more generous* than the hand-tuning — the weak
experiences at positions 3–5 get medium where they were marked low, worth
+0.05 each.

**Derived values are defaults.** `merge_importance()` layers explicit profile
tiers on top, so this profile — which states all 18 — is completely
unaffected. Verified: the baseline still reproduces 20/20. The 4/20 figure is
therefore not a change to this user; it is the distance between *derived* and
*hand-tuned* for a user who wrote nothing. Read that way it is the useful
number: **derivation lands within 4/20 selections of a hand-tuned profile.**

**Both consumers share the merge.** Component selection (Analysis) and bullet
budget allocation (Generation) each read importance independently and would
otherwise be free to disagree about a component's tier while allocating
against it.

**Home for the rest of Step 7:** `tools/profile/derivation.py`. Items 4 and 5
(header parsing, trigger vocabulary) belong there too, under the same
contract — derived is a default, stated wins.

---

## R16. Deriving personal info, and bootstrapping a profile from a resume

**Decision:** Done (August 2026). Derived at profile-creation time, not at
runtime, via `scripts/init_profile.py`.

**Why creation-time and not runtime.** The other derivations (importance,
vocabulary) are computed on every run because they track resume edits.
Personal info does not: it is stable, and the user may legitimately want to
override what the resume says. Deriving it once into a starter profile, then
letting the user correct it, is the better fit.

It also would not have helped at runtime. `personal_info` is consumed only
for logging, the output filename and `summary.md` — **the generated .tex
header is copied from the master resume, not built from the profile.** So
this changes no generated output whatsoever. The entire value is onboarding.

**The burden it removes.** All 13 `PersonalInfo` fields are required by the
schema, so a new user hand-writes every one — including eight the resume
header already states. `derive_personal_info()` covers nine:
name, email, phone, github_url, linkedin_url, school, degree,
graduation_date, graduation_term. **All nine match this project's
hand-written profile exactly.**

Left alone deliberately: `location`, `visa_status`, `us_citizen`,
`permanent_resident`. These carry legal and eligibility meaning a resume does
not reliably state — an address line is where you live, not where you are
allowed to work.

**Graduation parsing is the fiddly part** and the place a wrong answer does
real damage: an incorrect graduation date changes which jobs a user is
eligible for. It therefore fails to blank rather than guess. Two cases forced
the design:
- `"Sept 2022 – Present"` originally returned the *start* date, reporting a
  current student as already graduated. Only the last chunk of the range is
  considered now; no year there means the answer is unknown.
- `"Expected May 2026"` lost its month, because probing for any three letters
  matched "Exp". It searches for month names now, and normalises the result
  to `"May 2026"`.

Term inference maps months to Spring/Summer/Fall, with June deliberately in
Spring — commencement is June at plenty of schools while the term is still
Spring, which is what this project's own profile records. 7/7 cases pass.

**`scripts/init_profile.py`** ties it together: reads a resume, fills derived
`personal_info` and order-derived `component_importance` (R15), points
`master_resume_path` at the resume, writes `user_profiles/<name>.json`,
refuses to clobber without `--force`, prints exactly which fields still need
a human, and validates the result against the schema before exiting.

**Verified:** a bootstrapped profile validates and runs the full mock
pipeline end to end — discovery, analysis and generation — with no
hand-editing.

**What this does and does not prove about multi-user (Q15).** It removes the
single biggest onboarding blocker for personal data. It does not touch the
harder one: `conditional_inclusion` is still hand-authored, and R14 showed
the mechanism needed fixing before the vocabulary could be automated at all.
That remains Q14 item 5.

---

## R17. Profile rules that reference components which do not exist

**Decision:** Done (August 2026). Validated and warned about, not corrected
case by case.

Several profile fields are keyed by component ID — `always_include`,
`never_include`, `high_priority`, and the `conditional_inclusion` /
`rarely_include` maps. An ID matching no parsed component is not an error
anywhere: the lookup misses, the rule never applies, and nothing says so. A
stale rule is indistinguishable from a rule that simply did not match a JD.

**`user_profiles/template.json` shipped five of them:** `exp_company1`,
`exp_company2`, `exp_healthcare_company`, `proj_best_project`,
`proj_second_best`. Since `init_profile.py` copies the template wholesale,
**every bootstrapped profile inherited all five.** Two were in
`always_include`, which is worth +0.30 — the largest single term in the
composite score. Cleared; those collections now start empty, because a
component ID cannot be known before a resume is parsed.

**The check.** `find_unresolvable_ids()` resolves every ID-keyed field
through the parser's own `get_experience_by_id` / `get_project_by_id`, so it
agrees exactly with what the scorer would resolve. Called once per run from
the orchestrator and again by `init_profile.py` against its own output.
Schema validity was never the issue — a ghost rule loads fine.

**Correction to Q14.** That entry claimed `exp_outlier` and `exp_tutor` in
the live profile "do not resolve" and "have never fired". **That was wrong.**
Both resolve through the parser's prefix matching, to `exp_outlier_ai` and
`exp_tutor_com`. The original finding came from comparing ID sets exactly,
which is not how the code resolves them. Running the new check against the
live profile reports zero problems — which is the correct answer, and a
useful confirmation that the validator models real behaviour rather than a
stricter fiction.

**Found while checking: `high_priority` no longer affects scoring**, having
been deliberately superseded by the composite scorer (see the comment in
`resume_parser.select_components`). But `analysis_agent` still reported
`"High priority (profile)"` as the *reason* a project was selected. The
project was selected by score; the flag contributed nothing. The reasoning
text now states the real cause and mentions the flag separately, since a run
summary that misattributes causation is worse than one that says less —
especially once it is shown in a UI.

---

## R18. Keyword matching credited substrings, not terms

**Decision:** Done (August 2026). Word boundaries everywhere, with a narrow
escape hatch.

The motivating case — `java` matching inside `javascript` — turned out to be
the *smallest* part of this.

**The resume side** applied word boundaries only to terms of three characters
or fewer and used plain substring matching above that. So `scala` matched
"scalable" in 3 of 20 baseline JDs, `rust` matched "anti**trust** lawsuit",
and `bert` matched "**Rober**ts" and "Gil**bert** family foundation" — investor
names in a finance JD.

**The JD side had no boundaries at all**, not even for short terms, and that
is where the real damage was:

| term | matched inside |
|---|---|
| `ai` | email, paid, maintain, training, obtain |
| `rag` | coverage, storage, leverage |
| `go` | government, ago, goldman |

Those appear in essentially every job description, so any component carrying
`ai`, `go` or `rag` as a keyword collected a match on almost every job. The
keyword term was partly measuring nothing.

**The fix** is one shared `term_matches()` used by both extractors: word
boundaries, falling back to substring only for terms containing `+` or `#`,
where `\b` cannot work (the boundary after "c++" sits between two non-word
characters and never matches). Boundaries preserve the containments that
*should* match — "github" inside "github actions", "html" inside "html/css" —
because the following character is a non-word one. 14/14 unit cases pass.

**Two legitimate matches were lost and recovered properly.** Boundaries stop
`angular` matching "angularjs" and `bert` matching "distilbert", both of
which are real. The right fix was not to weaken the matcher but to add
`angularjs` and `distilbert` to the vocabulary — they are actual product
names that were simply missing from a tech keyword list.

**Measured: 6/20 selections changed** by the matcher alone, holding the
conditional term at its recorded values so this isolates the keyword change
from R14's.

Four of the six are the same experience swap, `exp_ai_ensured` losing to
`exp_tutor_com`. The cause is exactly the bug: `ai_ensured` carries `ai` as a
keyword, so it was matching every JD containing "email" or "training". That
credit is now gone. The outcome happens to reinforce Q17's concern about
role-type blindness, but the mechanism here is a correction, not a
regression.

**Methodological note — the baseline reconstruction now reproduces 14/20 by
design.** That check measured instrument fidelity against recorded values;
once scoring intentionally changes, it measures the delta instead. The
instrument itself is still trustworthy — item 2 validated it against a live
run, where it predicted 8/20 exactly. **A fresh baseline should be recorded
after item 5**, not before: re-baselining now would invalidate the comparison
point that R14, R15 and Q7's numbers were all measured against, and item 5
is going to move scoring again anyway.

---

## R19. Where do tests live?

**Decision:** Done (August 2026). `tests/`, stdlib `unittest`, 58 tests.

**Why unittest and not pytest.** `requirements.txt` is the install list for
anyone running the app, and a test framework does not belong there — this is
heading toward something a non-technical user installs locally. A separate
dev-requirements file is more structure than the ergonomic gain justifies at
this size. `python -m unittest discover -s tests -t .` needs nothing extra.
(`pytest>=7.0.0` has sat commented out in requirements.txt for months, which
is roughly the same conclusion reached passively.)

**What is covered**, chosen for being pure, deterministic, and load-bearing:

- `test_keyword_matching.py` — term-vs-substring matching (R18), skill-list
  splitting, vocabulary construction. Every false positive R18 found is a
  named test case, so `scala`/"scalable" and `ai`/"training" cannot come back.
- `test_bullet_compress.py` — the deterministic half of R6. Individual
  transforms, compression contracts (deterministic, never empties a bullet,
  only reports real stage names), zone boundaries, and the documented
  needs_review path when compression cannot reach a good zone.
- `test_derivation.py` — importance tiers (R15) and personal-info derivation
  (R16), including every graduation-parsing case: ongoing study must yield
  blank rather than the start date, "Expected May 2026" must not lose its
  month, June must land in Spring.
- `test_pdf_builder.py` — moved in from a scratch directory, and made
  cross-platform on the way.

**The stub pdflatex is the reason this suite is worth having.** It fakes each
outcome, so the paths that matter most — timeout, compile error, missing
engine, nonzero exit that still produced a PDF — are reachable deliberately
rather than by luck. It also means contributors with no LaTeX install can run
everything, which matters for a project about to be distributed.

That suite already earned its keep once: it caught the wrapped-log page-count
bug that had silently disabled the one-page gate for most resumes. That case
is now a named regression test.

**Not covered, deliberately:** anything requiring API calls, and
`select_components` end to end. The latter is better served by the frozen
baseline, which measures real selection against recorded output — a unit test
asserting a particular component wins would just restate the scoring formula.

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

## OOS5. Claude API integration

**Decision:** No (August 2026). Hard constraint: no money spent on this
project.

Claude Max gives chat access, not API credits — API usage is billed
separately at console.anthropic.com. Any integration costs real money, even
at Sonnet's ~$0.024/resume. That settles it regardless of output quality, so
the "is Claude meaningfully better on a few examples?" investigation Q4
proposed is moot and was never run.

This also kills the multi-provider abstraction Q4 proposed for Step 8.5. A
provider-agnostic `call_llm_json()` with exactly one provider behind it is
speculative generality. If a genuinely free second provider ever becomes
worth adding, build the abstraction then — at the point where there's a
second thing to put behind it.

The reliability problem Q4 existed to solve was solved without a second
provider. See R10.

---

# Meta: maintaining this doc

- Add new questions to **Active** as they come up
- When making a decision, move the question to **Resolved** with rationale + date
- When deciding something is *not* a goal, put it in **Out of scope**
- Don't delete entries — kept for posterity / future re-evaluation
- Review **Active** at the start of each new working session to remember context
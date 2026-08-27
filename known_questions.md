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

**Superseded 2026-08-25 for the hosted path — see R60.** The reasoning below
is sound and its arithmetic still holds; what changed is the premise. Every
line of it assumes *free-tier* quota, because a hard no-spend rule (OOS5) made
that the only kind available. Once revenue is on the table a paid key costs
about 1.5 cents per resume, and "twenty users exhaust the cap before noon"
stops being a constraint.

Local-first remains correct for the local app, which is now the free tier.
Nothing below is retracted.

The original follows.

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

## 5. Derive `conditional_inclusion` — DONE, with the premise unproven (2026-08-22)

**Done — see R21.** The derivation ships and bootstrapped profiles now get 17
rules and 104 triggers instead of an empty map. But the measurement did not
support this item's central claim. Derived triggers change 7 of 20 selections
against an empty map, so they do real work — and they land no closer to the
hand-tuned profile than the empty map does (8/20 either way). The gap this
item was written to close is not measurably closed, and the reason looks
structural: hand-authored triggers are domain words, derivation only reaches
technology words.

It is still the right thing to ship — it never overrides a hand-authored rule,
and it is strictly more signal than nothing — but "a bootstrapped user now
selects as well as a tuned one" is **not** demonstrated, and R21 says what
would demonstrate it.

The original entry follows.

### Original

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

## 6. Make the API key injectable — DONE (2026-08-22)

**Done — see R22.** `config.resolve_api_key()` is the single place that
decides what "no key passed" means, and `api_key` threads through
`JobScoutOrchestrator`, `AnalysisAgent`, `GenerationAgent`, `ResumeParser` and
the embedding scorer. Four of the five sites are injectable; the fifth is
`scripts/check_models.py`, a hand-run probe no UI calls. 6 new tests.

The original entry follows.

### Original

`os.getenv("GOOGLE_API_KEY")` is read at five sites, including inside
`_call_gemini_json` and the embedding scorer.

*Why before the UI:* fine for a CLI, wrong the moment a UI collects the key
from a user. Threading it through as a parameter is small now and invasive
once a UI exists — the same argument as R11's cache guard.

## 7. Decide the pdflatex distribution story — DONE (2026-08-22)

**Done — see R20.** Decided: `.tex` always, PDF when `pdflatex` is present,
and an install pointer when it is not. No bundling. The Overleaf handoff is
recorded as the known escape hatch if the gap turns out to bite.

The original entry follows, including the premise R20 rejects.

### Original

Asking a non-technical user to install MiKTeX is probably fatal to adoption.
The options are bundling a TeX distribution, falling back to `.tex`-only
downloads, or an Overleaf handoff.

*Why ahead of the UI rather than after:* this is not a fallback to bolt onto
a finished results screen. If a meaningful share of users have no LaTeX, the
download UX is `.tex` plus a handoff — **a different screen**, not a disabled
button. Deciding after item 8 means redesigning it.

Note `find_pdflatex()` already exists (R8) and detects this reliably.

## 8. The UI — first version shipped (2026-08-22)

**Stack decided (R25): Streamlit, kept as a pure view layer.** The
prerequisite refactor landed first (R26): the orchestrator reports progress
and resolves checkpoints through callbacks, so a UI can render a multi-minute
run and answer a checkpoint without touching stdin.

`app.py` now exists — four screens (resume, about you, preferences, run), live
progress, and downloads that branch on whether a LaTeX engine is installed per
R20. It imports only `agents.orchestrator` and `scripts.init_profile`, and
nothing from `tools/`; two facades (`pdflatex_available`, `available_profiles`)
and three profile helpers (`save_resume`, `create_profile`,
`update_profile_fields`) exist so that the view layer never has to know that a
profile is JSON on disk, or where resumes live.

**Verified**: all four screens render, navigation works forwards and
backwards, live progress streams from the orchestrator callback, and the
results screen renders downloads from a saved run. **Not yet verified end to
end against a live API run** — the day's free-tier Gemini quota was spent on
the R21/R23/R27 measurements, so the one path still unexercised is a real
generation run driven from the UI rather than the CLI.

**All three known gaps are now closed (R32):** previous runs, review before
generating, and a tuning screen for importance tiers and JD triggers.

What is still missing is distribution — nothing packages this, so the audience
is people willing to clone a repo and edit a `.env`.

The original entry follows.

### Original

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
- **INTERNAL cleanup** — **done (R52)**, and it was twenty-five fields rather
  than five. The template lost sixteen; the rest already had schema defaults.
- **Q9** — `gemini-embedding-001` is past its shutdown date and still
  serving. R11 made the cache model-aware, so the dangerous part is handled.
- **Q10** — clearance-gated employers. **Done (R56).** The investigation
  this asked for was one grep over the corpus: the JDs state it themselves.
- **Q3** — page headroom. Measurable, but wants live-run data on how often
  headroom appears before spending LLM output on bullets that may be trimmed.
- **Q2** — PDF and DOCX resume input. **Done (item 10, 2026-08-23).** This
  line described it as open until 2026-08-25; it had shipped two days before
  the line was written.
- **USER-INPUT fields** — **done (R40, R52)**. The debt list in
  `migration_plan.md` has no open rows left.

## Not scheduled

**Q6** — long master bullets. **Done (R58).** R45 covered the fabrication
half; R58 covers the other one, and reframed it on the way: the error is not a
dropped figure but a dropped figure whose magnitude the output still asserts.

---

# Phase 2 roadmap — beyond one user with a LaTeX resume

Added 2026-08-23. Items 0-8 above got the pipeline correct and usable by its
author. Everything here is about it being usable by somebody else. Ordered by
what unblocks what, not by appeal.

## 9. Local embeddings — DONE (2026-08-23)

**Done — see R36.** A full run now completes with no API key: keyless
discovery (R34), keyless scoring, keyless selection. Only bullet rewriting
still needs a model, which is item 11. The original entry follows.

### Original

**Why first: everything free depends on it.** Gemini is reached at exactly two
call sites — `_get_embedding` and `_call_gemini_json` — and embeddings are the
larger of the two, roughly 20 calls per run against 3 for generation. Moving
them to `sentence-transformers` on CPU means **discovery, scoring and component
selection work with no API access at all**, leaving only bullet rewriting
dependent on a model. It also dissolves Q9, since the retirement date of
`gemini-embedding-001` stops mattering.

Costs: a heavier dependency, a model download, and vectors that are not
comparable to the cached Gemini ones — so this needs its own frozen baseline
before and after, and R28's cache entries become model-scoped in practice as
well as in name.

## 10. PDF and DOCX resumes (Q2) — DONE (2026-08-23)

**Done — see R38 for the renderer and R39 for extraction.** A PDF or Word
resume now becomes a `.tex` the pipeline reads unchanged, and the user keeps
the `.tex`. The original entry follows.

### Original

**Widest reach gain available.** Requiring a LaTeX master resume excludes
almost everyone; a user with a Word CV cannot use JobScout at all today.

**The architecture is decided, and it is not either option Q2 sketched.**
Generation does not merely parse the master `.tex` — it **splices** it
(`generation_agent.py:1199`): everything before the Experience section and
everything from Technical Skills onward is reused verbatim, with generated
sections inserted between. The master `.tex` *is* the output template. So
parsing a PDF straight into the data model leaves nothing to splice, and
having an LLM emit LaTeX is fragile in exactly the way that breaks compilation.

Instead: **extract to a schema, render deterministically.**

1. An LLM (or heuristics) reads the PDF/DOCX and fills a *structured schema* —
   contact, education, experiences, projects, skills. It never emits LaTeX.
2. A Python renderer populates the known template from that schema, handling
   escaping.
3. The result is a valid `.tex` the existing pipeline consumes unchanged, and
   which the user can keep and edit.

The model does what it is good at, extracting structure from messy text, and
nothing it is bad at. Every input format becomes one importer behind the same
contract. Extraction will misread some resumes, which is why R33's confirmation
screen is not optional.

## 11. Provider-agnostic generation, and the free ladder — DONE (2026-08-23)

**Done — see R37.** Four rungs, detected and explained. With R36 that makes a
complete run possible with no key, no account and no network beyond the job
boards themselves. The original entry follows.

### Original

Both Gemini call sites already take an injected key (R22). Most providers —
OpenAI, Groq, OpenRouter, Together, DeepSeek, Ollama, LM Studio — speak an
OpenAI-compatible API, so **one adapter unlocks all of them**, Ollama included.

The goal is a ladder, not a replacement, because the options are not ordered:

| Path | Needs | Excludes |
|---|---|---|
| No-LLM | nothing | nobody, but no bullet rewriting |
| Ollama | install + 2-5GB + RAM | light machines |
| BYO key | a free account | people who will not sign up |

Ollama is *more* accessible on account, quota and privacy, and *less* on
install size and hardware. So: no-LLM always works, Ollama if the machine can,
a key if preferred. **Decided (R33): detect what is available, pick the best,
say plainly what was chosen and what it costs.**

The honest risk: prompts and the JSON validation-repair loop are tuned to
Gemini. Weaker models will fail validation more often and surface as
`needs_review`. Each backend needs measuring against the baseline before it is
trusted.

## 12. A durable job store — DONE (2026-08-23)

**Done — see R35.** SQLite, keyed on apply URL, never expires, and user status
survives re-discovery. The original entry follows.

### Original

**Implied by R33's job-board decision, and the largest consequence of it.**
Everything today is per-run: a `state.json` per date. A board needs jobs that
outlive runs.

`tools/cache/job_cache.py` is the closest thing and is nearly right — natural
key on URL, `first_seen`, title, company, plus cached JDs. Two things stop it
being the store:

- **No user state.** Nothing models applied / rejected / archived, which is
  most of what a board is *for*.
- **It expires on purpose.** `DEFAULT_URL_MAX_AGE_HOURS = 24*7` re-shows jobs
  after a week. A dedup tracker is built to forget; a board must not lose
  anything. Those are opposite intents living in one file.

So: a store carrying score, status, location, apply URL, generated resume
paths and which run produced the record — reusing `job_cache`'s dedup logic
rather than its retention policy.

## 13. Discovery beyond new grad — DONE (2026-08-23)

**Done — see R34.** A keyless ATS source plus a profile-driven seniority gate.
86 verified companies, ~11,600 open roles, no API key. The original entry
follows; its guess that this was "smaller than it looks" was right about the
query builder and wrong about where the real block was.

### Original

Smaller than it looks. `build_serper_query(role, seniority, site)` is already
parameterised and the caller simply passes `"new grad"`; Adzuna is generic
too. The work is making seniority a profile field with a range, and lifting
the hard-coded indicator lists in `job_filter.py:78` — which today encode one
person's eligibility as constants.

What is genuinely lost is that **`github_newgrad` is the only keyless source
and is inherently new-grad**; those curated repos have no general equivalent.
Expanding levels therefore leans on key-based sources, which pulls against
item 11's goal of needing no keys. Keyless general sources worth evaluating:
Arbeitnow, Remotive (remote only), USAJOBS (US federal). Terms change — verify
before designing around any of them.

## 14. The React frontend — now the public board (rewritten 2026-08-25)

**Rewritten by R60.** This item spent its life unable to answer "why bother",
because a React re-skin of a local Streamlit app reaches nobody. It has an
answer now: **the React frontend is the public job board**, which is the half
of the system with no auth, no key and no PII in it, and the first thing
strangers ever see.

That also resolves the local-vs-hosted question this item was blocked on. The
answer is both, split along the seam the pipeline already has:

    shared, public, no PII    discovery — 86 companies, ~11,600 roles, keyless
    personal, expensive       resume, embeddings, generation, LaTeX

The first half is hosted. The second half stays local and free, and becomes
paid convenience later. See R60 for the sequence and what gates it.

The original entry follows.

### Original (2026-08-23)

**All four R33 decisions are now built — see R40, R41 and R51.** The board,
the backend explanation, the seniority controls, the import confirmation
screen, and runs that outlive the tab that started them. What remains of this
item is the React port itself, which is a re-skin over facades that all exist:
`start_run` returns an id, progress is a row in `data/runs.db`, and the
polling loop reads exactly what an SSE endpoint would push.

The open question is not technical. **Local tool or hosted product?** Only the
second needs auth and per-user storage (Q1/Q15), and only the second makes the
port worth its cost — a React frontend reaches nobody new on its own.

Doing this in Streamlit first was the cheap order. Item 14 predicted items
9-13 would change what the screens must show, and they did — settling that in
a file you can edit in a text editor costs less than settling it in React.
What remains for React is a re-skin plus the two missing screens.

### Original

Cheaper than a rewrite because R25 built for it: `app.py` reaches the pipeline
only through `agents.orchestrator` and `scripts.init_profile`, and
`test_ui_contract` fails the build if that changes. Every facade React needs
already exists.

Deliberately after items 9-13, because each of them changes what the screens
must show: a confirmation step for extraction, a backend picker, seniority
controls, and a job list rather than a run log.

## 15. Packaging — DONE (2026-08-24)

**Done — see R50.** `pyproject.toml` plus `jobscout`, `jobscout-ui` and
`jobscout-doctor`. The doctor is the part that matters: item 8 argued it
outlives an install script, and it found a bug on its first run.

The audience is still people who have Python and a terminal. An installer for
people who have neither is a different project.

### Original

Last, because it packages whatever the above settles. Nothing packages this
today; the audience is people willing to clone a repo and edit a `.env`.


## V2. Verification pass after R34-R37 (2026-08-23)

Four items landed in a day — keyless discovery, a job store, local embeddings
and the rewriting ladder — each tested as it was built and none tested
*together*. This is the pass that checks the whole thing still works, written
down because "is it tested" is exactly the question this project keeps losing
track of.

### Verified

| | Result |
|---|---|
| Unit suite | 228 pass, 1 skipped (needs a machine without LaTeX) |
| Baseline manifest | `verify --all` clean |
| Full default run (Gemini) | 20 analysed, **3 valid, 0 needs_review**, 3/3 PDFs |
| PDF read by eye | One page, tailored, correct structure |
| Keyless run (local + no model) | One page, real content, `needs_review` for bullet length |
| ATS discovery | Live across all five boards |
| Job store | Dedup, user-state preservation and backlog all confirmed live |
| Streamlit UI | All five screens, previous runs and tuning, after every change |

The PDF is worth one specific note: `Outlier AI` renders with a single bullet
as a `low` tier, which is R27's allocation behaving as designed rather than
by accident.

### Not verified, and why

- **The Ollama rung.** Nothing is running on this machine. It shares its code
  path with the hosted providers, so it is covered indirectly, but nobody has
  watched a local model actually write a bullet. Its most likely failure —
  fenced JSON — has a unit test.
- **The `openai` rung against a real provider.** Same code, same caveat.
- **Replay mode does not reach the job store.** `--input` skips Discovery, so
  those jobs were never recorded, and the later `set_score` updates zero rows.
  Benign, and silent, which is the part worth remembering: a replay run looks
  identical while writing nothing to the board.
- **The job store is invisible in the UI.** Deliberate — the board is item 14
  — but it does mean the store is exercised only by the pipeline and its
  tests, and there are now two paths to "past results": run files in the
  Streamlit view and the store underneath.

### Untested in a different sense: unjudged quality

These are not gaps in coverage. The code runs; nobody has said whether the
output is *good*.

- **R21** — derived triggers plus the tuning editor versus hand-authored
  rules. Still nobody's judgement.
- **R36** — local embeddings spread scores across 88.7 points where Gemini
  spans 13.9, and agree with it on only 7 of 20 project selections. Wider is
  not automatically better and no one has read those resumes.
- **R37's floor** — a one-page resume in the user's own words, marked
  `needs_review` because some bullets exceed the length zones. Whether that is
  an acceptable product or a bad first impression is a judgement, not a test.

All three want the item-2 treatment: generate, read the PDFs, decide. That is
the one instrument this project has that no test replaces, and it has not been
run since R23.

---

## V3. The qualitative pass, and what only reading found (2026-08-23)

Three questions had been left open as *unjudged rather than untested* — R21's
derived triggers, R36's local embeddings, R37's no-model floor. This is the
item-2 treatment for all three: generate the same JD four ways, read the PDFs,
decide.

**The JD was chosen, not sampled.** Selections were computed across the frozen
20 under each configuration first, and Motorola Solutions, *Embedded Software
Engineer - Modern C++, Linux*, was picked because all three configurations
disagreed on it. A JD where everything agrees proves nothing.

| | Projects chosen | Status |
|---|---|---|
| A reference (Gemini + hand triggers) | jobscout, e-commerce, **computer_networking** | valid |
| B local embeddings | e-commerce, jobscout, diagnosify, search_engine | valid |
| C no model | jobscout, e-commerce, **computer_networking** | needs_review |
| D derived triggers | jobscout, e-commerce, **computer_networking**, spotify | valid |

### R36 — local embeddings are a fallback, not an upgrade

Answered, and against local. For an embedded C++/Linux role the obviously
relevant project is Computer Networking — Docker, ContainerLab, WSL/Linux,
EdgeShark, OSPF/ISIS/BGP, packet inspection. **A, C and D all select it. B
drops it**, substituting Diagnosify, a healthcare NLP web app, and Search
Engine, a Python crawler. Reading the PDF turned up a second swap the
component IDs had not shown: B also replaces Outlier AI with tutor.com, so an
embedded systems resume leads with "Tutored 100+ students in Python and Java".

So R36's headline — local spreads scores over 88.7 points where Gemini spans
13.9 — is **not** better discrimination. Wider is just wider. `auto` already
prefers Gemini when a key exists and should keep doing so; local is what makes
a keyless run possible, and it costs real quality. That is a fair trade to
offer and a bad one to make silently, which is why R37's backend line prints.

### R21 — derived triggers held up

D selected Computer Networking for this JD, same as the hand-authored profile,
and added Spotify as a fourth. On the case that discriminates, derivation
reached the right answer without anyone writing a rule. One JD is not a
verdict, but it is the first evidence in R21's favour rather than against.

### R37 — the floor works, and reading it found a bug no test could

C selected correctly and rendered one page. It also rendered this:

    in $\sim 503$$ms - collapsing ... from $\sim 10$ minutes

**Raw LaTeX leaking into the PDF as visible markup.** The master bullets
contain math spans, `_escape_latex` escaped them into
`\$\textbackslash{}sim 503\$ms`, and the result compiled cleanly and looked
broken. The model path never hits it because rewriting produces plain prose,
so the escaper is right for model output and wrong for the user's own text.

Fixed: `_escape_latex(text, already_latex=True)` for verbatim content, which
the no-model tailor marks. Four regression tests, one of which pins the
mangling itself so it cannot return quietly.

**This is the finding that justifies the whole exercise.** Both paths
compiled. Both produced exactly one page. Both passed 228 tests. The only
difference was that one of them was readable, and nothing except looking at it
would ever have said so.

### Left open

C is still `needs_review` on bullet length — 344 characters against a 316
maximum — which is honest, since deterministic compression cannot rewrite
prose. Whether that is an acceptable free-tier product is a judgement, not a
bug. Worth noting the fixed page now has visible whitespace, so
`VERBATIM_BULLET_SCALE = 0.5` is probably too aggressive once the markup
stopped inflating the rendered length; a later measurement should revisit it.

---

# Active questions

## Q23. The board cannot say when a job was posted

**Status:** Open. Surfaced 2026-08-26 while building R64, when freshness turned
out to be the board's primary sort and the field behind it was checked.

`first_seen` is correct: `JobStore.record()` stamps it once at insert and never
moves it, so an employer editing a posting cannot make a six-month-old role
read as new. It is safe to sort on. What it means is **"first seen by this
crawler"**, which on a board's first crawl is every job at once.

`JobListing.created` looks like the answer and is not. `ats_search.py:105` sets
`created=_now()` — the crawl time wearing a posting-date name — and the store
never persists it, which is the only reason it has caused no harm. A third
instance of the shape R31 and R61 already found: a field whose name describes
data and whose value describes the observation.

**The real dates exist and are being thrown away.** Greenhouse's payload
carries `updated_at`, Ashby's carries `publishedAt`, and the ATS adapters read
neither. Capturing them means a column, a migration (the R57 mechanism), and
deciding what to do for sources that offer nothing.

**Worth doing before the board ships**, because "posted 3 days ago" is the
single most load-bearing fact on a job board and the board currently cannot say
it. Until then the field is named `first_seen` in the export and must be
labelled as such in any UI — never "posted".

---

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

## Q2. How do we handle PDF and DOCX as input formats? — RESOLVED

**Status:** Resolved. Architecture decided 2026-08-23 and **built the same
day** — see Phase 2 item 10. `tools/resume/resume_import.py` accepts `.pdf`,
`.docx`, `.txt` and `.tex`; `tools/resume/tex_renderer.py` renders the schema
into the template; R41 added the confirmation screen extraction makes
necessary. This entry read "Not yet built" until 2026-08-25, and the deferred
list still called the architecture open — both were stale, and both were being
used to scope work.

Neither of the three options below: extract to a structured schema, then
render the known template deterministically. The deciding fact was that
generation *splices* the master .tex rather than only parsing it, so the
master file is the output template and cannot simply be replaced by a parsed
data model.

The original entry follows.

### Original

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

## Q6. How does the system handle very long master bullets? — RESOLVED (R58)

**Status:** Resolved 2026-08-25 — see R58. The failure this question spent its
life predicting was observed, and the answer turned out not to be "preserve
every metric". Compression legitimately drops figures; a 386-character master
bullet cannot keep six inside a 213-character budget, and a check that flags
that is measuring the job being done correctly — which is exactly what the
existing `_validate_metric_preservation` did, on 8 of 8 resumes.

What is not legitimate is dropping a figure and asserting its magnitude anyway.
The gate is now on that, and the first sub-question below is answered by the
prompt rule R58 added rather than by a metric list.

The original entry follows, with the case that closed it.

### The observed case

The antibiotic-resistance project's master bullet is 386 characters and reads:

> ... with XGBoost achieving 94.2\% accuracy ($\pm$0.2\%) and a 15-point
> macro-F1 lift over Random Forest (0.71 vs 0.56) - driven by recall gains on
> critical minority classes (carbapenem 0.17→1.00, aminoglycoside 0.42→0.89).

It came out of generation for Samsara as:

> ... achieving 94.2\% accuracy and significant macro-F1 gains over baseline
> models.

Four numbers survived as one. That is the compression loss this question
predicted, and it is worse than loss alone: **"significant" is a claim the
master never makes.** R45 cannot catch it, because R45 looks for figures in the
output that are absent from the master, and this is the reverse — a figure
present in the master replaced by a vague intensifier in the output.

The first sub-question below ("preserve these metrics: [...]") is now the
obvious thing to try, and there is finally a case to measure it against. Worth
noting that `find_invented_metrics` already extracts the master's figures for
its own check, so the list the prompt would need is already computed.

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

## Q8b. Where does pdflatex run once this is a web app? — ANSWERED (R63)

**Status:** The spike is done — see R63. **It works, and it costs the visitor
120-226 MB.**

Browser pdfLaTeX compiled the real template: exit code 0, a 52 KB `%PDF-1.7`,
including `\input{glyphtounicode}` and `\pdfgentounicode=1`, which were the
genuinely uncertain parts. So the option is real rather than theoretical.

What it costs is the finding. The engine is a 31 MB WASM binary and the TeX
Live data package is 88.5 MB (basic) or 191.9 MB (recommended) — cached in
IndexedDB after the first visit, but paid in full before the first resume
renders.

That inverts the argument R60 made for it. Client-side compilation was
attractive because "the server never touches a resume"; it is unattractive
because the paid tier's entire pitch is *no install, no LaTeX*, and a 120 MB
download is worse than the install it replaces — on a phone, considerably
worse.

**So the tentative direction below stands after all: containerised,
server-side.** WASM is kept as the documented fallback for the case where PII
custody, not convenience, turns out to be the binding constraint.

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

## Q10. Should Discovery filter out clearance-gated employers? — RESOLVED (R56)

**Status:** Resolved 2026-08-25 — see R56. **No, not employers: postings.** The
third case below is the one that was feared and it did not happen. Every
clearance-gated posting the corpus contains states the restriction in its own
text, so a denylist of defense primes was never needed, and reading the text
generalises where a list would have encoded one user's guess about who does
cleared work. The sub-question about overfitting to one visa status is answered
the same way: the gate compares the posting against
`personal_info.{us_citizen, permanent_resident}`, which the UI has collected
since R16 and nothing read.

The original entry follows.

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

6. ~~**Conditional triggers are still hand-authored**~~ — **derived since
   R21**, from the tech stack plus bullet keywords. This was called the single
   largest onboarding blocker and it is no longer a blocker at all. R21's own
   caveat stands: shipping it did not measurably close the gap to a hand-tuned
   profile.

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

## Q16. `rarely_include` is computed and thrown away — RESOLVED (R31)

**Deleted, not wired up — see R31.** The doc's own leaning was right.

The original entry follows.

### Original

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

## Q17. Embeddings reward vocabulary overlap, not role type — RESOLVED (R67)

**Status:** Resolved 2026-08-26 — see R67, which did **not** do what this entry
proposed. The suggested remedy was to derive a role-type signal from the title
and weight it; measured, that term is the maximum for **100% of scored jobs**,
because discovery already gates on `target_roles` and analysis only ever sees
survivors. It would have added a constant — a sixth instance of the dead-signal
bug this codebase keeps finding.

What was wrong was not that the embedding misunderstands role type. It is that
the embedding was the *entire* score, and on its own it barely discriminates:
69 real jobs spanned 41.5-55.8 with a standard deviation of 3.58. The fix is
concrete evidence — technologies both documents name — at 30% of the score.

The original entry follows.

**Scheduled by R60**, between the board and hosted generation. The board is
forgiving of an imperfect ranker; a paid product is not, and there is direct
evidence the scorer rewards shared vocabulary over role type — a *Finance &
Strategy* posting topped the 2026-08-25 run at 55.3%. Solving it during the
free phase is solving it where being wrong is cheap.

**Status:** Open — but its *app* half is built (R57), and the scoring half is
unchanged. The entry closed by arguing that a near-tie "should be a *choice*
rather than an artifact of a 0.033 distance", and that the fix argued for was
surfacing "why was this chosen" rather than solving it in scoring. The board
now says, in as many words, *"Chosen on semantic similarity alone, by 0.03. A
near-tie: the next component behind it is a defensible substitute."*

That does not make the embedding understand role type, and nothing here
claims it does. What it removes is the part that made the outcome untellable
from a verdict. Whether to also derive a role-type signal is still open, and
the observation that argues hardest for it is still the tutor.com one below.

Surfaced 2026-08-22 by the item-2 verification run.

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

## Q18. Generation drops the project that scoring worked hardest to include — RESOLVED (R23)

**Fixed same day — see R23.** The drop now ranks on the composite selection
already published. Measured on the frozen 20: 4/20 final project sets change,
and the number of projects dropped across the run falls from 6 to 2 — every
change is a drop that should not have happened. See Q20 for the half of this
that is not fixed.

The original entry follows.

### Original

Found while running the R21 comparison (2026-08-22). Ramp, "Mobile Engineer,
Android", against the hand-tuned profile:

```
sleeptracker  emb=0.58 kw=0.13 cond=0.20 imp=0.00 alw=0.00  ->  0.91
   Dropped lowest-priority project for depth: sleeptracker_mobile_sleep_logging_app
```

The mobile project earned the **full 0.20 conditional bonus** — the exact
3-hit maximum R14 was built to produce, from `mobile app`, `android` and
`mobile development` — giving it **0.91, the highest composite of any
project**. Generation then dropped it, and the resume sent to an Android role
contains no mobile work at all.

**Cause.** `_drop_weakest_project_for_depth()` ranks by
`importance_weight + proj_scores[pid]`, and `proj_scores` is
`EmbeddingScore.project_scores` — *raw embedding similarity only*. The keyword
and conditional terms that selection used are not in that number. Sleeptracker
embeds at 0.58 and is tier `low`, so it ranks last on a scale that cannot see
why it was chosen. The drop then fires because the weakest is `low` and
something else is `high`.

**Why this matters more than one bad resume.** It silently defeats R14 for
precisely the case R14 exists to serve: a component that is not semantically
close to the JD but is *specifically* relevant to it. The stronger the
trigger evidence, the more likely selection promotes a low-embedding project
into the set — and the more certain this stage is to throw it out.

**The fix is probably one line** — rank on the composite the selector already
computed rather than re-deriving a weaker one — but the composite is not
currently carried into the generation payload, so it needs threading. Measure
against the baseline before and after; this changes selection output.

## Q20. A rescued project arrives with one bullet — RESOLVED (R27)

**Fixed — see R27.** Allocation now ranks on JD fit rather than raw embedding,
and strong trigger evidence promotes a `low` tier to `medium` for depth.
Measured: 4/20 allocations change from the ranking fix, 6/20 with promotion.
**The framing in the original entry was wrong** — the one-bullet cap was not
the binding constraint, the ordering was; see R27.

The original entry follows.

### Original

R23 stopped generation discarding the JD-relevant project. It did not give it
room. On the Ramp Android role the mobile project now survives — and renders
with **one bullet**, because `_allocate_with_importance()` hard-caps
`low`-importance components at `_LOW_MAX_BULLETS` regardless of how they
scored.

That allocation ranks on `importance_weight + embedding_similarity` — the same
wrong number R23 removed from the drop decision, still in place one function
below. It was left alone deliberately: changing inclusion and depth in one
commit makes the measurement uninterpretable, and the importance weight (0/1/2)
dominates the embedding term (~0.6) there in a way it did not in the drop.

Two questions, and they are not the same:

1. Should allocation rank on the composite too? Probably, for R23's reasons.
2. Should a `low`-importance component still be capped at one bullet when the
   JD specifically called for it? The cap encodes "this is not central to your
   story", which is a statement about the *user*, not about the job. A trigger
   firing three times is the system saying this particular employer disagrees.

Worth measuring together, and after a fresh baseline rather than before.

## Q22. The board accumulates; the gates only run once — RESOLVED (R62)

**Status:** Resolved 2026-08-25 — see R62. The third option below, with one
change: the version is **derived from the gate's own source plus the profile
fields it reads**, rather than a constant somebody bumps. A version you have to
remember to update is the same shape as the field nobody read (R31) and the
flag nobody consulted (R61), and this project has now shipped that bug twice.

The original entry follows.

Every gate this project has built — R54's experience floor, R55's country
check, R56's eligibility — runs **between enrichment and analysis**. That is
the right place for a pipeline and the wrong place for a board, because the
board is a store that accumulates and the gates fire once, at the moment a job
is first scored.

So a gate shipped on Tuesday never sees a job scored on Monday.

**Measured, immediately after R61's purge:** of 69 scored jobs in the store,
**26 (38%) would be excluded by the gates as they stand today** — and they hold
the entire top of the board:

    55.8  Samsara       People Analytics AI Engineer     8+ years
    55.3  Samsara       Finance & Strategy AI Engineer   8+ years
    54.6  Databricks    AI Engineer - FDE                excludes new grads
    54.5  Scale AI      Forward Deployed SWE, Public     5+ years
    54.3  Affirm        Software Engineer II, Fullstack  5+ years

Every one of those is a posting R54 was written to remove, sitting at the top
of the board because it was scored before R54 existed.

**The options, none obviously right:**

- **Gate at read time.** Always current, no migration, and the store already
  holds `full_jd` so the gate has what it needs. Costs a regex pass per row
  per page load — free at 107 rows, not free at the scale a public board
  implies.
- **Sweep on demand.** Cheap reads, one pass after each gate change. Goes
  stale again the moment the next gate ships, which on this project's history
  is roughly weekly.
- **Store the verdict with a gate version**, recompute only when the version
  moves. Correct and the most machinery.

**What it must not do:** reuse `status`. That column is what the *user*
decided, and R47 exists because conflating a system decision with a human one
is a mistake this project already made once.

**Related:** the same shape as the R61 purge — code improvements do not reach
data already on disk. Worth asking, when the next gate is written, how it
reaches the rows that already exist.

---

## Q21. One skills slot changes between resumes, and picks the wrong thing — RESOLVED (R59)

**Status:** Resolved 2026-08-25 — see R59. Both halves this entry called
tangled turned out to be one thing: nothing ranked a skill by whether the page
supports it. The instability was a symptom, not a second problem — a line
ordered by the master's listing and then truncated by a character cap changes
with whatever else lands on the line.

The entry guessed that "within a category the order looks like master order
rather than match count", and asked for that to be confirmed before assuming.
Confirmed: non-JD-matching skills filled in master order exactly.

The original entry follows.

The `AI / ML & Data` category has thirteen entries in the master and six slots
in the output, so eight of the thirteen are dropped every time. On five of the
eight resumes the line ends `scikit-learn, XGBoost, NumPy`; on three — both
Experian postings and Scale AI — it ends `scikit-learn, XGBoost, OpenAI Gym`.

`OpenAI Gym` is real: it comes from a reinforcement-learning project in the
master. But none of those three JDs mention reinforcement learning, and the
skills it displaced (`Pandas`, `NumPy`) are named in most of them. So the last
slot is being spent on the least relevant candidate available, and it moves
between resumes for reasons the JD does not explain.

Two things are tangled here and only one is a bug:

- **The selection.** Categories are ordered by JD match count (R-era code in
  `_build_skills_section`), but *within* a category the order looks like master
  order rather than match count. Worth confirming before assuming.
- **The instability.** Even a correct selection that changes per JD is a
  feature, not a defect — the section is supposed to be tailored. What makes
  this read as wrong is that it changed *towards* the less relevant item.

Small, and visible on every resume, which is the argument for doing it: a
recruiter reading two of these side by side sees one inconsistency and it is
this one.

---

## Q19. Template defaults are stricter than the only tuned profile — RESOLVED (R24)

**Fixed — see R24.** `scoring_threshold` defaults to 40 in the schema and is
gone from the template, so the constant lives in code as
`migration_plan.md` says INTERNAL fields should. **One claim in the original
entry below was wrong**: `max_jobs_to_generate` is not shipped as `null`, it
is simply absent, and the schema default of 10 covers it. There was no funnel
hazard.

The original entry follows.

### Original

Also from the R21 comparison. `user_profiles/template.json` ships
`scoring_threshold: 50`; the live profile uses `40`. Ramp scored **48.4**, so
a bootstrapped user loses that job at the funnel before any tailoring happens,
while the tuned user gets a resume for it.

`overall_score` is embedding-derived and profile-independent, so this is
purely the threshold, not a scoring difference. Two things follow:

- The template ships a number nobody validated, and the one profile that has
  ever been tuned in anger disagrees with it by 10 points. `migration_plan.md`
  calls `scoring_threshold` INTERNAL — "default 50, internal calibration" —
  which is only defensible if the default is calibrated against something.
- The template also ships `max_jobs_to_generate: null` where the plan
  specifies a default of 30.

Worth checking the other INTERNAL defaults the same way: a bootstrapped
profile is the product, and every unvalidated constant in it is a decision
made on nobody's behalf.

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

## R20. What happens to users with no LaTeX toolchain?

**Decision:** (August 2026) Ship the `.tex` always, the PDF when `pdflatex`
is present, and a plain install pointer when it is not. No bundled TeX
distribution. No Overleaf integration for now.

**The roadmap's premise was stale, and rejecting it is most of the
decision.** Item 7 argued that "asking a non-technical user to install
MiKTeX is probably fatal to adoption." That sentence predates — or at least
never reconciled with — item 0's local-app decision. A local app already
asks the user to install Python, clone a repo, obtain their own Gemini API
key and place it in a `.env`. Against that, installing MiKTeX is not a cliff;
it is a fifth step for someone who has cleared four harder ones. The
fatal-to-adoption argument is a *hosted-app* argument that got carried over
when the product shape changed underneath it.

**What survives the reframing is narrower but real.** A user without LaTeX
gets a `.tex` file, and most applications want a PDF upload — so that user
cannot actually submit. That is the genuine gap. It is just much smaller than
"fatal", and it has an escape hatch that costs nothing to leave open.

**Why not bundle.** TinyTeX or MiKTeX-basic adds 100–200MB to distribution
and packaging work on three platforms, and still fetches `titlesec` and
`marvosym` over the network on first compile, because the template needs
them and neither base install carries them. Paying a packaging tax that does
not even remove the network dependency is the worst trade available here.

**Why not Overleaf yet.** An "Open in Overleaf" button would close the
can't-submit gap without any local install, by POSTing the document source
from the user's browser. It is the right thing to build *if* the gap turns
out to bite. It is not the right thing to build before a single external user
has hit it, and the mechanics need verifying against Overleaf's current API
rather than assumed.

**This item was on the roadmap ahead of the UI for a good reason, and that
reason still holds** — the answer determines a screen, not a button. It just
determines a simpler screen than item 7 expected:

```
pdflatex found:      [Download PDF]  [Download .tex]
pdflatex missing:    [Download .tex]  ⓘ Install MiKTeX or TeX Live for PDFs
```

**Nothing needs building to detect the case.** `find_pdflatex()` (R8) resolves
the binary once per run, and `PdfResult.status` already separates `skipped`
— no engine on this machine — from `failed` and `timeout`. The UI branches on
a signal that exists. What item 8 owes this decision is the second line of
that sketch, and an install pointer that names both distributions rather than
just MiKTeX.

---

## R21. Deriving conditional triggers, and what the measurement would not say

**Decision:** (August 2026) Shipped. `derive_conditional_triggers()` and
`merge_conditional_triggers()` in `tools/profile/derivation.py`, wired into
`scripts/init_profile.py`. A bootstrapped profile now carries 17 rules and 104
triggers where it used to carry none. 13 new tests.

### Three departures from the algorithm in `migration_plan.md`

Each came from looking at what the resume actually produces, not from taste.

**1. Genericness is corpus-relative, so `_GENERIC_TERMS` is the wrong
instrument on its own.** The plan says to filter candidates through the
scorer's generic-term set. That set holds words generic *in the abstract*
("backend", "api"). It cannot know that on this resume `python` sits in 7 of
13 project tech stacks — and a trigger carried by more than half the pool
moves every component together and separates none of them, which is the only
job a trigger has. So terms are also dropped by document frequency within
their pool.

**2. The component name is not a trigger source, though the plan proposes
it.** Names do yield the occasional good trigger — "spotify", "minecraft" —
but they are free text, and splitting the same 13 projects also yields
`resume`, `computer`, `object`, `search`, `engine` and `image`. Those are rare
across the resume, so the document-frequency filter sees nothing wrong with
them. They are common in *job descriptions*, which is the corpus that decides
whether a trigger fires and the one not available at derivation time. Every JD
says "resume" and "Computer Science"; `object` matches "object-oriented".

Dropping the name buys a property worth more than the terms it costs: every
derived trigger is a term from `TECH_KEYWORDS` or the user's own skills
section, so no free-text word can reach a trigger list at all.

**3. Compounds are pruned against their own parts.** `split_skill_list`
deliberately emits both "oauth 2.0" and "oauth", and the keyword vocabulary
supplies the short form too. R14 made the trigger term score per-hit, so
keeping the pair scores two hits for one listed technology. The shorter term
is kept, and it fires wherever the longer one would.

### The measurement, and the part that did not work

Replayed against `baselines/2026-08-21-pre-step7` — 20 JDs, verified against
its manifest first, embeddings computed once and reused so every
configuration saw identical inputs.

| config | differs from hand | vs. empty map |
|---|---|---|
| empty map (`none`) | 8/20 | — |
| derived, ratio 0.3 / 0.4 / 0.5 | 8/20 | 7/20 |
| derived, no ratio filter (plan as written) | 8/20 | 4/20 |
| domain terms harvested from bullets | 8/20 | — |

**Derivation does real work**: it changes 7 of 20 selections against an empty
map. **It does not converge on the hand-tuned profile**: 8/20 either way. It
fixes two JDs and breaks two others.

**A metric that looked finer and was not.** Counting mismatched component
slots rather than JDs gave exactly 16 in every row — including for pure noise.
That is not five coincidences: it is 2 x the JD count in all cases, because
every difference is a single one-for-one swap. The slot metric is a linear
function of the JD metric and carries no extra information. Recorded because
it looked like a better instrument for about ten minutes.

**Harvesting domain terms from bullets was tried and rejected.** The missing
signal is visible — hand-authored triggers for Diagnosify are `healthcare`,
`medical`, `clinical`; derivation reaches `distilbert`, `flask`, `pytorch`.
So bullets were mined for terms unique to one component, with a stoplist of
words appearing in half the baseline JDs. It surfaced the right kind of thing
(`clinical`, `ospf`, `bgp`, `accessibility`) buried in far more of the wrong
kind (`approaches`, `compare`, `configured`, `concrete`), and scored the same
8/20. Free-text harvesting reintroduces exactly the hazard departure 2 avoids.

**How much the 0.4 ratio is worth.** Less than it looks. 0.3, 0.4 and 0.5
produce identical selections, because only `python` is common enough for any
of them to drop. 0.4 is the middle of an indistinguishable band, not a
measured optimum. The filter *existing* is justified on principle; its exact
value is not justified by anything yet.

### Why agreement-with-hand could not settle this

Two reasons, and they were foreseeable:

- **Derivation structurally cannot reach the hand-authored vocabulary.** Those
  triggers are domain words — `radiology`, `ehr`, `ospf`, `pathfinding` — that
  appear in neither the tech stack nor the tech keyword list. Perfect
  agreement was never available, so distance-from-hand measures the gap
  between two vocabularies as much as it measures quality.
- **The hand-tuned profile is not ground truth about job fit.** It is one
  person's tuning. Item 2's verification run found the opposite assumption
  wrong once already: the Palantir swap looked worse on a skim and the numbers
  said it was better.

**What would actually validate this**: an item-2 style run — generate
resumes from a bootstrapped profile, read the PDFs, judge whether the selected
components suit the JDs. That is a qualitative check, and it is the same
instrument that settled item 2. It is not scheduled yet.

**A correction to item 5's own numbers.** It cited R14's finding that removing
conditionals changes 12/20. Measured now, empty-map vs hand is 8/20. The
difference is R18: the substring fix changed keyword scoring underneath, so
the older figure no longer describes current code.

### Why ship it anyway

Because the risk is bounded and the alternative is nothing. `merge_conditional_triggers`
gives explicit rules priority per component, so no hand-tuned profile changes
behaviour — this reaches only components whose profile says nothing, which for
a bootstrapped user is all of them. R17's validation confirms every derived ID
resolves to a real component. The honest summary is that a bootstrapped user
goes from no trigger signal to some trigger signal, and whether that is better
is not yet known.

---

## R22. Threading the API key instead of reading the environment

**Decision:** (August 2026) Done. `resolve_api_key(explicit=None)` in
`config.py` is the one place that resolves a key; `api_key` is a parameter on
`JobScoutOrchestrator`, `AnalysisAgent`, `GenerationAgent`, `ResumeParser`,
`embed_resume_components`, `score_job_with_embeddings` and `_get_embedding`.
Every default is `None`, meaning "no opinion" rather than "no key", so CLI
behaviour is byte-identical: nothing passed, environment used.

**Why a parameter and not a module-level setter.** A setter would have been
fewer lines, and it is the wrong shape. A UI that collects a key would have to
write it somewhere global for the pipeline to see it — in the worst version,
back into `os.environ` — which makes one user's credential process-wide,
order-dependent, and impossible to scope to a single run. A parameter that
defaults to the environment gets the UI what it needs while leaving the CLI
untouched.

**Empty string, not None, is the "nothing found" answer.** Callers can test it
plainly, and a missing key can never reach the API as the literal string
"None" — which would produce a puzzling auth error rather than an obvious
absence. An empty *explicit* key falls through to the environment too: a UI
form the user left blank means "no opinion", not "use no key".

**One site was deliberately left alone.** `scripts/check_models.py` still
reads `os.getenv` directly. It is a hand-run probe for checking which Gemini
models are alive, it is never called by the pipeline, and a UI has no path to
it. Threading a parameter into a script whose only caller is a human would be
ceremony.

**Tested by injection, not just by unit.** The resolution rules are unit
tested, but the test that matters replaces `genai.Client` with a fake and
asserts an explicit key reaches it *while a different key sits in the
environment*. That is the actual failure this work exists to prevent, and it
would pass trivially if the plumbing silently fell back to the environment
somewhere in the middle.

---

## R23. The depth drop ranked on the wrong number

**Decision:** (August 2026) Fixed. `_decide_project_count()` ranks candidates
on the composite score selection already computed and publishes in
`score_breakdown`, instead of re-deriving `importance_weight +
embedding_similarity`.

**The failure, exactly.** Ramp, "Mobile Engineer, Android", hand-tuned profile:

```
sleeptracker  emb=0.58 kw=0.13 cond=0.20 imp=0.00 alw=0.00  ->  0.91
   Dropped lowest-priority project for depth: sleeptracker
```

Full 0.20 conditional bonus — the 3-hit maximum, from `mobile app`, `android`
and `mobile development` — and the highest composite of any project. Dropped,
for an embedding of 0.58 and a `low` tier. The resume sent to an Android role
contained no mobile work.

**Why it was structural rather than unlucky.** The whole point of R14's
per-hit triggers is to promote a component that is *specifically* relevant
without being *semantically close* — that is the gap embeddings cannot cover.
Such a component has, by construction, a low embedding score. So the stronger
the trigger evidence that got a project selected, the more certainly this
stage ranked it last. The two mechanisms were pulling against each other, and
the later one won silently.

**The fix needed no plumbing**, contrary to the first read. `select_components`
already returns `score_breakdown` with every term and a `final`, and
`_canonicalize_selected_components` copies it through, so the composite was
sitting in `analysis_results.json` — in the frozen baseline's copy too —
unread. The composite already contains the importance term, so it is used
alone; adding `_IMPORTANCE_WEIGHTS` back would count importance twice.
`proj_scores` stays as a per-component fallback.

**Measured on the frozen 20.** 4/20 final project sets change. Projects
dropped across the run falls from **6 to 2**, and all four changes are a drop
that should not have happened — `sleeptracker` three times, `ubereats_ux_redesign`
once.

Note what that means: the depth optimisation now fires a third as often. That
is the honest cost of the fix and it is not obviously bad — it was firing
mostly on projects the old ranking had mis-ordered — but "we made a feature
mostly stop happening" deserves saying out loud rather than being buried in a
win.

**What this does not fix: see Q20.** The rescued project renders with one
bullet, because bullet allocation still ranks on the same wrong number and
hard-caps `low` importance at one. Inclusion is fixed; depth is not.

**Found by running the R21 comparison, not by looking for it.** Worth noting
for how future work gets scheduled: the bug had been live through every
scoring change since R14, invisible to all of them, because every measurement
so far compared *selections* and this stage runs after selection. Reading a
PDF found it in one afternoon.

---

## R24. The scoring threshold was a quality bar that could not grade

**Decision:** (August 2026) `scoring_threshold` defaults to **40**, set in
`AgentPreferences` rather than in `user_profiles/template.json`, which no
longer carries the field.

**What the numbers actually look like.** Over the frozen 20-JD baseline:

```
range 44.8 - 57.7    median 53.0

threshold 40 -> 20/20 pass      threshold 50 -> 15/20 pass
threshold 45 -> 19/20 pass      threshold 55 ->  4/20 pass
```

Every score lands in a 13-point band. That is not a defect in the scorer — it
is what embedding a new-grad SWE resume against new-grad SWE postings
produces, because they genuinely are all fairly similar. The consequence is
that a threshold at 50 does not separate good matches from bad ones, it slices
through the middle of a dense cluster: the jobs it cut scored 48.3-49.3
against survivors at 50.4-51.1, a difference of about one point. Ramp, at
48.4, was dropped this way while being a job the tuned profile happily wrote a
resume for.

**So the threshold is a floor, not a grader, and 40 is the honest setting.**
Worth stating plainly rather than dressing up: against this distribution a
threshold of 40 is close to inert. That is the correct outcome given the
evidence, not a calibration. What actually controls output volume is ranking —
`max_jobs_to_generate` takes the top K by score, which degrades gracefully
when scores are clustered in a way a hard cut does not. A threshold earns its
keep only against genuine mismatches, and nothing in the observed range was
one.

**Why the constant moved into code.** `migration_plan.md` lists
`scoring_threshold` under INTERNAL and flags it as a cleanup opportunity —
"should be code constants". It was shipping in the template as a number nobody
had validated, which is the worst of both: exposed enough to look like a
setting, unexamined enough to be wrong. The tuned profile still overrides it
explicitly, and that keeps working.

**A correction carried over from Q19.** That entry also claimed the template
shipped `max_jobs_to_generate: null` against the plan's stated default. It
does not — the key is absent, and `AgentPreferences.max_jobs_to_generate = 10`
supplies it. The comparison that produced the claim used `dict.get()`, which
cannot tell an absent key from a null one. No hazard existed and nothing
needed fixing there.

---

## R25. The UI is Streamlit, kept as a view layer

**Decision:** (August 2026) Streamlit, already pencilled into
`requirements.txt` under "Optional: UI" and now committed to.

**The deciding fact is not in this repo, which is why it is written here.**
The hosted tier, if it happens, is planned as **React + FastAPI**. That
intent exists — it is how JobScout is described outside the project — but it
appears nowhere in the code, `requirements.txt`, `migration_plan.md` or this
document. It is nonetheless the fact that settles the choice, so recording it
is the point of this entry. R12 and roadmap item 0 were both the same shape:
something load-bearing, invisible from inside the repo.

**Why it settles it.** A hand-written FastAPI + HTML/JS UI looks like the
disciplined option and is not. Split it in two: the HTTP boundary is
genuinely reusable under a later React frontend, and the pages are not — they
get deleted the day React arrives. The pages are where nearly all the work
sits. So that option pays full price for the half that gets thrown away.
Streamlit does not pretend to be the eventual frontend, so nothing is lost
when it is replaced.

A terminal wizard was also considered and rejected in one line: item 8 exists
to serve someone who will not use a CLI, and a prompt flow is the CLI with
more ceremony.

**The costs are real and aimed at the wrong things.** Streamlit adds roughly
50MB and caps layout control. Against a local-first, bring-your-own-key app
with three screens, nobody is measuring the install size, and R20's results
screen is a table with download buttons — inside Streamlit's range even if it
is not pixel-exact.

**The condition that makes this a good call rather than a trap:** Streamlit
stays a **pure view layer**. It loads a profile, calls the orchestrator, and
renders what comes back. No filtering, ranking, scoring or path-building in a
callback or in `session_state`. Enforced structurally by what the app file is
allowed to import:

```python
# app.py imports only these
from agents.orchestrator import JobScoutOrchestrator, StageProgress
from scripts.init_profile import build_profile
# nothing from tools/
```

If business logic leaks into the UI, the eventual React port becomes a rewrite
instead of a re-skin. This is the same discipline R22 already forced by making
the API key a parameter, so it is not a second tax.

## R26. Progress and checkpoints had no shape a UI could consume

**Decision:** (August 2026) `run()` takes `on_progress` and `on_checkpoint`.
Both optional; omitting them preserves CLI behaviour exactly.

**Two problems, and the second was worse than the first.**

The known one: `run()` was a single blocking call returning a `Dict`, with the
four stages as private sequential methods. Progress existed only as log lines
— fine in a terminal, unusable from a UI, and a multi-minute pipeline that
reports nothing is not something to put behind a spinner.

The one found while looking: checkpoints were literal stdin reads.

```
orchestrator.py:439   response = input("Continue to next stage? (y/n): ")
orchestrator.py:467   response = input("Continue to generation? (y/n): ")
```

and `AgentPreferences.checkpoint_after_scoring` defaults to **True**. A
bootstrapped profile is exactly what the UI produces, so the default path
would have hung the app on a prompt nobody could answer. Worse, declining
called `sys.exit(0)` — a library killing its host process.

**The shape.** `StageProgress(stage, done, total, message)` with a `fraction`
property that returns 0.0 rather than dividing by zero, because discovery
cannot know its total until it has looked. `_emit()` swallows exceptions from
the callback: a UI failing to draw a progress bar must not lose a run that has
already spent API quota. Checkpoints route through `_request_checkpoint()`,
which asks the callback when there is one and falls back to the terminal
prompt when there is not; the prompts now **return a decision** instead of
exiting, and declining raises an internal `_CheckpointStop` that `run()`
catches, saves state, and returns from.

Item-level ticks come from the two slow stages — `analyze_jobs()` and
`generate_resumes()` each take an `on_progress` and tick per item. Discovery
and enrichment report start and finish only, since neither exposes per-item
structure worth threading.

Verified end to end: 24 ticks over a replay run (analysis 0..20, generation
0..2), both checkpoint answers honoured without stdin being touched, and the
CLI producing byte-identical results to before the change. 12 new tests,
including one that replaces `builtins.input` and asserts it is never called
when a callback is supplied.

---

## R27. Bullet allocation had R23's bug, and a wrong diagnosis on top of it

**Decision:** (August 2026) `_allocate_with_importance()` ranks on **JD fit**
— the composite with the importance term removed — and `_promote_on_evidence()`
lifts a `low` tier to `medium` when this JD's triggers fired twice or more.

**Half of this is R23 again, one function further down.** Allocation ranked on
`importance_weight + embedding_similarity`, the same number R23 had just
removed from the drop decision. JD fit is used rather than the full composite
because allocation adds the tier weight itself; passing the composite would
count importance twice. Removing the term exactly (`final - importance`) is
cleaner than approximating around it.

**The other half was a diagnosis I got wrong, and the measurement caught it.**
Q20 framed the problem as the `_LOW_MAX_BULLETS = 1` hard cap: a project
rescued by R23 rendered with one bullet because `low` components are frozen
there. The obvious fix was to make a trigger-backed `low` component *eligible*
for extras.

Measured, that changed **nothing** — zero allocations moved. The cap was never
the binding constraint. A `low` component ranks on
`_IMPORTANCE_WEIGHTS['low']` = 0.0 against 1.0 and 2.0, so it sits last among
eligible components and the others absorb every spare bullet before it is
reached. Eligibility without standing is not eligibility.

What works is promoting the **tier**, which is also the more honest statement
of the argument. An importance tier is a claim about the *user* — "this is not
central to my story". A conditional trigger firing two or more times is the
system observing that *this employer disagrees*. Those are different claims,
and for one specific job the second one is about the job in front of you.

Two hits is the threshold, not one: R14 exists because a single incidental
mention used to carry a component. Promotion stops at `medium` — the evidence
says "this matters here", not "this is your strongest work".

**Measured on the frozen 20**, replayed from a stored analysis run rather than
re-embedding:

| change | allocations moved |
|---|---|
| JD-fit ranking only | 4/20 |
| ranking + tier promotion | 6/20 |

The two promotions are both well-evidenced: Ramp / `sleeptracker` at cond=0.20
(the full 3-hit bonus) and Warp / `ubereats_ux_redesign` at cond=0.14, each
1 → 2 bullets.

**Why this is low risk.** `total_budget` is fixed by component count
(`proj_budget_table`), and allocation distributes exactly `total_budget -
len(components)` extras. So promotion redistributes bullets and cannot create
them — the one-page constraint R9 enforces is untouched. There is a test
asserting the totals match before and after promotion, because that invariant
is the whole reason this change is safe.

**The Ramp resume, end to end across R23 and R27:** the mobile project is
selected (always was), survives generation (R23), and now renders with 2
bullets instead of 1, with `search_engine` giving one up and the project total
still 7.

---

## R28. The measuring instrument was also what exhausted the quota

**Decision:** (August 2026) `TextEmbeddingCache` — content-addressed, keyed on
`(model, task_type, text)` — wired into `_get_embedding()`, the single point
every embedding in the system passes through.

**The problem was structural, not incidental.** `embedding_cache.py` caches
the resume's own component vectors. Nothing cached the other side, so every
replay of the frozen baseline re-embedded all 20 job descriptions. That
baseline is what R14, R15, R21, R23 and R27 all rest on, and reaching for it
cost ~20 API calls each time. Five comparisons in one afternoon — an ordinary
amount for a day spent measuring — exhausted the free-tier daily quota. A
method that says "measure before and after every change" cannot be built on an
instrument that gets more expensive the more you use it.

Measured directly: 2.30s uncached, 0.008s cached, identical vectors.

**All three key components are load-bearing.** `model`, because vectors from
different models are not comparable — R11's exact lesson, where the resume
cache shipped without it. `task_type`, because `RETRIEVAL_QUERY` and
`RETRIEVAL_DOCUMENT` produce genuinely different vectors for identical text.
And `text` exactly as sent to the API, truncation included: keying on the
untruncated string would give two inputs that truncate identically two entries
for one identical call.

**Then the test suite caught the change breaking a test, and the breakage was
worse than the failure.** R22's injection test replaces `genai.Client` with a
double returning `[0.1, 0.2]`. With a cache in front of the client, that test
stopped reaching the client at all — and, before failing, **wrote its 2-element
stub into the live cache directory under the real model name.** A subsequent
real run embedding the string `"text"` would have received a 2-dimensional
vector and produced cosine similarities from it without complaint.

That is this project's recurring bug shape once more: not an error, a
plausible number. So the fix is not only "isolate the test":

- The test now points the module's cache at a disabled instance and restores
  it afterwards.
- `TextEmbeddingCache` takes an expected `dimensions` and **refuses to store,
  and deletes on read, any vector of the wrong length.** Wired from
  `EMBEDDING_DIMENSIONS`. A wrong-length vector is always a bug — a stubbed
  double, a truncated write, a model change that slipped the key — and it is
  precisely the kind that never announces itself.
- Empty vectors are already refused, because `_get_embedding` returns `[]` on
  API failure and caching that would turn one transient 429 into a permanent
  wrong answer.

**A latent bug fixed in passing:** `tools/cache/__init__.py` listed `JobCache`
in `__all__` without importing it, so `from tools.cache import *` raised
`AttributeError`. The package now exports what it advertises.

16 new tests.

---

## R29. The pipeline crashed after succeeding, printing a party emoji

**Decision:** (August 2026) `_console_print()` in the orchestrator: `print()`
that drops an unencodable character rather than the run.

`main()` reconfigures stdout to UTF-8, with a comment saying it does so "rather
than crashing the pipeline". That covers the CLI and nothing else. Called as a
library — from `app.py`, from a test, from a notebook — the orchestrator
inherits the host's encoding, which on Windows is cp1252.

The failure shape is the worst available. Discovery, enrichment, analysis and
generation all succeed. The resumes are on disk. The API quota is spent. Then
`_print_final_report()` raises `UnicodeEncodeError` on the completion banner
and `run()` propagates it to the caller, who sees a failed run and a stack
trace pointing at an emoji.

Found by writing `test_pipeline_integration`, which runs the orchestrator the
way the UI does. It was the first thing that test caught, before it had
asserted anything.

A library must not mutate its host's stdout, so the encoding is handled per
call rather than by moving `reconfigure` down. 47 console prints in the report
and checkpoint paths now route through it.

## R30. The UI could silently destroy a hand-tuned profile, and did

**Decision:** (August 2026) The first screen refuses to overwrite an existing
profile without an explicit, separate confirmation.

`app.py` called `create_profile(resume_path, name, force=True)` —
unconditionally. `create_profile` raises `FileExistsError` for exactly this
case and the UI bypassed it. Worse, the profile-name field is pre-filled from
`session_state.profile_name`, so selecting an existing profile and then
uploading any resume put that profile's own name in the field. Upload, click
**Build my profile**, and a hand-tuned profile is gone with no prompt and no
undo.

**This is not hypothetical.** `user_profiles/yash_pathak.json` was rebuilt on
2026-08-22 at 17:56, during UI testing. The evidence is unambiguous: derived
trigger descriptions ("Auto-derived from tech stack and bullet keywords"),
`always_include` and `high_priority` emptied, importance tiers matching R15's
derived pattern rather than the tuned ones, `exclude_keywords` down from 12 to
the template's 5, and `scoring_threshold: null` — a field the template only
lost at 17:25 that same day in R24. Every hand-authored JD trigger was
replaced: `radiology`, `ehr`, `clinical nlp`, `ionic`/`android`/`mobile
development`, `ospf`/`bgp`/`isis` — the domain vocabulary R21 established that
derivation structurally cannot reach.

**Measured cost, replayed over the fresh 20-JD baseline:** project selection
differs on **11 of 20** JDs. Experience selection is unchanged as a set,
though ordering moves — on the Anduril posting `tutor_com` outranks
`sorenson_communications` by 0.02, decided by a single derived trigger hit
worth 0.07, which is the sort of thing the hand-authored `rarely_include` rule
for tutoring existed to prevent.

**There is no backup.** Profiles are gitignored, so there is no git history,
and `state.json` records `profile` as the *name* only, not the contents. A
reconstruction from this session's record is at
`user_profiles/yash_pathak_restored.json`: every trigger list recovered
verbatim, importance tiers recovered exactly (the comparison run on 08-22
enumerated every tier that differed from derived, so derived-plus-overrides is
complete), and rule `description` strings mostly lost and marked as such.

**Two things this argues for beyond the guard:**

- Profiles are the only artefact in this project that is both hand-tuned and
  unbacked. Everything else is either derived, in git, or reproducible.
  `init_profile.py` writing a timestamped copy before overwriting would have
  made this a non-event.
- A destructive default in a UI is worse than the same default in a CLI. The
  CLI has always required `--force`; the UI passed it for the user.

---

## R31. `rarely_include` deleted rather than finished

**Decision:** (August 2026) Removed from the schema, from
`get_experience_selection_rules()`, from the loader's summary output, from
`validation.py`'s ID-keyed field list, and from the profiles on disk.

Q16 found it computed on every call and read by nothing: `result['rarely']`
was populated by matching triggers against the JD exactly as `conditional`
is, then consumed only by two `print` statements. Scoring never saw it. The
live profile carried two rules — `exp_outlier` and `exp_tutor` — which
resolved to real components and did nothing.

**Deleted rather than wired up, for two reasons.** `component_importance`
already expresses "rarely show this", and since R15 it is derived
automatically, so the feature was redundant before it was dead. And the
intended semantics were never written down — a penalty when the rule fires? a
penalty when it does not? — which is most of why it was never finished.
Inventing them now would be adding a scoring term on a guess, which is the
opposite of how every other term here was settled.

**The trigger was the UI.** A form field for a setting that does nothing is
worse than no field, and the next block of work is exactly that editor. This
had to go before the screen was built, not after.

**No migration needed.** Pydantic ignores unknown fields, so a profile still
carrying `rarely_include` loads fine and simply drops it. The key was stripped
from the profiles on disk anyway, so it cannot read as a live setting.

**One casualty worth naming:** the tutoring rule restored an hour earlier in
R30 — "only show tutor.com for education-focused roles" — is gone with it. It
never fired, so nothing changes behaviourally. What actually keeps tutor.com
down is its `low` importance tier, which the same restore brought back.

---

## R32. The UI grew the three things that made it a demo

**Decision:** (August 2026) Previous runs, a review-before-generating step,
and a component tuning screen. `app.py` is still a view layer — the boundary
is now enforced by `test_ui_contract`, not just asserted in R25.

**Previous runs.** Resumes outlive the session that made them; Streamlit's
`session_state` does not. Closing the tab lost every download link to files
still sitting in `outputs/`. `previous_runs()` and `load_run()` on the
orchestrator list past runs and reload one into the results view. Runs whose
state file cannot be read are skipped rather than raised on: a half-written
file from an interrupted run should cost one row, not the screen.

**Review before generating.** Generation is the expensive stage — one or two
Gemini calls per resume — so it is the one worth pausing before. Implemented
as two runs rather than a blocking callback, because a callback that waits
cannot work inside Streamlit's rerun model. Phase one declines the checkpoint
after scoring and returns its state; phase two replays from the enriched jobs
phase one already wrote, exposed as `enriched_jobs_file` so the UI never
builds a path. R28's cache makes re-scoring free, which is what makes running
twice reasonable at all.

**The integration test earned its place immediately.** `checkpoint=True` arms
a checkpoint at *every* stage, and the first version declined all of them —
so the run halted after Discovery, before anything was scored, and the review
screen would have shown zero jobs. The callback now declines only the
`analysis` stage. That bug is invisible by reading and obvious by running.

**Component tuning.** The screen R21 has been asking for since it was written.
Derivation reaches a component's tech stack — `ionic`, `capacitor` — but never
the domain words a posting uses, `android` and `mobile app`, because the
resume does not contain them. No amount of cleverness closes that from the
resume alone; a person closes it in ten seconds. Each component gets its
importance tier and its trigger list, editable.

`read_component_rules()` and `write_component_rules()` sit in
`init_profile.py`, so the UI never learns that a profile is JSON on disk.
Writing touches only the two maps the screen owns, normalises and deduplicates
terms, preserves existing rule descriptions, and **removes a rule whose list is
emptied rather than storing an empty one** — an empty rule cannot fire and
looks identical to one that never matched, which is the silence R17 removed.

Verified end to end through the browser: `CLINICAL TRIALS` typed into the
editor arrived as `clinical trials`, the other eleven triggers were preserved
and sorted, the description survived, and `always_include`, `high_priority`
and every other component were untouched.

21 new tests.

---

## R33. Four design decisions for the Phase 2 frontend

**Decision:** (August 2026) Taken before any React work, because each one
changes what gets built underneath it.

**The app is a job board you live in**, not a run log and not a wizard. The
main view is a persistent list of matched jobs with scores, statuses and
resumes attached, filterable by role, score, date and status. This is the
decision with a data consequence: it requires the durable job store in item 12,
because everything today is per-run.

**Runs are background jobs.** `POST /runs` returns an id; progress streams over
SSE; closing the tab does not cancel the run. A multi-minute pipeline behind a
page that must stay open is the wrong shape, and this is also the form a hosted
tier would need. The orchestrator is already callback-driven (R26), so the
progress half of this is done.

**Resume import is fully confirmed.** Every extracted field — contact,
education, each experience and project with its bullets — is shown for
correction before anything is saved. Extraction from PDF/DOCX will misread some
resumes, and a silent misparse produces bad resumes until somebody notices. It
doubles as the moment the user sees what the system understood about them,
which is a better first impression than a spinner.

**The model backend is detected, then explained.** On first run: is Ollama
running, is there a key in the environment? Pick the best available, then say
plainly what was chosen and what it costs in quality, with a settings screen to
override. Not silent, because quality differs materially between the rungs; not
a mandatory choice screen, because most people do not yet know enough to
answer it.

---

## R34. Keyless discovery at any level

**Decision:** (August 2026) `tools/search/ats_search.py` reads public ATS
boards, and the seniority gate reads the profile instead of a constant.

**The gap.** Every source was narrow or keyed. `github_newgrad` needs no key
but is new-grad-only by construction — those curated repos have no general
equivalent. Serper and Adzuna reach any level and cost a key. So there was no
way to find a mid-level backend role without paying for search, which is
awkward for a project whose whole distribution plan is "costs the maintainer
nothing".

**Greenhouse, Lever and Ashby serve their customers' boards as public JSON.**
One request returns Stripe's 578 open roles across every department and level.
Seniority stops being a property of the source and becomes a filter applied
afterwards, which is the entire trick.

Two gains beyond being free:

- **The JD arrives with the job.** Greenhouse honours `?content=true` and
  Ashby returns `descriptionPlain`, so ATS listings skip Enrichment entirely —
  the slowest and most breakable stage. Measured: 4,900-character descriptions
  inline, in the same call.
- **First-party data.** No markdown tables, no continuation glyphs (R13), no
  redirect shims. The existing cache is 840 URLs and every one is a
  `jobright.ai` redirect.

**The seed list is verified, not plausible.** None of these APIs can enumerate
companies, so slugs must be known. 145 candidates were probed live; **86
returned jobs and 59 returned nothing** and were dropped. Every Lever slug in
the first draft was dead — the API was fine, the guesses were not. Shipping
the unverified list would have produced a source that silently found less than
it should, which is this project's recurring failure shape. `harvest_slugs()`
grows the list from any apply URL landing on a known ATS host, so it compounds.

**Filtering happens before the cap, and that is not a detail.** The first
working version returned Stripe's alphabetically-first roles: five account
executives. A company board is the whole company, so `roles` must narrow
before `max_results` truncates. Matching uses lookarounds rather than a word
boundary — `-` is a word boundary, which would let "Stack Engineer" match
"Full-Stack Engineer" while the full phrase failed.

**Then the source worked and nothing came out.** 80 of 120 found roles were
senior or staff, and `job_filter` excluded every one: *"Seniority too high
(senior/staff/principal without entry-level indicator)"* — a constant written
for one new grad, applied to everybody.

`job_preferences.seniority` had been on every profile since the schema was
written, holding `["new grad", "entry level", "junior"]`, and **was read by
nothing but a print statement.** The same dead-field shape as `rarely_include`
(R31), found the same way: by needing it. The gate now expands the profile's
levels through a synonym map, because profiles store levels ("new grad") and
ads phrase them a dozen ways ("recent graduate", "0-2 years", "University
Graduate").

**Measured, over 150 live ATS listings:**

| profile | kept | senior/staff titles |
|---|---|---|
| new grad, before the change | 42 | 0 |
| new grad, after | **42 (identical set)** | 0 |
| `seniority: [mid, senior, staff]` | 126 | 82 |

Byte-identical for the existing profile, and a senior user now sees senior
roles. 34 new tests.

**Extended the same day to five boards.** The original claim was "every major
ATS", and three were shipped. Workable and SmartRecruiters were added after
probing; **Breezy was evaluated and rejected** — one live board, three jobs,
not worth the code.

The five are not redundant, they cover different segments. Greenhouse and
Ashby are where venture-backed startups post. SmartRecruiters is where
enterprises do, and one company there dwarfs a whole startup segment: Bosch
lists 4,774 roles against Stripe's 578. Workable covers small and European
employers neither of the others reach. For "beyond new grad" that matters more
than raw counts — enterprise ladders are where mid and senior titles live.

**SmartRecruiters needed a different shape.** Its listing call carries no
description, unlike the other four. Fetching one per posting would mean
~4,800 requests against Bosch to then discard almost all of them, so
descriptions are hydrated *after* role filtering and *after* the cap — in
practice a handful of requests. A description that will not load leaves
`full_jd` empty and Enrichment scrapes it the ordinary way. It also exposes a
structured `experienceLevel`, which is better evidence than parsing a title,
and is not yet used.

**What this does not solve:** the job cache dedups by URL with a 7-day
expiry, so a second run over the same boards returns almost nothing. That is
correct for a run log and wrong for the job board R33 chose — see item 12.

---

## R35. Jobs now outlive the run that found them

**Decision:** (August 2026) `tools/jobs/job_store.py` — every job ever
discovered, keyed on apply URL, in SQLite at `data/jobs.db`.

**The pressure was R34.** Five ATS boards reach roughly 17,000 roles.
`job_cache` decided which of them the pipeline saw, and it forgets a URL after
seven days by design — so most of that discovery was being thrown away, and a
second run over the same boards returned almost nothing. That behaviour is
correct for a dedup tracker and wrong for the board R33 chose. A tracker is
built to forget; a board must never lose anything. Opposite intents, so a
separate file rather than a retention flag on the old one.

**SQLite rather than another JSON file.** Everything else here is JSON and
that is usually right, but this is the only artefact that grows without bound
*and* gets asked questions — R33's board filters by role, score, date and
status. Re-parsing a multi-megabyte document on every run to answer those is
the wrong shape, and `sqlite3` is standard library, so it costs no dependency.

**A job's status belongs to the user.** Re-discovering a posting someone
marked `applied` must never reset it, and every write path here touches only
what the pipeline legitimately owns. Discovery moves `last_seen`; analysis
writes `score`; generation attaches resume paths; status is the user's alone.
There is a test for each of those, because the failure would be silent and
infuriating.

One subtlety worth naming: an empty re-discovery must not wipe a description
that arrived last time. ATS listings vary in whether they inline the JD, so a
posting can be found twice with a description only once.

**The store records what survives profile filtering, not everything found.**
The first version recorded all discovered jobs, and the board immediately
filled with manager and senior roles the profile explicitly rejects — Bosch
alone posts thousands of jobs with nothing to do with software. Filtering
first cut a real run from 200 stored rows to 23 relevant ones.

**Skipping is no longer forgetting.** The pipeline still only *works* on jobs
it has not scored, so a second run does not pay to analyse and generate the
same postings. The difference is what happens to the rest: they stay. Verified
on a live run — 23 jobs stored, 6 scored, 1 resume attached, **17 left
unscored and waiting for the next run**. Under the old behaviour those 17 were
gone within a week.

**Mock mode does not write to the store**, because `discover_jobs` returns
early for it. That is deliberate: fake jobs have no business on a real board.
It does mean the integration is only exercised by real runs and by
`tests/test_job_store.py`, not by the mock pipeline test.

**What this sets up:** the board in item 14 reads this rather than a run's
`state.json`, and `status` is what the UI writes. The Streamlit "previous runs"
view still reads run files and is now the older of two paths — worth
collapsing when React lands, not before.

22 new tests.

---

## R36. Scoring without a key

**Decision:** (August 2026) `tools/resume/local_embeddings.py`, selected via
`config.EMBEDDING_BACKEND` (`auto` / `gemini` / `local`). A pipeline run now
completes end to end with `GOOGLE_API_KEY` unset.

**model2vec, not sentence-transformers.** The obvious library pulls PyTorch —
2-3GB on Windows — which is not a thing to ask of someone trying a job-search
tool, and it would have made item 15's packaging story much worse. model2vec
uses static distilled embeddings: `tokenizers` plus numpy, no torch, no
transformers, a ~30MB model. Measured: **0.002s to encode three texts**
against roughly 2.3s for one Gemini round trip.

The trade is real. Static embeddings have no contextual attention, so they
capture topic well and syntax not at all. Matching a resume component to a job
description is closer to a bag-of-concepts comparison than to reading
comprehension, so it is a fair trade — but it is a trade, and it is not the
same thing as the model every earlier measurement used.

**The first version scored every job 0.0 and the pipeline found nothing.**
Component selection worked; `overall_score` did not. The cause was one line:

```python
overall_pct = max(0, min(100, (overall - 0.3) / 0.6 * 100))
```

a normalisation calibrated to Gemini, whose cosines for this text sit around
0.3-0.9. model2vec's run an order of magnitude lower — measured over the
frozen 20-JD baseline, raw overall ran from about 0.00 to 0.08 — so every job
fell under the floor. The same shape as R24: a constant tuned for one setup,
applied to everything.

Calibration is now per backend and measured for each. Worth noting how the
failure presented: not an error, not a warning, just a pipeline that
discovered jobs and scored all of them zero.

**An unexpected result, reported without a conclusion.** Over the same 20 JDs:

| backend | min | max | median | spread |
|---|---|---|---|---|
| gemini | 43.8 | 57.7 | 53.0 | **13.9** |
| local | 0.0 | 88.7 | 63.6 | **88.7** |

Q17 and R24 are both about Gemini's scores clustering so tightly that a
threshold slices a dense band rather than separating good from bad. The local
backend does not have that problem. **That is not yet a claim that it selects
better** — a wider spread could equally mean more noise. Selection agrees with
Gemini on 13/20 experiences and 7/20 projects, and nobody has read the
resulting resumes. Judging that needs the item-2 style qualitative pass.

**`auto` still prefers Gemini when a key is present**, deliberately. Every
measurement in this document was taken against it, and switching the default
would invalidate the baseline silently. Local is the fallback, which is what
makes a keyless run possible, and `EMBEDDING_BACKEND = "local"` makes it the
choice.

**Backends are resolved once per process.** A run that embedded the resume
with one model and the job description with another would produce a similarity
with no meaning. Both caches key on the model name (R11, R28), so switching
costs a re-embed rather than a wrong answer, and R28's dimension guard is now
sized to whichever backend is active — 768 against 256.

**What a keyless run still does not give you.** Generation falls back to its
mock path without a key, which writes placeholder content rather than the
user's real bullets. That is not the no-LLM mode worth having: selecting the
right components and emitting the master bullets verbatim would be. Item 11.

11 new tests.

---

## R37. A ladder for bullet rewriting, and a floor that always works

**Decision:** (August 2026) `tools/generation/llm_backends.py` plus
`config.LLM_BACKEND` (`auto` / `gemini` / `openai` / `ollama` / `none`).

    none    nothing needed          selection only, your own bullets
    ollama  install + ~4GB + RAM    free, local, private
    openai  a key                   any OpenAI-compatible provider
    gemini  a key                   what every measurement here used

**One adapter covers most of the world.** OpenAI, Groq, OpenRouter, Together,
DeepSeek, LM Studio and Ollama all speak `/chat/completions`, so `openai` and
`ollama` are the same code with a different base URL. Sent with `urllib`
rather than the `openai` package — it is one POST, and a dependency to send it
would cost everyone who installs this.

**The floor is the interesting rung.** `none` was already half-built and
called "mock": `_mock_tailor` returns the user's original bullets. What made
it useless was that mock mode skipped budget computation entirely, so every
bullet was emitted at full length and the result overflowed onto a second page
and failed validation. Budgets are selection work, not rewriting work — which
component appears and how many bullets it gets is decided without a model.
They are now computed on every rung, and the deterministic fitter (R6) runs on
the output.

**A master bullet is written to be complete, not to fit a line.** This
resume's run to about 500 characters where the model path rewrites them to
140-280, so a verbatim bullet takes roughly twice the space. Measured: the
model path's bullet count, used verbatim, rendered to 2 pages with 7 bullets
unable to compress. The one-page rule is the invariant and bullet count is the
only lever left when the text cannot be rewritten, so this rung takes half the
bullets and keeps them whole. That produces one page.

**Then a bug worth recording, because the fix is a principle.** Scaling inside
the tailor left validation still reading the *unscaled* budget, so every
component was reported as short — "1 bullet(s) but budget requires exactly 3".
The budget is the contract between tailoring and validation; scaling the
output without scaling the contract makes the two disagree. The scale is now
applied to the budget itself, before either sees it.

**What this rung honestly produces.** A one-page PDF, correct components
chosen for the job, the user's own words — and `needs_review`, because some
bullets exceed the template's length zones (344 characters against a 316
maximum). That is not a defect to hide: deterministic compression cannot
rewrite prose, and the status is telling the truth. A user with no key gets a
real, targeted resume and a note that a few bullets run long.

**Failures fall down the ladder rather than aborting.** A chat backend that
errors falls back to verbatim, because a resume in the user's own words beats
no resume.

**Untested against a real Ollama.** None is running on this machine, so the
adapter is exercised by unit tests and by its shared code path with the
hosted providers, not end to end. The parsing tests cover the failure that
actually bites — smaller models fence their JSON far more often than Gemini
does, and an unwrapped fence is the commonest reason a local reply fails to
parse.

**`auto` still prefers Gemini**, for R36's reason: every measurement in this
document was taken against it, and quietly preferring another backend would
invalidate all of them.

14 new tests.

---

## R38. Rendering imported resumes, and three parser bugs it uncovered

**Decision:** (August 2026) `tools/resume/tex_renderer.py` turns a structured
resume into the project's LaTeX template, plus `data/templates/base_preamble.tex`
as a committed, depersonalised base. This is the rendering half of Phase 2
item 10; extraction from PDF and DOCX is still to come.

**The model never emits markup.** Generation *splices* the master `.tex`, so a
resume that never existed as LaTeX has nothing to splice, and the obvious fix
— asking a model for LaTeX — fails in the worst way available: markup that
does not compile, with the error thirty lines from the cause. So the model
fills a schema and this renders it, in code that can be tested without an API.

**The test that mattered was the round trip**: render a schema, parse the
result with the pipeline's own parser, check nothing was lost. It found three
bugs, and two of them were not in the new code.

### The parser required a coursework line to see education at all

The education regex demanded a trailing
`\resumeItemListStart \resumeItem{\textbf{...} ...}`. Without it, no match —
and the failure was silent, because every other field still populated. It only
ever worked for resumes written against this exact template with a "Relevant
Coursework" bullet, which most resumes do not have. Now optional.

### The parser was discarding half the experience bullets

The worst of the three, and it had been live the whole time:

```python
re.findall(r"\\resumeItem\{(.*?)\}(?:\s*\\resumeItem|\s*$)", ...)
```

That group **consumes** the next bullet's opening token, so the scan resumes
past it and every second bullet vanishes. The projects path two functions
below always used a lookahead and was correct.

Measured on the live resume: **18 `\resumeItem` entries in the file, 10
parsed.** Eight bullets of real experience had been invisible to keyword
extraction, to component embeddings, and to every generation prompt ever
built. Sorenson parsed 3 of 6, 101gen 3 of 5.

**And the fix appeared to change nothing**, which was itself a finding. Scores
were byte-identical afterwards, because `embedding_cache.py` keys on the
*resume file's hash* — and the file had not changed, only the parse of it. So
it served vectors built from the truncated bullets. R11's lesson wearing a
different hat: a cache key must cover everything that affects the value, and
"the input file" is not the same as "what we understood the input file to
say".

With the cache cleared, the true impact is modest: overall scores move from
43.8-57.7 to 44.4-57.8, experience selection changes on **1 of 20** JDs and
project selection on **0**. Selection barely notices. Generation should notice
more — the prompt now carries 18 bullets of source material rather than 10 —
and that is not something a selection metric can show.

### The renderer transposed experience fields

Jake's template uses `\resumeSubheading{#1}{#2}{#3}{#4}` for both sections
with different meanings: education is `{school}{location}{degree}{dates}` and
experience is `{title}{dates}{company}{location}`. Getting it wrong parsed
cleanly and filed every job title as the employer. Nothing about the template
hints at this; only the round trip showed it.

### And one in the escaper

Sequential replacement cannot escape LaTeX: the substitution for a backslash
contains braces, so the later brace rules escaped those in turn and `a\b`
became `a\textbackslash\{\}b`. Now a single pass, where nothing a
replacement emits is looked at again.

**Worth noting what found these.** Not the 232 tests that were passing, and
not any amount of reading. Rendering a resume and parsing it back is a cheap
equivalence check, and it caught a parser bug that four scoring changes, three
verification runs and a frozen baseline had all missed — because every one of
them measured the pipeline against itself, with the same truncated input on
both sides.

13 new tests.

---

## R39. Reading a PDF resume, and two things only a real file showed

**Decision:** (August 2026) `tools/resume/resume_import.py`. A PDF or DOCX
becomes text, the text becomes a schema, and R38's renderer turns that into a
`.tex`. `save_resume` accepts all three formats, so the UI's upload path needs
no knowledge of any of it.

**The model fills a schema and never writes markup.** The worst an extraction
mistake can do is put the right words in the wrong field — recoverable, and
visible on R33's confirmation screen. Asked for LaTeX instead, the same
mistake produces a document that will not compile.

**Extraction rides R37's ladder.** `llm_backends.complete_json()` is a
standalone entry point rather than a method on the generation agent, because
at import time there is no profile and no parsed resume for that agent to
exist around. A user on the `none` rung falls through to heuristics.

**Tested against a PDF whose right answer was already known** — one this
pipeline generated, so the correct parse existed to compare against. That is
what surfaced both problems, and neither was a model failure.

### A PDF renders link text, not link targets

The header shows "GitHub" over a hyperlink, so extraction yields the word
`GitHub` and the model dutifully reported `"github": "GitHub"`. The URL is not
in the text layer at all — it is in the page annotations. Those are now read
and appended, and the prompt is explicit that visible link text is never a URL.
Recovered correctly on the next run.

### PDF kerning splits words, and "copy verbatim" makes it worse

Extraction produced `E-Commerce W ebApp` and `F rontend & Mobile`. The model
had been told to copy text exactly, so it faithfully copied the damage. The
instruction now carves out an exception for stray intra-word spaces, which is
the one repair a model should make and a regex should not attempt.

Both are worth noting as a pattern: an instruction as reasonable as "do not
alter the wording" produces wrong output when the input is already corrupt,
and no amount of prompt care substitutes for running it on a real file.

**The heuristic floor is honest about being a floor.** Contact details are
found by pattern because they have shapes. Everything structural — which
bullet belongs to which role, where a tech stack ends — is exactly what a
regex cannot judge, so unsplit text is kept under `_unparsed` for the
confirmation screen rather than dropped. Arriving with no model gets you a
screen with something on it, not an error.

**Verified end to end**: a PDF became a `.tex`, the pipeline's own parser read
it back with contact, education, three experiences, four projects and six
skill categories intact, and `create_profile` bootstrapped a working profile
with seven derived trigger rules from it.

**Not yet built: the confirmation screen.** R33 requires every extracted field
to be shown for correction before use, and the import path currently writes
the `.tex` straight out. Until that screen exists, a misread resume is only
discoverable by opening the file — which is precisely the failure mode R33
predicted.

22 new tests, all offline. The model path is checked by hand against a real
PDF, because mocking a model here would only test the mock.

---

## R40. The screens catch up with the pipeline, and a wizard that broke profiles

**Decision:** (August 2026) Three of R33's four frontend decisions now have
screens in `app.py`. Item 14 said each of items 9-13 changes what the screens
must show; this is the pass that changed them, and it is worth doing in
Streamlit before React because it settles *what* the screens are while the
cost of changing that answer is still a text editor.

**The board is the main view now.** `screen_board` lists every job the store
has ever held — score, location, source, status, and the resume written for it
— filterable by status, minimum score and whether a resume exists. It is not a
sixth wizard step: a step is something you finish and leave, and R33's whole
point is that this is the thing you come back to. Setup is what you pass
through to reach it. Six facades on the orchestrator carry it, because
`test_ui_contract` forbids the view layer from knowing the board is SQLite.

**The key stopped being mandatory.** The "about you" screen disabled Continue
until a Gemini key was entered. That was true when it was written and stopped
being true the moment R36 moved embeddings off the API and R37 gave rewriting
a floor that needs no model — at which point the UI was holding the door shut
on a pipeline that had already learned to run without a key. It now detects
the rung, says what that rung costs in plain words, and lets you through:

    ✍️  Jobs will be scored and the right components picked for each one,
        but your bullets will be used exactly as you wrote them.
        To get tailored bullets, add a Gemini key above, or install Ollama...

Detected and explained, per R33 — not asked, because nobody can answer "which
model backend?" before they have seen the tool work once.

**Seniority is a control.** R34 made the gate read `job_preferences.seniority`
instead of a constant, which helps nobody while the only way to set it is
editing JSON. The form offers the seven levels from `SENIORITY_SYNONYMS`, and
its help text says what the old copy hid: the exclusion list is a separate,
harder filter, and excluding "senior" while asking for senior roles finds you
nothing.

### The wizard could destroy a profile by being walked through

`update_profile_fields` merged one level deep. The preferences screen collects
two of `locations`' seven fields, so saving it replaced the whole section —
dropping `countries`, which the schema requires, along with `states_priority`,
which discovery reads. **The result was a profile that would not load at all.**
Walking a screen that says "Save and continue" left the pipeline unable to
start.

The docstring already promised the right behaviour ("a form that collects three
fields cannot wipe the other thirty"); the code just stopped one level short of
it. The merge is now recursive, and lists still replace, because merging two
lists is a guess about intent.

This is R30's shape for the third time: **a form destroying data it never
showed the user.** So the fix is not only the merge. `read_preferences` and
`read_personal` let both forms seed from what is stored, because a form that
cannot read what it wrote reverts it on the next save — the same destruction,
one layer up, and invisible for exactly as long.

**Verified against the real profile**, which is the only test that would have
convinced me: opening the preferences screen and clicking "Save and continue"
now leaves `yash_pathak.json` byte-identical. Before the fix, that click
dropped 9 target roles, 8 exclude keywords and 5 location fields.

### Two bugs only the running app could show

Neither is deep, and neither was findable by reading.

**Two postings can share one resume file.** Generation names a resume after
company and title, and Affirm posts the same title in several countries — so
two board rows pointed at one PDF, and Streamlit refused to render duplicate
widget keys. The board is the first screen to show both rows at once. Keyed on
the posting URL instead. *The underlying collision is real and not fixed here:
two different postings genuinely overwrite each other's resume on disk.*

**A job title ended in a space.** `"Software Engineer II, Backend (Furnishing
Platform) "` inside `**...**` breaks the closing delimiter, so that one row
printed its own asterisks. Titles are other people's HTML; `_plain` strips and
escapes them.

**What is still missing from R33:** the import confirmation screen (R39 also
flagged it), and runs as background jobs — a multi-minute run still needs the
tab open, which is a FastAPI concern rather than a Streamlit one.

25 new tests. The board's facades are tested against a store of their own, so
the suite never touches the user's real board.

---

## R41. The confirmation screen, and a key that only some entry points found

**Decision:** (August 2026) Importing is now two calls with a person in
between. `extract_resume` reads an upload into a schema and writes nothing;
`save_extracted` renders whatever the user confirmed. R33 required this and
R39 shipped the import without it, which left a misread resume discoverable
only by opening the generated `.tex` — the exact failure R33 predicted, and
one R39 flagged in its own entry.

The old `save_resume` extracted and wrote in a single call, so there was
nowhere for confirmation to happen. That is the whole reason the screen did
not exist: not that it was hard, but that the seam was missing. It still
exists, implemented in terms of the two halves, for callers that genuinely
have no screen.

**A `.tex` upload skips the screen.** It is the user's own file in the
pipeline's own format, so there is nothing a model guessed at, and asking
someone to proofread their own document back to them is friction that teaches
them to click past it.

**Entries can be dropped, not only corrected.** Extraction can invent an
experience out of a heading it misread, and a screen that only allows
correction leaves no way to say "this is not a job". Each entry has an
include toggle; the build is blocked if nothing is left, because a resume
with nothing to tailor is not a resume.

**Verified against a real PDF end to end**: a generated resume was read back
into three experiences, three projects, six skill categories and correct
GitHub and LinkedIn URLs — R39's link-annotation and kerning fixes both still
holding — then a corrected name and a dropped project were carried through
`save_extracted` into a rebuilt profile. The corrections are what landed, not
the extraction.

### `_normalise` threw away the hook R39 built for this screen

The heuristic floor stores text it could not split under `_unparsed`,
deliberately, so a confirmation screen can show it. `_normalise` then rebuilt
a fixed five-key dict — so the key was written, populated, and unreachable by
the only thing that wanted it. Carried through now, and the screen warns when
it is non-empty.

Worth naming as a pattern: **the floor was built for a consumer that did not
exist yet, and nothing failed when the wiring was cut.** No test could have
caught it, because until this screen there was no behaviour to assert.

### The `.env` file was loaded by agents, not by the project

`load_dotenv()` was called at import in each of the three agents, which covers
every path that goes through an agent and no others. `scripts/init_profile.py`
does not import an agent, so importing a PDF from the command line resolved no
key at all, dropped silently to the heuristic floor, and produced a resume
with **zero experiences** — on a machine with a perfectly good key in `.env`.

Found while testing this screen, and initially misread as a model failure. The
give-away was `complete_json` returning `None` rather than raising: the `none`
rung is a legitimate state, so falling to it looks identical to choosing it.
That is a fair design — R37 wanted the floor to be silent — but it means a
misconfiguration and a deliberate choice produce the same log line.

`load_dotenv()` now lives in `config.py`, which is already the module that
decides what "no key" means (`resolve_api_key`, R22) and which everything
imports. One place, every entry point. It is idempotent and never overrides a
variable already set in the real environment, so the agents' own calls are
harmless.

**The screens are now driven by tests, not by clicking.** `streamlit.testing`
runs `app.py` headlessly, which is how the corrections-propagate cases are
asserted: edit a field, click confirm, read the written `.tex`. Testing the
helpers instead would still pass on a version of `app.py` that skipped the
screen entirely.

13 new tests. R33 is now fully built except for runs as background jobs, which
is a FastAPI concern rather than a Streamlit one.

---

## R42. Three ways the system was quietly wrong

**Decision:** (August 2026) Three small fixes with one shape in common: each
kept working, produced wrong output, and said nothing. None was findable by
reading the code — one needed a machine with the "wrong" model pulled, one
needed two postings shown side by side, and one was a claim in the README that
no measurement supported.

### Detection and invocation disagreed about "available"

`ollama_is_running` returned true when the server had *any* model pulled. The
call then asked for `OLLAMA_MODEL`, hard-coded to `llama3.1`. Someone running
Ollama with `mistral` was detected as having Ollama, told bullets would be
rewritten locally, and then 404'd on a model that was never there — falling
back to verbatim bullets without a word, because a failed rung and a chosen
`none` are indistinguishable from outside.

Detection already fetched the model list and threw it away, so the fix reads
it: `ollama_models` returns the names, `choose_model` picks one, preferring the
config's default and settling for whatever is there. Tags match loosely on
purpose — `ollama pull llama3.1` stores `llama3.1:latest`, so a config naming
the bare model would otherwise miss its own default.

`choose_model` is split from the network call deliberately. The choosing is
where the bug was and is the only half a test can reach without a server.

### Two postings could share one resume file

Resumes are named after the company and the first three words of the title.
Affirm posts "Software Engineer I, Fullstack (Servicing International)" in
Spain and in Poland; both produced the same filename, so the second overwrote
the first and one posting's stored path pointed at a resume tailored to a
different job description.

The apply URL — already the job store's primary key — now contributes eight
hex characters of SHA-256. Hashed rather than slugged because a URL is long
and ugly, and *stable* rather than sequential, so a re-discovered posting
overwrites its own resume instead of accumulating near-duplicates beside it.

**Worth noting where this was found.** The generation loop had this bug from
the day it was written, and every run log looked fine, because a run log shows
one resume per row. The board shows both rows at once, and Streamlit refused
to render two download buttons with the same key. A UI that puts two records
side by side is a correctness test for whatever assumed they were distinct.

### The README recommended what nobody had run

R40 added a line calling a local Ollama "the free middle rung", and the backend
panel told users to `ollama pull llama3.1`. Both advertise a path that has
never completed a single call: detection is real, but `call_chat_json` has
never spoken to a live Ollama, and the tests say so in as many words. The same
adapter serves the `openai` rung, which has no key either — so two of the four
rungs are structurally plausible and empirically untested.

Both now say so. This is the smallest change here and the one most worth
making: the rest of this document is careful to separate what was measured
from what was assumed, and a README that quietly stopped doing that undoes the
reason the document is trusted.

The fix is honesty, not silence. The rung is still offered, still detected,
still the right answer for someone with no key — it is simply labelled as
unproven rather than described as if measurements existed behind it.

### What these three share

All three were introduced by someone (me, twice) doing something reasonable:
assuming a configured default is present, naming a file after what a human
would call it, recommending the option that helps users with no API key. The
common failure is not carelessness, it is that **nothing in the system
distinguishes "this worked" from "this fell back".** That is the same finding
as R41's `.env` bug, and it is still open — see A4 in the current inventory.

17 new tests, all offline.

---

## R43. The untested rung, tested — the half a socket can prove

**Decision:** (August 2026) `tests/test_openai_compatible_rung.py` stands up a
stdlib HTTP server on loopback that speaks Ollama's `/api/tags` and the OpenAI
`/v1/chat/completions` envelope, and drives the real adapter against it.

**The gap.** `ollama` and `openai` are one adapter with a different base URL,
and neither had ever completed a call. Detection was tested; the completion
was tested against its *parsing* only, with the tests saying "No network here"
in as many words. So the rung this project recommends to anyone without an API
key was, strictly, never known to work — a fact that surfaced only because
someone asked how Ollama was being used.

**Why a fake server rather than a mock.** A mock of `urlopen` tests that the
code calls the function you think it calls. This sends a real request over a
real socket through the real code path, and the assertions are about what
arrived: the model name in the body, `stream: false`, the `Authorization`
header present with a key and absent without one. It needs no download, no
account and no internet, and it runs in CI forever.

Two findings came straight out of it, neither reachable from a list literal:

- **A fenced reply parses.** Small local models wrap JSON in ```` ```json ````
  far more often than Gemini does, and `_strip_code_fence` existed for that
  reason without ever having unwrapped a reply that arrived over a wire.
- **The A2 fix holds end to end.** Config asks for `llama3.1`, the server has
  `llama3.1:latest`, and `complete_json` calls the one that exists.

**What this deliberately does not prove.** Bullet *quality* from a small local
model. The fake server returns whatever the test tells it to, so it can show
that a schema round-trips and cannot show whether `llama3.1` follows a prompt
tuned against Gemini. That is the question the README's "unmeasured" label is
about, and it stays unanswered until a real Ollama runs.

So this closes the plumbing half of A1 and leaves the quality half open. Worth
being precise about, because "we tested Ollama" would be exactly the kind of
claim R42 was written about.

16 new tests. 333 pass.

---

## R44. A real model ran, and invented a job

**Measured:** (August 2026) Ollama installed, `llama3.1:8b` pulled, and the
generation pipeline replayed over `outputs/2026-08-23/enriched_jobs.json` —
the same 20 JDs, the same resume, the same component selection as the Gemini
run of that date. Only the rewriting backend differs.

| | Gemini | llama3.1:8b |
|---|---|---|
| valid | **3** | **0** |
| needs_review | 0 | 3 |
| bullets left unmodified | — | 11 of 13 |

**Warm latency was never the problem.** 2–7 s per call on an RTX 5080; the
first call's 43 s is model load. Speed is fine. Everything below is about
what the model wrote.

### Every rewrite failed to parse, twice, for different reasons

The first failure was the wrapper. `_strip_code_fence` handled ```` ``` ````
fences and only those, which was a guess about *which* markup a small model
would use, and the guess was wrong: the first real reply came back as
`` `{"n": 1}` `` — a single-backtick inline span. Fixed, and every trivial
call worked afterwards.

The second failure survived the fix. On the real 14,600-character tailoring
prompt the reply opens with prose:

    Here is the rewritten JSON output:

    ```
    { "experiences": [ ... ] }

Pulling JSON out of that is four lines, and **those four lines are not being
written.** See below.

### The reply behind the prose was fabricated

This is the finding. The model did not paraphrase the resume badly; it wrote a
different resume:

| | Master resume | llama3.1:8b |
|---|---|---|
| dates | June 2025 – Oct. 2025 | "Summer 2022" |
| bullet 1 | Async serverless REST API, dual-Lambda fan-out, eliminated a 25-second downstream read timeout | "scalable web application using Python, Flask, and MySQL, resulting in a **30% reduction in development time**" |
| bullet 2 | Terraform (HCL) — API Gateway, Lambda, IAM least-privilege, CloudWatch | "cloud-based infrastructure using AWS EC2, S3, and Lambda, achieving a **25% increase in application performance**" |

Invented metrics, an invented date, and technologies that appear nowhere in
the resume. Nothing of the original survives. A resume is a factual claim about
a person, so this is not a quality gradient — it is the pipeline producing a
document its owner would have to defend in an interview.

**The parse failure is the only reason none of it shipped.** Generation caught
the error, fell to `_verbatim_tailor`, and wrote the user's real bullets. The
strictness that looked like a bug was load-bearing.

So `_strip_code_fence` now carries a comment saying exactly that, and a test
asserts the prose case still raises. Loosening it without a content check
first would convert a safe failure into a silent one — which is the whole
subject of A4.

### The instrument for this exists and was never plugged in

`_validate_metric_preservation` has been in `validation.py` all along. All
three call sites invoke `validate_resume_output(tailored,
bullet_budgets=...)` without `master_resume_text`, and the check is guarded on
that argument being present — so it has never once run.

That is the third time: `rarely_include` computed and discarded (R31),
`_unparsed` written and unreachable (R41), and now this. The pattern is a
capability built for a consumer that did not exist yet, with nothing failing
when the wiring was never made.

And wiring it is necessary but not sufficient. The check looks for master
metrics **missing** from the output; it would pass a resume whose every number
was invented, because it never asks where a number in the output came from.
Catching this needs the opposite direction: a metric in the output that is not
in the master is a fabrication.

**Q6's premise has changed.** That entry deferred a metric-preservation checker
as speculative — "building one before seeing a failure on gemini-3.5-flash is
the speculative work this doc otherwise avoids." The failure has now been seen.
Not on gemini-3.5-flash, on llama3.1:8b, which is a weaker claim than Q6 was
waiting for — but the ladder means untrusted models are a supported
configuration, so the checker is no longer speculative for the rung that needs
it most.

### What this changes

- The README and the backend panel now say the rung was measured and did not
  help, rather than that it was untested. "Unmeasured" was true this morning
  and would be a softer claim than the evidence supports.
- The rung stays. It fails safe, and it costs nothing to leave available for a
  better local model — `choose_model` (R42) means anyone can point it at one.
- Whether a larger local model behaves differently is unmeasured and worth
  measuring before concluding anything about local inference in general. One
  8B model is one data point.

6 new tests. The measurement script is not committed: it pins config and
replays a fixed input, which is a thing to re-run by hand, not a thing to keep
green in CI.

---

## R45. Making fabrication impossible, then visible, then irrelevant

**Decision:** (August 2026) R44 watched a model invent a job. This is the fix,
in four layers, done in that order because each one makes the next safe.

| | Gemini | llama3.1:8b |
|---|---|---|
| before | 3 valid | 0 valid, 3 needs_review, 11/13 bullets untouched |
| after | **3 valid** | 0 valid, 3 needs_review, **0 crashed** |

Gemini is unchanged, which was the point: a guard that costs the working
backend anything is not a guard, it is a trade.

### 1. Fields with a known correct value are no longer asked for

Dates, company, title and location are records, not writing, and the LaTeX
builder read them straight out of the model's reply — so `"dates": "Summer
2022"` was one successful parse from the page. `_restore_factual_fields` takes
all four back from the master resume, keyed by the component id the model
echoes.

This removes the class rather than detecting it. The model still chooses which
components appear and still rewrites their bullets; it simply no longer
supplies any field whose right answer was already known.

It lives inside `_apply_bullet_fitting` rather than at the five call sites
that post-process model output, because a guard that can be skipped by adding
a sixth path eventually is.

### 2. Figures inside bullets are checked against the resume

Bullets are the part the model genuinely has to write, so those need
detection rather than prevention. `find_invented_metrics` is the inverse of
the `_validate_metric_preservation` that has sat unused in this file for
months: that one asks whether the master's numbers survived, which a resume of
pure invention passes trivially, since every master metric is equally absent
whether it was dropped or replaced.

An invented figure is an **error**, not a warning. A resume is a factual claim
about a person.

**Calibrating it was most of the work, and the first version was wrong.** It
flagged 13 of 16 past Gemini resumes as fabricated. Every one was a false
positive: the master writes its numbers in LaTeX math mode — `$\sim 503$ms`,
`$\sim 10$ minutes`, `$\sim 3.6$x` — and a `$` between the number and its unit
defeats a substring search. Four more survived that fix, all the same case:
the master says "to under a second" and the bullet says "to <1 sec", which is
the same claim and the better line.

Worth stating plainly, because the temptation was to ship the first version
and call 13/16 a finding: **a fabrication check that cries wolf is worse than
no check**, because it teaches you to click past the error that eventually
matters. The audit existed to catch that, and did.

**The audit's real result: Gemini invented nothing.** 0 of 16 resumes across
6 runs, once the check could tell markup from a claim.

### 3. Parsing fixed at the protocol, not with a regex

R44 left the prose-preamble case deliberately unhandled, because the parse
failure was the only thing keeping fabricated content off resumes. With
layers 1 and 2 in place that is no longer load-bearing, so it could be fixed
properly: `response_format: {"type": "json_object"}` on the request.

Measured on llama3.1:8b: without it the reply is backtick-wrapped and takes
6.1s; with it the reply is bare JSON in 2.1s. Asking the server for JSON beats
asking the model nicely and scraping the result. A provider that rejects the
field costs one retry without it, since the same adapter serves every
OpenAI-compatible endpoint.

### 4. What that exposed: three crashes hiding behind a parse error

With replies finally parsing, llama3.1 returned `"experiences": ["exp_sorenson",
...]` — a list of id strings where the schema says objects. Valid JSON, wrong
contract, and it crashed `_restore_factual_fields`, then `_apply_bullet_fitting`,
then `find_invented_metrics`, then `_validate_selected_ids`, then the LaTeX
builder. Five sites, each looking like its own bug.

They were one missing gate. `validate_resume_output` now rejects a non-object
component up front and returns, the way it already did for a missing key. The
per-site guards stay as belt-and-braces, but the structural check is where a
structural problem belongs.

This is the shape worth remembering: **fixing the parse did not introduce
these, it revealed them.** They had been unreachable behind a failure that
happened earlier.

### And a cache that served one model's answers as another's

The clean measurement was nearly reported as a Gemini regression: a run pinned
to Gemini came back 0 valid, and the errors were budget violations that looked
like Gemini had got worse. It had not. `LLMCache` keys on the prompt alone, so
three llama3.1 responses were being served to it.

The docstring defended that on purpose — a fallback from gemini-3.5-flash to
flash-lite should still hit — and the reasoning was sound when written, before
R37 turned one provider into a ladder of four. Ollama's answer is not a
substitute for Gemini's.

Keyed on (backend, prompt) now: the rung rather than the model id, so a
fallback within a provider still hits. **This is R11 arriving a second time** —
that entry put the model in the embedding cache's key for this exact reason,
and the sibling module never got the lesson. Existing entries are keyed the
old way and are simply missed once.

### What is still true about llama3.1:8b

It cannot produce a valid resume here: bullet-count budgets ignored, lengths
outside every zone. What changed is that it now fails **safely and visibly** —
no fabricated dates, no invented figures, no crashes, everything routed to
needs_review. R37 predicted a smaller model would follow this prompt less
exactly and the validation loop would catch the difference. It does now.

Whether a larger local model does better is unmeasured, and the harness for
asking exists.

16 new tests, 355 pass, baselines clean.

---

## R46. The cap decided which companies existed

**Decision:** (August 2026) `search_ats` asks every seeded company before it
cuts anything, and fills the cap round-robin across employers.

**The symptom** was the board: 23 jobs, three companies — Affirm 18, Airtable
3, Airbnb 2 — scoring 52–55%. A three-point spread across 23 postings reads
like a scoring problem, and that is how it was first written up. It was not.

**The cause** was four lines in the discovery loop:

```python
for slug in companies.get(board, []):
    if len(listings) >= max_results:
        break
```

Companies were visited in seed-file order, which is alphabetical, and the loop
stopped the moment it had enough. Affirm alone fills a cap of 20. So 54 of 57
Greenhouse companies were never contacted, and Lever, Ashby, Workable and
SmartRecruiters were **never reached at all** — four of the five boards R34
built, dead on arrival for any default run.

R34 claimed 86 companies and ~11,600 roles. That number was real and had never
once been exercised.

**The fix is the argument `title_matches_roles` already makes.** Its docstring
says filtering has to precede the cap, because "truncating first returns an
alphabetical slice of the wrong jobs". That was solved *within* a company and
left unsolved *across* companies, which is the same sentence one level up.
Every board is now read, matches are grouped by employer, and `_spread` takes
one job from each in turn.

**Order is randomised per run.** Round-robin over a fixed order still hands
every run the same alphabetical head: 79 companies are hiring, and a cap of 20
would only ever show A through D. The store is durable (R35), so varying the
order means successive runs widen the board instead of re-finding the same
twenty employers. Deterministic replay is not lost — `--input` re-runs analysis
and generation over a saved `enriched_jobs.json`, which is where reproducing a
result actually matters.

### Measured

| | before | after |
|---|---|---|
| companies in one run | 3 | **11** |
| score spread in one run | 3.0 | **12.4** |
| durable store | 23 jobs, 3 companies, 1 board | **97 jobs, 49 companies, 5 boards** |
| boards reached | greenhouse | greenhouse, ashby, lever, workable, smartrecruiters |

A full sweep costs 58s for 94 board fetches, against roughly three before.
That is the honest price of the fix and it is worth it: discovery is keyless,
so the cost is wall-clock rather than quota, and it buys the difference
between three employers and forty-nine.

The first run after the change produced valid resumes for **Modal** and
**Cartesia** — both Ashby companies, from a board the old code could not
reach.

### What this says about the 57%

B1 assumed the score's ceiling was the problem and the display should change.
Half of that was wrong. The spread went from 3.0 to 12.4 without touching the
scorer, because **a metric cannot discriminate between twenty near-identical
postings at one employer** — it was being asked an impossible question and
answering it correctly.

The ceiling is still real: 54.6 remains the top, and cosine similarity between
a resume and a JD does not approach 1.0. So B1's display change is still worth
making. But it is now a smaller, better-informed change, and the thing that
actually made the number useful was fixing what it was ranking.

Worth stating plainly because the instinct was to reach for the scorer first.
The scorer was fine.

8 new tests, 363 pass, baselines clean.

---

## R47. Telling "you chose this" apart from "this broke"

**Decision:** (August 2026) The deliberate floor returns, a broken rung raises,
and anything that lands on the floor by accident says why somewhere the user
will actually look.

**The pattern this closes.** Five bugs in three days had one signature: the
pipeline kept working, produced something worse, and said nothing
distinguishable. An unloaded `.env` shipped a resume with zero experiences
(R41). An Ollama with the wrong model pulled promised local rewriting and
404'd (R42). A cache served one model's answers as another's, read as a
Gemini regression (R45). In every case the fallback was *right* — falling back
is the design — and what was missing was any way to tell a chosen floor from a
failed climb.

`complete_json` returned `None` for both. So did the generation path: two
routes into `_verbatim_tailor` producing byte-identical output, one because
you asked and one because something broke, sharing a log line.

### The rule

    none rung        →  returns None      (a choice)
    a rung that fails →  raises BackendFailure with a reason

`BackendFailure` subclasses `RuntimeError`, so callers already catching broadly
keep working — they can now say *what* went wrong instead of guessing the
friendlier of two possibilities.

### Carrying it to the user

A log line nobody reads is barely better than silence, so the reason travels:
`_verbatim_tailor(reason=...)` stamps `_verbatim_reason` on the payload, the
result record carries it as `degraded`, and both the run summary and the
results screen show it. On the payload rather than beside it, because every
caller already threads one dict through fitting, validation and the result —
an out-of-band value would be dropped by the first one that forgot.

> ⚠️ **Bullets were not rewritten** for 1 of 1 resume(s). Your own bullets
> were used instead, correctly selected for each job.
> - Ollama was selected but has no model pulled — run `ollama pull llama3.1`

### The instance the unit tests missed

Everything above passed, and a real run with a deliberately dead Ollama still
recorded `degraded: None`.

`_resolve_backend` downgrades an unusable rung to `none` at construction, so
the run reached the floor *by choice* as far as every later line of code could
tell. That is A4's exact shape surviving **inside R42's fix for it** — the fix
that added the warning in the first place. The warning was there; the result
was empty; the summary and the UI stayed quiet.

Worth recording as the more interesting half of this entry: a pattern is not
closed by fixing the instances you found it in, and the only thing that caught
this was running the pipeline against a broken backend rather than asserting
against a stub.

### While in there

The Gemini failure path fell back to `_mock_tailor`, not the verbatim floor —
so a real outage told the user their run had gone to "mock tailoring", which
sounds like test output and gives them nothing to act on. R37 built the floor
and explained why it is "no longer called mock"; this path was never moved
over. It is now.

**Verified in three directions**, because one is not enough for a change whose
whole point is not crying wolf:

| run | `degraded` | summary |
|---|---|---|
| broken rung (Ollama on a dead port) | the reason, with the fix | says so |
| deliberate `none` | `None` | silent |
| normal Gemini | `None` ×3, 3/3 valid | silent |

11 new tests, 374 pass, baselines clean.

---

## R48. From a list to a log

**Decision:** (August 2026) The board gains the filters the store always had,
paging with a total, and a `status_history` table that lets ghosting derive
itself.

A list shows what you have; a log shows what has **happened**. That needs two
things the board did not have: a way to find one row among thousands, and a
record of when each thing changed.

### The filters existed and were never offered

`JobStore.query` has taken `company` and `source` since the day it was
written, and no screen ever passed either. Three timestamps were stored and
none were displayed. That was survivable while the board held 23 jobs from
three employers; R46 made it 97 from forty-nine, and it will keep growing,
because the store never forgets.

Added to the store rather than the screen, so the view layer still builds no
SQL: multi-value `company` and `source`, a `search` over title and company,
`SORTS` as a named map, `offset`, `count()` and `facets()`.

Two details worth keeping:

- **The search term is escaped.** A user typing `100%` wants jobs mentioning a
  percentage, not every row in the table, and an unescaped `LIKE` gives them
  the latter. There is a test for `%` and one for `_`.
- **An unknown sort falls back rather than raising.** The keys are a fixed map
  and a stale bookmark should not be an error — and it means nothing a caller
  passes can reach the ORDER BY.

### Paging says how much is hidden

`limit` was 200 with no total, so "200 jobs" and "all 412 of your jobs" looked
identical. That is the silent-truncation shape this project keeps finding, and
C3 was on the inventory as its own item; it is closed here because a page
without a count is the same bug. The board now reads **Showing 1–25 of 97**.

### Ghosting is derived, never clicked

`ghosted` was the status you asked for, and it should not be a button. It
means *applied, and silence since* — a fact about time, not a decision. A
stored status would go stale the moment a reply arrived, and would need you to
notice the anniversary yourself, which is the work a log is supposed to do for
you.

So `status_history` records what changed and when, `ghosted(after_days=28)`
computes the rest, and a job that moved on from `applied` drops out by
construction — its current status is no longer `applied`, so it cannot be
silent.

The history is worth having on its own: it answers how long between applying
and hearing back, across everything, which nothing in this project could
answer before.

### A bug the tests would not have found

`ghosted_jobs(after_days=0)` returned the 28-day answer. The facade read
`after_days or GHOSTED_AFTER_DAYS`, and `0 or 28` is `28` — so a legitimate
threshold was silently swapped for a different question.

Found by calling it with 0 and disbelieving the result, not by reading it.
Same family as the rest of R47: a wrong answer that looks exactly like a right
one. There is now a test that pins zero specifically.

### Verified

28 new tests. The screen was driven in the running app: search narrowed 97 to
17, paging reported *Showing 1–25 of 97*, dates render as "found yesterday",
sources as "Greenhouse", and a backdated application surfaced the ghosted
banner with its own expander. The store was restored afterwards — the test
statuses and history rows were written to the real board and are gone.

402 pass, baselines clean.

---

## R49. The score was fine; the window it was shown through was not

**Decision:** (August 2026) The score is left exactly as it is, and the board
labels each job against the quartiles of the user's own scored jobs.

**My first two explanations were both wrong**, and it took reading the scorer
and then measuring to find out.

The first was "cosine similarity between two related documents tops out around
0.7, so 57% is near the ceiling." That assumed the displayed number was a raw
cosine. It is not: `_normalise` already maps raw onto 0-100 per backend, and
the Gemini calibration spans 0.30-0.90 — so 100 is reachable by construction.

The second was R46's, that the pool was the problem. That one was half right
and worth the work — fixing discovery took the *within-run* spread from 3.0 to
12.4 — but it did not move the band the numbers live in.

### What the measurement says

95 scored jobs across seven runs:

| | |
|---|---|
| displayed | 43.8 – 58.9 (mean 53.0, sd 3.0) |
| implied raw cosine | 0.563 – 0.653 |
| calibration assumes | 0.30 – 0.90 |
| **span actually used** | **15%** |

So the scale is not unreachable, it is **miscalibrated in the other
direction**: the window is three times wider than anything real, and every job
lands in a fifteen-point band that reads as "about 53" whatever it is. The
differences that exist are real and invisible.

### Why the calibration was not re-cut

That is the obvious fix and it would have been a bad one. `scoring_threshold`
gates the pipeline at 40 and is stored per profile. Moving the scale moves
that gate silently — a job that scored 41 before would score 12 after and stop
getting a resume, with nothing in the diff to say so.

That is R24 exactly: a number used as a quality bar that could not grade. The
answer there was to stop asking the number to mean something it could not, not
to renumber it.

There is a second reason. The observed range belongs to **one resume against
one corpus**. Constants tuned to it would be wrong for the next person, and
`CALIBRATION` already carries the warning: getting the floor wrong sends every
job to 0.0 and the pipeline finds nothing.

### So the presentation divides it instead

`score_bands()` reads the quartiles out of the store — the user's own scored
jobs — and the board appends **strong** or **weak** to the percentage. Nothing
below eight scored jobs, because a quartile over three is not information.

Self-calibrating by construction: a different resume in a different market
produces a different band of similarities and the labels move with it. No
constants, and nothing the pipeline reads.

The percentage stays alongside the label. It is the only part that is
comparable between two jobs on the same board, and hiding it to make the UI
tidier would lose the thing that works.

### Verified

Against the real store of 97 jobs: bands at 50.6 and 53.0, splitting 38 scored
jobs 11 strong / 18 typical / 9 weak. Driven in the running app — page 1 shows
strong, page 2 shows weak, and the counts match the store.

6 new tests, 408 pass, baselines clean.

**What is still true.** A 54% is not "54% of a perfect match" and no display
change makes it one. The label says where a job stands among yours, which is
the question you can actually act on. Making the absolute number meaningful
across users is Q17's problem — embeddings reward vocabulary overlap rather
than role type — and it is still open.

---

## R50. A doctor, and a package to put it in

**Decision:** (August 2026) `scripts/doctor.py` reports whether this machine
can run JobScout and what would fix it; `pyproject.toml` makes the project
installable, with `jobscout`, `jobscout-ui` and `jobscout-doctor` as commands.

Roadmap item 8 argued the doctor was worth more than an install script and the
argument has held: **an installer has to know how to put a LaTeX distribution
on six platforms; a doctor only has to notice one is missing and name it.**
The first goes stale every OS release. The second does not.

It also earns its keep against this project's own record. Three of the last
week's bugs were setup problems wearing logic problems' clothes — a `.env` no
entry point loaded (R41), an Ollama with no model pulled (R42), a rung nobody
had run (R44). Each took hours. Each is now one line of a report.

### Two rules, and they are the whole design

**Say what to do, not just what is wrong.** "pdflatex not found" is a
diagnosis. "install MiKTeX (Windows) or TeX Live (macOS/Linux)" is a fix.
Every non-ok line carries one, and there is a test per check that it does.

**Distinguish broken from absent.** Almost all of this pipeline is optional:
no Gemini key, no LaTeX engine and no local embeddings are supported
configurations that still produce real resumes. Reporting them as failures
would teach someone to skim the report, and then the one line that matters —
a profile that will not load — goes past unread.

That is R47's finding pointed at a diagnostic tool. A warning that fires when
nothing is wrong is worse than no warning, because it costs the ones that
are real.

So: **warnings for what is absent, failures only for what is broken**, and the
exit code follows failures alone, which is what lets CI call it.

### What it found on the first run

Three profiles, where there is one. `list_available_profiles` globbed `*.json`
and rebuilding a profile leaves a timestamped `.bak` beside it (R30) — so the
listing offered yesterday's copy of your own profile as a separate choice, and
the app's profile dropdown showed it. Small, invisible until something counted
them out loud, and exactly the kind of thing a doctor is for.

### The packaging

`pip install -e ".[local]"` and three commands. The `local` extra carries
`model2vec`, because R36's local embeddings are what make the tool work for
someone with no API key — optional to the code, essential to the audience.

`jobscout-ui` exists because `streamlit run app.py` stops being a usable
instruction the moment the file lives in site-packages. It shells out rather
than importing: Streamlit's entry point expects to own the process, and
calling it in-process works until it does not.

`requirements.txt` stays. It is the file people already know, and the
dependency list is duplicated rather than generated because a build that reads
a requirements file at install time is a build that breaks in ways nobody
enjoys debugging.

### Verified

Doctor run on this machine reports nine checks, all ok. Forced each optional
dependency to look missing and confirmed warnings with fixes rather than
failures. Forced an unloadable profile and confirmed a failure. The wheel
builds and `pip install --dry-run` resolves.

14 new tests, 422 pass, baselines clean.

**What packaging does not solve.** The audience is still people who have
Python and a terminal. A real installer for people who have neither is a
different project, and the doctor is what makes the terminal version
survivable in the meantime.

---

## R51. Runs that outlive the tab

**Decision:** (August 2026) `start_run()` returns an id immediately and the
work continues in a background thread; progress goes to `data/runs.db`, and
any screen can ask about it afterwards.

This is the last of R33's four decisions, and the reason is narrow. The
pipeline takes minutes, it ran inside the request that asked for it, and a
browser reload therefore lost the progress bar and every way of telling
whether the work was still going.

**Progress lives on disk, not in a session.** That is the whole design. Anything
held in `session_state` survives exactly as badly as the thing it replaces, so
the registry is SQLite next to the job store, and `active_runs()` finds a run
with no id at all — which is what a reloaded tab has.

**A thread, not a subprocess.** The requirement is that closing the tab does not
cancel the run, and the server outlives the tab. A subprocess would also survive
the *server* restarting, which is worth having and is not what was asked for.
Callers only ever see an id, so swapping it later changes nothing above.

**Checkpoints stay in the foreground, deliberately.** R26's review checkpoint
resolves through a callback that waits for an answer; in a background worker
there is nobody to ask, and waiting on a browser that may have closed would
hang the thread forever. So "show me the jobs before writing resumes" runs the
old way and says so in its help text. Two paths is worse than one, and a
checkpoint nobody can answer is worse than two paths.

### Why this is the shape FastAPI needs

R33 specified `POST /runs` returning an id, with progress over SSE. What is
here is that minus the transport: the id exists, the progress is a row, and
the polling loop reads exactly what an SSE endpoint would push. The React port
inherits the registry rather than replacing it.

### Verified in the browser, which is the only place the claim means anything

Started a run from the app, then **navigated away and loaded the page fresh**
— no session state, never pressed Run — and the new page found run
`089dc8a0d8dc` still going and adopted it. It then finished on its own and
reported *2 valid resumes from 20 scored jobs*.

14 new tests, 436 pass, baselines clean. Every test throws away its handle on
the run and asks the registry cold, because "a thread was started" is not the
guarantee — "the answer comes from disk" is.

---

## R52. The last hand-edited fields, and a template that asked too much

**Decision:** (August 2026) The three deferred items that did not depend on the
React question: always/never include, the rest of `locations`, and the
INTERNAL fields a new user should never see. `migration_plan.md`'s USER-INPUT
debt list is now empty.

### always_include / never_include

Both have been read by the parser since it was written — one boosts a
component, the other excludes it outright — so the behaviour worked and the
only way to reach it was opening the JSON. Two toggles per component on the
tuning screen.

The conflict is worth naming: ticking both is a contradiction, and the screen
says **never wins**, because that is what the pipeline already does. Inventing
a different answer in the UI would make the two disagree.

Decisions are passed as `{id: bool}` and only ids on the screen are touched,
so a rule naming a component the resume no longer has survives — R17's point,
that a rule which silently vanishes is indistinguishable from one that never
matched.

### The rest of `locations`

Countries, state priorities and relocation. Not inert: discovery searches the
**first priority state by name**, and the filter scores every posting against
all of them. R40 stopped the form destroying these; this is the half that lets
someone set them.

### INTERNAL fields, and why the note was wrong about them

The deferred entry called this "five profile fields that should be code
constants". It is about twenty-five, and a naive pass at it breaks the file.

**`description` is two different fields.** At the top level it is a developer's
note — "drop in production", per the plan. Inside every `conditional_inclusion`
rule it says *why the rule exists*, which is the entire reason R17 asked for
it. Stripping by field name removes both. It is a path, not a name.

Only two INTERNAL fields lacked a schema default, so the work was small once
that was known: `description` and `discovery_sources` now default, and the
template drops sixteen fields — 3322 characters to 2270. A profile built from
it is 6473 rather than 7813, and every removed field arrives from the schema.

Existing profiles are untouched and still load; the defaults only fill what is
absent.

### Verified

A profile created from the slimmed template loads, reports the same 5
experiences and 13 projects, and ran the pipeline over the frozen 20-JD input
to 1 valid resume. 447 tests, baselines clean, doctor green.

**What is deliberately still deferred:** Q9 (the embedding model past its
shutdown date, with R11 and R36 covering the danger) and Q10 (clearance-gated
employers, which needs investigation before implementation). Both keep their
original reasons.

---

## R53. The two characters that fail silently

**Decision:** (August 2026) `<` and `>` are escaped to `\textless{}` and
`\textgreater{}`. Found by a human reading a shipped PDF, which is the only
way it could have been found.

**Why it survived every guard this project has.** Each of the other nine
characters in the escape map fails *loudly*: `%` comments out the rest of the
line, `&` breaks table alignment, `#` is a macro parameter. `<` and `>` are
not errors at all. The file compiles, the PDF is one page, validation passes,
the page-count gate passes — and in the default OT1 font encoding a bare `<`
renders as an inverted exclamation mark.

Three resumes went out reading **"p99 query latency of ¡5ms"**.

Demonstrated rather than argued, by compiling the real bullet both ways and
reading the text back out of each PDF:

    BEFORE (raw <)         p99 query latency of ¡5ms at million-scale
    AFTER  (\textless{})   p99 query latency of<5ms at million-scale

Both compiled. Both were one page. That is the whole problem: **no test that
checks compilation, page count or validation can see this defect**, so the new
test renders a PDF and reads the glyph back.

### What the audit found, and did not

Seven unescaped `<` across every run ever generated — three in the latest one
(Elastic, Baseten, Modal). No `>`, and **no `~` anywhere**: not raw, not as
`\sim`. The floating tildes seen in the PDFs are a text-extraction artifact of
the reader, not something in the document. The reviewer flagged that
possibility themselves and it turned out to be the case.

Worth recording because the instinct was to fix both. One was real.

### An environment trap in the test itself

The rendered-glyph test could not compile anything at first: Python's
temporary directory on this machine lives under the 8.3 short name
`C:\Users\YASHPA~1\...`, and **pdflatex treats `~` as special in a filename**,
truncating the path at it and stopping before reading a byte. Fixed by running
with `cwd` set to the folder and passing a relative filename, which is more
portable anyway.

17 new tests, 464 pass, baselines clean. The eight resumes of 2026-08-25 were
regenerated and verified clean.

---

## R54. The requirement the title hides

**Decision:** (August 2026) A second deterministic gate, after enrichment and
before analysis, reading the JD body for requirements the title cannot show.

**The failure.** Three of eight resumes in one run went to postings that ruled
the candidate out in their second paragraph, all with clean titles:

| | title says | body says |
|---|---|---|
| Samsara | "Finance & Strategy AI Engineer" | 8+ years relevant experience |
| Scale AI | "Forward Deployed Software Engineer" | 5+ years experience |
| Databricks | "AI Engineer - FDE (**ALL LEVELS**)" | "not intended for internship, new graduate, or entry-level applicants" |

Databricks is the sharpest: the title advertises every level while the body
excludes new graduates by name. No `exclude_keywords` entry can fire on any of
these, because the discovery filter is title-scoped.

**Why title-scoped was right, and still is.** That filter runs *before*
enrichment so it needs no JD, which is what protects the scraping budget. The
answer is not to move it but to add a second pass downstream — and the reason
that is affordable is that enrichment is scraping, not inference. This gate
costs no model call and no request, just regex, so it can run on everything.

### The hard part is not finding the words

It is telling the disqualifying use from the identical words in a job worth
keeping. Elastic's JD — a genuinely good match — reads *"an entry-level
position perfect for new graduates or those with 0-2 years of experience"*. It
contains "entry-level", "new graduates" and a years figure, and means the
opposite of Databricks.

So:

- **Years are read as a floor, and the lowest floor wins.** A posting listing
  "5+ years backend, 2+ years Go" requires 2 to apply; taking the largest
  would reject on a nice-to-have. The floor is compared against the *profile's*
  range rather than a constant, so a senior candidate is not excluded by 8+.
- **A years figure only counts near an experience word.** "grew revenue 40% in
  3 years" is an achievement, not a bar.
- **Entry-level terms need a nearby negation to disqualify.** "not intended
  for", "not open to", "cannot consider" — within ~120 characters, so a "not"
  three paragraphs earlier about visa sponsorship does not govern it.

### A false positive it caught on the way

Discord's QA role asks for **"3-5+ years"**. The first version read that as a
floor of 5 and dropped it: the range pattern required the upper bound to be
followed directly by "years", so only the "5+" matched. The true floor is 3,
which the profile clears.

Worth fixing carefully because **a gate's false positives are invisible** —
nobody ever sees the job that was never shown. That asymmetry is the argument
for making the range form win.

### Measured

Against the 35 enriched jobs of the reviewed run: **4 dropped, 31 kept.** The
three above plus one genuine Okta posting with an 8-year floor — and *not* the
second Okta posting, which asks for 3. The top five for generation became
Elastic, Baseten, Experian ×2 and Modal; the first two are the ones a human
review called good matches for the right reasons.

Dropped jobs are logged with their reason rather than silently removed, which
is the shape this project keeps regretting when it is missing.

26 new tests, 490 pass, baselines clean.

---

## R55. The country that never parsed, and two cities that parsed wrong

**Decision:** (August 2026) The location matcher reads ISO country codes,
matches indicators as terms rather than substrings, and lets a named US state
settle the question before any city name is consulted.

**The report.** A São Paulo posting scored 54% and reached the top of the
funnel, while the profile lists `countries: ["United States"]` and the same
run excluded jobs in the UK, Ireland, Canada, Poland, India, Israel, China,
France and South Korea. Two hypotheses were offered: location scores rather
than gates, or the country never parses.

**The second, exactly.** `"São Paulo, BR"` produced `country=None`. The gate is
a hard exclusion and always was — it simply had nothing to compare, because
`BR` is an ISO code and the vocabulary held only full names. The countries
that were correctly excluded all spell themselves out.

### Codes, and why US states win

`COUNTRY_CODES` maps alpha-2 codes to names, and **every code that is also a
US state abbreviation is removed from it outright** rather than merely ordered
after the state check. The collisions are not exotic: CA is California and
Canada, IN is Indiana and India, DE is Delaware and Germany, and PA, LA, MT,
ID, AL, MS, SC, VA, WA, MO and OK all collide too. Reading "Los Angeles, CA"
as Canada would be a worse bug than the one being fixed. Those countries stay
reachable by name.

Codes are matched only as a **trailing token** — `BR` sits inside "Brooklyn"
and `IT` inside "Detroit".

### Two bugs the fix uncovered, both R18 again

**`"india"` matched inside "Indianapolis".** The indicator loop used plain
substring containment, so an Indiana posting was read as Indian and excluded.
That is R18's finding — a substring credited as a term — in a module that
never got the fix. Indicators are now matched with boundaries on their
alphanumeric ends, which leaves entries like `", bc"` and `"(uk)"` working.

**`"dublin"` matched "Dublin, Ohio".** Boundaries do not help here: it is a
real city name shared by two countries, and "Birmingham, Alabama" would have
become the United Kingdom the same way. So a spelled-out state or trailing
state abbreviation is now checked *first*, as much stronger evidence than a
city name. That also settles "Ontario, California" in favour of California
while leaving "London, Ontario" Canadian.

### The vocabulary was too small to be a filter

`"Reykjavik, Iceland"` spelled its country out and was still invisible,
because the curated list held nineteen countries. **An unknown country is not
neutral** — it silently passes a filter whose entire job is to exclude it. The
list is now derived from the code map as well, 73 countries, so adding a code
adds a name for free.

### Verified

The Experian posting is now excluded with *"Location country 'Brazil' not in
preferred countries ['United States']"*. San Francisco, Dublin Ohio and
Indianapolis are all kept. 24 new tests, 514 pass, baselines clean.

---

## R56. The clearance you hold and the clearance you could get

**Decision:** (August 2026) A deterministic eligibility gate reads what a
posting says about who may hold the job, and compares it against citizenship
facts the profile has carried since R16 plus one new field for a clearance.

**What was left.** The run of 2026-08-25 produced eight resumes and a review
named four postings that should not have been among them. Three were already
gone before the review was written: Samsara (8+ years) and Databricks ("not
intended for ... new graduate") fell to R54, Experian's two São Paulo listings
to R55. Replaying the run confirms it — five of thirty-five dropped, four of
them by gates that shipped that afternoon.

One survived, and it is the interesting one:

    Scale AI — DevOps Engineer, Infrastructure & Security
      years=2      passes R54
      country=US   passes R55
      "candidates will not be considered who do not hold at least a
       TS/SCI clearance"

R2's bet was that a wide pool plus funnel filtering removes the need for
hand-tuned exclusions. Q10 recorded where that bet does not hold, and this is
it: a wrong-*level* job scores low against a new-grad profile and leaves on its
own, but a clearance-gated job can be an excellent semantic match and score
high on merit. Different failure class, and it needed its own mechanism. The
profile's `exclude_keywords` did in fact list `security clearance required` and
`top secret clearance` — neither phrase appears in the posting.

### Postings, not employers

Q10's open sub-question was whether this wanted an employer denylist, and
worried that a list of defense primes would overfit to one user's visa status.
It does not want one. Every clearance-gated posting in the corpus states the
restriction in its own text — Scale AI twice, Accenture Federal ("Security
Clearance Required ... US Citizen Only"), Collins Aerospace ("U.S. citizenship
is required"). The third case Q10 feared, where the restriction is merely
implied by the employer, did not appear.

### Held or obtainable, which is the whole design

Scale AI wrote both sentences, one in each of two postings, and they differ by
a single clause:

    FDE, Public Sector   "An active TS/SCI clearance, or eligibility to
                          obtain one."                          obtainable
    DevOps, Infra        "will not be considered who do not hold at least
                          a TS/SCI clearance"                   held

A clearance takes months and an employer willing to sponsor the investigation,
so "must already hold one" excludes everyone who does not. "Able to obtain one"
excludes nobody who is a US person, because that is all eligibility means. Read
the same way, one of these two verdicts is wrong: either a citizen is shown a
job that will not consider them, or is never shown a job they could have had.

So when one sentence carries both cues the weaker one wins — the same rule
`required_years` uses for "5+ years backend, 2+ years Go", and for the same
reason: a gate's false positives are invisible, because nobody sees the job
that was never shown.

The cost of that rule is locality. `_plain` turns block-level tags into
sentence breaks rather than spaces, so an "able to obtain a corporate travel
card" three bullets below a hard requirement cannot soften it.

### The candidate facts already existed

`personal_info.us_citizen`, `.permanent_resident` and `.visa_status` have been
on every profile since R16, collected by the "about you" screen, and read by
nothing — the same dead-field shape as `rarely_include` (R31) and
`job_preferences.seniority` before R54. Wiring them was most of the work.

`personal_info.holds_security_clearance` is new, defaults to False, and is a
checkbox next to work authorisation. It is the one fact no resume implies. The
default hides jobs, which is normally the wrong direction, but the postings it
hides say in their own words that an applicant without a clearance will not be
considered.

`job_preferences.citizenship_restrictions` was **not** used and is still dead.
Its three booleans (`us_citizenship_required`, `green_card_acceptable`,
`h1b_sponsorship_ok`) describe what a *job* demands, not what a candidate can
clear, so there is nothing in them to compare a posting against. Left alone
rather than deleted, because deleting a field is a schema change and this
change did not need one.

### Two bugs the tests found

**"unable to provide visa sponsorship" did not match**, which is the commonest
phrasing there is. The pattern required the verb immediately after the
negation and so matched none of "unable to provide", "not be able to offer",
"does not currently sponsor".

**"U.S." ended a sentence three times.** Collins Aerospace writes "The ability
to obtain and maintain a U.S. government issued security clearance is
required" — one sentence, split on every period into three, which stranded
"ability to obtain" away from the requirement it qualifies. The gate then read
a job open to any US citizen as one demanding a clearance already in hand: the
exact false positive the held/obtainable rule exists to prevent, reintroduced
by punctuation. `_plain` now normalises the abbreviation before splitting.

### The boilerplate this had to be built around

Equal-opportunity footers are *made of* the vocabulary this gate matches on
and mean the opposite of it. Stripe's reads "military and veteran status
(including military spouse status), or any other characteristic protected by US
federal, state or local laws". Sentences carrying an EEO cue are not read at
all — and the skip is per sentence rather than per posting, so a footer cannot
launder a requirement stated in the body.

Without that guard the gate would have quietly emptied the board for every
candidate who is not a US citizen, and the symptom would have been "the tool
finds nothing", which is not a symptom anyone traces back to a footer.

### Verified

Scale AI's DevOps posting is excluded with *"requires a security clearance you
already hold; this profile does not list one"*. Its Forward Deployed posting is
**not** excluded by this gate — R54's years floor removes it, and a test pins
that, because the day this one starts firing the disjunction rule has broken.
Thirty of thirty-five jobs survive the whole body gate. Accenture Federal's
Pega role is dropped from the 2026-08-21 baseline, which is the Q10 case the
question was opened for. 28 new tests, 542 pass, baselines clean.

---

## R57. The explanation that was computed every run and thrown away

**Decision:** (August 2026) The selection each resume was built from is stored
with the job and shown on the board, explained by which term would have had to
change rather than by which number was largest.

**What already existed.** `_composite_score` has always returned all five terms
— embedding, keyword, conditional, importance, always — for every component it
scores, and `select_components` has always passed them up as `score_breakdown`
alongside `jd_keywords` and `conditional_fired`. Its docstring calls them "for
logging/debugging", and that is precisely where they went: one INFO line per
run, gone with the scrollback, plus a copy in a per-date `analysis_results.json`
that nothing ever opened.

So the question "why is my tutoring job on a backend resume" had an answer
sitting on disk and no way to reach it. The board reads a SQLite row keyed by
URL, which outlives any one run's output directory; the explanation lived in a
directory named after a date.

### Numbers are not an explanation

The obvious version — print the five terms — is the same debug line with better
punctuation. Embedding similarity is around 0.6 for everything and dwarfs every
other term, so "largest term" answers *semantic similarity* every time and
tells nobody anything.

What a person wants is which term **changed the outcome**: remove it, and does
this component still beat the best one that was left out? That is computable
here, because every scored component sits in the same dict and the cutoff is
just the highest-scoring component that did not make it. **A term that can be
removed without changing the selection did not decide anything, however large
it is.**

Each term is tested alone rather than in combination, because a rule that only
matters in concert with another is not something a user can act on. When more
than one is independently load-bearing the sentence says "without either"
rather than "without it" — they were not measured together and must not read
as though they were.

### It immediately contradicted the old strings

`_generate_reasoning` labelled 101gen.ai **"Always included (profile rule)"** on
every job in the run. The counterfactual says otherwise: final 1.25 against a
cutoff of 0.74, so dropping the +0.30 rule leaves it winning by half a point.
The rule fired and decided nothing. A test pins this across every job in the
real run.

The same function had a second defect of the same family, and the file already
carried a comment about a third. `"High relevance score (0.65)"` quoted
`score.experience_scores` — the **raw embedding similarity** — while selection
has run on the composite since the waterfall was replaced. The number in the
explanation was not the number that decided the outcome. Both now read the
composite.

### What the board says

Per job, behind "Why this resume": what was picked, one sentence each, what was
passed over and by how much, and the JD keywords that matched. Near-ties are
named as near-ties on both sides — the component that just got in, and the one
that just missed.

On the Samsara posting that means: `Outlier AI` got the third experience slot
on shared tech terms and drops out without them; `AI Ensured` missed by 0.00;
`Diagnosify` and two others each hold their slot on importance plus keywords
alone.

`describe()` lives beside the report and is called in the orchestrator facade,
not the view — `app.py` may not import from `tools/` and `test_ui_contract`
fails the build if it does. The view receives text and numbers and decides only
how they look.

### The migration this needed

`CREATE TABLE IF NOT EXISTS` is a no-op against a database that already exists,
which is every database the store was built for — 106 rows in the author's. A
new column reaches nobody without an `ALTER TABLE`, so `JobStore` now runs one
on open, driven by `PRAGMA table_info`. It is the first schema change `jobs.db`
has had; the pattern is there for the second.

Existing rows keep a null `selection` and simply show no panel, which is the
right outcome: an expander that promises an answer and opens on nothing is
worse than no expander. Reports appear as jobs are re-scored.

### Verified

The report round-trips through SQLite and renders on the board — checked with
`AppTest` against a copy of the real 106-row store, and the panel reproduces
the sentences above from the real run's data. Unreadable JSON in the column
reads as absent rather than raising. 25 new tests, 567 pass, baselines clean.

---

## R58. A figure replaced by a word

**Decision:** (August 2026) Dropping a metric under compression is allowed.
Dropping it and keeping the claim is an error, and the word that keeps the claim
is what makes it detectable.

**The case.** Q6 was opened as a suspicion — long master bullets lose metrics
when compressed — and sat unscheduled for days because it had no example. It
has one. Master:

    ... XGBoost achieving 94.2\% accuracy ($\pm$0.2\%) and a 15-point macro-F1
    lift over Random Forest (0.71 vs 0.56) - driven by recall gains on critical
    minority classes ...

Shipped on the Samsara resume:

    ... achieving 94.2\% accuracy and significant macro-F1 gains over baseline
    models.

Four numbers left and one word arrived.

### Why "preserve the metrics" is the wrong rule

That master bullet is 386 characters and the project budget is 213. Six figures
cannot fit. Compression is the job, and dropping a metric to do it is correct
behaviour — so a check that flags a missing figure is flagging the system
working.

`_validate_metric_preservation` was that check, and it had been shipping since
before R45. It compared *every* metric in the whole master against one tailored
resume, warned above three misses, and a tailored resume carries three of
thirteen components — so most of the master's figures are absent by
construction. **Measured: 8 of 8 resumes in the 2026-08-25 run tripped it.** A
warning that fires every time is not a signal, and this one sat directly beside
the case that mattered.

It is deleted rather than fixed, on R31's precedent: what it reached for is
expressed properly elsewhere now.

### The line that is checkable

The error is asserting a magnitude the output no longer states. "Significant"
is a claim the master never makes, which puts it in the same family as an
invented number — reached from the other direction. R45 catches a figure in the
output that is nowhere in the source; this catches a figure in the source that
became an adjective in the output.

`find_unsupported_claims` compares a component against **its own source
bullets**, which is why `master_bullets` had to be threaded through
`validate_resume_output` alongside the whole-file text. The whole file cannot
answer "did this component's numbers survive its rewrite" — every figure is
somewhere in the file by definition.

Per component rather than per bullet, because a rewrite may legitimately move a
figure from the second bullet to the first.

### Two failures, two severities

The word alone is not enough. Across every resume this repo has generated there
are exactly three of these words, and they split cleanly:

    "delivering a significant ~3.6x speedup (137s → 38s)"      padding, warning
    "...speedup..., significantly reducing redundant compute"   padding, warning
    "94.2\% accuracy and significant macro-F1 gains"            standing in, ERROR

The discriminator is whether that component actually dropped a figure. Treating
the first two as errors would push a resume into the repair loop over a style
nit and teach someone to click past the error that matters — the trap R45 was
calibrated against, and the reason it flagged 13 of 16 resumes on its first
draft.

### The premise, checked

**The master resume contains none of these words.** Not one, across every
bullet. That is what makes their appearance in output a signal rather than a
style preference wearing a validator's clothes, and there is a test that fails
if it ever stops being true.

### Two metrics nothing could see

`extract_metrics` had no pattern for either half of the lost claim: a margin
stated in points (`15-point`) or a before/after pair (`0.71 vs 0.56`). Both are
now extracted. Bare decimals deliberately are not — `0.71` alone cannot be told
from a version number, and a check that fires on "Python 3.11" is one people
learn to ignore. A decimal earns its place only when a comparison word puts it
beside another one.

Widening extraction also feeds R45's invented-metric **error** path, so its
calibration was re-run: **0 false positives across 33 generated resumes.**

### Before as well as after

The tailoring prompt now carries the rule with the real example, and the repair
prompt carries it too, since an error here routes straight into repair:

    If a bullet is too long to keep a figure, DROP THE WHOLE CLAIM.
    Never replace a number with a word that asserts its size.

### Verified

The Samsara bullet is now an error naming the figures it lost — *"'significant'
asserts a size your resume states as a number — 0.2%, 0.71 vs 0.56, 15-point —
and that number is not in the output"* — checked end to end against the real
master resume through `GenerationAgent._master_bullets`. The always-firing
warning is gone (0 of 8). 19 new tests, 586 pass, baselines clean.

---

## R59. The skills line advertised work the page did not show

**Decision:** (August 2026) A skill is ranked by what backs it: the posting
asked for it, a bullet on this page demonstrates it, nothing in particular owns
it, or its only evidence is a component left off this resume.

**The inversion.** `AI / ML & Data` holds thirteen entries and about seven fit
on a line. `OpenAI Gym` took the last slot on three resumes from the
2026-08-25 run, and which three is the finding:

    Scale AI    RL project NOT on the page      OpenAI Gym listed
    Experian    RL project NOT on the page      OpenAI Gym listed  (x2)
    Elastic     RL project ON the page          OpenAI Gym absent

Exactly backwards, in both directions. `OpenAI Gym` comes from one
reinforcement-learning project; a recruiter reading Scale AI's skills line
finds nothing about RL anywhere else on the page, and the one resume that could
have justified the claim did not make it.

### Two mechanisms, and only one of them was suspected

Everything that did not match the JD filled in **the order the master resume
happens to list it**, and that order clusters `stable-baselines3, OpenAI Gym,
MineRL` ahead of `Pandas, NumPy`. Q21 guessed this and asked for it to be
confirmed rather than assumed; it was right.

The second was not suspected. The character cap **skips rather than stops** — a
skill that does not fit is passed over and filling continues — so
`stable-baselines3` (17 characters) missed the line and `OpenAI Gym` (10) took
the slot behind it. The tail of every skills line was being selected by length.

The skip is kept. Stopping at the first miss wastes the rest of the line. What
changes is that priority now decides the order those skips happen in, so what
falls off the end is the least-supported claim rather than the longest word.

### The evidence was already computed

`select_components` returns `skills` — the union of the selected components'
keywords, 52 to 59 entries per job — and `_build_skills_section` never looked
at it. Same shape as R57: the answer sitting in the return value of a function
nobody asked.

The version used here is derived from the *tailored* output rather than the
selection, because that is what is actually on the page after generation drops
a component.

### The tier that needed a tiebreak

Ranking by evidence alone made one resume worse before it made them all better.
`MineRL` displaced `NumPy` on Databricks, because the keyword extractor tags
widely-used terms to components too — so `numpy` and `minerl` both landed in
the "evidence is elsewhere" tier, and inside that tier the master's order put
the RL stack first again.

So the last tier is ordered by **breadth**: how many components use the term at
all. One absent project's library is a weaker claim than a library running
through four. That is what puts `NumPy` back and leaves `MineRL` off.

### Verified

Across the five resumes in the run that show the category, **no resume
advertises an RL library without the RL project on the page** — measured by
re-rendering each one through `_build_skills_section` against its real
selection and JD. Databricks keeps `NumPy` and gains `Biopython`, which its
antibiotic project earns. The improvement is not confined to that category:
Scale AI's frontend line now leads `React, jQuery, Vega-Lite` — the RunKeeper
project is on that page — instead of `React, Angular, Next.js`, whose mobile
project is not. 22 new tests, 608 pass, baselines clean.

---

## R60. Where this is going, and the order it happens in

**Decision:** (2026-08-25) The destination is a hosted product with paid
tiers. The first thing built is the public job board, and hosted generation is
gated behind three verification items. The local app becomes the free tier.

### What changed

Not the architecture — the constraint. Every previous decision here was made
under OOS5's "no money spent on this project", and that rule is what made
free-tier Gemini the only option, which is what made "twenty active users
exhaust the daily cap before noon" decisive. Willingness to spend removes the
premise.

**The replacement is a number, not a condition: $10/month, the amount that may
be lost with zero users.** See OOS5. This entry first said spend was allowed
"where revenue justifies it" — which is not a constraint, because there is no
revenue and so the condition can never be tested. A ceiling still binds during
the phase that has no income, which is the phase this is.

**Measured, because the whole argument rests on it.** The real generation
prompt across the eight jobs of the 2026-08-25 run is a median of **6,200
input tokens and about 600 output**. At `gemini-3.5-flash`'s published rates
that is roughly **1.5 cents per resume**, or 3 cents through a repair pass:

    3 free resumes        ~5-9 cents per signup
    $5/mo for 50          $0.75-1.50 of inference, 70-85% gross margin

Those figures come from third-party pricing trackers and are **unverified
against Google's own pricing page**, which is one of the three gates below.

### Ollama's role inverts, and it is not a hosting rung

`config.py` points the Ollama rung at `http://localhost:11434`, so it runs on
whatever machine the process runs on. That is the whole point of it locally —
free, private, the user's own CPU. Hosted, `localhost` becomes the server, and
the rung built to avoid cost becomes the only one that needs a GPU instance
running continuously. At 1.5 cents a resume, a few hundred dollars a month of
GPU is what roughly twenty thousand Flash resumes cost.

R44 settles the rest: `llama3.1:8b` was measured and did not work — rewrites
failed to parse, resumes fell back to the user's own bullets, and the replies
that parsed invented metrics. Hosting it would buy the `none` rung at GPU
prices.

**So: Ollama stays, local only.** Hosted users get the paid Gemini key. There
is also a privacy reason the hosted path must use a paid key rather than a
free one — free-tier content is used to improve Google's products, which is
disqualifying for strangers' resumes.

### The seam

The pipeline already splits where the hosting question does:

    shared, public, zero PII    discovery: 86 companies, ~11,600 roles, keyless
    personal, expensive         resume, embeddings, generation, LaTeX

Hosting the first half needs no auth, no key, no LaTeX and no resume. It is a
scheduled crawl writing static output, plus a site that renders it — with the
R56 eligibility gate applied, so postings that rule the reader out never
appear. That is a real product and it is most of the way built.

### The free tier is the local app

"Three free resumes, then pay" needs identity to enforce, which means auth,
email verification, an abuse surface, and a bill for everyone who never
converts — from an audience defined by not having income.

The cleaner structure was already sitting there: **the local app is the free
tier.** Unlimited, on the user's machine, their key or no key at all. Hosted
generation is purely paid convenience — no install, no LaTeX, no key. Free
users cost nothing but the static board, paid users are gated at the door, and
no metering system ever has to tell a free user from a fresh browser profile.

The funnel is then honest: board → run it locally → pay if you would rather
not run anything.

### Redistribution: not silence, a scope that addresses somebody else

**Corrected 2026-08-25, same day.** This section first read "the documentation
is silent". That was wrong, and wrong in the direction that flatters the plan —
worth keeping, because a decision record exists so future-you can audit the
reasoning rather than inherit its conclusion.

What the docs actually do is **state a purpose, addressed throughout to the
platform's customer**. Greenhouse describes the Job Board API as exporting
information about *your* public job boards and job posts so *your* web
developers can build custom career and application sites. Ashby's line is the
same sentence with the same addressee: "if you host your own careers page, you
can use this data to populate it."

That is a stated scope that does not include a third-party aggregator. Whether
it *excludes* one is a different question and genuinely unresolved: the
endpoints are unauthenticated, the data is what each customer chose to publish,
and an entire aggregator industry operates on exactly this basis. But "the docs
say nothing" and "the docs describe a use case that is not mine" are different
findings, and only the second is accurate.

**Three places the check did not look**, and any real answer needs them:

- **Platform Terms of Service** on greenhouse.com and ashbyhq.com. API
  reference pages rarely carry terms; the terms live in the site ToS and
  usually cover programmatic access.
- **`robots.txt`** on the board domains.
- **Who owns the prose.** The job description is the *employer's* copyright,
  not the ATS's. Ashby granting or withholding anything says nothing about
  Stripe's rights in Stripe's job description — so permission from the platform
  would not settle it even if it existed.

### The mitigation, and why it survives all of that

Since it cannot be settled by reading, it is designed around: **link out, do
not mirror.** The board serves title, company, location, posted date, source,
apply URL and JobScout's own score and labels. It never serves the scraped
`full_jd`, which stays server-side as scoring input. Facts about a job carry
thin copyright; the job description's prose is the part somebody owns — and
that owner is the employer, which is precisely why not serving the prose
matters more than anything the ATS does or does not permit. The link sends
traffic to the original posting, which is what these feeds exist for.

This is a risk judgement rather than legal advice, and it is worth a real
opinion before there is revenue attached.

### Phase two is gated on three things

None of them block the board; all of them decide the shape of what follows.

1. ~~**Confirm Gemini pricing**~~ — **done 2026-08-25**, against
   `ai.google.dev/gemini-api/docs/pricing`. The third-party figures were
   right: `gemini-3.5-flash` is **$1.50/M input, $9.00/M output**, so the
   ~1.5 cents per resume above stands. `gemini-3.1-flash-lite` is **$0.25/M
   input (text), $1.50/M output**.

   The same page settles the privacy question this entry asserted, and in the
   direction it assumed: prompts and responses are used to improve Google's
   products on the **free** tier and **not** on the paid tier. So a paid key
   is not merely a quota decision for a hosted product handling strangers'
   resumes — it is the only defensible one.
2. ~~**Spike LaTeX in the browser**~~ — **done 2026-08-25, see R63.** It
   works and it is the wrong trade: 31 MB of WASM plus 88.5-191.9 MB of TeX
   Live before the first resume renders. Phase two is therefore designed
   around a **server-side TeX container**, and the PII custody that comes with
   it is real and has to be planned for rather than engineered away.
3. **A cost/quality measurement on `gemini-3.1-flash-lite`** against the
   frozen baselines. Now that both prices are known the prize is **6x, not
   10x** — 0.25 cents per resume against 1.5 — because the lite tier's output
   price is only a sixth of Flash's rather than a tenth. Still worth measuring;
   less worth contorting the design for.

### Sequence

    R56  the eligibility gate            done (924a601) — the board must not
                                         surface roles that rule the reader out
    ->   the public board                React, the design work, the deploy
    ->   Q17  role type vs vocabulary    solved while being wrong is still free
    ->   hosted generation + billing     once the three gates are answered

Deliberately not a build plan. The architecture document is worth writing when
phase two starts and the WASM spike has reported.

---

## R61. The pipeline invented job descriptions, and scored them

**Decision:** (2026-08-25) A failed scrape is recorded as failed. The mock is
reachable only when a person asks for it.

**What was happening.** When `scrape_jd` failed, enrichment called
`mock_scrape_jd` and returned its output as if it were the posting. That mock
writes invented boilerplate — *"a leading technology company building
innovative solutions that impact millions of users"*, *"an entry-level position
perfect for new graduates or those with 0-2 years of experience"* — and
hard-codes `scraped_successfully: True`.

R44 and R45 are about a model inventing. This is the *pipeline* inventing, and
it was invisible for three reasons at once:

- `scraper_used` said `mock_fallback`, and **nothing anywhere read it**.
- `scraped_successfully` was written by every path and **read by none**.
- The result was cached, and a cache hit hard-coded `scraped_successfully:
  True` as well — so on every subsequent run the invention came back *without
  even the warning*, because the warning happens at scrape time and a cache hit
  never scrapes. Each re-run made it quieter.

### Measured on real data

    cached JDs that were fabricated       36 of 178   (20%)
    scored jobs derived from one          34 of 103   (33%)
    of those, with a generated resume      8

And they were not scattered through the middle of the board — they **held the
top of it**: 55.8, 55.3, 55.0, 54.4, 54.1. Generic flattering prose matches
every query, which makes it an ideal embedding target. The invented text also
reads *"perfect for new graduates"*, which is exactly the phrasing R54's body
gate reasons about, so the fabrication **guaranteed its own pass** through the
gate built to catch bad fits.

The Elastic posting at 55.0 was the second-ranked job of the run this session
spent its first half analysing.

### The fix is three lines and a principle

A failed scrape returns the short description discovery already found — real
text, merely thin — with `scraped_successfully: False` and `scraper_used:
"failed"`. Cache hits carry their origin instead of asserting success.

The mock itself is untouched and stays. `--mock` is a thing a person asks for;
using it when nobody asked is R47's distinction exactly — "you chose this" has
to look different from "this broke".

Then something finally reads the flag: generation skips jobs whose description
was never read. Scoring them is still fine — a short description is thin, not
false, and the job belongs on the board — but spending a model call to tailor
against it produces a resume tailored to nothing. A missing flag counts as
readable, so replayed runs and older fixtures behave as they always did.

### Fixing the code does not clean the disk

`scripts/purge_fabricated.py` removes the fabricated cache entries and clears
the scores taken against them, keeping the jobs themselves — they are real
postings, and only what was concluded about them is worthless. Clearing
`scored_at` also returns them to `unprocessed_urls()`, so the next run scores
them against real text.

Run on the author's data: 36 cache entries removed, 34 scores cleared, cache
now holds zero fabricated descriptions. The eight resumes already on disk are
left alone and reported, because deleting someone's files is their call.

### Found by running the thing

None of this was visible from the tests, the board, or the summary — every one
of them reported success. It surfaced because a fresh run was made before
styling a board on top of stale artifacts, and one line of the log said
`using mock fallback`.

### Verified

20 new tests, 628 pass, baselines clean. The four test classes that read a real
run were also repointed at `baselines/2026-08-25-pre-r53/` rather than
`outputs/`, since a live output directory is overwritten by the next run — this
one silently cost three tests their fixture an hour before it was noticed.

---

## R62. A gate that only ever ran once

**Decision:** (2026-08-25) The board stores each job's gate verdict and
recomputes it when the gate's code or the profile it reads has changed.

**The gap.** Every gate — R54's experience floor, R55's country check, R56's
eligibility — runs between enrichment and analysis. Right for a pipeline, which
is a pass over new work. Wrong for a board, which accumulates: the gate fires
once, when a job is first scored, and a gate shipped on Tuesday never sees a
job scored on Monday.

Measured immediately after R61's purge: of 69 scored jobs, **26 (38%) would be
excluded by the gates as they stood**, and they held the entire top of the
board — Samsara's 8+ years role at 55.8, Databricks at 54.6, Scale AI at 54.5.
Every one a posting R54 was written to remove, sitting at the top because it
was scored before R54 was written.

### Stored, not recomputed per read

Read-time gating is tempting and wrong here for a boring reason: **the board is
paged.** Filtering a page the database already sliced turns a page of twenty
into a page of twelve, and the count in "showing 1-25 of 68" stops meaning
anything. So the verdict lives in a column and the filter is SQL.

Two columns, added through R57's migration mechanism: the reason, and the
fingerprint it was judged under.

### The fingerprint is derived, not declared

The obvious design is `GATE_VERSION = 3`, bumped by hand. This project has
shipped that bug twice already — a field computed and never read (R31), a flag
written by every path and consulted by none (R61) — and a version somebody must
remember to bump is the same thing waiting to happen a third time.

So the fingerprint is a hash of **this module's own source** plus the profile
fields the gates read. The only way to change a gate without invalidating the
stored verdicts is to not change it. Editing a comment in `job_filter.py`
re-runs the gate over the store, which costs milliseconds and is the right side
to err on.

The profile half matters as much as the code half: R52 lets someone change
their seniority range or preferred countries from the UI, and a verdict
computed against the old answer is wrong the moment they do. A test pins each
of those fields.

`refresh_board_gate` is called before each render. After the first pass it is
an indexed comparison matching nothing, which is what makes that affordable.

### Hidden, and said out loud

The gated jobs are not deleted and not silently dropped. The board shows a
count — *"Also show 39 job(s) that rule you out"* — and revealing them marks
each with the posting's own words: *"asks for 8+ years of experience; this
profile's range tops out around 3"*.

Silent removal is the shape this project keeps regretting, and `_apply_body_
gate`'s own docstring says so about the pipeline half of the same gate.

An unjudged row counts as eligible, so an unrun gate cannot empty a board.

### Verified

On the real store: 107 rows judged, **68 shown and 39 hidden**. The board's top
five went from *Samsara People Analytics (8+ years), Samsara Finance &
Strategy (8+ years), Databricks FDE (excludes new grads)* to *Software Engineer
I, AI Engineer, AI Engineer Product* — entry-level roles, which is what the
profile asks for. Checked end to end through `AppTest`: 68 shown, toggle on,
107 shown with reasons attached. 24 new tests, 652 pass, baselines clean.

---

## R63. LaTeX in the browser: it works, and it is the wrong trade

**Decision:** (2026-08-25) Phase two compiles PDFs server-side. Browser WASM is
documented as the fallback if PII custody becomes the binding constraint.

**The spike.** R60 gated phase two on three questions. This was the one that
decided the architecture, because the answer determines whether a hosted
JobScout ever holds a resume.

### It works

`texlyre-busytex` 1.4.0 (TeX Live 2026, published eleven days before this was
written) compiled the real template in a browser: **exit code 0 on every pass,
a 52 KB `%PDF-1.7`**. Every package the template needs resolved — `latexsym`,
`fullpage`, `titlesec`, `marvosym`, `color`, `verbatim`, `enumitem`,
`hyperref`, `fancyhdr`, `babel`, `tabularx` — as did `\input{glyphtounicode}`
and `\pdfgentounicode=1`, the two pdfTeX-specific lines that were the real
uncertainty. So did the constructs R53 spent a commit on: `\textasciitilde{}`,
`\textless{}`, `$|$`, `94.2\%`.

**Engine choice is not optional.** The demo defaults to XeLaTeX and XeLaTeX
*fails* on this template — `\pdfgentounicode` is a pdfTeX primitive XeTeX does
not have. Exit code 1 until the engine was switched to pdfLaTeX, then 0. Worth
recording because "LaTeX in the browser works" is not a fact; "pdfLaTeX in the
browser works" is.

### And it costs the visitor 120-226 MB

Measured directly from the asset server rather than estimated:

    busytex.wasm                31.0 MB
    texlive-basic.data          88.5 MB
    texlive-recommended.data   191.9 MB

The template compiled against *recommended*. So the first visit costs roughly
**226 MB**, or about **120 MB** with the basic collection plus an on-demand
package endpoint. IndexedDB caches it afterwards — the cost is paid once, in
full, before the first resume renders.

That inverts R60's argument. Client-side compilation was attractive because the
server would never touch a resume. It is unattractive because **the paid tier's
entire pitch is "no install, no LaTeX"**, and a 120 MB download is a worse
imposition than the install it is replacing. On a phone it is not a trade at
all.

### A prediction that was wrong, and how

Before compiling anything, the collection indexes were read to work out which
packages ship where, and they said `fullpage`, `titlesec` and `enumitem` were
in *Extra* only — implying a 340 MB download. The compile then succeeded on
*recommended*.

The index lists `\ProvidesPackage` declarations, and not every `.sty` announces
itself that way, so absence from the index is not absence from the collection.
The empirical test overruled the analysis, which is the entire reason the
reviewer asked for a compile rather than a survey.

### Licensing, which nobody asked about

`texlyre-busytex` is **AGPL-3.0-or-later** (bundling MIT-licensed BusyTeX
components). SwiftLaTeX upstream ships no compiled engine at all — the
repository holds C sources and a Makefile, so "point a script tag at it" is not
available without building it yourself.

AGPL against a commercial product with paid tiers is a question for someone
qualified, not for this document. It is recorded because it is the kind of
thing that is cheap to notice now and expensive to notice after launch.

### What this settles

Phase two compiles server-side, in a container with a trimmed TeX Live — the
direction Q8b tentatively recorded long before there was a reason to care.
**The PII custody that comes with it is now a planned cost rather than
something the architecture avoids**, which is a materially different product to
design: retention, deletion, and what the privacy policy has to say.

---

## R64. Facts about the posting, not verdicts about the reader

**Decision:** (2026-08-26) The public board extracts what each posting demands
and lets the reader filter. Every facet carries the basis it was read on.

**The hole in R60.** R60 said the board would apply "the R56 eligibility gate
so the ineligible postings never appear". It cannot. **Eligibility is defined
relative to a person and a public board has no visitor** — the same is true of
the match score, which is computed against one resume and means nothing to a
stranger. The plan read fine and only failed on contact with the code.

So: facets, not gates. The board says a role wants eight years; it does not say
you are unqualified.

### Most of it already existed

`required_years`, `excludes_entry_level` and `parse_location` were already
profile-free — they read the posting, not the person — and needed no changes.
The one refactor was splitting `posting_demands(text)` out of R56's
`eligibility_disqualifiers(text, profile)`: the sentence loop, the EEO guard
and the held-vs-obtainable rule moved out unchanged, and the judgement stayed
behind. R56's 28 tests passed untouched, which is what made the split safe to
make.

### Three states, because a filter is not a gate

`required_years` returns None for two different things: the posting states no
floor, and the text could not be read. **Under a gate that collapse was
harmless** — it meant a job slipped through. Under a filter it is not: a
five-years role whose floor failed to parse lands in the early-career view
looking like it belongs there.

So `years_basis` is `stated`, `none_stated` or `unknown`, and `unknown` covers
both a body too thin to read and a body that asks for experience in words no
parser turns into a number ("several years of experience"). `demands_basis`
does the same for clearance and citizenship.

The frontend must show `unknown` under a filter rather than hide it, which is
why `include_unknown_years` is in the default preset. That is R62's lesson —
a filter that removes things without saying so — applied to the visitor's side.

**The threshold is calibrated, not guessed.** Real scraped bodies in the store
start at 818 characters (p10 = 2,987, median = 5,663); the short descriptions a
failed scrape falls back to since R61 run 25-300 characters. Nothing lands
between 300 and 818, so `READABLE_MIN_CHARS = 500` sits in an empty gap with
margin either side, and a test fails if it ever drifts into the occupied range.

### Counting the facets changed a frontend decision

The export reports what each facet actually knows, because a control over a
field that is mostly empty looks useful and does nothing. On 107 real rows:

    years_basis    stated 60,  none_stated 42,  unknown 5
    years stated   1:4  2:8  3:20  4:3  5:20  8:5
    level          unspecified 46,  mid 32,  senior 25,  entry 4
    country known  62 / 107
    demands        clearance 1,  us_person 7,  no_sponsorship 1

**The years filter is the useful control and the level facet is not.** Level is
`unspecified` for 43% of rows, and only four postings classify as entry —
because most genuinely early-career roles state no floor at all, and inventing
"entry" for a posting that never said would put senior roles in the view most
visitors start on. So the board leads with years and treats level as secondary.

That is a finding the frontend would otherwise have discovered by building the
wrong control first.

### The seam

`full_jd`, `score`, `selection`, `status`, `scored_at`, `resume_tex`,
`resume_pdf` and `gate_reason` never cross. The first is the employer's prose —
R60's redistribution answer is that the board links out rather than mirroring —
and the rest are one person's.

`build_row` emits an allow-list, so none of them can appear by construction,
and the exporter asserts it anyway and refuses to write on a leak. "True by
construction" is exactly what was true of `scraped_successfully` before R61.
A test also checks that no marker planted in a JD appears anywhere in the
payload, because the field list is not the point — the text is.

**Population is every job in the store, deliberately.** `board_export_rows()`
does not pass `eligible` and must never learn to: the gate columns hold *this*
profile's verdict, and a mid-level reader wants the five-years roles this
machine's owner is filtered out of. Filtering there would quietly rebuild the
opinionated single-user board that facets exist to replace.

### The export itself

`schema_version` so the frontend cannot drift silently, `generated_at`,
`facet_summary`, and `default_preset` — the early-career view as **data rather
than React**, because facets were chosen over gates precisely on the grounds
that early-career is a default and defaults should be changeable without a
deploy.

72 KB for 107 rows, so roughly 700 bytes a row; ten thousand postings would be
about 7 MB. Gitignored: committing a file of real listings to a public repo
*is* the redistribution act R60 left unresolved, and it should not happen as a
side effect of running a script.

### Verified

35 new tests, 687 pass, three baselines clean. Against the frozen baseline
Samsara reads 8 years and senior, Scale AI's DevOps posting demands a clearance
in hand while its Forward Deployed posting demands only US-person status — the
held-versus-obtainable distinction surviving the refactor — Databricks excludes
early career, and Experian resolves to Brazil.

---

## R65. The board people will actually see

**Decision:** (2026-08-26) The public board is a static React page over R64's
export. Vite, React 19, Tailwind 4, no component library.

**Why no shadcn.** The advice was not to hand-roll a component library for a
board, and the advice is right — but shadcn's init pulls Radix, CVA and path
aliases to supply what turned out to be five controls, against React 19 /
Tailwind 4 / Vite 8, all new enough that a generator is a risk of its own. Five
controls written directly cost less than the setup and are quality this project
controls. The finished bundle is **198 KB, 62 KB gzipped** — worth stating next
to R63's 120-226 MB, which is what the browser-LaTeX path would have added.

### The facet counts decided the controls, as intended

R64 measured what each facet knows before anything was designed, and it changed
the layout: **years leads and level is not a control at all.** Level reads
`unspecified` on 43% of postings and `entry` on four, because genuinely
early-career roles mostly state no floor. A level filter would have looked like
the obvious primary control and done almost nothing.

### Three states, all the way to the screen

The rule R64 established in the data survives into the UI: a facet the export
could not read is *shown*, and hiding it is a choice the reader makes with the
count in front of them. "Include postings that don't say" is checked by
default and says how many hang on it.

**The country filter is where this stopped being theoretical.** 45 of 107
postings resolve to no country, because the location text reads "*HQ - San
Francisco, CA". Dropping those under a United States filter hides US jobs from
someone filtering for the US — so they are kept, and the first version of this
page then showed a São Paulo role under a United States filter, because a bare
"São Paulo" is unresolved in exactly the same way. Neither default is right, so
it is a toggle: *"Include 45 with an unclear location"*, and the count moves
68 → 38 when it is turned off.

### Two smaller calls

**Amber means "this rules you out"** — clearance, US-person, no sponsorship,
excludes-new-grads. The first draft flagged the years tag too, so a "3+ years"
posting matching a "max 3 years" filter appeared as a warning about itself. If
every tag is a warning, none of them is.

**The heading says "tech roles", not "engineering roles"**, because the data
contains business analyst postings and the title was quietly wrong about its
own contents.

### What the page refuses to do

It renders nothing if `schema_version` does not match — a frontend drawing a
shape it does not understand is worse than one that stops. And the footer says
the requirements are read from the posting and can be wrong, because they are
extracted by regex and the employer's posting is the authority.

`frontend/public/jobs.json` is gitignored for the same reason `data/board/` is:
committing a file of real listings to a public repo *is* the redistribution act
R60 left open, and it should not happen as a side effect of a build.

### Verified

23 frontend tests over the filter rules — where a three-state bug hides
silently — plus a typecheck and a production build. The Python suite is
untouched at 687. Driven in a real browser rather than reasoned about: the
country filter moves 77 → 68 → 38 as it is tightened, São Paulo leaves when it
should, and a fresh tab loads with zero console errors.

**Not done:** the deploy and the nightly crawl, so this runs on localhost only.
Q23 still means the page can say "first seen today" and not "posted today".

---

## R66. The product found its audience, and the code had not

**Decision:** (2026-08-26) JobScout is a paid product for tech job seekers at
any level who hand-tailor resumes against job descriptions. The public board is
dropped. `CLAUDE.md` records the definition so no session has to re-derive it.

**What changed.** JobScout worked — it ran its author's job search and he got
hired. That turns the project from a personal tool into a product with a
proven premise, and the audience becomes people doing by hand, with a chatbot,
what this does in a pipeline.

### The board was built on a premise this goal makes false

R60 argued for the public board on a seam: discovery is *shared* — keyless,
PII-free, identical for every user — while the resume half is personal and
expensive. Host the first, keep the second local.

That seam exists only while every user wants the same jobs. Once a profile
drives **what gets discovered** rather than only what gets ranked afterwards,
discovery is per-user, there is no shared half, and the board is a different
product rather than a funnel into this one.

R64 had already found the first crack without recognising it: the board could
not apply R56's eligibility gate, because eligibility is defined against a
person and a public board has no visitor. That was not a gap to design around.
It was the seam failing.

**Dropped, not deferred.** `frontend/` and `scripts/export_board.py` are
deleted, recoverable at commit `717c50a`. Code that looks live and is not
misleads whoever reads it next (R31).

### What the two days bought anyway

The refactor turns out to be the multi-user architecture, not a workaround.
Splitting `posting_demands(text)` out of `eligibility_disqualifiers(text,
profile)` was done because the board had no visitor; **one posting evaluated
against many users** is exactly that shape, and it would have been needed
regardless. Kept, along with `required_years`, `excludes_entry_level` and
`parse_location`, which were already profile-free.

`board_export.py` becomes `posting_facts.py` — the three-state basis rules
describe a posting without reference to any reader. The board-only parts
(`SCHEMA_VERSION`, `DEFAULT_PRESET`, `build_rows`, `summarise_facets`) are gone.

### The live bug the audit found

`build_serper_query(role, seniority, site)` has always been parameterised.
Both callers passed a literal:

    discovery_agent.py:222   build_serper_query(role, "new grad", ...)
    discovery_agent.py:251   query = f"{role} new grad"

**So discovery searched for new-grad roles whoever you were.** A mid-level
user's pool was filtered twice — once by a constant nobody had noticed, then
again by their own gate, which discarded what came back.

R34 made the *gate* read `job_preferences.seniority` and roadmap item 13
recorded the work as done, quoting the very function whose caller was wrong:
*"already parameterised and the caller simply passes `new grad`"*. The
observation was correct and was read as a description rather than a defect.

`primary_seniority_term(profile)` supplies the term, empty for a profile with
no opinion, since `build_serper_query` already omits an empty seniority and an
unfiltered role search beats a wrong one:

    ['new grad', 'entry level']   -> "Backend Engineer new grad site:greenhouse.io"
    ['mid', 'senior']             -> "Backend Engineer mid site:greenhouse.io"
    []                            -> "Backend Engineer site:greenhouse.io"

`github_newgrad` is also now skipped unless the profile's range reaches
early-career. Those repos are curated new-grad lists with no senior
equivalent, so for anyone else they fill the pool with postings the gate throws
straight out.

### Dead fields, four and five

- `graduation_eligibility` — declared in the schema, read by **nothing**.
- `experience_level` — read by one print statement in the profile summary.

Both new-grad-shaped, neither doing anything: the same pattern as
`rarely_include` (R31), `scraped_successfully` (R61) and the selection
breakdown (R57). Removed from the schema and the template; existing profiles
load unchanged because pydantic ignores extra keys.

That is five instances of one bug, so it is now written at the top of
`CLAUDE.md`: **wire the consumer in the same change, or do not add the field.**

### Scope, stated rather than implied

**Tech job seekers, any level, any location.** Not "all fields", and the
reasons are specific rather than caution: Greenhouse, Ashby and Lever skew hard
to tech, so a nurse's postings are largely not in the corpus; Jake's template
is a one-page tech resume with a projects section; and Q17's
vocabulary-over-role-type problem worsens where "analyst" names five different
jobs. That is still the whole software labour market instead of one graduating
cohort.

`README.md` had been describing the old product — "discovers new-grad /
entry-level software roles" — and now describes this one.

### Verified

691 tests, three baselines clean, doctor green, and the author's own profile
still produces exactly the searches it did before. 16 new tests pin the query
term across four seniority ranges and pin `github_newgrad` being skipped for
profiles that cannot use it.

---

## R67. The score that could not tell jobs apart

**Decision:** (2026-08-26) A job's score is 70% embedding similarity and 30%
concrete overlap — technologies named by both the posting and the resume — and
it carries its own parts.

### The measurement that started it

Q17 was a component-selection anecdote: a tutoring job beat an AI internship by
0.033. The product version is worse and countable. Across 69 real scored jobs:

    embedding score   41.5 - 55.8   stdev 3.58   CoV 0.071

Half of every job sat inside a four-point band. **A user shown "55% match"
against "52% match" was reading noise.** R49 met this symptom and answered it
with display bands relative to the user's own distribution; that was the right
patch for a board and never touched the cause.

Concrete overlap on the same corpus:

    shared technologies   0 - 12    stdev 2.78   CoV 0.586

**Eight times more discriminating**, computed by machinery this codebase
already had — `_composite_score` uses exactly this for *component* selection,
so job scoring was the less sophisticated of the two.

### They disagree, and the embedding is the one that is wrong

Spearman rank correlation between the two orderings: **0.312**. Where they
disagreed:

    Samsara      Finance & Strategy AI Engineer   2nd    3 shared terms
    Affirm       Software Engineer I, Fullstack   4th    2 shared terms
    Nuro         Full Stack Software Engineer    47th   11 shared terms
    Squarespace  Software Engineer, Frontend    near last  11 shared terms

The resume is AI-heavy, so the embedding rewards a posting that *reads* like AI
over one that names the same tools. A job sharing two technologies outranked
one sharing eleven.

### What Q17 asked for, and why it was not built

Q17 proposed deriving a role-type signal from the title. Measured before
building: `role_score` is the maximum for **100% of the 69 scored jobs**.
Discovery filters on `target_roles` before anything is scored, so by the time
analysis sees a posting it matches by construction — the signal is destroyed by
conditioning on survivors.

Adding it would have been a term that changes nothing, which is the bug found
in `rarely_include` (R31), `scraped_successfully` (R61), the selection
breakdown (R57), and `graduation_eligibility`/`experience_level` (R66). A test
pins the negative result and fails if discovery ever stops gating on roles, at
which point the idea is worth revisiting.

### The weights, and where they came from

`KEYWORD_WEIGHT = 0.3` mirrors `_composite_score`, where the keyword term caps
at 0.25 against an embedding near 0.6 — about 30% of the total. It was **not**
tuned to flatter this corpus.

`KEYWORD_SATURATION = 8` is the 90th percentile of shared-term counts. Past
that, more overlap says little, and the cap stops a keyword-stuffed posting
from climbing on repetition.

Blended *after* normalisation, not before: `_normalise` is calibrated per
backend against measured raw cosine ranges (R36), and folding a keyword count
into the raw figure would push it outside the window those constants were
measured for and silently rescale everything.

### Result

    stdev    3.58  ->  9.04      (2.5x)
    range   41.5-55.8  ->  33.8-68.2

Brex's *AI Engineer, Product* — one shared technology — falls 45 places.
Squarespace's *Software Engineer, Frontend* — nine — rises 53.

### The score can now be taken apart

`EmbeddingScore` carries `embedding_score`, `keyword_score` and
`keyword_hits`. R57's lesson applied one level up: a single number nobody can
decompose is exactly what let two shared technologies outrank eleven without
anyone noticing for months.

Mock scoring blends too. A mock that behaves differently from production is how
an invented job description survived a week (R61).

### Migration

The 69 stored scores were computed under the old formula, and a board mixing
two scales is R62's problem again. Migrated in place with **no API calls** —
the stored value *was* the embedding half, so the blend is arithmetic over what
was already there. `data/jobs.db` backed up first.

### Verified

17 new tests, 708 pass, three baselines clean, doctor green. The corpus test
asserts that blending *widens* the spread rather than pinning a number, so a
future change that flattens the score again fails rather than passing quietly.

**What this does not do:** make the embedding understand role type. Nothing
here claims that. It bounds the embedding to 70% of the score and puts evidence
beside it.

---

## R68. Asking the question a person can answer

**Decision:** (2026-08-26) The wizard asks how long you have worked and derives
the seniority vocabulary. Three fields with no consumer were wired, three were
deleted, and the tool stopped defaulting to its author.

### The wrong question

The wizard asked a stranger to pick a *range of seniority levels* — modelling
work pushed onto them — and `YEARS_BY_LEVEL` converted the answer straight back
into a number of years, which is what R54's gate had always used. Years is the
fact somebody knows about themselves.

`years_experience` is now the question. Levels stay internal because the text
matching genuinely needs them: `accepted_seniority_terms` matches a dozen ad
phrasings per level, and R66's search queries need one word.

**The tolerance constant reproduces measured behaviour rather than looking
tidy.** `years + 3` is what the old map already produced at both points a real
profile had been measured at: a new grad tolerated a floor of 3, and a
`[mid, senior]` profile tolerated 8, which is 5 + 3. Replaying the frozen
corpus, the gate drops **the same five postings for the same reasons**.

### The override had to survive, so nothing writes to it

Someone with six years who narrows the range to mid-level must keep that choice
when they later edit an unrelated screen. So the derivation never writes into
`seniority`: **emptiness is the flag**, exactly as R15's `merge_importance`
treats a component the profile does not mention. A field recomputed on save is
a field that loses your answer.

Verified by walking it: set six years, override to `[mid]`, then edit the
location screen and then the target roles — `[mid]` throughout.

### Three fields wired, three deleted

`willing_to_relocate` was the worst of the six with no consumer, because the
wizard **asked for it** and nothing read the answer. It is now a **gate, not a
weight**, and R55 is why: a weighted location penalty gets outrun by vocabulary
overlap, which is how a São Paulo posting scored 54%. Guarded, too — a profile
naming no cities and no priority states has expressed no preference, and gating
on the flag alone would empty the board.

`exclude_countries` is one clause beside the whitelist, checked first because
it is the narrower statement. `employment_types` became `employment_facet` in
`posting_facts.py`, carrying R64's three-state basis so a posting whose scrape
failed reads "unknown" rather than "full-time by default".

Deleted: `citizenship_restrictions` (job-shaped, replaced by R56's candidate
facts), `comments`, `job_recency_hours`.

### Stop defaulting to one person

Four agent CLIs defaulted `--profile` to `yash_pathak`, which for anyone else
fails by looking for a profile they never had. Now: the only profile when there
is one, and argparse demands it when there are several.

`ROLE_OPTIONS` went from nine titles to nineteen, and `EXCLUDE_OPTIONS` — fixed
at "senior, staff, 3+ years" — is now derived from the user's own experience.
A senior engineer was being offered their own roles to exclude.

### A dead guard, and four cities in the wrong country

Testing the relocation gate turned up something worse than the feature.

R55 removed US state abbreviations from `COUNTRY_CODES` so "Los Angeles, CA"
could not read as Canada. **That removal never ran.** `US_STATES` holds its
abbreviations lower-case and `COUNTRY_CODES` holds its keys upper-case, so
`code not in _AMBIGUOUS_WITH_US_STATES` compared `"MA"` against `{"ma", ...}`
and matched nothing. The codes R55's comment credits it with removing — CA, IN,
DE — were safe only because they had *also* been struck from the literal by
hand. The guard was decoration.

Four collisions survived, and they are not obscure places:

    Chicago, IL       -> Israel
    Boston, MA        -> Morocco
    Denver, CO        -> Colombia
    Little Rock, AR   -> Argentina

Zero jobs in the store were affected, which is why nothing caught it: those
postings spell their states out ("Chicago, Illinois"). A user in Boston reading
"Boston, MA" would have had every local job excluded as Moroccan — a bug that
could only ever hit somebody who was not the author.

One `.upper()` fixes it. Every R55 case still resolves as it did.

### Verified

742 tests, three baselines clean, doctor green. The frozen corpus drops the
same five postings for the same reasons; the author's profile keeps its
explicit range and its tolerance of 3; the override survives two unrelated
saves; and the relocation gate cannot empty a board when no location is named.

---

## R69. The glyph bug that escaping could not reach

**Decision:** (2026-08-26) A tilde is written `$\sim$`, both renderers escape
the same characters, and the template deliberately does not load `fontenc`.

**Why this survived three sweeps.** R53 found that `<` prints as an inverted
exclamation mark under this template's OT1 encoding and escaped it. Twice since
then the report came back that the bug was still there, and twice a search of
the generated `.tex` files found nothing. Both searches were right and both
were looking in the wrong place.

### The twin renderer

R53 fixed `generation_agent._escape_latex_impl` and not `tex_renderer.escape`,
which is the path an **imported PDF or DOCX** resume takes. So the identical
bug sat in the module only a *new* user reaches — the author's resume is a
`.tex` that never passes through it.

That is the second bug this week reachable only by somebody who is not the
author, after "Boston, MA" reading as Morocco (R68). The generalisation work is
finding a class of defect nothing else could.

### The half no escape could fix

`\textasciitilde` is the *correct* escape for a tilde, and under OT1 it renders
as a raised diacritic: "˜2 min" rather than "~2 min". It also extracts from the
PDF as an unmappable character, so ATS software reading the text loses the
qualifier on the number entirely. R53 could not have fixed this by escaping,
because the escape is the thing that renders wrong.

### T1 was tried, measured, and rejected

Loading `\usepackage[T1]{fontenc}` fixes all three glyphs — and it was
implemented, including injection into existing masters, before being backed
out. Compiling the real preamble both ways and extracting the text:

    without T1   Sep. 2021 – June 2025      tilde renders wrong
    with T1      Sep. 2021 \x15 June 2025   tilde renders correctly

T1 breaks the ToUnicode mapping for the en-dash, so **every date range extracts
as a control character**. For a document whose whole purpose is being read as
text by ATS software, trading every date for three glyphs is the wrong way
round. The `\pdfgentounicode` machinery already in the template does not cover
it.

`$\sim$` fixes the tilde with no such cost: it renders correctly, extracts as
U+223C, and is what a resume means by a tilde anyway. It is also what the
author's own master already writes by hand.

The template now carries a comment explaining the omission, and a test fails if
someone adds `fontenc` without revisiting the measurement — an absent line is
otherwise indistinguishable from an oversight.

### A round trip that broke on the way

`_clean_latex` un-escaped `\textasciitilde{}` and knew nothing of `$\sim$`, so
rendering an imported resume and parsing it back turned "~500 samples" into
"500 samples". Caught by an existing round-trip test, which is the test earning
its keep.

### The doc's claims are now executable

Three times now a decision entry has described a state the code never reached:
roadmap item 13 on discovery seniority, Q2 on PDF/DOCX import, and R55's
state-code removal. The shape is consistent — **a claim that something is
removed, guarded or wired, sitting on top of an outcome that looked right for
another reason.**

Prose cannot check itself, so `tests/test_doc_claims_hold.py` asserts the
load-bearing ones: no US state code resolves to a country, the guard compares
like with like, the dead profile fields are gone, the real scrape path cannot
reach the mock, no literal "new grad" reaches a query, both escape tables
agree. Plus structural checks on the log — that no entry points at a resolution
that was never written, and no number is reused.

Running it immediately found a stale docstring inside the very function R61
fixed, still promising to "fall back to mock if scraping fails".

### The mid-level run

Everything this week changed assumptions about users who are not new graduates,
and nothing had exercised that path end to end. A profile with six years, based
in Boston, on an H1B, unwilling to relocate:

    derived levels   mid, senior          (from years, not picked)
    search term      "mid"                (was the literal "new grad")
    tolerated floor  9
    github newgrad   skipped
    excluded         Canada 5, New York 22, California 17, Illinois 2

**"Illinois" appears as a US state**, which before today read as Israel. The
run produced *Senior Software Engineer* resumes — a path that a week ago hunted
new-grad postings.

It also found one more three-state mistake. `location_score == 0` covers both
"in a state you did not name" and "state unknown", so three postings listed
only as "United States" were excluded as somewhere the user would have to move
to. Unknown is not elsewhere — the same distinction R64 drew for years and R55
for countries, and the third time this session it has come up.

### Verified

767 tests, three baselines clean. Both renderers now produce identical output
for every special character; a compiled PDF renders `<5ms`, `>1s`, `∼2 min` and
`94.2%` correctly while keeping the en-dash extractable.

---

## R70. The same transposition, in the renderer nobody parses back

**Decision:** (2026-08-26) Both renderers write experience as
`{title}{dates}{company}{location}`, and a test compares them rather than
checking each against itself.

**The bug is already in this document.** R38's round trip found that the import
renderer transposed company and title, filing every job title as the employer,
and fixed it there — the note is above, under "The renderer transposed
experience fields". `generation_agent._generate_latex_file` wrote
`{company}{dates}{title}{location}` and was never looked at.

### Why four months of reading did not find it

The PDF is *fine*. Bold company over italic title is a legitimate resume style;
nothing about the rendered page looks wrong, which is why every visual check
passed. What is wrong is only visible by reading the file back:

    master (hand-written):
      exp_sorenson_communications  company='Sorenson Communications'
      exp_101gen_ai                company='101gen.ai'

    generated by the tool, parsed by the tool:
      exp_software_engineer_intern company='Software Engineer Intern'
      exp_software_engineer_intern company='Software Engineer Intern'
      distinct ids: 2 of 3

Component ids derive from the employer, so two internships sharing a job title
became one component. **A user who saves a tailored resume as their new master
loses an experience**, silently, and a resume with two internships is the
common case rather than the corner one.

### The fifth instance, and the shape it has

`rarely_include` (R31), `scraped_successfully` (R61), the selection breakdown
(R57), the escape table (R69), this. R69 named the mechanism for the pair it
found: the author's resume is a `.tex`, so the import renderer is a path he
never walks. This is the same pair of modules and the same asymmetry — he reads
generated resumes as PDFs and never re-parses one.

So the rule is not "check both renderers". It is: **where two paths exist and
only one is walked, no amount of care on the walked path finds anything.** The
fix has to be a test that walks both and compares them, because either renderer
checked against itself looks correct — `test_tex_renderer.py` asserted the
right argument order the whole time, for its own module.

`tests/test_renderers_agree.py` renders the same two-internship schema through
both, parses both back, and asserts the fields land in the same places. It also
holds a list of every module that encodes the argument order — two writers and
the parser they both answer to — and fails if a third appears.

### Verified

Round-tripping a generated resume now recovers both employers and both ids.
The rendered page changes: bold is the job title, matching the master's own
layout and Jake's template, where before the tool's output disagreed with the
file it was tailoring. 6 new tests, 773 pass, baselines clean.

---

## R71. An adjective is not a smaller claim than an adverb

**Decision:** (2026-08-26) R58's list gains the size adjectives — `low-latency`,
`high-performance`, `high-speed`, `high-throughput`, `high precision` — and
nothing else. The words that were proposed and rejected are recorded, because
the rejection is the more useful half.

**The live case.** From the 2026-08-26 run, the first made by a profile that
was not the author's. Master:

    Benchmarked Weaviate against AWS Elasticsearch and Pinecone ... achieving
    p99 query latency of $<$5ms and 5K+ QPS at million-scale

Shipped:

    ... architecting a robust storage system utilizing Weaviate and MongoDB to
    facilitate high-performance retrieval ...

And, worse, on the same resume:

    ... trained XGBoost classifiers under stratified 5-fold cross-validation to
    predict antibiotic resistance with high precision and generalizability.

Seven figures in the master; none in the output. `validate_resume_output`
returned no error for either, because R58's list is nineteen adverbs and the
model reached for adjectives.

### Measured, not guessed

Eleven words were proposed. Counting each across **61 generated resumes**, split
by whether the component had actually dropped a figure:

    low-latency        7 error-shaped   5 padding    ADD
    high-performance   2                0            ADD
    high precision     1                0            ADD
    high-speed         1                0            ADD
    strongly           0               13            padding only
    optimal            0                3            padding only
    comprehensive      0                1            padding only
    highly, strong, extensive, superior — never occur at all

Seven of the eleven would have bought zero signal. Two more — `strongly` and
`efficient` — **appear in the author's own master bullets**, so R58's premise
test rejects them outright: a word the source uses carries no information when
the output uses it.

`robust`, `scalable`, `seamless` and `efficient` stay off by rule rather than by
rate. They assert a quality, not a size, and
`test_the_word_list_is_only_intensifiers` exists to hold that boundary. The
`robust` in the shipped bullet above is still uncaught, and that is correct.

A blanket `high-*` rule was tested and is a trap: `high-concurrency` (29
occurrences), `high-traffic` (12) and `near real` (15) are all padding and all
in the master.

### The calibration set could not see the failure

`TestAgainstEveryResumeInTheRepo` globbed `outputs/*/*.tex` and not
`outputs/*/needs_review/*.tex`. The resume carrying both errors was in
`needs_review` — held back for an unrelated length problem — so the check
calibrated against the corpus that excluded it. **A check calibrated only on
output that passed cannot measure what fails.** The glob now includes it.

### Verified

Both shipped bullets are now errors naming the figures they lost, and route
into repair; the tailoring and repair prompts carry the adjective example
beside R58's original. Rate across the widened corpus: 21 hits over 61 resumes
against a threshold of 30, and 13 of the 21 are error-shaped. 6 new tests, 779
pass, baselines clean.

---

## R72. The template stored instructions where answers go

**Decision:** (2026-08-26) A profile template states nothing it has not been
told. Blank is how a file says unknown, and a default is not a statement.

**Severity: the worst-consequence defect found in this five-day stretch.**
Worse than the glyphs (R69), worse than the field transposition (R70). Those
produce a resume that looks slightly wrong. This one told a stranger they were
eligible for work they are legally barred from holding.

### The line that did it

    "us_citizen": true

In `user_profiles/template.json`, asserted about every person who ever builds a
profile. `_is_us_person` in `tools/jobs/job_filter.py` reads it — citizen or
permanent resident, the ITAR sense — and postings restricted to US persons are
gated on the answer. So a new user on an H1B who did not walk the About-you
screen had a profile claiming US citizenship, and JobScout showed them
ITAR-restricted roles and wrote tailored resumes for them.

Under a paid service that is the failure to be most afraid of. The user spends
their time, submits, and is rejected on a ground the product could have known
and in fact claimed to know. Nothing in the output looks wrong.

### The rest of the block

Every field was guidance wearing a value's clothes:

    name            "Your Name"
    email           "your.email@example.com"
    location        "City, State"
    visa_status     "US Citizen | Green Card | F1 OPT | H1B"      <- a menu
    graduation_date "Month YYYY"
    target_roles    [..., "Add your target roles here"]           <- a query

`location` is the one that shows what the shape costs. The About-you form
seeds itself from the stored profile, which is correct — saving a blank form
over stored answers is a silent revert this wizard has done before. So the box
arrived pre-filled with `City, State` and Continue was **enabled**: agreeing
with the screen recorded a location that does not exist, into the exact field
R55 and R69 score against.

`visa_status` held the option list itself, which matches no option, so the
Streamlit select fell back to index 0 — "US Citizen" — silently. Two separate
paths to the same wrong claim.

### The invariant, third costume

R69 named it for rendering: unknown is never displayed as a value. R71's
sibling finding named it for the frontend. This is the data layer:

- a **placeholder** is not an answer
- a **default** is not a statement
- `years_experience: 0` is a claim of new-graduate status; `null` is the truth

Anything downstream that reads a profile cannot tell an instruction from an
answer, because at the type level there is nothing to tell.

### Why it survived

The template is a frozen artifact from the single-user era. The author's own
profile predates the wizard and was never rebuilt from it, so nobody had read
what a fresh profile actually contains since the tool became general. R68 fixed
the wizard's *offered* exclusions relative to where the user sits and did not
touch the file the wizard starts from — the same one-of-two-paths shape as R69
and R70, with the untaken path being "arrive as a new user".

Found by building a stranger — six years, Boston, Staff Engineer, a PDF from a
template this repo has never produced — and reading the profile that came out.
It also excluded `senior` and `staff`, the two words in her own job title.

### The fix, and what it is not

Fields blanked, guidance moved to `_comment`, `us_citizen` and
`permanent_resident` default false, `years_experience` null, one person's
states removed. False for citizenship is the safe direction on the same
reasoning the schema already gives for `holds_security_clearance`: it hides
postings rather than surfacing ones the reader cannot hold.

Blanking is not sufficient on its own. The React About-you screen now **gates
Continue on work authorisation** rather than defaulting to the first option, so
an unanswered question stays unanswered rather than being answered by omission.

### Verified

`tests/test_template_presumes_nothing.py` — eleven tests: no level word in the
exclusions, no instruction text in any value, the two fields a resume cannot
state are blank, nothing asserted about citizenship, and the guidance still
exists in `_comment`. Priya's rebuilt profile reads Boston / H1B /
`us_citizen: false` / `years_experience: null`, with name, email, school and
degree surviving the nested merge. 813 tests, three baselines clean.

**Open:** the work-authorisation select's click-through is unverified in a
browser. The bug found in it — `value={x || undefined}` making a Radix Select
uncontrolled, so the display stops tracking state — is the class that passes
contract tests and fails in front of a person, and this is the one control
whose field gates ITAR postings. `tests/test_web_controls.py` holds the source
shape; the widget itself still wants a human click.

---

## R73. In memory a bullet is plain text; LaTeX exists only in a file

**Decision:** (2026-08-26) Every boundary honours one invariant. The parser
converts LaTeX to plain text on the way out, the renderer escapes on the way
in, and nothing asks which of the two a string happens to be. `already_latex`
is deleted.

**Severity: this made the free tier produce files that will not compile.**
Not wrong output — no output. `page_count: 0` on a machine with LaTeX
installed, and the run reported that it had written a resume.

### Three reasonable decisions, one broken product

    tex_renderer.escape      escapes on the way into a file
    parse_latex_resume       unescapes on the way out
    _escape_latex(..., True) trusts what it is handed

Each is defensible alone. Together they guarantee that any bullet making the
round trip comes out broken. The author's master holds five `\%`; the parser
returns all five bare; the no-model rung writes them straight back. **A bare
`%` comments out the rest of the line including the closing brace.**

### Why a flag could never have been right

The premise behind `already_latex=True` was "the user's own master bullets are
valid LaTeX". Measured, that premise was *half* true, which is worse than
false. `_clean_latex` unescaped `\%`, `\&`, `\_`, `\#` and `\$` while leaving
math spans and `\texttt{}` standing:

    in the file    ... 94.2\% accuracy ($\pm$0.2\%) ... $\sim 503$ms ...
    in memory      ... 94.2%  accuracy (  ±  0.2% ) ... $\sim 503$ms ...
                       ^ plain text                     ^ still LaTeX

One boolean cannot describe a string that is both. Escaping it printed the
markup; not escaping it broke the file. `already_latex` is the sentinel
pattern in its purest form — one variable standing for two different truths
depending on which path built the string.

### The fix is the invariant

`_clean_latex` now converts math spans too, via `MATH_TO_TEXT`: `$\sim 503$`
becomes `~503`, `$\pm$` becomes `±`, `0.17$\rightarrow$1.00` becomes
`0.17→1.00`, `$CC \leftrightarrow PSTN$` becomes `CC ↔ PSTN`. The escape table
gains the return journey for each. Measured across every master on disk:
**nothing with a backslash or a `$` survives into memory.**

R69's `~` → `$\sim$` mapping is what makes this closed rather than lossy — the
tilde is a real character on a resume, meaning "about", and it has somewhere
to go in both directions.

### Two tables became one, on the third offence

Adding the math characters to `tex_renderer` and not to the generation agent
desynchronised the escape tables **within the hour**, and
`test_both_tables_cover_the_same_characters` caught it — the test R69 wrote
after the same pair produced the same class of bug twice. Rather than
synchronise by hand a third time, `generation_agent._escape_latex_impl` now
calls `tex_renderer.escape`. Two tables kept equal by a test is better than
two tables; one table is better still, which is where the scorers ended up
for the same reason.

### Verified

Generated a keyless resume for both masters and compiled it. Priya
Raghunathan: no bare `%`, **98,888-byte PDF** where the same path produced
`page_count: 0` an hour earlier. Extracted text carries every figure —
`340ms to 48ms`, `12 shards`, `4,200 duplicate charges`, `18K+ merchants`,
`2.5K requests per second`, `6 hours to 40 minutes`, `31%`. The author's:
125,417 bytes, exit 0.

`tests/test_latex_round_trip.py` is a property test over every master on disk
rather than assertions about particular characters — parse, render, parse
again, and require the bullets identical, the rendered file free of unescaped
specials, and a second render byte-identical to the first. That closes the
family; the five percents were never the point.

**Why it was invisible.** Gemini rewrites the author's bullets, and rewritten
prose routes through the escaper. The no-model rung is the only path that
writes parser output straight back to the renderer — the free tier, on the
machine of somebody who has not paid.

---

## R74. Three defects that were the author's own file, used as a ruler

**Decision:** (2026-08-26) The tailored resume is ordered by date, budgeted by
page rather than by half a page, and keeps the skill categories the source
document was written in. Priya Raghunathan's free-tier resume goes from three
bullets in relevance order under a scrambled skills line to eight bullets
newest-first under four real categories, one page, compiled.

This is the end of the stranger pass on the *output* — R66 fixed what she
could enter, the score fix (`test_score_shape_independence`) fixed what she
matched, R73 made the file compile, and this is the page that comes out.

### 1. Relevance is not an order

Selection ranks components by fit to the posting and that ranking reached the
page untouched, so her resume opened with the job she left in 2020 and buried
the one she currently holds. The author's own resume had it too — 101gen.ai
(2024) above Sorenson (2025) — and it is invisible on a page you already know
the contents of.

`tex_renderer.reverse_chronological` sorts on the **start** date, which is the
convention and the only thing that separates a job still running from one that
began later. It lives in `tex_renderer` because both renderers pass through
it; anywhere else recreates the fork that produced R69 and R70.

**All of them or none of them.** One unreadable date and nothing moves.
Sorting the rest around an unknown files it under "oldest", which is this
codebase's oldest mistake wearing yet another hat.

### 2. A page is a page, whatever sections are on it

`exp_budget_table` and `proj_budget_table` were measured in Q3 against resumes
that have both sections — three experiences and three projects, twelve bullets
with two spare — so each table describes **half a page**. Priya has no
projects. The projects half was spent on nothing: three jobs shared six
bullets and the bottom third of the page stayed blank.

Eighth instance of absence read as a value, and the second one to land on this
exact resume — the scoring cap divided her three jobs by five for the same
reason. When one section is empty the other now gets the page, bounded by the
per-component maximum and by how many bullets the master actually holds.

### 3. `VERBATIM_BULLET_SCALE = 0.5` was a measurement of one man's prose

The no-model rung took `count // 2` bullets because a master bullet "occupies
roughly twice the space" of a rewritten one. Measured, on the files in the
repo:

| | bullet length | rendered |
|---|---|---|
| Gemini output, all 13 bullets | 195-217 chars | 2 lines |
| author's master | 220-440 chars | 3 lines |
| Priya's master | 59-192 chars | 1 line |

So the constant was wrong even for the author (0.67, not 0.5) and inverted for
Priya, whose bullets are already the size Gemini writes. Halving spent half her
page on nothing and printed **one bullet per job** — not a thin resume, a
resume that looks like the person had nothing to say. Her entire master is
eight bullets and she was sent three.

The replacement is the quantity that was always meant. `line_2` is the zone
the prompt and the validator both aim at, so **a budget of N bullets is a
claim on 2N lines**; a rung that cannot shorten a bullet keeps the claim and
changes the count. Two refinements, both found by reading real output:

- **Zones are measured in characters, not by name.** An `orphan_2` bullet
  renders two lines, one of them half empty. Treating every unnamed zone as
  the worst case cost the Toast job a bullet it had room for.
- **Skipped, not stopped.** 101gen's bullets measure 3, 4, 2, 1, 2 lines
  against a budget of 6. Stopping at the four-line one shipped a single
  bullet; three fit exactly. Order is preserved among those kept.

`_bullets_within_lines` is called by both the tailor and the budget, because a
count computed in one place and a slice taken in another is the shape that has
produced six bugs here. `_fit_budgets_to_lines` now restates the contract for
validation *after* tailoring rather than scaling it beforehand, which also
fixes a Gemini failure falling back to verbatim with unscaled budgets.

### 4. The skills section was destroyed before anything could use it

The no-model import floor read the section as `{"Skills": ", ".join(lines)}`.
Four labelled rows became one value, and generation — correctly, for a
category — reordered it by relevance and cut it to a line:

    Skills: Python, Go, TypeScript, mentoring, Kotlin, Spark,
            contract testing, Languages: Java, SQL

`Languages: Java` offered as a skill, three quarters of what she can do gone.
Nothing downstream was wrong: the schema is `{"Category": "comma, separated"}`
and a `Label: values` line already **is** one. The structure was in the source
and the join threw it away. An unlabelled line joins the category above it or
lands under the section's own heading — nothing is invented, and a short label
is required so a stray bullet with a colon in it does not become a category.

### Verified

Priya's free-tier resume, compiled: one page, 98KB, four skill categories,
three jobs newest-first, all eight of her bullets. The author's, same rung,
same three postings: 6 bullets to 11, still one page, order corrected. 909
tests, three baselines clean.

**Left standing, deliberately.** Her page is roughly half full — her master has
eight bullets and the tool will not invent a ninth. That is Q3's headroom
question, unchanged. And her PDF's own text layer says `A WS` for AWS, a
kerning artifact of the file: repairing spaces inside words guesses at content,
which is the trade `test_stranger_import` already refused for the glued email.

---

## R75. The sweep, and the wall that was rebuilt one field over

**Decision:** (2026-08-26) A focused pass over the recurring bug class rather
than over a diff. Seven candidates went in; **two were already dead**, one was
mis-stated, and the pass turned up **two the list did not have** — including a
regression of R72 that shipped in the fix for R72.

Recorded because the yield of the sweep was in the checking, not the list. Two
candidates had been fixed by earlier work and would have been "fixed" a second
time by anyone who trusted the note; the highest-severity finding was not on
the list at all and was reached by following a field rather than a hunch.

### Already dead, and worth saying so

* `already_latex` — deleted by R73. It survives only in comments explaining
  its absence and in `test_nothing_asks_whether_text_is_already_latex`, which
  fails if it returns.
* `--popover`'s undefined tokens — defined in both themes, with
  `test_theme_is_complete` holding the whole token set.

Two of seven. This is the doc going stale in the direction that costs the most
— a candidate list is a claim about the present, and this one was three
commits old.

### Mis-stated: the header location

Filed as "collected on import, never rendered". It is neither.
`CONTACT_PATTERNS` has no location pattern, so nothing collects it; the line
it sits on is the one that glues `Boston, MA` onto the email
(`test_stranger_import` documents why that is not repaired). A resume for
someone whose location decides half their matches prints no location at all.
That is a **missing feature**, not a dropped field, and it needs the header
and the parser to learn a field together.

### 1. The wall R72 tore down, rebuilt one field over — both UIs

R72's finding: the Save button on the preferences screen was gated on the
seniority override, which is empty for every profile a new user builds, so the
button was dead for everyone but the author. The fix moved the gate to the
levels *in force*.

`derived_levels(None)` is `[]`. `/api/levels` returns `derived: []` for an
unanswered profile **on purpose**, and its docstring tells the caller to
"render that as a question rather than as a level". Both callers fed it
straight into the gate. So anyone who declines to state their years — a field
with a placeholder, no required marker, and a legitimate unknown state — met
the same dead button, with nothing on screen saying why.

`test_preferences_gate` could not see it: `test_every_plausible_number_of_years
_derives_something` walks `range(0, 41)` and never `None`. **A test that walks
every answer and never the absence of one.** Ninth instance of the invariant,
and the first to be reintroduced by the fix for a previous instance.

Both gates are now on target roles alone. "Any level" is a real state — the
caption says so, `_tolerated_years` reads it as the widest tolerance rather
than as zero, and the run works.

### 2. `int(years or 0)` — the twin path, with a note attached

The Streamlit field did `value=int(current.get("years_experience") or 0)`, and
`st.number_input` has no unanswered state to return, so **saving the screen
wrote the zero back**. A six-year engineer who never touched the field was
filtered as a new grad from then on. Not a display bug: a write.

The React field next door has been correct since it was written, and its
comment names this exact line as the thing it is not doing. Fixed on the path
being built, left standing on the path being replaced — the two-path bug with
a signed confession beside it.

`st.number_input(value=None)` returns `None` untouched and the number after
(verified with `AppTest`), which is why `requirements.txt` now floors
Streamlit at 1.31 rather than 1.30.

### 3. The skills section was printed and never offered

The React confirmation screen showed skills as the number `4` and nothing
else, on a screen headed *correct anything that is wrong*. The section reaches
the employer verbatim and was the only one nobody could touch — while the
Streamlit screen has had an editable skills field the whole time.

This is what makes `A WS` matter. The kerning artifact in Priya's own PDF is
not repairable in code (repairing spaces inside words guesses at content, the
trade already refused for the glued email), and that is survivable **only**
because R33 puts every field in front of its owner. Skills were the exception,
so the one defect that needed the mitigation was the one that did not have it.

### 4. `contact.portfolio`, and `from_parsed` dropping `url`

`portfolio` appeared **once in the entire repository**: as a labelled input on
the confirmation screen. Nothing extracted it, nothing stored it, `_header`
does not print it. Removed rather than rendered — printing it honestly needs a
parser counterpart, and `latex_parser` recovers GitHub and LinkedIn by
matching the domain, which an arbitrary portfolio URL has no way to do. It
would print once and vanish on the next round trip.

`from_parsed` omitted `url`, so every project link died on a re-render — and
because `from_parsed` is what the round-trip test renders through, **the test
was blind to the loss it existed to catch**. Both sides agreed on nothing
being there. A round trip that compares only what the bridge carries certifies
the bridge.

### The test that closes the class

`tests/test_form_and_renderer_agree.py` asserts both directions:

* every field the renderer **prints** is offered by the form
* every field the form **offers** is printed by the renderer

The read-set is *measured*, not read: each field is rendered with a sentinel
and the output searched for it, so it describes what `tex_renderer` prints
rather than what its source appears to say. Grepping a renderer for
`.get('url')` passes the moment somebody renames the accessor — testing a path
against itself, again. The form side is extracted from the `.tsx` and **raises
rather than returning an empty set**, so it cannot pass by comparing nothing
to nothing.

Verified to bite in both directions and on the skills case, by reintroducing
each defect and watching the right test fail.

### Verified in a browser, not only in tests

The class this pass is about includes the one that passes contract tests and
fails in front of a person. So: years cleared on the preferences screen →
caption reads "Answer the years above and the levels follow from it", **Save
enabled**, click, and `years_experience` on disk is `null` — not `0` — with
`derive_levels` reading it back as no opinion. Import screen: contact shows
five fields and no Portfolio; Skills renders four editable groups; editing a
value updates state and blanking a label drops the header count 4 → 3, which
is `skillsFromRows()` driving what gets saved.

925 tests, three baselines clean.

**Still open.** The header prints no location. Priya's page remains about half
full (Q3). And `test_every_plausible_number_of_years_derives_something` is
worth reading as a pattern rather than a fixed test: **any test that walks a
range is a test that has not walked the absence.**

---

## R76. The re-run, and the verdict addressed to somebody who was not there

**Decision:** (2026-08-26) A rung that may not rewrite a bullet is not judged
as one that may. Priya Raghunathan's free-tier run goes from **0 valid, 5
needs review** to **5 valid**, on the same five files.

### What the re-run was for, and what it caught

R74's verification ran `_verbatim_tailor` and `_generate_latex_file` by hand
and checked the PDF. That was true as far as it went — one page, eight
bullets, correct order — and it skipped `validate_resume_output` entirely. The
whole pipeline, run end to end for the first time since, filed every one of
those five PDFs under needs_review.

**A spot-check that walks part of a path is a spot-check that certifies part
of a path.** The R74 note says the resume was verified; what was verified was
the file, not the verdict on it.

### 1. The orphan zone was addressed to a model that was not there

`_validate_bullet_length` errors on a bullet in an orphan zone and names two
target ranges — "either compress to ≤110 or expand to 180-213". Its own
docstring says why: *"the repair loop is the recovery path... feedback names
exact target ranges so the LLM can correct on retry."*

On the no-model rung there is no LLM and no retry. The text is the user's own,
rewriting it is forbidden by the fabrication guard, and `fit_bullet` has
already tried to compress it and failed. Priya's Toast bullet is 126
characters. The error's only remaining effect was to condemn a resume she
would have sent as it was.

So on that rung it is a **warning**: still reported, with advice addressed to
the only rewriter present ("shortening it by hand would tighten the line"), no
longer a verdict. **Overflow stays an error on every rung** — a bullet past the
maximum spills onto a second page, which is a consequence rather than an
opinion about typography.

This is the rule the codebase keeps rediscovering, in a new place: a check
belongs to a domain, and this one had drifted outside its own. The zone rule
governs *text the tool wrote*.

### 2. The rung was read from the settings, not from what happened

`self.llm_backend` is the rung that was **configured**. Both model rungs fall
back to `_verbatim_tailor` when the model does not answer, so a run set to
Ollama can produce a verbatim resume and then be validated against a budget
nothing had spent — every component reported short.

`_verbatim_tailor` now stamps `_verbatim: True` on every payload it produces,
and both the budget re-fit and the validator read that. The tailor is the only
thing that knows what it did; asking the settings was asking the wrong object.
`_verbatim_reason` stays separate and still means "this rung was not the one
you asked for" (R47), so a free-tier run does not read as a broken paid one.

### Verified, end to end this time

`python -m agents.orchestrator --profile priya_raghunathan --input <cached>`
on the no-model rung: **5 valid, 0 needs review**, five PDFs, one page each,
scores 70.0-73.8 against a threshold of 40. The same command before this
change: 0 valid, 5 needs review. 935 tests, three baselines clean.

### Found on the way, not fixed here

**Ollama has no repair loop.** `_gemini_tailor` validates and makes one narrow
repair attempt; `_chat_tailor` returns whatever came back. Measured on the
same five jobs, llama3.1:8b writes bullets at 122-126 characters — the orphan
zone, every time — and returns the wrong bullet count for at least one
component. Those are real defects by a model that could be told to try again,
and nothing tells it. **Twin-path shape, and it lands on the rung that is
supposed to be the free tier's answer.**

**There is no way to choose a rung.** `LLM_BACKEND = "auto"`,
`OLLAMA_BASE_URL`, `OLLAMA_API_URL` and `OLLAMA_MODEL` are all hardcoded
literals in `config.py` with no environment override, so testing the no-model
floor on a machine with Ollama installed requires a script that reaches in and
sets the module attribute. Confirmed rather than assumed: `detect()` prefers
Gemini whenever a key is present, and clearing the key here selected Ollama,
not `none`.

Both belong to the Ollama work rather than to this fix, and both are now
measured rather than suspected.

---

## R77. A third resume, and the four things one run of it found

**Decision:** (2026-08-26) The pattern reader recognises a heading by its
words, ends a section at a heading it does not know, keeps two degrees as two
degrees, and does not read the link appendix as resume content.

### Why a third resume at all

Yash's is a `.tex` he wrote. Priya's is a PDF, and the whole point of her — but
**she was invented to test the importer, so she can only ever contain problems
somebody thought of.** The third is a real resume from outside the project.
One run of `heuristic_schema` over it found four defects, none of which either
existing fixture could express.

The method generalises past "build against Priya, not against yourself": a
fixture you wrote is a fixture that agrees with you.

### 1. `Research/Projects` was not a heading

Section matching was `lowered.startswith(word)`. That line begins with
"research", so it matched nothing, and **the projects section did not exist**
— thirty-six lines of projects and the publications below them were filed
under Experience, the section above, and offered on the confirmation screen as
work history.

Headings now match on words: every word in a short line must be a section term
or filler ("technical", "professional", "research", "and"), and at least one
must be a term. Both halves were learned by breaking the other resume:

* matching a term *anywhere* made `iSteer Technologies Bangalore, India` a
  skills heading — an employer became a section break and took the experience
  section with it
* matching *whole words* made `Skills` stop matching the term `skill`, and
  Priya's entire skills section vanished

So: prefix per word, whole line accounted for.

### 2. An unknown heading did not end the section above it

`Publications` is not a section this importer wants, and it therefore was not
a heading, so two conference papers became project bullets. `OTHER_HEADINGS`
is a closed list of sections that **end** the current one and claim nothing.

Closed, not heuristic, and the reason is measured: on that resume `AI/ML Intern
Jan 2025 - April 2025` is 34 characters and `iSteer Technologies Bangalore,
India` is 36. Any rule of the form "a short line is a heading" deletes the
experience section. `"language"` was dropped from the list on the same
grounds — it is a skills category label far more often than it is a section.

### 3. Two degrees became one wrong record

`_heuristic_education` built exactly one entry, by construction. A masters and
a bachelors merged into:

    school: "University of Massachusetts Masters of Science in Computer
             Science PES University Bangalore, India"
    degree: "Bachelor of Technology..."   dates: "Aug. 2025 - May 2027"

The bachelors degree under the masters' dates. **Wrong rather than missing**,
which is the worse of the two — R64's rule applied to a whole record. A blank
field is visibly blank on the confirmation screen; that is a plausible
sentence nobody would look at twice.

Entries now flush on conflict: a second date range, a second degree, or a
school line arriving after the current entry already has both.

### 4. `\bmaster\b` does not match "Masters"

Only "Bachelor of ..." was ever recognised as a degree, which is why the merge
scrambled the way it did rather than merely splitting badly — the masters line
was not a degree, fell through to the school name, and took the structure with
it. Every spelled-out qualification now takes an optional `s`.

Bare `MA` and `BA` stay out of the pattern, because "Boston, MA" is a state,
and `test_a_city_and_state_is_not_read_as_a_masters` holds that — adding
plurals is exactly the edit that would put them back.

### 5. An affordance for one path, reaching the path that could not use it

`extract_text` appends the PDF's link targets under `LINKS FOUND IN THIS
DOCUMENT:` so the **model** can recover a URL the visible text does not carry;
the extraction prompt says so in as many words. The pattern reader has no such
instruction. After R75 taught it that `Label: values` is a skill category, the
appendix arrived on the page as a category named `https` holding three URLs,
with the marker glued to the end of the real skills.

Twin-path again, in a new direction: not a fix applied to one of two paths,
but a *feature* built for one and never considered against the other.

### Verified

Both PDFs on disk, before and after. The third: sections went from
`{education: 4, experiences: 36}` — everything after Experience swallowed — to
`{education: 4, experiences: 17, projects: 13, skills: 4}`, two education
entries with the right degree against the right dates, four real skill
categories and no `https`. Priya: unchanged, one education entry, the same four
categories. 954 tests, three baselines. Each new test was run against the old
code first: 13 of 19 fail there.

### Left standing, measured

* **Non-US locations.** `_CITY_STATE` requires `City, ST`, so "Bristol, United
  Kingdom" is not a location and stays glued to the school name. Fixing it
  needs a country vocabulary, not a looser regex — the comment on that pattern
  already records what a looser class did.
* **A school name leaking into the location.** `Northeastern University Boston,
  MA` with no separator gives up its name to the location field; with " - " it
  does not, which is why Priya never showed it. Asserted as observed.
* **Kerning splits in labels and project names** — `F rameworks`, `Developer
  T ools`, `T railSpecies`. The extraction prompt already tells the *model* to
  repair these and names `"W ebApp"` as an example. The floor cannot, so this
  is another defect that exists only for the tier without a key.
* **Mojibake.** En-dashes, `R²` and `×10` arrive as `�` from this
  particular PDF, past everything `_tidy` knows about.
* **A standalone `Research` heading** would not be recognised, because
  "research" had to become filler for `Research/Projects` to work.

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

**The no-spend constraint is replaced by a ceiling (R60, 2026-08-25); the
decision about Claude specifically still stands.**

**The new rule: $10/month, which is the amount that may be lost with zero
users.** Revisited when revenue exists, and not before.

It is written as a number on purpose. The first draft of this amendment said
spend was allowed "where revenue justifies it", which is not a constraint at
all — there is no revenue, so the condition can never be tested and the rule
becomes "spend, and argue about it later". A ceiling does the work a
constraint is for during the phase where it matters most, which is this one.

What $10 buys at the measured rates: a domain, a small paid host, and roughly
600 Flash-generated resumes a month (~4,000 on Flash-Lite) — comfortably more
than a board plus a proving run of hosted generation needs. Phase one is
expected to come in under it on free tiers regardless.

This changes the *reason* this entry gives rather than its conclusion. Gemini
Flash at roughly 1.5 cents per resume is the cheap rung, and nothing about
paying for it argues for adding a second provider. The speculative-generality
point below is the durable half.

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
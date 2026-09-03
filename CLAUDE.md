# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# JobScout — what this is

**The problem.** People hand-tailor their resume against job descriptions with
a chatbot, one posting at a time, over and over. JobScout does it for them:
they give it a resume and a profile, it discovers matching jobs and writes a
tailored resume per posting.

**It works.** This tool ran its author's job search — discovery, matching,
tailoring — and he got hired. That is the proof, not a hypothesis.

**Who it is for:** tech job seekers, **any level, any location**. It began as a
new-grad tool for one person; that constraint is gone and the code should not
assume it.

**Not other fields, yet.** Three specific blockers, not squeamishness:
Greenhouse/Ashby/Lever skew heavily to tech; the LaTeX template is a one-page
tech resume with a projects section; and Q17's vocabulary-over-role-type
problem gets worse when "analyst" means five different jobs. Expanding means
solving those first.

**Where it is going:** a hosted, paid web app. The local CLI stays for
developers. Spend ceiling is **$10/month** until there is revenue (OOS5).

**Not building:** a public job board. It was tried and dropped on 2026-08-26 —
it assumed discovery was shared across users, and once a profile drives *what
gets discovered* rather than only what gets ranked, there is no shared half
(R66).

---

## Working here

- `known_questions.md` is the decision log and the planning substrate. Every
  question and every resolution lives there, numbered. **Read the relevant
  entry before changing what it describes** — and check it against the code,
  because entries have gone stale while the code moved (Q2 claimed unbuilt work
  that had shipped two days earlier).
- Decisions are recorded as `R<n>`, open questions as `Q<n>`, one commit each.
  Commit subjects name the finding, not the file: *"fix: the acceptance run
  imported through a rung it was not asked for (R83)"*.
- `plan.md` is the current tracker — the week-to-a-URL plan.
  `known_questions.md` is why; `plan.md` is what next.
- `app.py` is a view layer and imports only `agents.orchestrator` and
  `scripts.init_profile`. `tests/test_ui_contract.py` fails the build otherwise,
  and it enforces the same rule on `api/main.py`.

## Working with me

Explain decisions as you make them, not after I ask.
For any non-trivial choice, state: what you chose, what
you rejected, and what breaks if the choice is wrong.

When a decision has a blast radius beyond the file you
are editing — a schema, a default, a shared invariant,
anything a user sees — say who or what it affects before
you write the code.

If I accept something without questioning it and the
reasoning is load-bearing, tell me anyway. Silence from
me is not understanding.

## Commands

Both of these must pass before a commit:

```bash
python -m unittest discover -s tests -q       # the suite (~1000 tests)
python scripts/baseline.py verify --all       # the frozen measurement baselines
```

Stdlib `unittest`, not pytest — deliberately, so `requirements.txt` stays the
install list for people running the app rather than a dev manifest. The suite
needs no LaTeX: `pdf_builder`'s tests stub `pdflatex`, so the timeout,
compile-error and missing-engine paths are all reachable without TeX.

```bash
python -m unittest tests.test_tex_renderer -q                          # one module
python -m unittest tests.test_tex_renderer.TestClass.test_method       # one test
```

Running the pipeline:

```bash
python -m agents.orchestrator --profile priya_raghunathan --max-jobs 5 --mock
python -m agents.orchestrator --profile <name> --max-jobs 5            # real run
```

`--mock` is zero API calls; `--mock-embeddings` and `--mock-generation` mock one
half each. `--input <enriched_jobs.json>` replays analysis and generation
without re-scraping — that is how every scoring change here gets measured.
`--backend gemini|openai|ollama|none` pins the rung; `--no-cache` makes every
model call fresh, because a measurement that counts cache hits as model answers
is fiction. `--no-pdf` skips compilation, `--checkpoint` pauses between stages.

The two UIs (see below — they are views of one facade):

```bash
streamlit run app.py                                      # Streamlit
python -m uvicorn api.main:app --reload --port 8000       # FastAPI, plus...
npm install --prefix web && npm run dev --prefix web      # ...Vite/React on 5173
```

Diagnostics — `doctor` first when anything is wrong, because most of what has
gone wrong in this project was setup rather than logic:

```bash
python scripts/doctor.py            # what this machine is missing
python scripts/acceptance.py        # what this project means by "working"
python scripts/check_models.py      # live-probe which Gemini models answer
python scripts/inspect_resume.py    # bullet counts, page count, headroom
```

`scripts/acceptance.py` is the bar: three stranger resumes × both supported
rungs, each ending in a compiled one-page PDF that records which rung wrote it.
`--rung none` and `--fixture priya` narrow it. **The list is frozen** —
anything found while fixing an item goes to `known_questions.md` as backlog; it
does not get added to the checklist.

Frontend lint is `npm run lint --prefix web` (oxlint); Python lint is `ruff`
from the `dev` extra, line length 90.

## Architecture

**Four agents behind one orchestrator.** `Discovery → Enrichment → Analysis
→ Generation`, coordinated by `agents/orchestrator.py`, which checkpoints,
emits progress and writes state to `outputs/<date>/`.

- `discovery_agent` queries keyless ATS boards (`tools/search/ats_search.py` —
  Greenhouse, Ashby, Lever) plus optional keyed sources, then filters by profile.
- `enrichment_agent` scrapes each posting's real JD. **A posting whose JD could
  not be read is dropped, never scored** (R61).
- `analysis_agent` embeds resume components and JDs, then blends embedding
  score, keyword overlap, component importance and conditional triggers.
- `generation_agent` — 2600 lines, the largest thing here — selects
  components, rewrites bullets through an LLM rung, validates against the
  fabrication rules, repairs, then fits bullets to a one-page budget
  deterministically. **The LLM writes, Python fits.**

**The UI facade is the architectural spine.** `agents/orchestrator.py` exposes
roughly two dozen module-level functions — `board_jobs`, `board_total`, `start_run`,
`run_status`, `backend_status`, `score_bands`, `set_job_status`,
`derived_levels` — and *both* front ends call exactly those and nothing else
from the project. Adding UI behaviour means adding a function there, never
reaching into `tools/`. `tests/test_ui_contract.py` walks the AST of both
`app.py` and `api/main.py` and fails the build on any other project import.
`api/main.py` is a thin HTTP wrapper over that same facade.

**Runs are background threads with on-disk progress.** `start_run` returns an id
immediately; `tools/jobs/run_registry.py` records progress in `data/runs.db`, so
a closed tab, another session or another process can still ask. A thread rather
than a subprocess, deliberately — callers only ever see an id, so swapping it
later changes nothing above.

**Three SQLite stores, two of which look alike and are not.**
`tools/jobs/job_store.py` (`data/jobs.db`) is the durable board: every job ever
discovered, and a user's `applied`/`rejected` status on it survives
re-discovery. `tools/cache/job_cache.py` is a seven-day dedup tracker built to
*forget*. `data/runs.db` is run progress.

**Configuration is one file.** `config.py` holds the Gemini fallback chain, the
embedding model and backend, and the cache settings. `resolve_backend` holds the
entire precedence chain for the LLM rung — `--backend` >
`JOBSCOUT_LLM_BACKEND` > profile > `config.LLM_BACKEND` — and
`test_backend_selection.py` fails if anything outside `config.py` reads that
constant. Model IDs live here because Google's retirement cadence is fast;
`check_models.py` live-probes, because `models.list()` has reported full support
for a model that 404s on real calls.

**Four LLM rungs, one adapter.** `tools/generation/llm_backends.py`:
`gemini` / `openai` / `ollama` / `none`. The middle two are the same
`/chat/completions` client with a different base URL. **`none` is a complete
product** — discovery, scoring, selection, one-page layout and PDF all work
with no key at all; only the rewriting is skipped. Every measurement in
`known_questions.md` was taken on Gemini.

**Paths resolve two different ways on purpose.** `tools/paths.py`: assets
(`tools/assets/`) resolve relative to the code because they ship in the wheel;
user data resolves to `JOBSCOUT_HOME`, else the repo root in a checkout, else
the platform user-data directory. Nothing may compute
`Path(__file__).parent.parent` and reach for `data/` — that shipped a wheel
that could not render a resume and would have written profiles into
site-packages.

**Profiles are the input contract.** `user_profiles/<name>.json`, schema in
`tools/profile/profile_schema.py`, bootstrapped from a real resume by
`scripts/init_profile.py` — which is also the importer both UIs call. Keyword
vocabulary, component importance and JD triggers are *derived* from the resume
(`tools/profile/derivation.py`), not hand-authored. A PDF or DOCX import is
shown field by field for correction before anything is written (R33).

**Hosting is in progress**, not done: `Dockerfile` and `fly.toml` exist, the API
serves the built React from its own origin, and a shared secret gates it
(`tests/test_hosted_boundary.py`). That gate is **authentication, not
authorization** — no endpoint has a per-user check, and with one user the two
coincide. `plan.md` tracks the rest.

## The recurring bug in this codebase

Fields and flags that are **computed and never read**. It has been found five
times: `rarely_include` (R31), `scraped_successfully` (R61) — which let the
pipeline invent job descriptions and score them — the whole selection
breakdown (R57), and `graduation_eligibility` / `experience_level` (R66).

When adding a field, wire the consumer in the same change, or do not add it.

**A sixth, and it was committed inside the change that adds a setting (R80).**
`resolve_backend` was written to hold the precedence chain for the LLM rung
and its first draft never read `LLM_BACKEND` — the constant whose only purpose
is to be read there. Reasoning did not catch it; five tests that pin a rung by
setting that constant fell through to detection and started making real
network calls, and the suite went from 66 seconds to 197. **A config value you
just made overridable is a config value with a new way to go unread.**

## A cache key encodes how much variation lives inside a category

Three times, the same fix one level down, and each was correct when written:

- **R11** — the embedding cache needed the *model* in its key
- **R45** — the LLM cache needed the *rung*: three llama3.1 replies were
  served to a run pinned to Gemini and read as a Gemini regression
- **R80** — the LLM cache needed the *model too*, because `llama3.1:8b` and
  `qwen2.5:7b` are both the `ollama` rung and shared one key

Nothing edited those decisions and none of them was wrong. What changed was
**the meaning of the category underneath them**. "Provider" meant Gemini's
fixed fallback chain, where flash-lite answering for flash is the entire
point; R37 made it mean "whatever you happened to pull", and the same key
became a bug without a character of it changing.

The tell was a comment: *"the rung, not the model id, so a fallback within a
provider still hits."* A correct sentence that stopped being correct while
nobody was editing it — the same shape as R55's comment crediting a guard that
never fired.

So when a rung, a provider or a source is added: **ask what the key assumes is
interchangeable, and whether that is still true.** A key is a claim about which
differences do not matter, and widening a category is exactly the change that
falsifies one silently — there is no error, only a table that agrees with
itself.

## The other recurring bug: two paths, one walked

A fix lands on the path the author uses and not on the twin. Found five times,
twice in the same pair of modules: the escape table (R69) and the experience
field order (R70) were both fixed in one renderer and left in the other.

The author's resume is a `.tex`, so he never walks the PDF/DOCX import path.
He reads generated resumes as PDFs, so he never parses one back. Both bugs
lived exclusively where he does not go, and neither was findable by care on
the path he does — `test_tex_renderer.py` asserted the correct behaviour the
whole time, for its own module.

**And the rule is not "check the other one" — it is *count them* (R80).** The
plan for the backend seam predicted two consumers. The code had four:
`GenerationAgent._resolve_backend`, `complete_json`, `backend_status`, and a
caption in `app.py` telling users to edit `config.py`. The count is reliably
higher than the pair in mind, which is why the closing move is a test that
fails on a fifth — `test_nothing_outside_config_reads_the_constant` walks the
syntax tree, not the text, because prose that *explains* the seam is not a
violation of it.

So: **a test that checks one path against itself proves nothing about the
other.** Walk both and compare them. The known forks are `.tex` upload vs.
PDF/DOCX import, Gemini vs. `none` vs. `ollama`, LaTeX installed vs. not, and
cached vs. cold. Each is a branch where one machine takes the same side every
time.

## `yash_pathak.json` is the least representative fixture in this repo

It predates every question the wizard has since changed, so it carries fields
no newly-built profile has — and it therefore **satisfies gates that a new
profile cannot**. Four times now:

- R70/R72's shape: the template presumed a new grad; his profile did not
- the seniority literal (R68): fixed in the wizard, not in what it starts from
- `us_citizen: true`: never seen, because his says what he is
- the preferences Save button, gated on `seniority` — populated in his profile
  from before R68, empty in every profile built since, so the button was dead
  for every new user and enabled for him

That last one is the worst of them in product terms. **A stranger does not
file a bug report; they close the tab.**

**And a fixture you wrote is a fixture that agrees with you (R77, R78).** Priya
was invented to test the importer, so she can only contain problems somebody
thought of. Two real resumes from outside the project have now found eight
defects between them — a `Research/Projects` heading that matched nothing, a
`Publications` section filed as project bullets, two degrees merged into one
wrong record, `\bmaster\b` never matching "Masters", the PDF link appendix
becoming a skills category, a coursework bullet becoming a school name, its
margin wrap becoming a second school, and `Lakeside UniversityFairview, IL`
read as a location.

Both live in `tests/fixtures/` as **anonymized extracted text**: identity
replaced, every structural artifact kept byte for byte. Text, not PDF, because
they are strangers' resumes and this repository is public. Keep at least one
fixture nobody here authored, and do not tidy it — a fixture cleaned up is a
fixture that has stopped testing anything.

The same trap catches a fixture *derived* from a real one. R77's tests used
text written here from the real resume, so the thing verifying the heading
rule was authored by the person the rule existed to escape. If a fixture is a
paraphrase, it agrees with you too.

## A measurement taken through a terminal is a measurement of the terminal

R77 recorded a data defect that did not exist: en dashes, `²` and `×` "arriving
as `�`" from a PDF. The code points were correct — U+2013, U+00B2, U+00D7
— and the console could not print them. Left standing, that entry was an
invitation to write a repair pass for a problem nobody had.

**Before recording a defect in what a byte says, check what is doing the
saying.** Assert the code point, not the glyph: `assertIn("–", body)`
passes or fails on the data, and `print()` does not. The same applies to
anything read through a shell, a log line, or a screenshot — R74's own note
says a screenshot is not a measurement, and this is that rule pointed at
encodings.

**And it applies hardest to the tools that do the measuring (R81).** The
acceptance run crashed while printing its first real finding: a validation
error quoting a bullet contained `→`, the console was cp1252, and the report
died on the thing it existed to report. **A measurement tool that fails on
some findings is worse than no tool**, because it does not fail uniformly —
it reports success on exactly the cases it cannot render, and those are
correlated with the interesting ones. Two other page-count reads and one log
parse in this repo have had the same shape. Any harness that prints what it
found needs the encoding guard `agents/orchestrator._console_print` already
carries.

**The other half: check the instrument before trusting the reading.** R81
recorded Ollama at 0 of 3, and re-scoring the same output against a corrected
bar made it 1 of 3 — no change to the model or the code. The first number was
an artifact of the measuring bar, and had it been accepted it would have
entered the log as fact and survived there the way R44's verdict did for four
months. **When a result is bad enough to close a direction, re-derive it once
before writing it down.**

## The pattern reader never guesses at content

It surfaces what it cannot resolve, for a person or a model to fix. Stated once
because it has now been decided three times, identically:

- the glued email (`Boston, MApriya@...`) — every rule that trims the prefix
  also breaks `JSmith@example.com`
- `A WS` for AWS — repairing spaces inside words invents content
- `Lakeside UniversityFairview, IL` — rejected as a location, never split,
  because the same boundary splits PostgreSQL, JavaScript and LinkedIn

What makes this survivable is R33: every field is shown for correction before
anything is written. The extraction prompt asks the *model* to repair these,
and it names `"W ebApp"` as its example — the model can tell the difference and
a regex cannot. So the floor's job is to be honestly wrong in a visible place,
never quietly right-looking.

So: **build against Priya, not against yourself.** `priya_raghunathan` — six
years, Boston, Staff Engineer, imported from a PDF this repo did not produce —
is the default fixture for anything touching profile shape, gates, defaults or
onboarding. `yash_pathak` is a **legacy-migration test case**, which is what it
actually is: the shape a profile has when it was built before the current
questions existed. Both are worth testing. Only one of them is what a new user
gets.

## Ignore by pattern, never by filename

`.gitignore` named `data/jobs.db`. `data/runs.db` arrived four months later
(R51) and nobody added a second line, so a live store holding real run history
was committed while its twin was ignored. The same rule had already been
written for `data/master_resumes/*.tex` and missed every PDF and Word resume a
user uploads (R38 added that path).

**Any directory the app writes to gets a pattern, not a list of names.** A new
file format or a second store is exactly the change nobody remembers to
mirror, and the cost lands in a published commit rather than in a test.

## The invariant: unknown is never a value

**Nothing may render or score "not yet known" as though it were known.** Every
field with a "not yet" state needs a third case — known, absent, and unknown —
and the code has to carry all three to the place that displays or ranks it.

Five instances, and the fourth is what makes it a rule rather than a run of bad
luck:

- `years_required: None` read as "no experience required" (R64)
- country parse failures read as a country that did not match (R55)
- `location_score == 0` meant both "a state you did not name" and "state
  unknown", so three postings listed only as "United States" were excluded as
  relocation (R69)
- the React board rendered every job as **"Not scored"** for the beat before
  the score bands arrived, telling the reader analysis had skipped their whole
  list — a claim, where a placeholder was wanted

- the bullet budget spent half a page on the projects section a resume did
  not have, so three jobs shared six bullets and the bottom third was blank
  (R74). Not a display this time — an *allocation*. The rule reaches further
  than rendering: any budget, quota or average split across sections has to
  ask whether a section is empty or absent

The fourth appeared within hours of a frontend existing, which is the point:
**anything that arrives asynchronously has an unknown state by construction.**
Every screen in the wizard displays data that loads after it mounts, so this
will keep firing. A loading state is not an empty state, an empty state is not
a zero, and a zero is not a "no".

**The sharpest form of it, found by R75:** the preferences Save button was
gated on the levels a profile's years imply, and an unanswered years field
implies none — so the fix for R72's dead button rebuilt the same dead button
one field over, on both UIs, and the test could not see it because it walked
`range(0, 41)` and never `None`. **Any test that walks a range is a test that
has not walked the absence.**

Related and older: **a filter that removes things must say how many.** The
board hides jobs the gates reject (R62) and states the count under the current
filters — 59 of 136, and 14 of 19 when narrowed to one company. Silent
subtraction is the same failure wearing product clothes.

# JobScout

> An end-to-end multi-agent system that discovers relevant jobs, scores them
> against your resume, and generates tailored, ATS-optimized resumes per posting.

[![PyPI](https://img.shields.io/pypi/v/jobscout)](https://pypi.org/project/jobscout/)
[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://python.org)
[![Google ADK](https://img.shields.io/badge/Google%20ADK-1.0+-green)](https://google.github.io/adk-docs/)
[![Gemini](https://img.shields.io/badge/Gemini-3.5%20Flash-orange)](https://ai.google.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## What it does

Four specialized agents coordinated by an orchestrator. Each run:

1. **Discovers** software roles at the levels your profile asks for, from
   keyless ATS boards and optional key-based sources
2. **Enriches** each posting by scraping the full JD from its apply URL
3. **Analyzes** resume fit using Gemini embeddings + composite scoring
4. **Generates** tailored LaTeX resumes that mirror each JD's terminology,
   then compiles each one to PDF

The result is a directory of PDFs (with their `.tex` sources) ready to review
and submit.

---

## Architecture

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Discovery   │ -> │  Enrichment  │ -> │   Analysis   │ -> │  Generation  │
├──────────────┤    ├──────────────┤    ├──────────────┤    ├──────────────┤
│ GitHub repos │    │ Scrape JDs   │    │ Embed resume │    │ Tailor       │
│ Serper       │    │ (Greenhouse, │    │ Score fit    │    │ bullets w/   │
│ Adzuna       │    │  Lever,      │    │ Select top   │    │ Gemini       │
│              │    │  Ashby, etc) │    │ components   │    │ Validate +   │
│ Filter by    │    │              │    │              │    │ repair loop  │
│ profile      │    │ Cache        │    │              │    │              │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
        \                  \                  \                    \
         \------------------ Orchestrator ------------------------/
                       (coordinates, checkpoints, state)
```

Each agent uses [Google ADK](https://google.github.io/adk-docs/) and has
specialized tools. The orchestrator is stateful and supports replay
(`--input` flag) so you can debug analysis/generation without re-scraping.

---

## Quick start

### 1. Install

```bash
pip install "jobscout[local]"
```

The `local` extra installs `model2vec`, which lets JobScout score jobs with no
API key at all. Leave it off and scoring needs a Gemini key instead.

Python 3.10 or newer. To work on it rather than use it:

```bash
git clone https://github.com/YashPathak1446/jobscout.git
cd jobscout
python -m venv venv
source venv/bin/activate    # on Windows: venv\Scripts\activate
pip install -e ".[local]"
```

Your profiles, resumes and databases live outside the package — in the repo
itself when you run from a checkout, and under your platform's user data
directory when installed. Set `JOBSCOUT_HOME` to put them somewhere else.

That gives you three commands:

| | |
|---|---|
| `jobscout-doctor` | checks this machine and says what to fix |
| `jobscout-ui` | the local web app |
| `jobscout` | the command-line pipeline |

**Run `jobscout-doctor` first.** It checks the Python version, the
dependencies, your `.env`, whether a model backend is reachable, whether a
LaTeX engine is installed, and whether your profile and resume actually load —
then tells you what to do about anything missing. Most of what has ever gone
wrong in this project was setup rather than logic, and this is the fast way to
see it.

Optional things are reported as warnings rather than errors, because a run
with no LaTeX engine and no API key still produces real resumes — it just
produces `.tex` files using your own bullets. `pip install -r requirements.txt`
still works if you would rather not install the package.

### 2. Configure environment

```bash
cp .env.example .env
# Fill in GOOGLE_API_KEY — that is the variable the code reads,
# and .env.example already has the line waiting for it.
```

Get a Gemini API key at [aistudio.google.com](https://aistudio.google.com).
Free tier is sufficient for development.

**Optional — and the free tier does not depend on it.** Discovery, scoring,
component selection, the one-page layout and PDF compilation all need no key
and no model at all. Without one, your own bullets are used exactly as you
wrote them rather than rewritten per posting. That is a complete, working
product: it finds and scores jobs and builds you a tailored resume for each
one. A model changes the bullets, not whether you get a resume.

Both of those rungs are checked by `python scripts/acceptance.py`, which is
what this project means by "working".

A local [Ollama](https://ollama.com) sits between them and is **not currently
recommended**. Measured 2026-08-27 on `llama3.1:8b`: it failed the acceptance
run on all three fixture resumes, returning the wrong number of bullets per
component and landing in the orphan length zone. That is one measurement on
one deliberately-stale model — chosen for comparability with a four-month-old
result — and three plausible causes are undiagnosed, including that the Ollama
path lacks the validate-and-retry loop the Gemini path has. See R81 in
`known_questions.md`. If you have a key, use Gemini; if you do not, the
no-model floor is the tested option.

### 3. Set up your profile

Copy the template and customize:

```bash
cp user_profiles/template.json user_profiles/<your_name>.json
```

Edit `user_profiles/<your_name>.json` with your job preferences,
target roles, locations, and resume preferences.

### 4. Add your master resume

Drop your LaTeX resume at `data/master_resumes/<your_name>.tex` and
update `master_resume_path` in your profile JSON to match.

The system uses [Jake Gutierrez's resume template](https://github.com/jakegut/resume)
as its formatting reference.

### 5. Run

```bash
# Mock mode — zero API calls, useful for testing the pipeline
python -m agents.orchestrator --profile <your_name> --max-jobs 5 --mock

# Real run
python -m agents.orchestrator --profile <your_name> --max-jobs 5
```

Generated resumes appear in `outputs/<date>/`.

### 6. Or use the app

```bash
streamlit run app.py
```

The React port is being built alongside it and currently covers the job
board. It is two processes — an HTTP boundary over the same pipeline, and a
Vite dev server:

```bash
python -m uvicorn api.main:app --reload --port 8000
```

```bash
npm install --prefix web && npm run dev --prefix web
```

Both UIs are views of one surface. `api/main.py` calls exactly the functions
`app.py` calls and imports nothing else from the project, which
`tests/test_ui_contract.py` enforces for both — the condition R25 accepted
Streamlit on, now that there is a second view to test it against.

Five screens: upload your resume, answer the two things a resume cannot state
(where you live, and what you are allowed to work as), pick what you are
looking for and at which levels, optionally tune what gets shown, then run.
Progress streams while it works, and each result offers a download.

**A PDF or Word resume is confirmed before it is used.** Everything read out
of it — contact details, education, each experience and project with its
bullets — is shown for correction, and you can drop an entry extraction got
wrong entirely. Nothing is written until you agree with it, because a silent
misparse otherwise produces bad resumes until somebody notices. A `.tex`
upload skips that step; it is already in the pipeline's own format.

**An API key is optional.** The app detects what is available — a Gemini key,
an OpenAI-compatible key, a local Ollama, or nothing — and says plainly what
it picked and what that costs. With nothing configured you still get jobs
discovered, scored, and a resume per posting with the right components
selected; only the bullet rewriting is skipped.

**"Your jobs"** in the sidebar is the board: every posting ever discovered,
with its score, its status and the resume written for it. Mark jobs applied or
rejected and that sticks across runs — a re-discovered posting never loses
what you recorded about it.

If you already have a profile, the first screen lets you pick it and skip
straight to running.

PDFs need a LaTeX engine — MiKTeX on Windows, TeX Live elsewhere. Without one
you still get the `.tex` files, and the app says so rather than showing you a
dead button.

---

## Useful flags

| Flag | What it does |
|---|---|
| `--profile <name>` | Which profile to use (e.g. `yash_pathak`) |
| `--max-jobs N` | How many jobs to discover and analyze |
| `--mock` | Use mock data for all stages — zero API calls |
| `--mock-embeddings` | Mock embeddings only (saves embedding quota) |
| `--mock-generation` | Mock generation only (saves Gemini calls) |
| `--input <path>` | Replay analysis on a cached `enriched_jobs.json` (skips Discovery + Enrichment, useful for debugging) |
| `--checkpoint` | Pause for review between stages |
| `--no-pdf` | Write `.tex` only, skip pdflatex compilation |
| `--verbose` | Verbose logging |

---

## Tests

```bash
python -m unittest discover -s tests -t .
```

Stdlib `unittest` rather than pytest, deliberately: `requirements.txt` is the
install list for anyone running the app, and a test framework does not belong
there. The suite needs no LaTeX — `pdf_builder`'s tests stand in a stub
`pdflatex` so the failure paths (timeout, compile error, missing engine) are
reachable, and contributors without TeX can still run everything.

Two of them are not unit tests and are worth knowing about: `test_ui_contract`
parses `app.py` and fails if the UI imports anything from `tools/`, which is
the condition the Streamlit decision rests on; and `test_pipeline_integration`
runs the whole orchestrator in mock mode through the same callbacks the UI
uses, so a checkpoint that would hang the app is caught here rather than in
front of a user.

## Caching

Three caches, all under `.cache/` or `cache/` and all gitignored:

| Cache | Keyed on | Saves |
|---|---|---|
| Resume embeddings | Resume file hash + model | ~19 calls per run |
| Text embeddings | Model + task type + exact text | ~20 calls per baseline replay |
| LLM responses | Prompt hash | A full generation per repeated job |

The text embedding cache matters more than it sounds. Every scoring decision
in `known_questions.md` was measured by replaying a frozen set of job
descriptions, and before this existed each replay re-embedded all of them —
so the instrument you are meant to reach for before every change was also
what exhausted the daily free-tier quota.

## Project layout

```
jobscout/
├── agents/                 # ADK agents
│   ├── discovery_agent.py
│   ├── enrichment_agent.py
│   ├── analysis_agent.py
│   ├── generation_agent.py
│   └── orchestrator.py
├── tools/                  # Agent tools (search, scraping, scoring, etc.)
│   ├── search/
│   ├── scraping/
│   ├── resume/
│   ├── generation/
│   ├── profile/
│   ├── jobs/
│   └── cache/
├── data/
│   └── master_resumes/     # Your LaTeX resume(s) — gitignored
├── user_profiles/          # Profile JSONs — personal ones gitignored
│   └── template.json       # Starting point for new users
├── outputs/                # Generated resumes (gitignored)
├── cache/                  # Embedding/job caches (gitignored)
├── README.md
├── scripts/                # Diagnostics and setup
│   ├── init_profile.py     # Bootstrap a profile from a resume
│   ├── inspect_resume.py   # Bullet counts, page count, headroom
│   ├── baseline.py         # Freeze/verify measurement baselines
│   └── check_models.py     # Probe which Gemini models are live
├── tests/                  # Stdlib unittest, no extra dependency
├── known_questions.md      # Open architectural questions
├── migration_plan.md       # Multi-user migration roadmap
└── requirements.txt
```

---

## Status

This is an active project. Current state (August 2026):

- ✅ End-to-end pipeline working with real data
- ✅ Multi-agent architecture with ADK
- ✅ Composite component scoring (embeddings + keywords + importance + conditional triggers)
- ✅ Validation + repair loop for generation failures
- ✅ Deterministic bullet-length fitting (LLM writes, Python fits)
- ✅ Persistent caches (embeddings, scraped JDs, LLM responses by prompt hash)
- ✅ Multi-source discovery (GitHub repos active; Serper/Adzuna wired but inactive)
- ✅ PDF output via pdflatex (skips cleanly when no LaTeX is installed)
- ✅ One-page enforcement — resumes that render to 2+ pages, or whose page
  count cannot be read, are demoted to `needs_review/` rather than shipped
- ✅ Import from PDF, Word or LaTeX, with every extracted field shown for
  correction before anything is written
- ✅ A profile derived from your own resume — keyword vocabulary, component
  importance and JD triggers, none of it hand-authored
- ✅ A choosable model backend: `--backend`, `JOBSCOUT_LLM_BACKEND`, a profile
  field or detection, and every run records which one actually wrote it
- ✅ `python scripts/acceptance.py` — the fixed checklist this project means
  by "working": three resumes it did not author, both supported rungs, ending
  in compiled one-page PDFs
- 🚧 Working on: a hosted version — accounts, per-user storage, server-side
  LaTeX. The local CLI stays.
- 📋 Tracked in `known_questions.md`

### PDF output

Generation compiles each `.tex` to a `.pdf` beside it. This needs a LaTeX
toolchain on PATH — MiKTeX on Windows, TeX Live elsewhere:

```bash
winget install --id MiKTeX.MiKTeX     # Windows
sudo apt install texlive-latex-extra  # Debian/Ubuntu
```

Without one, the pipeline logs a warning and writes `.tex` only — nothing
fails. Pass `--no-pdf` to skip compilation even when LaTeX is available.

---

## License

MIT — see [LICENSE](LICENSE).

---

## Author

[Yash Pathak](https://github.com/YashPathak1446) — built while job-hunting after my CS undergrad at UC Irvine.

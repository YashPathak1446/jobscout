# JobScout

> An end-to-end multi-agent system that discovers relevant jobs, scores them
> against your resume, and generates tailored, ATS-optimized resumes per posting.

[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://python.org)
[![Google ADK](https://img.shields.io/badge/Google%20ADK-1.0+-green)](https://google.github.io/adk-docs/)
[![Gemini](https://img.shields.io/badge/Gemini-2.5%20Flash-orange)](https://ai.google.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## What it does

Four specialized agents coordinated by an orchestrator. Each run:

1. **Discovers** new-grad / entry-level software roles from curated sources
2. **Enriches** each posting by scraping the full JD from its apply URL
3. **Analyzes** resume fit using Gemini embeddings + composite scoring
4. **Generates** tailored LaTeX resumes that mirror each JD's terminology

The result is a directory of LaTeX resumes (PDF generation coming) ready to
review and submit.

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
git clone https://github.com/YashPathak1446/jobscout.git
cd jobscout
python -m venv venv
source venv/bin/activate    # on Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

Get a Gemini API key at [aistudio.google.com](https://aistudio.google.com).
Free tier is sufficient for development.

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
| `--verbose` | Verbose logging |

---

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
├── known_questions.md      # Open architectural questions
├── migration_plan.md       # Multi-user migration roadmap
├── requirements.txt
└── pyproject.toml
```

---

## Status

This is an active project. Current state (May 2026):

- ✅ End-to-end pipeline working with real data
- ✅ Multi-agent architecture with ADK
- ✅ Composite component scoring (embeddings + keywords + importance + conditional triggers)
- ✅ Validation + repair loop for generation failures
- ✅ Persistent caches (embeddings, scraped JDs)
- ✅ Multi-source discovery (GitHub repos active; Serper/Adzuna wired but inactive)
- 🚧 Working on: PDF output, format-agnostic resume parsing (PDF/DOCX inputs), wider discovery sources
- 📋 Tracked in `known_questions.md`

---

## License

MIT — see [LICENSE](LICENSE).

---

## Author

[Yash Pathak](https://github.com/YashPathak1446) — built while job-hunting after my CS undergrad at UC Irvine.

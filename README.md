# 🔍 JobScout — AI-Powered Job Discovery & Resume Automation

> **Built to solve a real problem:** As a new grad navigating a competitive job market, I wanted a system that could automatically find relevant roles, score them against my resume, and generate tailored, ATS-optimized resumes — all without spending hours on manual applications.

[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://python.org)
[![Google ADK](https://img.shields.io/badge/Google%20ADK-1.0+-green)](https://google.github.io/adk-docs/)
[![Gemini](https://img.shields.io/badge/Gemini-2.5%20Flash-orange)](https://ai.google.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## What It Does

JobScout V2 is an end-to-end automated job application pipeline. Every day, it:

1. **Discovers** new grad / entry-level software engineering roles from curated GitHub repos, Google search (Serper), and job APIs (Adzuna)
2. **Filters** irrelevant jobs using a single LLM call — removes senior roles, PhD requirements, non-US positions, expired listings, and citizenship-only roles
3. **Enriches** each listing by scraping the full job description from the apply URL (Greenhouse, LinkedIn, Lever, etc.)
4. **Scores** all jobs semantically using Gemini embeddings — cosine similarity between your resume components and each JD
5. **Checkpoints** with you — shows scores, best-matching resume components, apply links
6. **Generates** tailored, ATS-optimized resumes in LaTeX (Jake's Resume format) with role-specific bullets, reordered skills, and cherry-picked projects

**Result:** 10–15 tailored PDF resumes per run, ready to submit.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      JobScout V2 Pipeline                        │
├──────────────┬──────────────┬──────────────┬────────────────────┤
│  Phase 1     │  Phase 2     │  Phase 3     │  Phase 4           │
│  Discovery   │  Enrichment  │  Scoring     │  Generation        │
├──────────────┼──────────────┼──────────────┼────────────────────┤
│ GitHub repos │ Scrape full  │ Gemini       │ LLM tailors        │
│ Serper.dev   │ JD from URL  │ embeddings   │ bullets (XYZ)      │
│ Adzuna API   │ (Greenhouse, │ + cosine     │ LaTeX template     │
│              │ LinkedIn,    │ similarity   │ injection          │
│ LLM filter   │ Lever, etc.) │              │ pdflatex / Overleaf│
│ (1 API call) │              │ Human        │                    │
│ Dedup across │ 8000 char    │ checkpoint   │ outputs/           │
│ runs         │ cap          │              │ applied_jobs.csv   │
└──────────────┴──────────────┴──────────────┴────────────────────┘
```

### Key Design Decisions

**Hybrid scoring — embeddings + LLM:** Gemini embeddings handle bulk scoring (free, fast, zero tokens). The LLM only runs on the top 10-12 matches for detailed analysis and resume generation. This keeps daily API costs near zero while getting high-quality output where it matters.

**Template-based resume generation:** Instead of generating LaTeX from scratch, the pipeline injects tailored content into your own `main.tex` template. Formatting is always identical to your master resume — only the content changes per role.

**LLM filter over keyword exclusion:** A single Gemini call filters all discovered jobs at once, understanding context rather than matching keywords. "New Grads 2026 - Software Engineer" passes. "Sr. Principal Engineer - 8+ years" does not.

**Graceful fallback chain:** GitHub repos → Serper → Adzuna. If one source fails or is exhausted, the next picks up automatically. Every step handles failures without crashing.

---

## V1 vs V2

| Feature | V1 | V2 |
|---------|----|----|
| Input | One job posting (manual paste) | Automatic discovery (50+ per run) |
| Scoring | Deterministic keyword matching | Gemini semantic embeddings |
| Output | Fit analysis + interview prep | Tailored LaTeX resume PDFs |
| Job sources | None (manual) | GitHub new grad repos, Serper, Adzuna |
| LLM usage | 3 agents per job | 1 filter call + embeddings + 1 per resume |
| Interface | ADK Dev UI, Streamlit, CLI | CLI with human checkpoints |

V1 is preserved in `v1/` — still useful for deep analysis of a single role.

---

## Quick Start

### Prerequisites

- Python 3.10+
- [Gemini API key](https://aistudio.google.com/app/apikey) — free tier (1500 req/day)
- [Serper.dev API key](https://serper.dev) — free tier (2,500 searches one-time)
- [Adzuna API keys](https://developer.adzuna.com) — free tier (unlimited)

### Setup

```bash
git clone https://github.com/YashPathak1446/jobscout.git
cd jobscout

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -e .
pip install python-docx google-genai

cp .env.example .env
# Edit .env — add GOOGLE_API_KEY, SERPER_API_KEY, ADZUNA_APP_ID, ADZUNA_APP_KEY
```

Add your master resume:
```bash
# Place your LaTeX resume at:
data/master_resume.tex   # Jake's Resume format (primary)
data/master_resume.txt   # Plain text fallback
```

### Run

```bash
# Test with zero API calls (mock data)
python -m jobscout.v2 --mock --threshold 30

# Dry run — real jobs, real scoring, no resume generation
python -m jobscout.v2 --dry-run --threshold 30 --max-jobs 20

# Full pipeline — generates tailored resumes
python -m jobscout.v2 --threshold 30 --max-jobs 30

# Reset seen job history (run weekly for fresh results)
python -m jobscout.v2 --reset-seen
```

### CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--max-jobs` | 5 | Max jobs to discover per run |
| `--threshold` | 75 | Minimum embedding similarity score (0–100) |
| `--dry-run` | off | Skip resume generation |
| `--mock` | off | Use mock data, zero API calls |
| `--mock-embeddings` | off | Real jobs, fake scoring (for testing flow) |
| `--reset-seen` | off | Clear seen job history |

---

## Configuration

All behavior is controlled from `config.py` — no need to touch pipeline code:

```python
# Discovery sources (tries in order, auto-fallback)
JOB_DISCOVERY_PRIORITY = ["github_newgrad", "serper", "adzuna"]

# Scoring threshold
FIT_THRESHOLD = 40

# Resume rules passed directly to the LLM
RESUME_RULES = """
- ALWAYS include Sorenson Communications and 101gen.ai as first two experiences
- Third experience: 1-2 bullets max
- Each project: 2 bullets (3 only if resume fits on 1 page)
- Max 4 lines of technical skills, Languages must be first
- Target: 1 page total
"""

# Technology equivalency map (AWS ≈ GCP for scoring purposes)
SIMILAR_TECH_MAP = {"aws": "gcp", "pytorch": "tensorflow", ...}
```

---

## Project Structure

```
jobscout/
├── config.py                        # All pipeline settings
├── data/
│   ├── master_resume.tex            # Your LaTeX resume (Jake's format)
│   └── master_resume.txt            # Plain text fallback
├── jobscout/
│   ├── v2.py                        # Main pipeline runner
│   ├── tools/
│   │   ├── job_search_tools.py      # Serper + Adzuna + GitHub scrapers + JD enrichment
│   │   ├── embedding_scorer.py      # Gemini embeddings + cosine similarity
│   │   ├── latex_parser.py          # Parses master_resume.tex into components
│   │   ├── resume_generator.py      # LLM tailoring + LaTeX template injection
│   │   ├── resume_parser.py         # Plain text resume parser (fallback)
│   │   └── component_selector.py    # Keyword-based component scoring
│   └── utils/
│       ├── dedup.py                 # Cross-run deduplication + applied_jobs.csv
│       └── model_fallback.py        # Gemini 3 Flash -> 2.5 Flash fallback
├── v1/                              # Original multi-agent analyzer (preserved)
│   ├── agents/                      # Research, Fit, Prep agents (Google ADK)
│   └── tools/                       # Deterministic skill matching tools
└── outputs/
    ├── YYYY-MM-DD/                  # Dated run outputs
    │   ├── Yash_Pathak_*.tex        # Generated LaTeX resumes
    │   ├── Yash_Pathak_*.pdf        # Compiled PDFs (if pdflatex available)
    │   └── summary.md               # Scored job list with apply links
    └── applied_jobs.csv             # Running log for spreadsheet import
```

---

## Job Discovery Sources

| Source | Coverage | Free Tier | Notes |
|--------|----------|-----------|-------|
| **GitHub new grad repos** | ~30-50 roles/day | Unlimited | Manually curated, verified entry-level US roles updated daily |
| **Serper.dev** | Broad (Google Search) | 2,500 searches | Site-targeted to Greenhouse, Lever, LinkedIn job views |
| **Adzuna** | US job market | Unlimited | API with `max_days_old` filtering. Used as fallback |

GitHub sources used:
- [`jobright-ai/2026-Software-Engineer-New-Grad`](https://github.com/jobright-ai/2026-Software-Engineer-New-Grad)
- [`speedyapply/2026-AI-College-Jobs`](https://github.com/speedyapply/2026-AI-College-Jobs)

---

## Scoring Pipeline

```
For each discovered job:
  1. Scrape full JD from apply URL (Greenhouse, LinkedIn, Lever -> 5-8K chars)
  2. Embed JD text using gemini-embedding-001 (free, separate quota)
  3. Compare against pre-computed embeddings of each resume component
  4. Score = weighted cosine similarity (40% exp + 30% projects + 30% skills)
  5. Normalize to 0-100 scale

Typical scores: 40-65% for relevant roles
(100% would mean JD and resume are identical text — not realistic)
```

---

## Resume Generation

The pipeline uses `master_resume.tex` as a template and only replaces three sections:

```
master_resume.tex
    |
    v
LLM receives: JD text + selected experiences + selected projects + skills
LLM outputs:  JSON with tailored bullets (XYZ formula), reordered skills
    |
    v
Template injection: replace Experience, Projects, Technical Skills sections
    |
    v
pdflatex compile -> PDF
(or save .tex for Overleaf if pdflatex unavailable)
```

Every resume has identical formatting to your master — only the tailored content changes.

---

## API Cost Breakdown (per daily run, 30 jobs)

| Step | API | Calls | Cost |
|------|-----|-------|------|
| Discovery | Serper | ~9 searches | ~9 / 2,500 free |
| JD filter | Gemini chat | 1 | ~1K tokens |
| Embedding | Gemini embed | ~30 | Free separate quota |
| Resume gen | Gemini chat | ~10 | ~50K tokens |
| **Total** | | | **~$0 on free tier** |

---

## V1 — Multi-Agent Fit Analyzer (preserved)

The original version is still available for deep single-role analysis:

```bash
adk web                          # ADK Dev UI
python -m jobscout.main --jd data/sample/sample_jd.txt --resume data/master_resume.txt
streamlit run jobscout/app.py    # Streamlit UI
```

V1 uses three specialized Google ADK agents (Research → Fit → Prep) to produce a detailed fit report, interview questions, and cover letter for one job at a time.

---

## Roadmap

- [ ] Local PDF compilation via TeX Live (currently uses Overleaf)
- [ ] LLM-based detailed scoring to replace embedding-only approach
- [ ] Cover letter generation per application
- [ ] GitHub Actions scheduled runs with email digest
- [ ] Visa sponsorship filter (H-1B / OPT friendly roles)

---

## License

MIT — use it, fork it, land the job.

---

*Built by [Yash Pathak](https://github.com/YashPathak1446) — UC Irvine CS '25*
*Open to Software Engineering, ML Engineering, and DevOps roles in the US*
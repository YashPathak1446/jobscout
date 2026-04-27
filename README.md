# 🔍 JobScout — Multi-Agent Job Research & Fit Analyzer

An AI-powered multi-agent system that analyzes job postings against your resume, using **Google Agent Development Kit (ADK)** to orchestrate specialized agents for company research, fit scoring, and interview preparation.

> **Built to solve a real problem:** As a new grad navigating the job market, I wanted a tool that could instantly tell me how well I match a role, what gaps to address, and how to prepare — all from a single job posting URL or text.

---

## Architecture

JobScout uses a **Sequential Multi-Agent Pipeline** — three specialized agents coordinated by ADK's `SequentialAgent`:

```
┌─────────────────────────────────────────────────────┐
│                  JobScout Orchestrator               │
│                  (SequentialAgent)                    │
│                                                      │
│  ┌──────────┐   ┌──────────┐   ┌──────────────┐    │
│  │ Research  │──▶│   Fit    │──▶│    Prep      │    │
│  │  Agent    │   │  Agent   │   │    Agent     │    │
│  └────┬─────┘   └────┬─────┘   └──────┬───────┘    │
│       │              │                  │            │
│  ┌────▼─────┐   ┌────▼─────┐   ┌──────▼───────┐    │
│  │ search   │   │ skill    │   │ search_web   │    │
│  │ scrape   │   │ match    │   │ (for company │    │
│  │ extract  │   │ score    │   │  context)    │    │
│  │ keywords │   │ bullets  │   │              │    │
│  └──────────┘   └──────────┘   └──────────────┘    │
└─────────────────────────────────────────────────────┘
```

| Agent | Role | Tools |
|-------|------|-------|
| **Research Agent** | Gathers company info, tech stack, recent news, culture signals | `search_web`, `scrape_webpage`, `extract_keywords` |
| **Fit Agent** | Scores resume-to-JD match, identifies gaps, suggests improvements | `analyze_skill_match`, `score_experience_level`, `generate_resume_bullets` |
| **Prep Agent** | Generates interview questions, talking points, cover letter | `search_web` |

---

## Quick Start

### Prerequisites
- Python 3.10+
- A [Gemini API key](https://aistudio.google.com/app/apikey) (free tier works)

### Setup

```bash
# Clone the repo
git clone https://github.com/YashPathak1446/jobscout.git
cd jobscout

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[ui,dev]"

# Configure API key
cp .env.example .env
# Edit .env and add your GOOGLE_API_KEY
```

### Run — CLI

```bash
# Using sample data
python -m jobscout.main \
    --jd data/sample/sample_jd.txt \
    --resume data/sample/sample_resume.txt

# Or paste JD inline
python -m jobscout.main \
    --jd-text "Software Engineer at Stripe..." \
    --resume data/sample/sample_resume.txt
```

### Run — ADK Dev UI

```bash
# Launch ADK's built-in web interface
adk web --port 8000
# Open http://localhost:8000 and select "jobscout_orchestrator"
```

### Run — Streamlit UI

```bash
streamlit run jobscout/app.py
# Open http://localhost:8501
```

### Run — Docker

```bash
docker build -t jobscout .
docker run -p 8501:8501 --env-file .env jobscout
```

---

## Example Output

Given a Stripe SWE new-grad posting and my resume, JobScout produces:

**Research Agent →**
- Company overview, funding stage, tech stack (Ruby, Java, AWS)
- Recent news and engineering blog highlights
- Culture signals from Glassdoor

**Fit Agent →**
- Overall Fit Score: **72/100**
- Matched: Python, AWS, Docker, Kubernetes, REST APIs, CI/CD, Terraform
- Gaps: Ruby, Go, large-scale distributed systems experience
- Tailored resume bullet suggestions

**Prep Agent →**
- 10 likely interview questions with answer strategies
- 5 STAR-format talking points using my actual experience
- Custom cover letter draft
- Gap-bridging strategies for the employment timeline

---

## Project Structure

```
jobscout/
├── agent.py                    # ADK CLI entry point (adk web / adk run)
├── pyproject.toml              # Dependencies and project metadata
├── Dockerfile                  # Container deployment
├── .env.example                # API key template
├── data/
│   └── sample/                 # Sample JD and resume for testing
│       ├── sample_jd.txt
│       └── sample_resume.txt
└── jobscout/
    ├── __init__.py
    ├── main.py                 # CLI entry point
    ├── app.py                  # Streamlit web UI
    ├── agents/
    │   ├── __init__.py
    │   ├── orchestrator.py     # SequentialAgent coordinator
    │   ├── research_agent.py   # Company & role research
    │   ├── fit_agent.py        # Resume fit analysis
    │   └── prep_agent.py       # Interview prep generation
    └── tools/
        ├── __init__.py
        ├── research_tools.py   # Web search, scraping, keyword extraction
        └── resume_tools.py     # Skill matching, scoring, bullet generation
```

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Agent Framework | **Google ADK** | Production-grade multi-agent orchestration with built-in dev UI |
| LLM | **Gemini 2.5 Flash** | Fast, cost-effective, optimized for tool use in ADK |
| Web Research | **SerpAPI** (optional) | Real-time search; graceful fallback to LLM knowledge |
| Frontend | **Streamlit** | Rapid prototyping, zero-config web UI |
| Deployment | **Docker** | Portable, reproducible builds |
| Language | **Python 3.10+** | ADK native language, rich ML/AI ecosystem |

---

## Key Design Decisions

1. **SequentialAgent over LLM-based routing** — Deterministic pipeline ensures all three analyses always run. No dropped steps from LLM hallucination.

2. **Tools as pure functions** — Each tool is a typed Python function with docstrings that ADK automatically converts to function-calling schemas. Easy to test, easy to extend.

3. **Graceful degradation** — Works without SerpAPI key by falling back to LLM knowledge. Never crashes on missing optional config.

4. **ADK CLI compatible** — The `agent.py` entry point means you get ADK's dev UI (`adk web`) for free, with session management and debugging tools.

---

## Extending JobScout

Ideas for V2 (and good follow-up projects):

- **Add a Salary Research Agent** using Levels.fyi API or Glassdoor scraping
- **LinkedIn integration** — auto-fetch the hiring manager's profile for personalized outreach
- **Batch mode** — analyze multiple JDs at once with `ParallelAgent`
- **Memory/State** — track applications over time using ADK sessions
- **Deploy to Cloud Run** with Terraform (IaC!)

---

## License

MIT — use it, fork it, land the job.

---

*Built by [Yash Pathak](https://github.com/YashPathak1446) — UC Irvine CS '25*

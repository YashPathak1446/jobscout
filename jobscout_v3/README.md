# JobScout V3 - Multi-Agent Job Discovery & Application System

**Powered by Google ADK | Built for New Grads**

---

## 🎯 What is JobScout V3?

An **end-to-end automated job application system** that:
- 🔍 **Discovers** relevant jobs from multiple sources
- 📄 **Enriches** job listings with full descriptions
- 🎯 **Analyzes** resume fit using semantic embeddings
- 📝 **Generates** tailored, ATS-optimized resumes

**Key Feature:** True multi-agent architecture using Google ADK. Each agent reasons, uses tools, and collaborates to solve complex job search tasks autonomously.

---

## 🏗️ Architecture

### 4 Specialized Agents

```
Discovery Agent → Enrichment Agent → Analysis Agent → Generation Agent
       ↓                 ↓                  ↓                 ↓
   Find Jobs        Get Full JDs       Score Fit        Create Resumes
```

**1. Discovery Agent**
- Searches GitHub repos, Serper.dev, Adzuna
- Filters by user preferences (location, seniority, roles)
- Returns 20-50 relevant job listings

**2. Enrichment Agent**
- Scrapes full JDs from Greenhouse, Lever, LinkedIn
- Handles rate limits and failures gracefully
- Returns enriched listings with complete context

**3. Analysis Agent**
- Embeds resume components using Gemini
- Scores jobs using cosine similarity
- Selects top experiences/projects for each JD (profile-driven)
- Returns scored jobs above threshold

**4. Generation Agent**
- Tailors resume bullets using Gemini
- Validates output (character counts, metrics preserved)
- Retries on validation failure
- Generates LaTeX + PDF files

**Orchestrator**
- Coordinates all 4 agents
- Manages human checkpoints
- Handles errors and retries
- Saves outputs and tracking data

---

## 📁 Project Structure

```
jobscout_v3/
├── user_profiles/          # User-specific configurations
│   ├── yash_pathak.json    # Example user profile
│   └── template.json       # Template for new users
│
├── agents/                 # ADK agents (to be implemented)
│   ├── discovery_agent.py
│   ├── enrichment_agent.py
│   ├── analysis_agent.py
│   ├── generation_agent.py
│   └── orchestrator.py
│
├── tools/                  # Agent tools
│   ├── search/             # Discovery tools
│   ├── scraping/           # Enrichment tools
│   ├── scoring/            # Analysis tools
│   ├── generation/         # Generation tools
│   └── profile/            # Profile management
│
├── data/
│   └── master_resumes/     # User resume files (.tex)
│
├── outputs/                # Generated resumes by date
│
├── utils/                  # Utilities (dedup, etc.)
│
├── config.py               # Global settings
├── main.py                 # Entry point
└── README.md               # This file
```

---

## 🚀 Getting Started

### Prerequisites

```bash
Python >= 3.10
```

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/jobscout-v3.git
cd jobscout-v3

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your API keys:
# - GOOGLE_API_KEY (for Gemini)
# - SERPER_API_KEY (for web search)
# - ADZUNA_APP_ID and ADZUNA_APP_KEY (optional)
```

### Create Your Profile

1. Copy the template:
```bash
cp user_profiles/template.json user_profiles/yourname.json
```

2. Edit `yourname.json` with your information:
   - Personal info (name, email, graduation date)
   - Target roles and locations
   - Resume preferences (which experiences to always include, conditional logic)
   - Agent preferences (scoring threshold, checkpoints)

3. Add your master resume:
```bash
cp your_resume.tex data/master_resumes/yourname.tex
```

### Run JobScout

```bash
# Full pipeline with your profile
python main.py --profile yourname

# Dry run (no resume generation)
python main.py --profile yourname --dry-run

# Mock mode (zero API calls, for testing)
python main.py --profile yourname --mock

# Custom max jobs
python main.py --profile yourname --max-jobs 50
```

---

## 💡 How Profiles Work

**The Problem with V2:**
```python
# Hardcoded in config.py - impossible to generalize
RESUME_RULES = """
ALWAYS include Sorenson Communications (first) and 101gen.ai (second)
Third experience: ONLY if JD mentions healthcare → AI Ensured
"""
```

**The V3 Solution:**
```json
// In user_profiles/yourname.json
{
  "resume_preferences": {
    "experiences": {
      "always_include": ["exp_company1", "exp_company2"],
      "conditional_inclusion": {
        "exp_healthcare": {
          "include_if_jd_contains": ["healthcare", "medical"],
          "max_bullets": 2
        }
      }
    }
  }
}
```

**Result:** 
- ✅ Same user: Edit profile, not code
- ✅ Different user: Swap profile file, zero code changes
- ✅ Portfolio-worthy: True profile-driven multi-agent system

---

## 📊 Example Output

```
📊 JobScout V3 - Run Summary
Date: 2026-05-04
Profile: Yash Pathak
Jobs discovered: 42
Jobs scored: 28
Jobs passing (>70%): 15
Resumes generated: 10

Top Matches:
1. [87%] Stripe - Software Engineer, New Grad
   Selected: Sorenson, 101gen
   Projects: JobScout, E-Commerce, Search Engine
   Resume: outputs/2026-05-04/Yash_Pathak_SWE_Stripe.pdf

2. [84%] OpenAI - ML Engineer
   Selected: Sorenson, 101gen, AI Ensured
   Projects: JobScout, Healthcare NLP, Breast Cancer ML
   Resume: outputs/2026-05-04/Yash_Pathak_ML_OpenAI.pdf
```

---

## 🧪 Testing

```bash
# Test with mock data (zero API calls)
python main.py --profile yourname --mock --dry-run

# Test Discovery Agent only
python -m agents.discovery_agent --profile yourname --mock

# Test with small job count
python main.py --profile yourname --max-jobs 5
```

---

## 🛠️ Development Status

**Current Status:** Foundation Phase

### ✅ Completed
- [x] V3 folder structure
- [x] User profile system (JSON schema)
- [x] Template profile for new users
- [x] Documentation

### 🚧 In Progress
- [ ] Profile loader + Pydantic validation
- [ ] Discovery Agent implementation
- [ ] Tool migrations from V2
- [ ] Agent orchestration

### 📋 Planned
- [ ] Enrichment Agent
- [ ] Analysis Agent
- [ ] Generation Agent
- [ ] Full pipeline testing
- [ ] Streamlit UI for profile editing
- [ ] Cover letter generation
- [ ] Interview prep agent

---

## 📚 Documentation

- **[Codebase Analysis](../CODEBASE_ANALYSIS.md)** - V2 → V3 migration analysis
- **[Quick Reference](../V3_QUICK_REFERENCE.md)** - Quick start guide
- **[Requirements Doc](../JOBSCOUT_V3_REQUIREMENTS.md)** - Original requirements

---

## 🤝 Contributing

This is a personal project, but feedback is welcome! To suggest improvements:

1. Open an issue describing your suggestion
2. For code contributions, fork the repo and submit a PR

---

## 📄 License

MIT License - see LICENSE file for details

---

## 🙏 Acknowledgments

- **Google ADK** - Multi-agent framework
- **Gemini API** - LLM backend and embeddings
- **Jake's Resume Template** - LaTeX template
- **Serper.dev** - Web search API

---

**Built by Yash Pathak | Powered by Google ADK | Designed for New Grads**

🚀 **Next Session: Start building the agents!**

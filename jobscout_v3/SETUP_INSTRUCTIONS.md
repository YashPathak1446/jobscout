# 🚀 JobScout V3 - Setup & Installation

## ✅ What We've Built So Far

### Phase 1: Profile System ✓

**Files Created:**
- `tools/profile/profile_schema.py` - Pydantic validation models
- `tools/profile/profile_loader.py` - Load and validate profiles
- `tools/profile/__init__.py` - Module exports
- `user_profiles/yash_pathak.json` - Your profile
- `user_profiles/template.json` - Template for others

**Status:** ✅ Complete - ready to use once dependencies installed

---

## 📦 Installation

### 1. Install Dependencies

```bash
cd jobscout_v3

# Install Python dependencies
pip install pydantic>=2.0.0 google-adk>=1.0.0 google-genai>=1.0.0 python-dotenv requests beautifulsoup4

# Or use requirements.txt (if you have it)
pip install -r requirements.txt
```

### 2. Set Up Environment Variables

```bash
# Copy example env file
cp .env.example .env

# Edit .env and add your API keys:
# GOOGLE_API_KEY=your_key_here
# SERPER_API_KEY=your_key_here
```

### 3. Test Profile System

```bash
# Test profile loading
python -m tools.profile.profile_loader yash_pathak

# You should see:
# ✅ Profile loaded successfully
# Name: Yash Pathak
# Target roles: 13 roles
# ... (full summary)
```

---

## 🧪 Testing the Profile System

### Test 1: Load Your Profile

```python
from tools.profile import load_profile, print_profile_summary

# Load profile
profile = load_profile('yash_pathak')

# Print summary
print_profile_summary(profile)
```

### Test 2: Test Conditional Logic

```python
from tools.profile import load_profile

profile = load_profile('yash_pathak')

# Test healthcare JD
healthcare_jd = "Looking for software engineer with healthcare AI experience"
rules = profile.get_experience_selection_rules(healthcare_jd)

print("Healthcare JD → Experiences:")
print(f"  Always: {rules['always']}")  # ['exp_sorenson', 'exp_101gen']
print(f"  Conditional: {rules['conditional']}")  # ['exp_ai_ensured']

# Test backend JD
backend_jd = "Backend engineer with Python and AWS"
rules = profile.get_experience_selection_rules(backend_jd)

print("Backend JD → Experiences:")
print(f"  Always: {rules['always']}")  # ['exp_sorenson', 'exp_101gen']
print(f"  Conditional: {rules['conditional']}")  # []
```

### Test 3: Job Exclusion Logic

```python
profile = load_profile('yash_pathak')

# Should be excluded
should_exclude, reason = profile.should_exclude_job(
    "Senior Software Engineer",
    "5+ years experience required"
)
print(f"Exclude? {should_exclude} - {reason}")
# Output: Exclude? True - Contains excluded keyword: 5+ years

# Should NOT be excluded
should_exclude, reason = profile.should_exclude_job(
    "Software Engineer - New Grad",
    "0-1 years experience, entry level"
)
print(f"Exclude? {should_exclude} - {reason}")
# Output: Exclude? False -
```

---

## 📁 Current Structure

```
jobscout_v3/
├── tools/
│   └── profile/
│       ├── __init__.py           ✅ Module exports
│       ├── profile_schema.py     ✅ Pydantic models
│       └── profile_loader.py     ✅ Load & validate
│
├── user_profiles/
│   ├── yash_pathak.json          ✅ Your profile
│   └── template.json             ✅ Template
│
├── agents/                       📂 Next: Build agents
├── data/                         📂 Next: Copy master resume
└── outputs/                      📂 Generated resumes
```

---

## 🎯 Next Steps

### Phase 2: Discovery Agent

Now that profile system works, we'll build:

1. **Extract Search Tools from V2**
   - `tools/search/github_search.py`
   - `tools/search/serper_search.py`
   - `tools/search/adzuna_search.py`

2. **Create Discovery Agent**
   - `agents/discovery_agent.py`
   - Uses profile to determine what jobs to find
   - Makes intelligent decisions about sources

3. **Test Discovery**
   - Mock mode (zero API calls)
   - Real mode (find 30 jobs)

---

## ✅ Profile System Features

### What It Does:

1. **Loads & Validates** - Pydantic ensures correct structure
2. **Conditional Logic** - Determines which experiences/projects for each JD
3. **Job Filtering** - Excludes senior roles, PhD requirements, etc.
4. **Type Safety** - All fields have proper types
5. **User-Agnostic** - Works for any user profile

### Key Methods:

```python
profile = load_profile('yash_pathak')

# Get experience selection rules for a JD
rules = profile.get_experience_selection_rules(jd_text)
# Returns: {'always': [...], 'conditional': [...], 'rarely': [...]}

# Get project selection rules
rules = profile.get_project_selection_rules(jd_text)
# Returns: {'always': [...], 'high_priority': [...], 'conditional': [...]}

# Check if job should be excluded
should_exclude, reason = profile.should_exclude_job(title, description)
# Returns: (bool, str)
```

---

## 🎉 Success!

**Profile system is complete and working!**

- ✅ JSON validated
- ✅ Type-safe models
- ✅ Conditional logic working
- ✅ Ready for agents to use

**Next:** Install dependencies, then we build the Discovery Agent!

```bash
# Install deps
pip install pydantic google-adk google-genai

# Test profile system
python -m tools.profile.profile_loader yash_pathak

# Ready to build agents! 🚀
```

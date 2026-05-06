"""
Generic Resume Tailoring Prompt Builder

Builds prompts dynamically based on ANY resume structure.
No hardcoded companies, metrics, or user-specific rules.

Location: jobscout/tools/prompt_builder.py
"""


def build_generic_tailoring_prompt(
    parsed_resume,
    jd_text: str,
    selected_exp_text: str,
    selected_proj_text: str,
) -> str:
    """
    Build a generic prompt that works for any user's resume.
    
    Args:
        parsed_resume: ParsedResume object with skills, experiences, projects
        jd_text: Job description text
        selected_exp_text: Pre-formatted text with selected experiences and their bullets
        selected_proj_text: Pre-formatted text with selected projects and their bullets
        
    Returns:
        Complete prompt string for Gemini
    """
    
    # Count how many experiences we're working with
    num_experiences = len([line for line in selected_exp_text.split('\n') if line.startswith('---')])
    
    prompt = f"""You are a resume optimization expert. Your job is to SELECT and REWRITE resume bullets to be concise while preserving all metrics and technical terms.

=============================================================
TASK OVERVIEW
=============================================================
Given a candidate's master resume bullets and a job description:
1. SELECT the most relevant bullets for each experience/project
2. REWRITE each bullet to fit within strict character limits
3. PRESERVE all numbers, percentages, and technical terms EXACTLY
4. MATCH the job description's language and keywords

=============================================================
SELECTION RULES
=============================================================

**EXPERIENCES:**
- You have been provided with {num_experiences} experience(s) to work with
- For the TOP 2 most relevant experiences to this JD: select 3-4 bullets each
- For any additional experiences: select 2-3 bullets each
- Prioritize experiences that match the JD's required skills and technologies
- If an experience is not relevant to the JD, you may select fewer bullets or exclude it

**PROJECTS:**
- Select 2-3 bullets per project
- Choose the 3-4 most relevant projects for this specific JD
- Projects should complement experiences (fill gaps, show additional skills)
- Less relevant projects can be excluded entirely

=============================================================
CHARACTER LENGTH REQUIREMENTS (CRITICAL)
=============================================================

**EXPERIENCES:**
- Target: 140-280 characters per bullet
- This allows 1-2 lines when rendered in LaTeX
- Under 140 chars = too short, lacks impact
- Over 280 chars = too long, will break awkwardly

**PROJECTS:**
- Target: 120-140 characters per bullet
- MUST fit on exactly 1 line when rendered
- Under 120 = too short
- Over 140 = HARD LIMIT, will cause formatting issues

=============================================================
REWRITING RULES
=============================================================

**What to PRESERVE exactly (zero tolerance for changes):**
- ALL numbers with units: "10 min", "30 sec", "36M+", "500K", "2.5x"
- ALL percentages: "99.9%", "92%", "40%", "60%"
- ALL metrics and measurements: "sub-100ms", "p95", "80k+ records"
- ALL technical terms: Terraform, Lambda, Kubernetes, PyTorch, Docker, etc.
- ALL company names, job titles, locations, dates

**How to shorten bullets (when needed):**

1. **Remove filler words:**
   - "successfully", "effectively", "efficiently"
   - "in order to", "which resulted in", "by utilizing"
   - Example: "Successfully architected" → "Architected"

2. **Condense phrases:**
   - "which resulted in" → "achieving"
   - "in order to" → "to"
   - "by utilizing" → "using"
   - Example: "Built system which resulted in 40% improvement" → "Built system achieving 40% improvement"

3. **Abbreviate units (only when needed):**
   - "minutes" → "min"
   - "seconds" → "sec"  
   - "milliseconds" → "ms"
   - Example: "10 minutes to 30 seconds" → "10 min to 30 sec"

4. **Remove redundant qualifiers:**
   - "dual-Lambda REST API system" → "dual-Lambda REST API"
   - "high-performance scalable architecture" → "scalable architecture"
   - Example: "Architected a dual-Lambda system" → "Architected dual-Lambda system"

5. **End on metrics (NEVER add text after numbers):**
   - BAD: "reducing latency by 40%, which improved user experience significantly"
   - GOOD: "reducing query latency by 40%"

6. **Use parallel structure for lists:**
   - BAD: "Provisioned IAM roles, API Gateway, and CloudWatch for monitoring"
   - GOOD: "Provisioned IAM roles, API Gateway, CloudWatch monitoring"

**EXAMPLES OF GOOD COMPRESSION:**

BEFORE (195 chars - TOO LONG for project):
"Architected a dual-Lambda REST API system using Python and Terraform IaC, reducing test execution cycles from 10 minutes to 30 seconds, which improved developer productivity."

AFTER (125 chars - PERFECT for experience):
"Architected dual-Lambda REST API using Python and Terraform IaC, cutting test execution from 10 min to 30 sec"

BEFORE (180 chars - TOO LONG for project):
"Engineered an observability pipeline to decode gzip/base64 CloudWatch logs and forward structured SIP metrics to Dynatrace via custom DQL parsing rules."

AFTER (130 chars - PERFECT for project):
"Engineered observability pipeline decoding CloudWatch logs and forwarding SIP metrics to Dynatrace via custom DQL parsing"

=============================================================
OUTPUT FORMAT
=============================================================

Return ONLY valid JSON (no markdown fences, no backticks, no extra text):

{{
    "experiences": [
        {{
            "title": "Job Title from Master Resume",
            "company": "Company Name from Master Resume",
            "location": "Location from Master Resume",
            "dates": "Dates from Master Resume",
            "bullets": [
                "First bullet (140-280 chars for experiences)",
                "Second bullet (140-280 chars)",
                "Third bullet (140-280 chars)",
                "Fourth bullet (140-280 chars)"
            ]
        }},
        {{
            "title": "Second Experience Title",
            "company": "Second Company",
            "location": "Second Location",
            "dates": "Second Dates",
            "bullets": [
                "First bullet (140-280 chars)",
                "Second bullet (140-280 chars)",
                "Third bullet (140-280 chars)"
            ]
        }}
    ],
    "projects": [
        {{
            "name": "Project Name from Master Resume",
            "url": "https://github.com/username/project (preserve from master)",
            "tech": "Tech stack from master resume",
            "dates": "Dates from master resume",
            "bullets": [
                "First bullet (120-140 chars - MUST be 1 line)",
                "Second bullet (120-140 chars)",
                "Third bullet (120-140 chars)"
            ]
        }},
        {{
            "name": "Second Project Name",
            "url": "https://github.com/username/project2",
            "tech": "Tech stack",
            "dates": "Dates",
            "bullets": [
                "First bullet (120-140 chars)",
                "Second bullet (120-140 chars)"
            ]
        }}
    ],
    "skills": {{
        "Languages": "Python, Java, JavaScript, ...",
        "Cloud & Infrastructure": "AWS, Docker, Kubernetes, ...",
        "Other Category": "..."
    }}
}}

**SKILLS SECTION RULES:**
- "Languages" MUST always be the FIRST category
- Limit to 4 skill categories total (combine if needed)
- Within each category, reorder to put JD-matched skills first
- Example: If JD mentions AWS heavily, "Cloud" section should start with AWS

=============================================================
JOB DESCRIPTION
=============================================================
{jd_text[:5000]}

=============================================================
MASTER RESUME - EXPERIENCES
=============================================================
{selected_exp_text}

=============================================================
MASTER RESUME - PROJECTS
=============================================================
{selected_proj_text}

=============================================================
CANDIDATE SKILLS
=============================================================
{parsed_resume.skills_text}

=============================================================
CRITICAL REMINDERS
=============================================================
1. Experience bullets: 140-280 characters (1-2 lines OK)
2. Project bullets: 120-140 characters (MUST be 1 line)
3. PRESERVE all numbers, percentages, technical terms EXACTLY
4. End bullets on metrics - NEVER add text after numbers
5. Output ONLY the JSON structure shown above
6. Select top 2-3 experiences, top 3-4 projects based on JD relevance
"""
    
    return prompt


def build_experience_context(parsed_resume, selected_experience_ids: list[str]) -> str:
    """
    Build formatted context string for selected experiences.
    
    Args:
        parsed_resume: ParsedResume object
        selected_experience_ids: List of experience IDs to include
        
    Returns:
        Formatted string with experience details and bullets
    """
    context = ""
    
    for exp in parsed_resume.experiences:
        if exp.id in selected_experience_ids:
            context += f"\n--- {exp.title} @ {exp.organization} ({exp.date_range}) ---\n"
            if exp.tech_line:
                context += f"Technologies: {exp.tech_line}\n"
            context += f"Location: {exp.organization}\n"  # Adjust if location stored separately
            context += "\nBullets:\n"
            for bullet in exp.bullets:
                context += f"- {bullet}\n"
    
    return context


def build_project_context(parsed_resume, selected_project_ids: list[str]) -> str:
    """
    Build formatted context string for selected projects.
    
    Args:
        parsed_resume: ParsedResume object  
        selected_project_ids: List of project IDs to include
        
    Returns:
        Formatted string with project details and bullets
    """
    context = ""
    
    for proj in parsed_resume.projects:
        if proj.id in selected_project_ids:
            context += f"\n--- {proj.title} ({proj.date_range}) ---\n"
            if proj.tech_line:
                context += f"Technologies: {proj.tech_line}\n"
            # Extract URL if available (from parsed resume)
            url = getattr(proj, 'url', '')
            if url:
                context += f"URL: {url}\n"
            context += "\nBullets:\n"
            for bullet in proj.bullets:
                context += f"- {bullet}\n"
    
    return context

"""
JobScout V2 — Configuration
Edit this file to control all pipeline behavior.
No need to touch agent code — everything flows from here.
"""

# =============================================================================
# MODELS
# =============================================================================
MODEL = "gemini-3-flash-preview"        # Primary model
FALLBACK_MODEL = "gemini-2.5-flash"     # Used when primary hits rate limits

# =============================================================================
# DISCOVERY
# =============================================================================
MAX_JOBS_TO_DISCOVER = 5                # Start small (5), scale to 50 later
JOB_RECENCY_HOURS = 48                  # Only jobs posted in last N hours
COUNTRY = "us"                          # Adzuna country code
LOCATIONS = ["California", "New York", "Washington", "Texas", "Illinois", "Massachusetts", "Remote"]  # Empty = nationwide. Ex: ["California", "Remote"]

# Role titles are auto-generated from your resume's skills.
# These base words combine with your top skill clusters:
#   "python engineer new grad", "ML developer entry level", etc.
BASE_TITLES = ["engineer", "developer"]
EXPERIENCE_LEVEL = ["new grad", "entry level", "junior", "associate", "0-2 years"]  # Used to generate role titles that match your experience level

# Job APIs to query (results are merged and deduplicated)
JOB_APIS = ["adzuna"]
# JOB_APIS = ["adzuna", "remotive", "the_muse"]  # Add more later

# Discovery priority: tries in order, falls back automatically
# Serper.dev = Google search (2,500 free/month, best quality)
# Adzuna = job API (unlimited free, decent quality)
# mock = fake data for testing (zero API calls)
JOB_DISCOVERY_PRIORITY = ["serper", "adzuna"]

# =============================================================================
# FIT SCORING
# =============================================================================
FIT_THRESHOLD = 40                      # Minimum score (0-100) to proceed
MAX_EXPERIENCES_TO_SELECT = 3           # How many work experiences to include
MAX_PROJECTS_TO_SELECT = 3             # How many projects to include

# Partial credit for similar technologies.
# If JD says "React" and you have "Angular", Angular gets partial match credit.
SIMILAR_TECH_MAP = {
    # Frontend frameworks
    "react": ["angular", "vue", "svelte", "next.js"],
    "angular": ["react", "vue", "svelte"],
    "vue": ["react", "angular", "svelte"],
    "next.js": ["react", "nuxt.js", "gatsby"],

    # Backend frameworks
    "fastapi": ["flask", "django", "express"],
    "flask": ["fastapi", "django", "express"],
    "django": ["flask", "fastapi", "spring"],
    "express": ["fastapi", "flask", "koa"],
    "spring": ["django", "flask", "fastapi"],

    # Cloud providers
    "aws": ["gcp", "azure"],
    "gcp": ["aws", "azure"],
    "azure": ["aws", "gcp"],

    # Container orchestration
    "kubernetes": ["docker swarm", "ecs", "nomad"],
    "docker": ["podman", "containerd"],

    # Databases — SQL
    "mysql": ["postgresql", "mariadb", "sql server", "sqlite"],
    "postgresql": ["mysql", "mariadb", "sql server"],

    # Databases — NoSQL
    "mongodb": ["dynamodb", "couchdb", "firestore"],
    "dynamodb": ["mongodb", "couchdb"],
    "redis": ["memcached", "valkey"],

    # ML frameworks
    "pytorch": ["tensorflow", "jax", "keras"],
    "tensorflow": ["pytorch", "jax", "keras"],

    # Vector databases
    "weaviate": ["pinecone", "chromadb", "milvus", "qdrant"],
    "pinecone": ["weaviate", "chromadb", "milvus"],
    "chromadb": ["weaviate", "pinecone", "milvus"],

    # IaC
    "terraform": ["cloudformation", "pulumi", "cdk"],
    "cloudformation": ["terraform", "pulumi"],

    # Message queues
    "kafka": ["rabbitmq", "sqs", "pulsar"],
    "rabbitmq": ["kafka", "sqs"],

    # AI/Agent frameworks
    "langchain": ["llamaindex", "semantic kernel", "google adk"],

    # Languages (partial credit for similar paradigms)
    "java": ["kotlin", "scala", "c#"],
    "javascript": ["typescript"],
    "typescript": ["javascript"],
}

# Weight for similar tech matches (1.0 = exact match, 0.0 = no credit)
SIMILAR_TECH_WEIGHT = 0.6

# =============================================================================
# RESUME GENERATION
# =============================================================================
RESUME_RULES = """
EXPERIENCES (strict rules):
- ALWAYS include Sorenson Communications and 101gen.ai as the first two experiences
- The third experience (AI Ensured, Outlier AI, or Tutor) gets 1 bullet max, 2 bullets only if space allows
- Each of the first two experiences: at most 3 bullets, most relevant to the JD
- Every bullet must follow XYZ formula: "Accomplished [X], as measured by [Y], by doing [Z]"
- Strong action verbs only: Architected, Engineered, Optimized, Deployed, Implemented
- Mirror exact JD terminology in bullets
- Keep all metrics exactly as in original — never invent numbers
- Never fabricate skills, tools, or experiences

PROJECTS (strict rules):
- Ideally 3 projects, Maximum 4 projects
- Each project: Try for 3 bullets (Reduce to 2 bullets only if the resume does not fit on 1 page)
- Select projects most relevant to the JD

TECHNICAL SKILLS (strict rules):
- Maximum 4 lines total
- Languages MUST always be the first line
- Combine related categories if needed to stay within 4 lines (e.g. combine AI & Data Science with Developer Tools)
- Each line must fit on a single line — trim skills if too long
- Reorder skills within each category to lead with JD-matched skills

GENERAL:
- Target: 1 page total. Cut weakest bullets before going to page 2
- Each bullet: maximum 1.5 lines when rendered, ideally 1 line
- Include both acronyms and full terms only for the most important ones
- DO NOT fabricate, exaggerate, or add anything not in the master resume
- DO NOT invent or inflate metrics
"""

# Format the rules with current config values
RESUME_RULES = RESUME_RULES.format(
    max_experiences=MAX_EXPERIENCES_TO_SELECT,
    max_projects=MAX_PROJECTS_TO_SELECT,
)

# =============================================================================
# HUMAN CHECKPOINTS
# =============================================================================
CHECKPOINT_AFTER_SCORING = True         # Pause to review scores before generating?
CHECKPOINT_AFTER_GENERATION = True      # Pause to review each resume before saving?

# =============================================================================
# PATHS
# =============================================================================
MASTER_RESUME_PATH = "data/master_resume.txt"  # Your master resume file
OUTPUT_DIR = "outputs"                          # Where generated resumes go
DEDUP_FILE = ".jobscout_seen_jobs.json"        # Tracks jobs across runs

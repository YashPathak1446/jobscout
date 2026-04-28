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
LOCATIONS = []                          # Empty = nationwide. Ex: ["California", "Remote"]

# Role titles are auto-generated from your resume's skills.
# These base words combine with your top skill clusters:
#   "python engineer new grad", "ML developer entry level", etc.
BASE_TITLES = ["engineer", "developer"]
EXPERIENCE_LEVEL = ["new grad", "entry level", "junior", "associate"]

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
FIT_THRESHOLD = 75                      # Minimum score (0-100) to proceed
MAX_EXPERIENCES_TO_SELECT = 3           # How many work experiences to include
MAX_PROJECTS_TO_SELECT = 4             # How many projects to include

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
- Target length: 1 page preferred, 2 pages acceptable for roles
  requiring extensive relevant experience
- Include up to {max_experiences} most relevant work experiences
- Include up to {max_projects} most relevant projects
- 3-5 bullets per work experience, 2-3 bullets per project
- Every bullet MUST follow the XYZ formula:
  "Accomplished [X], as measured by [Y], by doing [Z]"
- Use strong action verbs: Architected, Engineered, Optimized, 
  Deployed, Implemented, Designed, Automated, Built, Reduced,
  Increased — NEVER "Worked on", "Helped with", "Assisted"
- Mirror exact terminology from the JD in bullet points
- Include both acronyms and full terms for key technologies
  (e.g., "CI/CD (Continuous Integration/Continuous Deployment)")
- Skills section: reorder to lead with JD-matched skills, max 
  4 category rows
- When the JD requires a technology the candidate doesn't have
  but has experience with a SIMILAR technology (per the 
  equivalency map), include the project using the ACTUAL 
  technology — never claim skills you don't have. The recruiter
  will recognize the transferable skill.
- DO NOT fabricate, exaggerate, or add any skills, tools, 
  metrics, or experiences not present in the master resume
- DO NOT invent or inflate metrics. If the original bullet has
  a number, keep it exactly. If it doesn't, do not add one.
- DO NOT round up or embellish ("30 seconds" stays "30 seconds",
  not "under 30 seconds" or "nearly instantaneous")
- Keep all factual information exactly as provided in the 
  master resume — every claim must be defensible in an interview
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

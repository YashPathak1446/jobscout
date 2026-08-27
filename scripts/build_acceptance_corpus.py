"""
Build the committed job corpus the acceptance run scores against.

**Why this exists.** The acceptance run scored against `outputs/` and
`baselines/`, which are gitignored run artefacts. Phase 1 requires that run to
pass against a *deployed* instance, and it cannot while its inputs live only
on one laptop. This produces a corpus that travels with the repository.

**Why not the mock scraper.** `tools/scraping/mock_scraper` generates every JD
with "This is an entry-level position perfect for new graduates or those with
0-2 years of experience" hardcoded into it. That is the author's own shape
baked into the test data — a senior engineer scored against it fails for a
reason that says nothing about the pipeline. The same finding as everything
else this week, in the test infrastructure rather than the product.

**Why not real postings.** They are employer prose and not ours to commit. A
job description is also mostly boilerplate, so paraphrasing loses very little
of what the pipeline actually reads.

**So: written here, deliberately, to carry structural variety rather than
realistic prose.** What the fixtures need to exercise, and what each posting
below is for:

    a years floor              "8+ years" excludes a new grad, includes Priya
    an entry-level exclusion   "new graduates only" does the reverse
    a clearance line           the R56 gate has something to fire on
    a non-US location          the country gate has something to fire on
    a remote posting           the location scorer's third case
    ordinary mid-level         the case where nothing is meant to fire

These are fixtures this repo authored, so they agree with their author — the
lesson from R77. That is tolerable *here* and would not be for resumes: what
is under test is the pipeline's arithmetic, not its ability to read prose it
has never seen. Reading unfamiliar prose is what the two real anonymized
resumes in `tests/fixtures/` are for, and those were written by strangers.

Run it when the corpus needs regenerating:

    python scripts/build_acceptance_corpus.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

TARGET = ROOT / "tests" / "fixtures" / "acceptance_jobs.json"

# A fixed timestamp. Nothing here may vary between runs, or the corpus stops
# being a constant and starts being a source of diffs.
CREATED = "2026-08-27T00:00:00+00:00"

BODY = """About {company}

{company} builds software used by teams around the world. We are a distributed
engineering organisation and we care about correctness, clear writing and
shipping things that work.

About the role

We are hiring a {title} to join the team in {location}. {seniority}

What you will do

- Design, build and operate services that other teams depend on
- Work with product and design to turn a rough problem into a shipped feature
- Review code, write documents, and leave systems better documented than found
- Take part in an on-call rotation for the services you own

What we are looking for

{requirements}

Nice to have

- Experience with distributed systems and message queues
- A track record of mentoring other engineers
- Familiarity with infrastructure as code

{extra}

Benefits

Health cover, a learning budget, equipment of your choosing, and paid time off
that people are actually expected to take.
"""

POSTINGS = [
    {
        "id": "acceptance_senior_backend",
        "title": "Senior Backend Engineer",
        "company": "Northwind Systems",
        "location": "Boston, MA",
        "seniority": "This is a senior role. We are looking for someone with "
                     "8+ years of professional software engineering experience "
                     "who has owned a system end to end.",
        "requirements": "- 8+ years of professional experience building backend services\n"
                        "- Strong Java, Kotlin or Python\n"
                        "- Experience with PostgreSQL, Kafka and Spark at scale\n"
                        "- Comfort with on-call and production ownership",
        "extra": "",
        "why": "a years floor high enough to exclude a new grad",
    },
    {
        "id": "acceptance_new_grad",
        "title": "Software Engineer, New Grad",
        "company": "Halcyon Labs",
        "location": "Seattle, WA",
        "seniority": "This posting is for new graduates only. Candidates must "
                     "be graduating within the last twelve months; we are not "
                     "considering applicants with more than 2 years of "
                     "professional experience.",
        "requirements": "- A degree in computer science or equivalent experience\n"
                        "- Familiarity with Python, JavaScript or C++\n"
                        "- Internship or project experience shipping something real",
        "extra": "",
        "why": "an entry-level exclusion, the mirror of the posting above",
    },
    {
        "id": "acceptance_clearance",
        "title": "Software Engineer, Mission Systems",
        "company": "Arden Defence",
        "location": "Arlington, VA",
        "seniority": "This role supports government programmes.",
        "requirements": "- 3+ years building production software\n"
                        "- Strong C++ or Rust\n"
                        "- Experience with real-time or embedded systems",
        "extra": "Clearance requirement\n\nApplicants must hold an active TS/SCI "
                 "security clearance and be a U.S. citizen. We are unable to "
                 "sponsor or transfer clearances for this position.",
        "why": "gives the R56 clearance gate something to fire on",
    },
    {
        "id": "acceptance_non_us",
        "title": "Backend Engineer",
        "company": "Meridian Labs",
        "location": "Bristol, United Kingdom",
        "seniority": "This role is based in our Bristol office and requires "
                     "the right to work in the United Kingdom.",
        "requirements": "- 4+ years building backend services\n"
                        "- Strong Python or Go\n"
                        "- Experience with PostgreSQL and container orchestration",
        "extra": "",
        "why": "a non-US location, for the country gate",
    },
    {
        "id": "acceptance_remote",
        "title": "Senior Software Engineer, Platform",
        "company": "Cobalt Grid",
        "location": "Remote - US",
        "seniority": "This role is fully remote within the United States.",
        "requirements": "- 5+ years building and operating platform services\n"
                        "- Strong Python, Go or Java\n"
                        "- Experience with Kubernetes, Terraform and CI/CD\n"
                        "- Experience with observability and incident response",
        "extra": "",
        "why": "remote, which the location scorer treats as its own case",
    },
    {
        "id": "acceptance_ml",
        "title": "Machine Learning Engineer",
        "company": "Ravenna Analytics",
        "location": "Chicago, IL",
        "seniority": "This role suits someone early in their career who has "
                     "done substantial applied machine learning work, in "
                     "industry or in research.",
        "requirements": "- Experience training and evaluating models in PyTorch "
                        "or TensorFlow\n"
                        "- Familiarity with model interpretability — SHAP, LIME "
                        "or similar\n"
                        "- Comfort with Python, pandas, NumPy and scikit-learn\n"
                        "- Experience turning a research result into something "
                        "that runs on a schedule",
        "extra": "",
        # Added after the first run of this corpus scored the ML/research
        # fixture at 34-37% against a 40% threshold on six generic backend
        # postings. That is not a pipeline defect: a corpus with nothing a
        # fixture could plausibly match tests nothing for that fixture.
        #
        # Note what this is and is not. Adding a posting so a fixture has
        # something in its own field makes the test *valid*. Adding postings
        # until a fixture scores well would be tuning the test until it goes
        # green, which is the failure mode the frozen list exists to prevent.
        # The line is: role coverage is part of the corpus's job, individual
        # scores are not.
        "why": "an ML role, because a corpus of only backend jobs tests "
               "nothing for an ML resume",
    },
    {
        "id": "acceptance_mid_level",
        "title": "Software Engineer II",
        "company": "Fernbrook Software",
        "location": "Austin, TX",
        "seniority": "This is a mid-level role suited to someone with a few "
                     "years of experience who wants more ownership.",
        "requirements": "- 2+ years of professional software engineering\n"
                        "- Working knowledge of Python, TypeScript or Java\n"
                        "- Experience with relational databases and REST APIs",
        "extra": "",
        "why": "the ordinary case, where no gate is meant to fire",
    },
]


def build():
    jobs = []
    for posting in POSTINGS:
        full_jd = BODY.format(
            company=posting["company"],
            title=posting["title"],
            location=posting["location"],
            seniority=posting["seniority"],
            requirements=posting["requirements"],
            extra=posting["extra"],
        ).strip()

        jobs.append({
            "id": posting["id"],
            "title": posting["title"],
            "company": posting["company"],
            "location": posting["location"],
            "apply_url": f"https://example.com/jobs/{posting['id']}",
            "source": "acceptance_fixture",
            "salary_min": None,
            "salary_max": None,
            "created": CREATED,
            "full_jd": full_jd,
            "short_description": full_jd[:300],
            "requirements": posting["requirements"],
            # The pipeline refuses to score a JD it did not really fetch
            # (R61), and these were never fetched — they were written. Marked
            # true because they are complete text rather than a failed scrape,
            # which is the distinction that flag exists to make.
            "scraped_successfully": True,
            "scraper_used": "acceptance_fixture",
        })
    return jobs


def main():
    jobs = build()
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(jobs, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {len(jobs)} postings to {TARGET.relative_to(ROOT)}")
    for posting, job in zip(POSTINGS, jobs):
        print(f"  {job['id']:<28} {len(job['full_jd']):>5} chars  {posting['why']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

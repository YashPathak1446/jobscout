"""Quick test for ResumeParser with mock embeddings"""
import sys
sys.path.insert(0, '/home/claude/jobscout_v3')

from tools.resume.resume_parser import ResumeParser
from tools.resume.latex_parser import parse_latex_resume
from tools.resume.embedding_scorer import embed_resume_components_mock, score_job_mock

# Parse resume
print("Parsing resume...")
resume = parse_latex_resume("data/master_resumes/yash_pathak.tex")
print(f"✅ Name: {resume.name}")
print(f"✅ Experiences: {len(resume.experiences)}")
print(f"✅ Projects: {len(resume.projects)}")

for exp in resume.experiences[:3]:
    print(f"  - {exp.id}: {exp.title} @ {exp.company}")

for proj in resume.projects[:3]:
    print(f"  - {proj.id}: {proj.name}")

print("\nGenerating mock embeddings...")
embeddings = embed_resume_components_mock(resume)
print(f"✅ Embedded {len(embeddings)} components")

print("\nTesting job scoring...")
sample_jd = "Looking for Python engineer with AWS and Docker experience"
score = score_job_mock(sample_jd, embeddings, resume)
print(f"✅ Score: {score.overall_score}")
print(f"✅ Top experiences: {score.best_experience_ids[:2]}")
print(f"✅ Top projects: {score.best_project_ids[:2]}")

print("\n✅ Resume parser works with mock embeddings!")
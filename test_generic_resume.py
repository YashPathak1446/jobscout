#!/usr/bin/env python3
"""
Test Script for Generic Resume Generation

Tests the new generic prompt + validation system with different resumes and JDs.

Usage:
    python test_generic_resume.py
    python test_generic_resume.py data/master_resume.tex
"""

import os
import sys
import json
from pathlib import Path

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Verify API key is loaded
if not os.getenv("GOOGLE_API_KEY"):
    print("❌ Error: GOOGLE_API_KEY not found in environment")
    print("   Please add it to your .env file or set it as an environment variable")
    print("   Example: export GOOGLE_API_KEY='your-key-here'")
    sys.exit(1)

# Ensure we can import from jobscout package
# (Assuming this script is in project root)

from jobscout.tools.resume_generator import tailor_resume_with_llm
from jobscout.tools.latex_parser import parse_latex_resume
from jobscout.tools.resume_parser import parse_resume_file, ParsedResume, ResumeComponent
from jobscout.tools.validation import validate_resume_output


def test_with_resume(resume_path: str, jd_text: str, test_name: str):
    """
    Test resume generation with a specific resume and JD.
    
    Args:
        resume_path: Path to resume file (.tex or .txt)
        jd_text: Job description text
        test_name: Name for this test (for output)
    """
    print(f"\n{'='*60}")
    print(f"TEST: {test_name}")
    print(f"{'='*60}\n")
    
    # Parse resume
    if resume_path.endswith('.tex'):
        print(f"Parsing LaTeX resume: {resume_path}")
        latex_resume = parse_latex_resume(resume_path)
        
        # Convert to ParsedResume format
        experiences = []
        for exp in latex_resume.experiences:
            experiences.append(ResumeComponent(
                id=exp.id,
                type="experience",
                title=exp.title,
                organization=exp.company,
                date_range=exp.dates,
                tech_line="",
                bullets=exp.bullets,
                raw_text=" ".join(exp.bullets),
                keywords=exp.keywords
            ))
        
        projects = []
        for proj in latex_resume.projects:
            projects.append(ResumeComponent(
                id=proj.id,
                type="project",
                title=proj.name,
                organization="",
                date_range=proj.dates,
                tech_line=proj.tech,
                bullets=proj.bullets,
                raw_text=" ".join(proj.bullets),
                keywords=proj.keywords
            ))
        
        skills_text = ""
        skills_list = []
        for label, value in latex_resume.skills.categories.items():
            skills_text += f"{label}: {value}\n"
            skills_list.extend([s.strip().lower() for s in value.split(",")])
        
        parsed = ParsedResume(
            contact_info=f"{latex_resume.name}\n{latex_resume.email}",
            education=f"{latex_resume.education_school} | {latex_resume.education_degree}",
            skills_text=skills_text,
            skills_list=list(set(skills_list)),
            experiences=experiences,
            projects=projects,
            raw_text=latex_resume.raw_tex
        )
    else:
        print(f"Parsing text resume: {resume_path}")
        parsed = parse_resume_file(resume_path)
    
    print(f"✅ Parsed: {len(parsed.experiences)} experiences, {len(parsed.projects)} projects\n")
    
    # Select components (for now, just take first 2-3)
    exp_ids = [exp.id for exp in parsed.experiences[:3]]
    proj_ids = [proj.id for proj in parsed.projects[:4]]
    
    print(f"Selected experiences: {exp_ids}")
    print(f"Selected projects: {proj_ids}\n")
    
    # Generate tailored resume
    print("Calling Gemini to tailor resume...")
    result = tailor_resume_with_llm(
        master_resume_text=parsed.raw_text,
        jd_text=jd_text,
        selected_experience_ids=exp_ids,
        selected_project_ids=proj_ids,
        lead_skills=[],
        parsed_resume=parsed,
        resume_rules="",
        similar_tech_map={},
        model="gemini-2.5-flash",
        fallback_model="gemini-2.5-flash",
        max_retries=2
    )
    
    if not result:
        print("❌ FAILED: No output from Gemini")
        return False
    
    # Save output
    output_dir = Path("test_outputs")
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / f"{test_name.replace(' ', '_')}.json"
    
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(f"\n✅ Output saved to: {output_file}")
    
    # Validate
    print("\nRunning validation...")
    validation = validate_resume_output(result, parsed.raw_text)
    print(validation)
    
    # Display summary
    print(f"\n📊 SUMMARY:")
    print(f"  Experiences: {len(result.get('experiences', []))}")
    for exp in result.get('experiences', []):
        print(f"    - {exp.get('company', 'Unknown')}: {len(exp.get('bullets', []))} bullets")
    
    print(f"\n  Projects: {len(result.get('projects', []))}")
    for proj in result.get('projects', []):
        print(f"    - {proj.get('name', 'Unknown')}: {len(proj.get('bullets', []))} bullets")
    
    return validation.valid


def main():
    """Run test suite."""
    
    # Test JDs
    backend_jd = """
    Backend Software Engineer - Stripe
    
    Requirements:
    - 0-2 years experience
    - Strong Python, Java, or Go
    - Experience with AWS, microservices, REST APIs
    - Database design (MySQL, PostgreSQL)
    - CI/CD, Docker, Kubernetes
    
    Bonus:
    - Distributed systems experience
    - Payment processing knowledge
    """
    
    ml_jd = """
    ML Engineer - OpenAI
    
    Requirements:
    - 1-3 years experience
    - PyTorch, TensorFlow, distributed training
    - Python, C++
    - Kubernetes, cloud infrastructure (AWS/GCP)
    - Model serving, ML pipelines
    
    Bonus:
    - LLM fine-tuning experience
    - Research background
    """
    
    devops_jd = """
    DevOps Engineer - AWS
    
    Requirements:
    - 0-2 years experience
    - Terraform, CloudFormation, infrastructure as code
    - CI/CD pipelines (GitHub Actions, Jenkins)
    - Docker, Kubernetes
    - AWS services (Lambda, EC2, S3, CloudWatch)
    - Monitoring and observability
    """
    
    # Get resume path from command line or use default
    if len(sys.argv) > 1:
        resume_path = sys.argv[1]
    else:
        print("Usage: python test_generic_resume.py <path_to_resume.tex>")
        print("\nOr place your resume at data/master_resume.tex")
        resume_path = "data/master_resume.tex"
        
        if not os.path.exists(resume_path):
            print(f"\n❌ Resume not found at: {resume_path}")
            print("Please provide resume path as argument")
            return
    
    # Run tests
    print(f"\n🧪 Starting Resume Generation Tests")
    print(f"Resume: {resume_path}\n")
    
    results = []
    
    # Test 1: Backend role
    results.append(test_with_resume(resume_path, backend_jd, "Backend_Stripe"))
    
    # Test 2: ML role
    results.append(test_with_resume(resume_path, ml_jd, "ML_OpenAI"))
    
    # Test 3: DevOps role
    results.append(test_with_resume(resume_path, devops_jd, "DevOps_AWS"))
    
    # Final summary
    print(f"\n\n{'='*60}")
    print(f"FINAL RESULTS")
    print(f"{'='*60}")
    print(f"  Passed: {sum(results)}/{len(results)}")
    print(f"  Failed: {len(results) - sum(results)}/{len(results)}")
    
    if all(results):
        print("\n✅ ALL TESTS PASSED!")
    else:
        print("\n⚠️  Some tests failed - check outputs for details")


if __name__ == "__main__":
    main()
"""
Mock Scraper - Generate Fake Full Job Descriptions

For testing the enrichment pipeline without making real HTTP requests.

Location: jobscout_v3/tools/scraping/mock_scraper.py
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


def mock_scrape_jd(url: str, title: str, company: str) -> Dict[str, any]:
    """
    Generate a fake full job description.
    
    Args:
        url: Job posting URL (ignored, just for API compatibility)
        title: Job title
        company: Company name
        
    Returns:
        Dict with full_jd, requirements, and metadata
    """
    
    # Generate realistic-looking full JD based on title
    full_jd = _generate_mock_jd(title, company)
    
    # Extract mock requirements
    requirements = _extract_mock_requirements(title)
    
    return {
        'full_jd': full_jd,
        'requirements': requirements,
        'scraped_successfully': True,
        'scraper_used': 'mock',
    }


def _generate_mock_jd(title: str, company: str) -> str:
    """Generate a realistic-looking job description."""
    
    title_lower = title.lower()
    
    # Determine role type
    is_ml = any(kw in title_lower for kw in ['ml', 'machine learning', 'ai', 'data scientist'])
    is_backend = 'backend' in title_lower or 'back-end' in title_lower
    is_fullstack = 'full' in title_lower or 'fullstack' in title_lower
    is_data = 'data engineer' in title_lower or 'data analyst' in title_lower
    
    # Base JD template
    jd = f"""
About {company}

{company} is a leading technology company building innovative solutions that impact millions of users. We're looking for talented engineers to join our growing team.

About the Role

We're seeking a {title} to join our engineering team. This is an entry-level position perfect for new graduates or those with 0-2 years of experience. You'll work closely with senior engineers, contribute to production systems, and grow your skills in a supportive environment.

What You'll Do

• Design, develop, and deploy scalable software solutions
• Collaborate with cross-functional teams including product, design, and data
• Write clean, maintainable, and well-tested code
• Participate in code reviews and contribute to engineering best practices
• Ship features that directly impact our users
"""

    # Add role-specific responsibilities
    if is_ml:
        jd += """
• Build and deploy machine learning models to production
• Work with large datasets to train and evaluate models
• Implement ML pipelines for data processing and model serving
• Experiment with state-of-the-art ML techniques
"""
    elif is_backend:
        jd += """
• Build robust APIs and backend services
• Optimize database queries and improve system performance
• Design distributed systems that scale to millions of requests
• Work with microservices architecture
"""
    elif is_fullstack:
        jd += """
• Develop both frontend and backend features
• Build responsive user interfaces with modern frameworks
• Design RESTful APIs and integrate with databases
• Work across the full technology stack
"""
    elif is_data:
        jd += """
• Build and maintain data pipelines and ETL processes
• Design data models and optimize data warehouse performance
• Create dashboards and visualizations for business insights
• Work with large-scale datasets using modern data tools
"""
    else:
        jd += """
• Contribute to all parts of our technology stack
• Build features end-to-end from database to UI
• Work on challenging technical problems
• Learn from experienced engineers
"""

    # Add requirements section
    jd += """
Requirements

Must Have:
• Bachelor's degree in Computer Science or related field (or equivalent experience)
• Strong programming skills in at least one language
"""

    # Add role-specific requirements
    if is_ml:
        jd += """• Experience with Python and ML frameworks (TensorFlow, PyTorch, scikit-learn)
• Understanding of machine learning fundamentals
• Familiarity with data analysis libraries (pandas, numpy)
"""
    elif is_backend:
        jd += """• Proficiency in Python, Java, Go, or similar backend languages
• Understanding of databases (SQL and/or NoSQL)
• Familiarity with cloud platforms (AWS, GCP, or Azure)
"""
    elif is_fullstack:
        jd += """• Experience with JavaScript/TypeScript and modern frameworks (React, Vue, or Angular)
• Backend development experience in Python, Java, or Node.js
• Understanding of databases and APIs
"""
    elif is_data:
        jd += """• Strong SQL skills and experience with data modeling
• Familiarity with data pipeline tools (Airflow, dbt, or similar)
• Experience with Python for data analysis
"""
    else:
        jd += """• Programming experience in Python, Java, C++, or JavaScript
• Understanding of data structures and algorithms
• Strong problem-solving skills
"""

    # Add nice-to-have section
    jd += """
Nice to Have:
"""
    
    if is_ml:
        jd += """• Experience with deep learning and neural networks
• Publications or projects in machine learning
• Familiarity with MLOps and model deployment
• Experience with Kubernetes and Docker
"""
    else:
        jd += """• Internship or project experience in software engineering
• Contributions to open source projects
• Familiarity with agile development methodologies
• Experience with version control (Git)
"""

    # Add benefits and closing
    jd += f"""
What We Offer

• Competitive salary and equity compensation
• Comprehensive health, dental, and vision insurance
• 401(k) with company match
• Unlimited PTO and flexible work arrangements
• Professional development budget
• Modern office with free meals and snacks
• Collaborative and inclusive team culture

{company} is an equal opportunity employer. We celebrate diversity and are committed to creating an inclusive environment for all employees.

To Apply

Send your resume and a brief cover letter explaining why you're interested in joining {company}. We look forward to hearing from you!
"""

    return jd.strip()


def _extract_mock_requirements(title: str) -> Dict[str, List[str]]:
    """Extract mock requirements based on job title."""
    
    title_lower = title.lower()
    
    requirements = {
        'must_have': [
            'Bachelor\'s degree in Computer Science or related field',
            'Strong programming skills',
            '0-2 years of experience',
        ],
        'nice_to_have': [
            'Internship experience',
            'Open source contributions',
            'Agile methodology familiarity',
        ],
        'education': ['Bachelor\'s degree in Computer Science or related field'],
        'experience_years': '0-2',
    }
    
    # Add role-specific requirements
    if any(kw in title_lower for kw in ['ml', 'machine learning', 'ai']):
        requirements['must_have'].extend([
            'Python programming',
            'Machine learning fundamentals',
            'TensorFlow or PyTorch',
        ])
        requirements['nice_to_have'].extend([
            'Deep learning experience',
            'ML research publications',
            'MLOps knowledge',
        ])
    
    elif 'backend' in title_lower:
        requirements['must_have'].extend([
            'Backend programming (Python/Java/Go)',
            'Database knowledge (SQL/NoSQL)',
            'Cloud platforms (AWS/GCP/Azure)',
        ])
        requirements['nice_to_have'].extend([
            'Distributed systems experience',
            'Microservices architecture',
            'Docker and Kubernetes',
        ])
    
    elif 'full' in title_lower or 'fullstack' in title_lower:
        requirements['must_have'].extend([
            'JavaScript/TypeScript',
            'React or Vue',
            'Backend language (Python/Node.js)',
        ])
        requirements['nice_to_have'].extend([
            'GraphQL experience',
            'CI/CD pipelines',
            'Cloud deployment',
        ])
    
    elif 'data' in title_lower:
        requirements['must_have'].extend([
            'SQL and data modeling',
            'Python for data analysis',
            'ETL/data pipeline tools',
        ])
        requirements['nice_to_have'].extend([
            'Airflow or dbt experience',
            'Data warehouse optimization',
            'BI tools (Tableau/Looker)',
        ])
    
    else:
        requirements['must_have'].extend([
            'Data structures and algorithms',
            'Problem-solving skills',
            'Version control (Git)',
        ])
    
    return requirements


# CLI for testing
if __name__ == "__main__":
    print("Mock Scraper Test\n")
    
    test_jobs = [
        ("Software Engineer - New Grad", "Stripe"),
        ("ML Engineer - Entry Level", "OpenAI"),
        ("Backend Engineer", "Databricks"),
        ("Data Engineer - New Grad", "Snowflake"),
    ]
    
    for title, company in test_jobs:
        print(f"{'='*80}")
        print(f"Job: {title} @ {company}\n")
        
        result = mock_scrape_jd("http://example.com", title, company)
        
        print("Full JD Preview:")
        print(result['full_jd'][:500] + "...\n")
        
        print("Requirements:")
        print(f"  Must Have: {result['requirements']['must_have'][:3]}")
        print(f"  Nice to Have: {result['requirements']['nice_to_have'][:2]}")
        print()
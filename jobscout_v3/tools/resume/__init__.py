"""
Resume Tools Module

Tools for parsing, analyzing, and scoring resumes:
- LaTeX parsing (extract structured data from .tex files)
- Embedding generation (Gemini API)
- Similarity scoring (cosine similarity between job and resume)
- Component selection (choose experiences/projects for each job)
"""

from .latex_parser import parse_latex_resume, extract_experiences, extract_projects
from .embedding_scorer import (
    generate_embeddings,
    compute_similarity,
    score_job_resume_fit,
)
from .resume_parser import ResumeParser

__all__ = [
    # LaTeX parsing
    'parse_latex_resume',
    'extract_experiences',
    'extract_projects',
    
    # Embedding & scoring
    'generate_embeddings',
    'compute_similarity',
    'score_job_resume_fit',
    
    # Unified parser
    'ResumeParser',
]
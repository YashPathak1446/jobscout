"""
Resume Tools Module

Tools for parsing, analyzing, and scoring resumes:
- LaTeX parsing (extract structured data from .tex files)
- Embedding generation (Gemini API)
- Similarity scoring (cosine similarity between job and resume)
- Component selection (choose experiences/projects for each job)
"""

from .latex_parser import (
    parse_latex_resume,
    print_latex_resume,
    LatexResume,
    LatexExperience,
    LatexProject,
    LatexSkills,
)
from .embedding_scorer import (
    embed_resume_components,
    embed_resume_components_mock,
    score_job_with_embeddings,
    score_job_mock,
    EmbeddingScore,
)
from .resume_parser import ResumeParser

__all__ = [
    # LaTeX parsing
    'parse_latex_resume',
    'print_latex_resume',
    'LatexResume',
    'LatexExperience',
    'LatexProject',
    'LatexSkills',
    
    # Embedding & scoring
    'embed_resume_components',
    'embed_resume_components_mock',
    'score_job_with_embeddings',
    'score_job_mock',
    'EmbeddingScore',
    
    # Unified parser
    'ResumeParser',
]
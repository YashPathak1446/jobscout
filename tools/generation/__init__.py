"""
Generation Tools Module

Tools for generating tailored resumes:
- Prompt building (create Gemini prompts)
- Output validation (check quality)
- LaTeX generation (create .tex files)
- PDF compilation (.tex -> .pdf via pdflatex)
"""

from .prompt_builder import (
    build_generic_tailoring_prompt,
    build_validation_repair_prompt,
)

from .validation import validate_resume_output, ValidationResult

from .pdf_builder import (
    compile_pdf,
    detect_flavor,
    find_pdflatex,
    PdfResult,
)

__all__ = [
    'build_generic_tailoring_prompt',
    'build_validation_repair_prompt',
    'validate_resume_output',
    'ValidationResult',
    'compile_pdf',
    'detect_flavor',
    'find_pdflatex',
    'PdfResult',
]
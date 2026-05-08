"""
Job Listing Data Structure

Standardized job listing format used across all search sources.

Location: jobscout_v3/tools/search/job_listing.py
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class JobListing:
    """Standardized job listing from any source."""
    id: str
    title: str
    company: str
    location: str
    description: str              # Short snippet from search
    apply_url: str
    salary_min: float | None
    salary_max: float | None
    created: str
    source: str                   # "serper", "adzuna", "github", etc.
    full_jd: str = ""            # Populated during enrichment phase
    
    def __str__(self) -> str:
        """Human-readable representation."""
        salary = ""
        if self.salary_min or self.salary_max:
            if self.salary_min and self.salary_max:
                salary = f" | ${self.salary_min/1000:.0f}K-${self.salary_max/1000:.0f}K"
            elif self.salary_min:
                salary = f" | ${self.salary_min/1000:.0f}K+"
        
        return f"[{self.source}] {self.title} @ {self.company} - {self.location}{salary}"
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'id': self.id,
            'title': self.title,
            'company': self.company,
            'location': self.location,
            'description': self.description,
            'apply_url': self.apply_url,
            'salary_min': self.salary_min,
            'salary_max': self.salary_max,
            'created': self.created,
            'source': self.source,
            'full_jd': self.full_jd,
        }
    
    @staticmethod
    def from_dict(data: dict) -> 'JobListing':
        """Create from dictionary."""
        return JobListing(**data)

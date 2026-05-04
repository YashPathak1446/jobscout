"""
Agents Module

Multi-agent job application pipeline:
- Discovery: Find relevant jobs
- Enrichment: Scrape full job descriptions
- Analysis: Score & select resume components
- Generation: Tailor resumes for each job
"""

from .discovery_agent import DiscoveryAgent

__all__ = ['DiscoveryAgent']

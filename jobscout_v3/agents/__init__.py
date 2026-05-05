"""
Agents Module

Multi-agent job application pipeline:
- Discovery: Find relevant jobs
- Enrichment: Scrape full job descriptions
- Analysis: Score & select resume components
- Generation: Tailor resumes for each job
"""

from .discovery_agent import DiscoveryAgent
from .enrichment_agent import EnrichmentAgent
from .analysis_agent import AnalysisAgent
from .generation_agent import GenerationAgent

__all__ = ['DiscoveryAgent', 'EnrichmentAgent', 'AnalysisAgent', 'GenerationAgent']
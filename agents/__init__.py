"""
Agents Module

Multi-agent job application pipeline:
- Discovery: Find relevant jobs
- Enrichment: Scrape full job descriptions
- Analysis: Score & select resume components
- Generation: Tailor resumes for each job
- JobScoutOrchestrator: Manages the end-to-end process
"""

from .discovery_agent import DiscoveryAgent
from .enrichment_agent import EnrichmentAgent
from .analysis_agent import AnalysisAgent
from .generation_agent import GenerationAgent
from .orchestrator import JobScoutOrchestrator

__all__ = ['DiscoveryAgent', 'EnrichmentAgent', 'AnalysisAgent', 'GenerationAgent', 'JobScoutOrchestrator']
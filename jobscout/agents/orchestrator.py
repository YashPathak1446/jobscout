"""
Orchestrator Agent — The root agent that coordinates Research, Fit, and Prep agents.
Uses ADK's SequentialAgent to run them in pipeline order.
"""

from google.adk.agents import Agent, SequentialAgent

from jobscout.agents.research_agent import research_agent
from jobscout.agents.fit_agent import fit_agent
from jobscout.agents.prep_agent import prep_agent


def build_orchestrator() -> SequentialAgent:
    """
    Build the orchestrator that runs all three agents in sequence:
    1. Research Agent → gathers company/role intel
    2. Fit Agent → analyzes resume match
    3. Prep Agent → generates interview prep materials

    Returns a SequentialAgent that coordinates the pipeline.
    """

    orchestrator = SequentialAgent(
        name="jobscout_orchestrator",
        description=(
            "Coordinates a multi-agent pipeline to analyze a job opportunity. "
            "Runs research, fit analysis, and interview prep in sequence."
        ),
        sub_agents=[research_agent, fit_agent, prep_agent],
    )

    return orchestrator

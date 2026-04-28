"""
ADK-compatible entry point.
Run with: adk web or adk run from the project root.
This file exposes the root_agent that ADK's CLI expects.
"""

from jobscout.agents.orchestrator import build_orchestrator

# ADK CLI looks for a `root_agent` or `agent` variable
root_agent = build_orchestrator()

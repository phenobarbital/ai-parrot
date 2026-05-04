"""parrot.bots.flows.crew — AgentCrew sub-package.

Exports the crew orchestrator and its node type.

Note: ``AgentCrew`` is added to this init in TASK-979 after the class is
moved from ``parrot.bots.orchestration.crew``.
"""
from .nodes import CrewAgentNode

__all__ = [
    "CrewAgentNode",
]

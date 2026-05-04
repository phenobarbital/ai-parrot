"""parrot.bots.flows.agents — orchestrator agents sub-package.

Exports the orchestrator agents moved from ``parrot.bots.orchestration``
as part of FEAT-143 flows consolidation.

Usage::

    from parrot.bots.flows.agents import (
        OrchestratorAgent,
        A2AOrchestratorAgent,
        ListAvailableA2AAgentsTool,
        HRAgentFactory,
        RAGHRAgent,
        EmployeeDataAgent,
    )
"""
from .orchestrator import OrchestratorAgent
from .a2a_orchestrator import (
    A2AOrchestratorAgent,
    ListAvailableA2AAgentsTool,
    DiscoverA2AAgentsInput,
)
from .hr import HRAgentFactory, RAGHRAgent, EmployeeDataAgent

__all__ = [
    # Core orchestrator
    "OrchestratorAgent",
    # A2A orchestrator and helpers
    "A2AOrchestratorAgent",
    "ListAvailableA2AAgentsTool",
    "DiscoverA2AAgentsInput",
    # HR agents
    "HRAgentFactory",
    "RAGHRAgent",
    "EmployeeDataAgent",
]

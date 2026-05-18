"""Agent Factory: orchestrator + specialist builders that generate, validate
and register new agent YAML definitions in the ``AgentRegistry``.
"""
from parrot.bots.factory.contracts import (
    AgentDefinition,
    BuilderOutput,
    BuilderType,
    FactoryRequest,
    FactoryResult,
    FactoryStatus,
    HITLCheckpoint,
    ProvisioningRecord,
    RouterDecision,
)
from parrot.bots.factory.orchestrator import AgentFactoryOrchestrator

__all__ = [
    "AgentDefinition",
    "AgentFactoryOrchestrator",
    "BuilderOutput",
    "BuilderType",
    "FactoryRequest",
    "FactoryResult",
    "FactoryStatus",
    "HITLCheckpoint",
    "ProvisioningRecord",
    "RouterDecision",
]

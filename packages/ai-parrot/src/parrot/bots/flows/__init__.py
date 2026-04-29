"""parrot.bots.flows — shared orchestration primitives for AgentCrew & AgentsFlow.

All public symbols are re-exported from the ``core`` sub-package.

Usage::

    from parrot.bots.flows import (
        AgentLike, FlowStatus,
        Node, AgentNode, FlowResult, FlowContext, FlowTransition,
    )
"""
from .core import (
    # Types & protocols
    AgentLike,
    AgentRef,
    DependencyResults,
    PromptBuilder,
    ActionCallback,
    FlowStatus,
    # FSM
    AgentTaskMachine,
    TransitionCondition,
    # Node hierarchy
    Node,
    AgentNode,
    StartNode,
    EndNode,
    # Result models
    FlowResult,
    NodeExecutionInfo,
    build_node_metadata,
    determine_run_status,
    # Context
    FlowContext,
    # Transitions
    FlowTransition,
    # Storage
    ExecutionMemory,
    VectorStoreMixin,
    PersistenceMixin,
    SynthesisMixin,
)

__all__ = [
    # Types & protocols
    "AgentLike",
    "AgentRef",
    "DependencyResults",
    "PromptBuilder",
    "ActionCallback",
    "FlowStatus",
    # FSM
    "AgentTaskMachine",
    "TransitionCondition",
    # Node hierarchy
    "Node",
    "AgentNode",
    "StartNode",
    "EndNode",
    # Result models
    "FlowResult",
    "NodeExecutionInfo",
    "build_node_metadata",
    "determine_run_status",
    # Context
    "FlowContext",
    # Transitions
    "FlowTransition",
    # Storage
    "ExecutionMemory",
    "VectorStoreMixin",
    "PersistenceMixin",
    "SynthesisMixin",
]

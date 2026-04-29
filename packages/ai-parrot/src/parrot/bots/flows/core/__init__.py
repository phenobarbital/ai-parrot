"""parrot.bots.flows.core — canonical public API for flow primitives.

All shared types, FSM, node hierarchy, result models, context, transitions,
and storage mixins are available from this single import path.

Usage::

    from parrot.bots.flows.core import (
        AgentLike, FlowStatus,
        AgentTaskMachine, TransitionCondition,
        Node, AgentNode, StartNode, EndNode,
        FlowResult, NodeExecutionInfo, FlowContext, FlowTransition,
        ExecutionMemory, PersistenceMixin, SynthesisMixin,
    )
"""
# Types & protocols
from .types import (
    AgentLike,
    AgentRef,
    DependencyResults,
    PromptBuilder,
    ActionCallback,
    FlowStatus,
)

# FSM
from .fsm import AgentTaskMachine, TransitionCondition

# Node hierarchy
from .node import Node, AgentNode, StartNode, EndNode

# Result models
from .result import (
    FlowResult,
    NodeExecutionInfo,
    build_node_metadata,
    determine_run_status,
)

# Execution context
from .context import FlowContext

# Transitions
from .transition import FlowTransition

# Storage
from .storage import ExecutionMemory, PersistenceMixin, SynthesisMixin, VectorStoreMixin

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

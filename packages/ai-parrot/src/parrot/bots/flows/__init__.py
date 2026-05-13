"""parrot.bots.flows — shared orchestration primitives for AgentCrew & AgentsFlow.

All public symbols are re-exported from sub-packages:

- ``core``: shared types, FSM, nodes, result models, context, storage
- ``crew``: ``AgentCrew``, ``CrewAgentNode``
- ``agents``: orchestrator agents
- ``tools``: ``ResultRetrievalTool``

Usage::

    from parrot.bots.flows import (
        AgentLike, FlowStatus,
        Node, AgentNode, FlowResult, FlowContext, FlowTransition,
        AgentCrew, CrewAgentNode,
        OrchestratorAgent,
        ResultRetrievalTool,
    )
"""
from .core import (
    # Types & protocols
    AgentLike,
    AgentRef,
    DependencyResults,
    PromptBuilder,
    ActionCallback,
    CrewHookCallback,
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
    NodeResult,
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

# Crew sub-package (AgentCrew + CrewAgentNode)
from .crew import AgentCrew, CrewAgentNode

# Orchestrator agents (moved from parrot.bots.orchestration)
from .agents import (
    OrchestratorAgent,
    A2AOrchestratorAgent,
    ListAvailableA2AAgentsTool,
    DiscoverA2AAgentsInput,
    HRAgentFactory,
    RAGHRAgent,
    EmployeeDataAgent,
)

# Flow tools
from .tools import ResultRetrievalTool

# New AgentsFlow executor (FEAT-163)
from .flow import AgentsFlow, NODE_REGISTRY, register_node, CompletionEvent

__all__ = [
    # Types & protocols
    "AgentLike",
    "AgentRef",
    "DependencyResults",
    "PromptBuilder",
    "ActionCallback",
    "CrewHookCallback",
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
    "NodeResult",
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
    # Crew
    "AgentCrew",
    "CrewAgentNode",
    # Orchestrator agents
    "OrchestratorAgent",
    "A2AOrchestratorAgent",
    "ListAvailableA2AAgentsTool",
    "DiscoverA2AAgentsInput",
    "HRAgentFactory",
    "RAGHRAgent",
    "EmployeeDataAgent",
    # Tools
    "ResultRetrievalTool",
    # AgentsFlow executor (FEAT-163)
    "AgentsFlow",
    "NODE_REGISTRY",
    "register_node",
    "CompletionEvent",
]

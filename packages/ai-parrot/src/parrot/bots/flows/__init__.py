"""parrot.bots.flows — shared orchestration primitives for AgentCrew & AgentsFlow.

All public symbols are re-exported from sub-packages:

- ``core``: shared types, FSM, nodes, result models, context, storage
- ``crew``: ``AgentCrew``, ``CrewAgentNode``
- ``agents``: orchestrator agents
- ``tools``: ``ResultRetrievalTool``
- ``flow``: ``AgentsFlow``, flow definition models, decision nodes

Usage::

    from parrot.bots.flows import (
        AgentLike, FlowStatus,
        Node, AgentNode, FlowResult, FlowContext, FlowTransition,
        AgentCrew, CrewAgentNode,
        OrchestratorAgent,
        ResultRetrievalTool,
        AgentsFlow,
        FlowDefinition, NodeDefinition, EdgeDefinition,
        DecisionFlowNode, BinaryDecision,
    )

Demoted (submodule-only — not exported at root):
- ``CELPredicateEvaluator``  → ``parrot.bots.flows.flow.cel_evaluator``
- ``ACTION_REGISTRY``, action classes → ``parrot.bots.flows.flow.actions``
- ``FlowLoader`` → ``parrot.bots.flows.flow.loader``
- ``from_svelteflow``, ``to_svelteflow`` → ``parrot.bots.flows.flow.svelteflow``
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
)

# Flow tools
from .tools import ResultRetrievalTool

# AgentsFlow executor (FEAT-163)
from .flow import (
    AgentsFlow,
    NODE_REGISTRY,
    register_node,
    CompletionEvent,
    FlowEdge,
    EDGE_CONDITIONS,
    FlowLifecycleAdapter,
)

# Flow definition models (FEAT-196)
from .flow.definition import (
    FlowDefinition,
    NodeDefinition,
    EdgeDefinition,
)

# Decision node primitives (FEAT-196)
from .flow import (
    DecisionFlowNode,
    InteractiveDecisionFlowNode,
    InteractiveDecisionNode,
    BinaryDecision,
    ApprovalDecision,
    MultiChoiceDecision,
)

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
    "NodeResult",
    "NodeExecutionInfo",
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
    # Tools
    "ResultRetrievalTool",
    # AgentsFlow executor
    "AgentsFlow",
    "NODE_REGISTRY",
    "register_node",
    "CompletionEvent",
    "FlowEdge",
    "EDGE_CONDITIONS",
    "FlowLifecycleAdapter",
    # Flow definition
    "FlowDefinition",
    "NodeDefinition",
    "EdgeDefinition",
    # Decision nodes
    "DecisionFlowNode",
    "InteractiveDecisionFlowNode",
    "InteractiveDecisionNode",  # backward-compatible alias for InteractiveDecisionFlowNode
    "BinaryDecision",
    "ApprovalDecision",
    "MultiChoiceDecision",
]

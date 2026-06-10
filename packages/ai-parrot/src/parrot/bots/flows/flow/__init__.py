"""parrot.bots.flows.flow -- AgentsFlow sub-package.

Exports the AgentsFlow executor and its registry utilities.
Mirrors the layout of parrot.bots.flows.crew.

Node types from flow.py (@register_node decorated):
  DecisionNode, InteractiveDecisionNode, SynthesisNode
  -- these are the DAG-executor node wrappers (use NODE_REGISTRY keys).

Decision primitive types from nodes.py (canonical decision logic):
  DecisionFlowNode, InteractiveDecisionNode (canonical), plus config/result types.

Note: InteractiveDecisionNode exported here is from flow.py
(the @register_node('interactive_decision') wrapper). The canonical
InteractiveDecisionNode from nodes.py is available as:
  from parrot.bots.flows.flow.nodes import InteractiveDecisionNode
"""
from .flow import (
    AgentsFlow,
    EDGE_CONDITIONS,
    FlowEdge,
    NODE_REGISTRY,
    register_node,
    CompletionEvent,
    DecisionNode,
    InteractiveDecisionFlowNode,
    InteractiveDecisionNode,
    SynthesisNode,
)
from .nodes import (
    DecisionMode,
    DecisionType,
    VoteWeight,
    BinaryDecision,
    ApprovalDecision,
    MultiChoiceDecision,
    DecisionResult,
    EscalationPolicy,
    DecisionNodeConfig,
    DecisionFlowNode,
)

__all__ = [
    "AgentsFlow",
    "EDGE_CONDITIONS",
    "FlowEdge",
    "NODE_REGISTRY",
    "register_node",
    "CompletionEvent",
    # DAG-executor node wrappers (registered in NODE_REGISTRY)
    "DecisionNode",
    "InteractiveDecisionFlowNode",
    "InteractiveDecisionNode",  # backward-compatible alias for InteractiveDecisionFlowNode
    "SynthesisNode",
    # Decision primitive types (from nodes.py)
    "DecisionMode",
    "DecisionType",
    "VoteWeight",
    "BinaryDecision",
    "ApprovalDecision",
    "MultiChoiceDecision",
    "DecisionResult",
    "EscalationPolicy",
    "DecisionNodeConfig",
    "DecisionFlowNode",
]

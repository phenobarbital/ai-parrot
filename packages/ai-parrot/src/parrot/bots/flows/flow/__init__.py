"""parrot.bots.flows.flow — AgentsFlow sub-package.

Exports the AgentsFlow executor and its registry utilities.
Mirrors the layout of parrot.bots.flows.crew.
"""
from .flow import AgentsFlow, NODE_REGISTRY, register_node, CompletionEvent
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
    InteractiveDecisionNode,
)

__all__ = [
    "AgentsFlow",
    "NODE_REGISTRY",
    "register_node",
    "CompletionEvent",
    # Decision node types
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
    "InteractiveDecisionNode",
]

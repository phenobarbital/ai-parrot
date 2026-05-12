from .node import Node
from .nodes import StartNode, EndNode
# Retargeted to new package locations (FEAT-163 TASK-1069 — legacy fsm.py deleted).
# NOTE: Lazy imports below to avoid circular import:
#   parrot.bots.flows.flow → parrot.bots.flow.definition
#   parrot.bots.flow → parrot.bots.flows.flow (circular)
from parrot.bots.flows.core.fsm import AgentTaskMachine, TransitionCondition
from parrot.bots.flows.core.transition import FlowTransition
# NOTE: FlowNode is not available after fsm.py deletion. Use parrot.bots.flows.core.node.AgentNode.
# FlowNode = (not re-exported — removed in FEAT-163)
from .decision_node import (
    DecisionFlowNode,
    DecisionMode,
    DecisionType,
    DecisionNodeConfig,
    DecisionResult,
    BinaryDecision,
    ApprovalDecision,
    MultiChoiceDecision,
    EscalationPolicy,
    VoteWeight,
)
from .interactive_node import InteractiveDecisionNode
from .definition import (
    FlowDefinition,
    FlowMetadata,
    NodeDefinition,
    NodePosition,
    EdgeDefinition,
    ActionDefinition,
    LogActionDef,
    NotifyActionDef,
    WebhookActionDef,
    MetricActionDef,
    SetContextActionDef,
    ValidateActionDef,
    TransformActionDef,
)
from .actions import (
    ACTION_REGISTRY,
    register_action,
    create_action,
    BaseAction,
    LogAction,
    NotifyAction,
    WebhookAction,
    MetricAction,
    SetContextAction,
    ValidateAction,
    TransformAction,
)
from .cel_evaluator import CELPredicateEvaluator
from .svelteflow import to_svelteflow, from_svelteflow
from .loader import FlowLoader


def __getattr__(name: str) -> object:
    """Lazy-import AgentsFlow to avoid circular dependency with parrot.bots.flows.flow.

    parrot.bots.flows.flow imports parrot.bots.flow.definition at module level;
    if parrot.bots.flow.__init__ eagerly imported parrot.bots.flows.flow a circular
    import would result. Deferring via __getattr__ breaks the cycle.
    """
    if name == "AgentsFlow":
        from parrot.bots.flows.flow import AgentsFlow  # noqa: PLC0415
        return AgentsFlow
    raise AttributeError(f"module 'parrot.bots.flow' has no attribute {name!r}")

"""JSON-safe ``NodeDefinition.config`` models for the built-in node types.

``NodeDefinition.config`` is a bare ``Dict[str, Any]``, which is why
``AgentsFlow._materialize_nodes`` historically could not build a
``"decision"`` or ``"interactive_decision"`` node from a definition alone —
their constructors require ``decision_config`` / ``question``, and nothing
read ``config`` to supply them. A ``FlowDefinition`` could therefore only
express ``start`` / ``agent`` / ``end`` unless the caller also passed a
matching ``node_factories`` entry.

The models here close that gap. Each is registered against its node type via
``register_node(..., config_model=...)`` so that:

* ``_materialize_nodes`` validates ``node_def.config`` and expands the result
  into the node constructor (the pattern already proven by
  ``parrot.bots.flows.plan.node.make_tool_node_factory``); and
* the authoring catalog can publish a real JSON Schema per node type instead
  of an opaque ``object``.

Why these are separate models rather than the runtime configs themselves:
``DecisionNodeConfig`` carries ``decision_schema: Optional[type]`` and
``EscalationPolicy`` carries ``hitl_manager: Any`` — live Python objects that
have no JSON representation and are excluded from serialization. A definition
loaded from JSON can never supply them, so the declarative surface omits them
entirely rather than advertising fields that cannot be set.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .nodes import (
    DecisionMode,
    DecisionNodeConfig,
    DecisionType,
    EscalationPolicy,
    VoteWeight,
)

__all__ = (
    "DecisionConfigDef",
    "EscalationPolicyDef",
    "InteractiveDecisionConfigDef",
    "SynthesisConfigDef",
)


class EscalationPolicyDef(BaseModel):
    """Declarative subset of :class:`EscalationPolicy`.

    Omits ``hitl_manager`` (a live ``HumanInteractionManager``): the host
    application wires that at runtime, and no JSON document can express it.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    on_low_confidence: Optional[float] = Field(
        default=None, description="Escalate when confidence is below this value"
    )
    on_split_vote: bool = Field(
        default=True, description="Escalate on an evenly split vote"
    )
    on_explicit_keyword: bool = Field(
        default=True, description="Escalate when the decision is ESCALATE"
    )
    target_humans: List[str] = Field(
        default_factory=list, description="Human identifiers to escalate to"
    )
    timeout_seconds: float = Field(
        default=7200.0, gt=0, description="HITL response timeout in seconds"
    )
    fallback_decision: Optional[Any] = Field(
        default=None, description="Decision used if HITL is unavailable or times out"
    )

    def to_runtime(self) -> EscalationPolicy:
        """Build the runtime :class:`EscalationPolicy`."""
        return EscalationPolicy(**self.model_dump())


class DecisionConfigDef(BaseModel):
    """Declarative ``config`` block for ``type: "decision"``.

    Maps onto the ``decision_config`` constructor argument of
    ``parrot.bots.flows.flow.flow.DecisionNode``. Omits
    ``DecisionNodeConfig.decision_schema`` (a Python type).
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    mode: DecisionMode = Field(
        ..., description="Operating mode: cio, ballot or consensus"
    )
    decision_type: DecisionType = Field(
        ..., description="binary, approval, multi_choice or custom"
    )
    vote_weight_strategy: VoteWeight = Field(
        default=VoteWeight.EQUAL, description="How votes are weighted"
    )
    custom_weights: Optional[Dict[str, float]] = Field(
        default=None, description="Per-agent weight overrides"
    )
    minimum_votes: Optional[int] = Field(
        default=None, ge=1, description="Quorum: minimum number of votes required"
    )
    coordinator_agent_name: Optional[str] = Field(
        default=None, description="Coordinator agent name (consensus mode)"
    )
    cross_pollination_rounds: int = Field(
        default=1, ge=0, description="Revision rounds (consensus mode)"
    )
    escalation_policy: Optional[EscalationPolicyDef] = None
    options: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Available options (multi_choice)"
    )
    agent_refs: List[str] = Field(
        default_factory=list,
        description=(
            "Names of registered agents that vote in this decision. This is "
            "the declarative half of 'agents': a JSON document names them, "
            "and AgentsFlow.from_definition resolves each one through the "
            "AgentRegistry before the node is built."
        ),
    )
    agents: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Participating agents as live instances. Not expressible in JSON "
            "— a definition names them in 'agent_refs' instead, and the "
            "executor injects the resolved instances here."
        ),
    )

    def to_node_kwargs(self) -> Dict[str, Any]:
        """Expand into ``DecisionNode`` constructor keyword arguments.

        ``agent_refs`` is a resolution instruction, not a
        ``DecisionNodeConfig`` field, so it is excluded from the runtime
        config; ``AgentsFlow._build_node_from_config`` merges the agents it
        resolved from those refs into the ``agents`` mapping returned here.
        """
        payload = self.model_dump(
            exclude={"agents", "agent_refs", "escalation_policy"}
        )
        if self.escalation_policy is not None:
            payload["escalation_policy"] = self.escalation_policy.to_runtime()
        return {
            "decision_config": DecisionNodeConfig(**payload),
            "agents": dict(self.agents),
        }


class InteractiveDecisionConfigDef(BaseModel):
    """Declarative ``config`` block for ``type: "interactive_decision"``."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1, description="Prompt shown to the user")
    options: List[str] = Field(
        default_factory=list, description="Choices offered to the user"
    )

    def to_node_kwargs(self) -> Dict[str, Any]:
        """Expand into ``InteractiveDecisionFlowNode`` constructor kwargs."""
        return {"question": self.question, "options": list(self.options)}


class SynthesisConfigDef(BaseModel):
    """Declarative ``config`` block for ``type: "synthesis"``.

    ``SynthesisNode`` takes no extra constructor arguments today; the model
    exists so the node type still publishes an explicit (empty, closed)
    schema rather than an untyped ``object``.
    """

    model_config = ConfigDict(extra="forbid")

    def to_node_kwargs(self) -> Dict[str, Any]:
        """No extra constructor arguments."""
        return {}

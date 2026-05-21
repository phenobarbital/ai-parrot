"""Core data models for the Human-in-the-Loop system."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


__all__ = [
    "InteractionType",
    "InteractionStatus",
    "TimeoutAction",
    "ConsensusMode",
    "ChoiceOption",
    "EscalationActionType",
    "EscalationTier",
    "EscalationPolicy",
    "HumanInteraction",
    "HumanResponse",
    "InteractionResult",
]


class InteractionType(str, Enum):
    """Type of interaction requested from the human."""

    FREE_TEXT = "free_text"
    SINGLE_CHOICE = "single_choice"
    MULTI_CHOICE = "multi_choice"
    APPROVAL = "approval"
    FORM = "form"
    POLL = "poll"


class InteractionStatus(str, Enum):
    """Lifecycle status of a human interaction."""

    PENDING = "pending"
    DELIVERED = "delivered"
    PARTIAL = "partial"
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    ESCALATED = "escalated"
    CANCELLED = "cancelled"


class TimeoutAction(str, Enum):
    """Action to take when an interaction times out."""

    CANCEL = "cancel"
    DEFAULT = "default"
    ESCALATE = "escalate"
    RETRY = "retry"


class ConsensusMode(str, Enum):
    """How to consolidate responses when multiple humans are involved."""

    FIRST_RESPONSE = "first_response"
    ALL_REQUIRED = "all_required"
    MAJORITY = "majority"
    QUORUM = "quorum"


class ChoiceOption(BaseModel):
    """A selectable option presented to the human."""

    key: str
    label: str
    description: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EscalationActionType(str, Enum):
    """Actions performed when escalating to a tier."""

    INTERACT = "interact"  # Standard bi-directional interaction
    NOTIFY = "notify"  # One-way notification
    TICKET = "ticket"  # Open a ticket in an external system


class EscalationTier(BaseModel):
    """Definition of a single level in an escalation policy."""

    level: int = Field(ge=1, description="1-based tier ordering")
    name: str
    channel_type: Optional[str] = Field(
        default=None,
        description=(
            "Channel to dispatch this tier through. When None the manager "
            "falls back to the channel of the originating interaction."
        ),
    )
    target_humans: List[str] = Field(default_factory=list)
    timeout: float = Field(default=3600.0, gt=0, description="Seconds")
    action_type: EscalationActionType = EscalationActionType.INTERACT
    action_metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_interact_has_targets(self) -> "EscalationTier":
        if (
            self.action_type == EscalationActionType.INTERACT
            and not self.target_humans
        ):
            raise ValueError(
                f"Tier {self.level} ('{self.name}') uses INTERACT but has "
                "no target_humans"
            )
        return self


class EscalationPolicy(BaseModel):
    """A series of tiered levels for escalating human-in-the-loop requests."""

    policy_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    tiers: List[EscalationTier] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_tier_levels(self) -> "EscalationPolicy":
        if not self.tiers:
            return self
        levels = sorted(t.level for t in self.tiers)
        expected = list(range(1, len(levels) + 1))
        if levels != expected:
            raise ValueError(
                f"Tier levels must be contiguous starting at 1, got {levels}"
            )
        return self


class HumanInteraction(BaseModel):
    """Represents a request for human input."""

    interaction_id: str = Field(default_factory=lambda: str(uuid4()))

    # Content
    question: str
    context: Optional[str] = None
    interaction_type: InteractionType = InteractionType.FREE_TEXT
    options: Optional[List[ChoiceOption]] = None
    form_schema: Optional[Dict[str, Any]] = None
    default_response: Any = None

    # Routing
    target_humans: List[str] = Field(default_factory=list)
    consensus_mode: ConsensusMode = ConsensusMode.FIRST_RESPONSE

    # Timeout and escalation (seconds)
    timeout: float = Field(default=7200.0, gt=0)
    timeout_action: TimeoutAction = TimeoutAction.CANCEL
    escalation_targets: List[str] = Field(default_factory=list)

    # Tiered Escalation
    policy_id: Optional[str] = None
    policy: Optional[EscalationPolicy] = None
    current_tier_level: int = Field(default=0, ge=0)

    # Traceability
    source_agent: Optional[str] = None
    source_flow: Optional[str] = None
    source_node: Optional[str] = None

    # State (managed by the engine)
    status: InteractionStatus = InteractionStatus.PENDING

    @model_validator(mode="after")
    def _check_payload(self) -> "HumanInteraction":
        """Ensure required payload fields match the interaction type."""
        if self.interaction_type == InteractionType.FORM and not self.form_schema:
            raise ValueError(
                "FORM interactions require a non-empty form_schema"
            )
        if self.interaction_type in {
            InteractionType.SINGLE_CHOICE,
            InteractionType.MULTI_CHOICE,
            InteractionType.POLL,
        } and not self.options:
            raise ValueError(
                f"{self.interaction_type.value} interactions require options"
            )
        return self


class HumanResponse(BaseModel):
    """Response from a human to an interaction.

    Note:
        ``response_type`` reuses :class:`InteractionType` to describe the
        *format* the channel actually delivered (e.g. Telegram may deliver
        a FORM as FREE_TEXT). The compatibility map lives in
        ``HumanInteractionManager._COMPATIBLE_TYPES``.
    """

    model_config = ConfigDict(extra="forbid")

    interaction_id: str
    respondent: str
    response_type: InteractionType

    # Value depends on response_type:
    #   free_text     -> str
    #   single_choice -> str (key of ChoiceOption)
    #   multi_choice  -> List[str] (keys)
    #   approval      -> bool
    #   form          -> dict
    #   poll          -> str (key)
    value: Any

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the response was captured",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_value_shape(self) -> "HumanResponse":
        """Light type-check against ``response_type``.

        Only validates the cases where the runtime shape is unambiguous
        (bool / list / dict). ``free_text`` and the *_choice text-key
        variants accept ``Any`` to stay tolerant of channel quirks.
        """
        rt = self.response_type
        v = self.value
        if rt == InteractionType.APPROVAL and not isinstance(v, bool):
            raise ValueError("approval responses must be a bool")
        if rt == InteractionType.MULTI_CHOICE and not isinstance(v, list):
            raise ValueError("multi_choice responses must be a list")
        if rt == InteractionType.FORM and not isinstance(v, dict):
            raise ValueError("form responses must be a dict")
        return self


class InteractionResult(BaseModel):
    """Consolidated result of an interaction after consensus evaluation."""

    interaction_id: str
    status: InteractionStatus
    responses: List[HumanResponse] = Field(default_factory=list)
    consolidated_value: Any = None
    timed_out: bool = False
    escalated: bool = False
    tier_level: int = Field(default=0, ge=0)
    action_metadata: Dict[str, Any] = Field(default_factory=dict)

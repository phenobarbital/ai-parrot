"""Core data models for the Human-in-the-Loop system."""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


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


class HumanInteraction(BaseModel):
    """Represents a request for human input."""

    interaction_id: str = Field(default_factory=lambda: str(uuid4()))

    # Content
    question: str
    context: Optional[str] = None
    interaction_type: InteractionType = InteractionType.FREE_TEXT
    options: Optional[List[ChoiceOption]] = None
    form_schema: Optional[Dict[str, Any]] = None
    default_response: Optional[Any] = None

    # Routing
    target_humans: List[str] = Field(default_factory=list)
    consensus_mode: ConsensusMode = ConsensusMode.FIRST_RESPONSE

    # Timeout and escalation (seconds)
    timeout: float = 7200.0
    timeout_action: TimeoutAction = TimeoutAction.CANCEL
    escalation_targets: Optional[List[str]] = None

    # Traceability
    source_agent: Optional[str] = None
    source_flow: Optional[str] = None
    source_node: Optional[str] = None

    # State (managed by the engine)
    status: InteractionStatus = InteractionStatus.PENDING


class HumanResponse(BaseModel):
    """Response from a human to an interaction."""

    interaction_id: str
    respondent: str
    response_type: InteractionType

    # Value depends on type:
    #   free_text   -> str
    #   single_choice -> str (key of ChoiceOption)
    #   multi_choice  -> List[str] (keys)
    #   approval    -> bool
    #   form        -> dict
    #   poll        -> str (key)
    value: Any

    timestamp: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class InteractionResult(BaseModel):
    """Consolidated result of an interaction after consensus evaluation."""

    interaction_id: str
    status: InteractionStatus
    responses: List[HumanResponse] = Field(default_factory=list)
    consolidated_value: Any = None
    timed_out: bool = False
    escalated: bool = False

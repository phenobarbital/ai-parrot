"""Structured event models for HITL multi-tier escalation tier transitions.

Provides Pydantic event models emitted by :class:`~parrot.human.manager.HumanInteractionManager`
on every tier-transition decision.  Subscribers register via the
``on_event`` constructor kwarg on the manager.

Design decision (TASK-1280): the **hook pattern** was chosen over
``EventEmitterMixin`` inheritance.  The existing ``EventRegistry.emit()``
expects a ``LifecycleEvent`` (frozen dataclass) with ``TraceContext``,
``source_type``, etc. — a different base type than the Pydantic models
specified here.  Wiring the manager into that hierarchy would require
non-trivial MRO changes and couples HITL to the lifecycle-events
infrastructure unnecessarily.  The ``on_event`` hook is simpler, test-friendly,
and keeps HITL self-contained.

Event name strings use dot-namespaced convention:
- ``"hitl.tier.entered"``   — ``HitlTierEnteredEvent``
- ``"hitl.tier.advanced"``  — ``HitlTierAdvancedEvent``
- ``"hitl.tier.action_executed"`` — ``HitlTierActionExecutedEvent``
- ``"hitl.tier.action_failed"``   — ``HitlTierActionFailedEvent``
- ``"hitl.chain.exhausted"`` — ``HitlChainExhaustedEvent``

FEAT-194 — TASK-1280
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HitlTierEnteredEvent(BaseModel):
    """Emitted when the escalation cursor enters a tier for the first time.

    Attributes:
        interaction_id: UUID of the interaction being escalated.
        policy_id: Identifier of the escalation policy in use.
        tier_level: The tier level being entered (1-based).
        cause: What triggered the entry — ``"initial"`` when the manager
            first resolves the policy; ``"timeout"``, ``"reject"``,
            ``"business_hours_off"``, or ``"action_failed"`` on
            subsequent advances.
        timestamp: UTC datetime of the event.
    """

    event_name: Literal["hitl.tier.entered"] = "hitl.tier.entered"
    interaction_id: str
    policy_id: Optional[str] = None
    tier_level: int
    cause: str
    timestamp: datetime = Field(default_factory=_utcnow)


class HitlTierAdvancedEvent(BaseModel):
    """Emitted when the escalation cursor moves from one tier to another.

    Attributes:
        interaction_id: UUID of the interaction being escalated.
        policy_id: Identifier of the escalation policy in use.
        from_level: The tier level being left.
        to_level: The tier level being entered.
        cause: Why the advance happened — ``"timeout"``, ``"reject"``,
            ``"business_hours_off"``, or ``"action_failed"``.
        timestamp: UTC datetime of the event.
    """

    event_name: Literal["hitl.tier.advanced"] = "hitl.tier.advanced"
    interaction_id: str
    policy_id: Optional[str] = None
    from_level: int
    to_level: int
    cause: str
    timestamp: datetime = Field(default_factory=_utcnow)


class HitlTierActionExecutedEvent(BaseModel):
    """Emitted after a NOTIFY or TICKET action completes successfully.

    Attributes:
        interaction_id: UUID of the interaction.
        policy_id: Escalation policy identifier.
        tier_level: Tier level on which the action ran.
        kind: The action kind (e.g. ``"email"``, ``"zammad"``,
            ``"webhook"``), taken from ``action_metadata.get("kind")``.
        action_metadata: The raw result dict returned by the action
            backend (may contain message, ticket_id, url, etc.).
        timestamp: UTC datetime of the event.
    """

    event_name: Literal["hitl.tier.action_executed"] = "hitl.tier.action_executed"
    interaction_id: str
    policy_id: Optional[str] = None
    tier_level: int
    kind: str
    action_metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utcnow)


class HitlTierActionFailedEvent(BaseModel):
    """Emitted when an action raises an exception or returns ``error=True``.

    Attributes:
        interaction_id: UUID of the interaction.
        policy_id: Escalation policy identifier.
        tier_level: Tier level on which the action failed.
        kind: The action kind that failed.
        reason: Human-readable failure description.
        timestamp: UTC datetime of the event.
    """

    event_name: Literal["hitl.tier.action_failed"] = "hitl.tier.action_failed"
    interaction_id: str
    policy_id: Optional[str] = None
    tier_level: int
    kind: str
    reason: str
    timestamp: datetime = Field(default_factory=_utcnow)


class HitlChainExhaustedEvent(BaseModel):
    """Emitted when the escalation chain terminates after exhausting all tiers.

    Attributes:
        interaction_id: UUID of the interaction.
        policy_id: Escalation policy identifier.
        timestamp: UTC datetime of the event.
    """

    event_name: Literal["hitl.chain.exhausted"] = "hitl.chain.exhausted"
    interaction_id: str
    policy_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=_utcnow)


__all__ = [
    "HitlTierEnteredEvent",
    "HitlTierAdvancedEvent",
    "HitlTierActionExecutedEvent",
    "HitlTierActionFailedEvent",
    "HitlChainExhaustedEvent",
]

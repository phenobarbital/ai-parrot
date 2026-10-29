"""Roost message model and the structural seam over the Squawk envelope (FEAT-747 M1)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from parrot.core.events.lifecycle import TraceContext

from .performatives import CarrierKind, FailureCode, InteractionProtocol, Performative, obligation_for


@runtime_checkable
class EnvelopeLike(Protocol):
    """Fields Roost reads from an envelope."""

    envelope_id: str
    correlation_id: str
    trace: Optional[TraceContext]
    budget_ms: Optional[int]
    token_budget: Optional[int]
    caller: Any
    idempotency_key: Optional[str]


class LocalEnvelope(BaseModel):
    """Roost's minimal envelope, used when the Squawk satellite is absent (resolved Q1)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    envelope_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    correlation_id: str
    trace: Optional[TraceContext] = None
    budget_ms: Optional[int] = None
    token_budget: Optional[int] = None
    caller: str
    idempotency_key: Optional[str] = None


class AgentAddress(BaseModel):
    """Where an agent can be reached: registry name + carrier (+ room id / topic / host id)."""

    name: str
    carrier: CarrierKind = CarrierKind.IN_PROCESS
    endpoint: Optional[str] = None


class FailureInfo(BaseModel):
    """Payload of a ``failure`` act."""

    code: FailureCode
    detail: str = ""
    retryable: bool = False


class RoostMessage(BaseModel):
    """One Roost speech act riding one envelope. ``content`` is by reference; ``body`` is for humans."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    message_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    performative: Performative
    protocol: InteractionProtocol
    conversation_id: str
    in_reply_to: Optional[str] = None
    sender: AgentAddress
    receivers: list[AgentAddress] = Field(default_factory=list)
    capability_filter: Optional[str] = None
    content: Any = None
    content_type: Optional[str] = None
    body: Optional[str] = None
    envelope: Any = None
    failure: Optional[FailureInfo] = None
    permission_context: Any = None
    auth_token: Optional[str] = None
    hops: int = 0
    tokens: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _validate_receivers_or_capability_filter(self) -> "RoostMessage":
        """Require a capability filter for messages without explicit receivers."""
        if not self.receivers and not self.capability_filter:
            raise ValueError("receivers or capability_filter is required")
        return self

    def reply(
        self,
        performative: Performative,
        *,
        content: Any = None,
        body: Optional[str] = None,
        failure: Optional[FailureInfo] = None,
        tokens: int = 0,
    ) -> "RoostMessage":
        """Build a valid reply while retaining the content object by reference.

        Args:
            tokens: Tokens the host spent producing this reply. A wake callback MUST set
                this for ``token_budget`` to be enforceable — the endpoint charges it via
                ``ProtocolEngine.charge`` and cannot observe a provider's usage itself.

        Raises:
            ValueError: The performative is not an allowed reply, or this message has no explicit receiver.
        """
        allowed_replies = obligation_for(self.performative).allowed_replies
        if performative is not Performative.NOT_UNDERSTOOD and performative not in allowed_replies:
            raise ValueError(f"{performative.value} is not allowed in reply to {self.performative.value}")
        if not self.receivers:
            raise ValueError("cannot reply to a capability-filtered broadcast without an explicit receiver")
        return RoostMessage(
            performative=performative,
            protocol=self.protocol,
            conversation_id=self.conversation_id,
            in_reply_to=self.message_id,
            sender=self.receivers[0],
            receivers=[self.sender],
            content=content,
            body=body,
            envelope=self.envelope,
            failure=failure,
            tokens=tokens,
            permission_context=self.permission_context,
            auth_token=self.auth_token,
        )

    def is_addressed_to(self, name: str) -> bool:
        """True when *name* is in ``receivers``; False for capability-filtered broadcasts."""
        return any(receiver.name == name for receiver in self.receivers)

    def trace_id(self) -> Optional[str]:
        """Return ``envelope.trace.trace_id`` when present, else ``None``."""
        trace = getattr(self.envelope, "trace", None)
        return getattr(trace, "trace_id", None)

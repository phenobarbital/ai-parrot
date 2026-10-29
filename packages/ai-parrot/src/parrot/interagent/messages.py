"""Pydantic mirrors of the Squawk message set (squawk.capnp lives in the satellite; these are transport-free)."""

from __future__ import annotations

import secrets
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from parrot.core.events.lifecycle import TraceContext
from parrot.interagent.contract import CapabilityCategory, ContractDelta
from parrot.interagent.errors import SquawkErrorCode
from parrot.interagent.handles import ArtifactHandle
from parrot.interagent.ledger import CallCost, CallerIdentity
from parrot.interagent.provenance import HandleProvenance

PROTOCOL_MAJOR = 1


class Budget(BaseModel):
    """Budget constraints for a capability call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tokens: int | None = None
    ms: int | None = None
    rows: int | None = None


class HelloMessage(BaseModel):
    """Initial handshake message from a client to a server."""

    model_config = ConfigDict(extra="forbid")

    protocol_major: int = PROTOCOL_MAJOR
    agent_id: str
    token: bytes | None = None
    known_hashes: dict[str, str] = Field(default_factory=dict)
    known_digests: tuple[str, ...] = ()
    trace_id: str


class WelcomeMessage(BaseModel):
    """Server response to a successful handshake."""

    model_config = ConfigDict(extra="forbid")

    protocol_major: int = PROTOCOL_MAJOR
    session_id: str
    delta: ContractDelta
    max_frame_bytes: int = Field(ge=1)


class CallMessage(BaseModel):
    """One capability call. Structurally satisfies FEAT-747's EnvelopeLike."""

    model_config = ConfigDict(extra="forbid")

    envelope_id: str
    cap_id: str
    contract_hash: str
    args: bytes
    out_hints: dict[str, Any] = Field(default_factory=dict)
    budget: Budget = Budget()
    trace_id: str
    correlation_id: str
    idempotency_key: str
    reply_to: str | None = None
    caller: CallerIdentity | None = (
        None  # set by the server from the handshake / envelope metadata, never trusted from the payload
    )

    @property
    def trace(self) -> TraceContext:
        """TraceContext for the hop; span_id is fresh per access."""
        return TraceContext(trace_id=self.trace_id, span_id=secrets.token_hex(8))

    @property
    def budget_ms(self) -> int | None:
        """Budget in milliseconds."""
        return self.budget.ms

    @property
    def token_budget(self) -> int | None:
        """Token budget."""
        return self.budget.tokens


class ResultMessage(BaseModel):
    """Result of a capability call."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["OK"] | SquawkErrorCode
    inline: bytes | None = None
    handle: ArtifactHandle | None = None
    transfer: Literal["frames", "skipped", "none"] = "none"
    provenance: HandleProvenance | None = None
    cost: CallCost
    trace_id: str
    correlation_id: str
    detail: str | None = None
    current_category: CapabilityCategory | None = None


class ProgressMessage(BaseModel):
    """Progress update for a long-running operation."""

    model_config = ConfigDict(extra="forbid")

    op_id: str
    phase: str
    frame: bytes | None = None
    frame_index: int = Field(ge=0)
    is_last: bool = False


class CancelMessage(BaseModel):
    """Cancellation request for an in-flight operation."""

    model_config = ConfigDict(extra="forbid")

    op_id: str
    trace_id: str

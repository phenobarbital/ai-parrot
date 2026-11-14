"""Generic gate data model (FEAT-890 M1). Must not import parrot.flows.dev_loop."""

from __future__ import annotations

from enum import Enum
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

GateStatusValue = Literal["pending", "approved", "rejected", "expired"]


class GateErrorCode(str, Enum):
    """Stable error codes emitted by the generic gate host."""

    UNKNOWN_KIND = "UNKNOWN_KIND"
    GATE_KIND_CONFLICT = "GATE_KIND_CONFLICT"
    NOT_FOUND = "NOT_FOUND"
    NOT_PENDING = "NOT_PENDING"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


class GateError(Exception):
    """Typed gate failure carrying a GateErrorCode."""

    def __init__(self, code: GateErrorCode, message: str) -> None:
        """Initialize the failure with its stable code and human-readable message."""
        super().__init__(f"{code.value}: {message}")
        self.code = code


class GateSpec(BaseModel):
    """What to gate on; kind must be registered (kinds.py)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    title: str
    instructions: str = ""
    questions: list[str] = Field(default_factory=list)
    ttl_seconds: int | None = None
    on_expiry: Literal["fail", "approve"] = "fail"
    pre_review: str | None = None


class PreReviewVerdict(BaseModel):
    """Advisory output of a pre_review expert — never resolves a gate (AC4)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    expert: str
    recommendation: Literal["approve", "reject", "unsure"]
    summary: str
    error: str = ""


class GateRecord(BaseModel):
    """Persisted gate state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    gate_id: str
    kind: str
    owner: str
    status: GateStatusValue = "pending"
    spec: GateSpec
    payload_ref: str = ""
    opened_at: float
    expires_at: float | None = None
    resolved_by: str = ""
    resolved_at: float | None = None
    comment: str = ""
    answers: dict[str, str] = Field(default_factory=dict)
    pre_review: PreReviewVerdict | None = None


class GateEvent(BaseModel):
    """Lifecycle event emitted by GateHost."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["opened", "resolved", "expired"]
    record: GateRecord


@runtime_checkable
class GateStore(Protocol):
    """Persistence for gate records (Redis, SQLite; HelixDB deferred — spec §8 Q1)."""

    async def put(self, record: GateRecord) -> None:
        """Persist a gate record."""

    async def get(self, gate_id: str) -> GateRecord | None:
        """Return a gate record by identifier, if it exists."""

    async def pending(self, owner: str | None = None) -> list[GateRecord]:
        """Return pending records, optionally filtered by owner."""

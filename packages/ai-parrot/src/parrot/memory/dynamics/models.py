"""Versioned dynamics state; review evidence is added by the evidence-contract task."""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import IntEnum

from parrot.memory.episodic.models import MemoryNamespace
from pydantic import BaseModel, ConfigDict, Field


FSRS6_REFERENCE = "fsrs-6@v6.3.2:9446cb06605c597a063aeee49f7d188d42e34dc2"
DEFAULT_PARAMETERS = (
    0.212,
    1.2931,
    2.3065,
    8.2956,
    6.4133,
    0.8334,
    3.0194,
    0.001,
    1.8722,
    0.1666,
    0.796,
    1.4835,
    0.0614,
    0.2629,
    1.6483,
    0.6014,
    1.8729,
    0.5425,
    0.0912,
    0.0658,
    0.1542,
)
LOWER_BOUNDS_PARAMETERS = (
    0.001,
    0.001,
    0.001,
    0.001,
    1.0,
    0.001,
    0.001,
    0.001,
    0.0,
    0.0,
    0.001,
    0.001,
    0.001,
    0.001,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.1,
)
UPPER_BOUNDS_PARAMETERS = (
    100.0,
    100.0,
    100.0,
    100.0,
    10.0,
    4.0,
    4.0,
    0.75,
    4.5,
    0.8,
    3.5,
    5.0,
    0.25,
    0.9,
    4.0,
    1.0,
    6.0,
    2.0,
    2.0,
    0.8,
    0.8,
)


class Grade(IntEnum):
    """Ordered FSRS grades, admitted only after evidence verification."""

    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


class MemoryParameters(BaseModel):
    """Immutable algorithm, time-policy and parameter identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    algorithm: str
    time_policy: str
    parameter_id: str = Field(min_length=1)
    weights: tuple[float, ...] = DEFAULT_PARAMETERS
    reference: str = Field(default=FSRS6_REFERENCE, min_length=1)
    provenance: str = Field(min_length=1)

    def __init__(self, **data: object) -> None:
        """Validate the accepted FSRS-6 parameter identity and bounds."""
        super().__init__(**data)
        if self.algorithm != "fsrs-6":
            raise ValueError("algorithm must be fsrs-6")
        if self.time_policy not in {"days-v1", "hours-v1"}:
            raise ValueError("time_policy must be days-v1 or hours-v1")
        if self.reference != FSRS6_REFERENCE:
            raise ValueError("reference must pin the accepted FSRS-6 version")
        if len(self.weights) != len(DEFAULT_PARAMETERS):
            raise ValueError("weights must contain exactly 21 values")
        if any(not lower <= weight <= upper for weight, lower, upper in zip(
            self.weights, LOWER_BOUNDS_PARAMETERS, UPPER_BOUNDS_PARAMETERS
        )):
            raise ValueError("weights must be finite and within the accepted FSRS-6 bounds")


class MemoryState(BaseModel):
    """Persisted state and earned-review count; uninitialized legacy state is neutral."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    difficulty: float | None = None
    stability: float | None = None
    reviewed_at: datetime | None = None
    review_count: int = Field(default=0, ge=0)
    apply_revision: int = Field(default=0, ge=0)
    status: str = Field(default="uninitialized", min_length=1)
    parameter_id: str | None = Field(default=None, min_length=1)

    def __init__(self, **data: object) -> None:
        """Validate neutral legacy state and bounded reviewed state."""
        super().__init__(**data)
        if self.status == "uninitialized":
            if any(value is not None for value in (self.difficulty, self.stability, self.reviewed_at, self.parameter_id)):
                raise ValueError("uninitialized state cannot carry review state or parameter identity")
            if self.review_count != 0:
                raise ValueError("uninitialized state cannot carry earned reviews")
            return
        if self.difficulty is None or not 1.0 <= self.difficulty <= 10.0:
            raise ValueError("difficulty must be finite and within [1.0, 10.0]")
        if self.stability is None or not self.stability >= 0.001:
            raise ValueError("stability must be finite and at least 0.001")
        if self.reviewed_at is None:
            raise ValueError("reviewed state requires reviewed_at")
        offset = self.reviewed_at.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("reviewed_at must be an aware UTC datetime")
        if self.parameter_id is None:
            raise ValueError("reviewed state requires parameter_id")


class MemoryRef(BaseModel):
    """Identify a delivered version inside its full namespace."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    namespace: MemoryNamespace
    kind: str = Field(pattern="^(episode|brain)$")
    memory_id: str = Field(min_length=1)
    content_version: str = Field(min_length=1)

    def __init__(self, **data: object) -> None:
        """Validate version semantics for episode and brain memory references."""
        super().__init__(**data)
        if self.kind == "episode" and self.content_version != "v1":
            raise ValueError("episode content_version must be v1")
        if self.kind == "brain" and (
            len(self.content_version) != 40
            or any(character not in "0123456789abcdef" for character in self.content_version)
        ):
            raise ValueError("brain content_version must be a lowercase SHA-1 digest")

    @property
    def canonical_key(self) -> str:
        """Return the version- and namespace-scoped durable identity key."""
        digest = hashlib.sha256()
        for value in (
            self.namespace.tenant_id,
            self.namespace.agent_id,
            self.namespace.user_id,
            self.namespace.session_id,
            self.namespace.room_id,
            self.namespace.crew_id,
            self.kind,
            self.memory_id,
            self.content_version,
        ):
            encoded = b"\x00" if value is None else b"\x01" + value.encode("utf-8")
            digest.update(len(encoded).to_bytes(4, "big"))
            digest.update(encoded)
        return f"mref-v1-{digest.hexdigest()}"

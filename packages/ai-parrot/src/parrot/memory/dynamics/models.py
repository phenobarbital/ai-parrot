"""Versioned dynamics state; review evidence is added by the evidence-contract task."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from datetime import datetime
from enum import IntEnum
from typing import Literal

from parrot.memory.agent_memory.models import ChatStorageEvidenceRef, MemoryRequestScope
from parrot.memory.episodic.models import MemoryNamespace
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CODER_EVIDENCE_RE = re.compile(r"^coder-review/v1/[^/\s]+/[^/\s]+/[^/\s]+$")
_STRUCTURAL_REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+=-]{0,255}$")


def _require_identifier(value: str, field_name: str) -> str:
    """Require a bounded, non-blank durable identifier."""
    if not value.strip():
        raise ValueError(f"{field_name} must be non-blank")
    return value


def _require_utc(value: datetime) -> datetime:
    """Require an aware UTC timestamp without silently shifting its value."""
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError("timestamps must be aware UTC datetimes")
    return value


def _length_prefixed_hash(values: tuple[str | int | None, ...]) -> str:
    """Hash scope-safe identity components using the accepted binary encoding."""
    digest = hashlib.sha256()
    for value in values:
        encoded = b"\x00" if value is None else b"\x01" + str(value).encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
    return digest.hexdigest()


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
        if any(
            not lower <= weight <= upper
            for weight, lower, upper in zip(self.weights, LOWER_BOUNDS_PARAMETERS, UPPER_BOUNDS_PARAMETERS, strict=True)
        ):
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
            if any(
                value is not None for value in (self.difficulty, self.stability, self.reviewed_at, self.parameter_id)
            ):
                raise ValueError("uninitialized state cannot carry review state or parameter identity")
            if self.review_count != 0:
                raise ValueError("uninitialized state cannot carry earned reviews")
            return
        if self.difficulty is None or not 1.0 <= self.difficulty <= 10.0:
            raise ValueError("difficulty must be finite and within [1.0, 10.0]")
        if self.stability is None or not math.isfinite(self.stability) or self.stability < 0.001:
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


class MemoryExposure(BaseModel):
    """Runtime-minted manifest of memory actually delivered in one model attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exposure_id: str = Field(min_length=1)
    scope: MemoryRequestScope
    attempt_id: str = Field(min_length=1)
    refs: tuple[MemoryRef, ...] = Field(max_length=64)
    packed_digest: str

    @field_validator("exposure_id", "attempt_id")
    @classmethod
    def _validate_identifiers(cls, value: str, info: object) -> str:
        return _require_identifier(value, getattr(info, "field_name", "identifier"))

    @field_validator("refs")
    @classmethod
    def _validate_refs(cls, refs: tuple[MemoryRef, ...]) -> tuple[MemoryRef, ...]:
        if len({ref.canonical_key for ref in refs}) != len(refs):
            raise ValueError("exposure refs must be unique")
        return refs

    @field_validator("packed_digest")
    @classmethod
    def _validate_packed_digest(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("packed_digest must be a lowercase SHA-256 hex digest")
        return value


class MemoryCitation(BaseModel):
    """A subset of a delivered manifest; a citation never assigns a grade."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exposure_id: str = Field(min_length=1)
    refs: tuple[MemoryRef, ...] = Field(max_length=64)

    @field_validator("exposure_id")
    @classmethod
    def _validate_exposure_id(cls, value: str) -> str:
        return _require_identifier(value, "exposure_id")

    @field_validator("refs")
    @classmethod
    def _validate_refs(cls, refs: tuple[MemoryRef, ...]) -> tuple[MemoryRef, ...]:
        if len({ref.canonical_key for ref in refs}) != len(refs):
            raise ValueError("citation refs must be unique")
        return refs


class ReviewSignal(BaseModel):
    """Immutable observed outcome with engine-verifiable provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome_id: str = Field(min_length=1)
    outcome_revision: int = Field(ge=0)
    observed_at: datetime
    scope: MemoryRequestScope
    evidence_ref: str = Field(min_length=1)
    source: Literal["tool_runtime", "coder_engine"]
    outcome: Literal["success", "failure", "cancelled", "incomplete"]
    first_attempt: bool
    correction_count: int = Field(ge=0)
    error_signature: str | None = None
    recovery_refs: tuple[str, ...] = Field(default=(), max_length=16)
    passed_check_ids: tuple[str, ...] = Field(default=(), max_length=16)

    @field_validator("outcome_id")
    @classmethod
    def _validate_outcome_id(cls, value: str) -> str:
        return _require_identifier(value, "outcome_id")

    @field_validator("observed_at")
    @classmethod
    def _validate_observed_at(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @field_validator("error_signature")
    @classmethod
    def _normalize_error_signature(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(unicodedata.normalize("NFKC", value).lower().split())
        if len(normalized) > 200:
            raise ValueError("error_signature must contain at most 200 characters")
        return normalized

    @field_validator("recovery_refs", "passed_check_ids")
    @classmethod
    def _validate_structural_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not _STRUCTURAL_REFERENCE_RE.fullmatch(value) for value in values):
            raise ValueError("recovery and passed-check references must be structural identifiers")
        return values

    @model_validator(mode="after")
    def _validate_evidence(self) -> "ReviewSignal":
        if self.evidence_ref.startswith("chatstorage/v1/"):
            reference = ChatStorageEvidenceRef.parse(self.evidence_ref)
            if (
                reference.tenant_id,
                reference.agent_name,
                reference.user_id,
                reference.session_id,
            ) != (
                self.scope.tenant_id,
                self.scope.agent_id,
                self.scope.user_id,
                self.scope.session_id,
            ):
                raise ValueError("ChatStorage evidence reference must match the request scope")
        elif not _CODER_EVIDENCE_RE.fullmatch(self.evidence_ref):
            raise ValueError("evidence_ref must be a ChatStorage or coder review reference")
        if self.outcome == "failure" and not self.error_signature:
            raise ValueError("failure outcomes require an error_signature")
        if self.outcome != "failure" and self.error_signature is not None:
            raise ValueError("only failure outcomes may carry an error_signature")
        if self.source == "coder_engine" and not self.passed_check_ids:
            raise ValueError("coder_engine evidence requires a passed check identifier")
        return self

    @property
    def can_review(self) -> bool:
        """Return whether this outcome may enter a durable state transition."""
        return self.outcome not in {"cancelled", "incomplete"}


class ReviewCommand(BaseModel):
    """Validated version-specific request for one atomic state transition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: MemoryRef
    signal: ReviewSignal
    exposure_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)

    @field_validator("exposure_id")
    @classmethod
    def _validate_exposure_id(cls, value: str) -> str:
        return _require_identifier(value, "exposure_id")

    @model_validator(mode="after")
    def _validate_scope_and_outcome(self) -> "ReviewCommand":
        if (
            self.ref.namespace.tenant_id,
            self.ref.namespace.agent_id,
            self.ref.namespace.user_id,
            self.ref.namespace.session_id,
        ) != (
            self.signal.scope.tenant_id,
            self.signal.scope.agent_id,
            self.signal.scope.user_id,
            self.signal.scope.session_id,
        ):
            raise ValueError("review ref namespace must match the signal scope")
        if not self.signal.can_review:
            raise ValueError("cancelled and incomplete outcomes cannot produce a review")
        return self

    @property
    def dedupe_key(self) -> str:
        """Return the scoped idempotency identity for this review command."""
        return "rdk-v1-" + _length_prefixed_hash(
            (
                self.signal.scope.tenant_id,
                self.signal.scope.agent_id,
                self.signal.scope.user_id,
                self.signal.scope.session_id,
                self.signal.outcome_id,
                self.signal.outcome_revision,
                self.ref.canonical_key,
            )
        )

    @property
    def payload_digest(self) -> str:
        """Return the canonical payload digest used to distinguish dedupe conflicts."""
        canonical_json = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class ReviewRecord(BaseModel):
    """Replayable evidence and before/after state for a committed application."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    command: ReviewCommand
    before: MemoryState
    after: MemoryState
    parameter_id: str = Field(min_length=1)

    @field_validator("parameter_id")
    @classmethod
    def _validate_parameter_id(cls, value: str) -> str:
        return _require_identifier(value, "parameter_id")


class ReviewReceipt(BaseModel):
    """Report durable application, duplicate, conflict or no-review without false success."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal[
        "applied", "duplicate", "conflict", "stale_revision", "ignored", "pending", "storage_unavailable"
    ]
    dedupe_key: str = Field(min_length=1)
    outcome_id: str = Field(min_length=1)
    ref_key: str = Field(min_length=1)
    reason: str | None = None
    apply_revision: int | None = Field(default=None, ge=0)
    replay_ref: str | None = None

    @field_validator("dedupe_key", "outcome_id", "ref_key")
    @classmethod
    def _validate_identifiers(cls, value: str, info: object) -> str:
        return _require_identifier(value, getattr(info, "field_name", "identifier"))

    @field_validator("replay_ref")
    @classmethod
    def _validate_replay_ref(cls, value: str | None) -> str | None:
        if value is not None:
            return _require_identifier(value, "replay_ref")
        return value

    @model_validator(mode="after")
    def _validate_status_invariants(self) -> "ReviewReceipt":
        if self.status in {"applied", "duplicate"} and self.apply_revision is None:
            raise ValueError(f"{self.status} receipts require apply_revision")
        if self.status == "pending" and self.replay_ref is None:
            raise ValueError("pending receipts require a durable replay_ref")
        if self.status in {"storage_unavailable", "conflict"} and self.apply_revision is not None:
            raise ValueError(f"{self.status} receipts cannot carry apply_revision")
        return self


class CheckedPattern(BaseModel):
    """Untrusted application claim to be checked against engine-owned evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern: str = Field(min_length=1, max_length=500)
    ref: MemoryRef
    exposure_id: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(default=(), max_length=16)

    @field_validator("pattern", "exposure_id")
    @classmethod
    def _validate_claim_identifiers(cls, value: str, info: object) -> str:
        return _require_identifier(value, getattr(info, "field_name", "claim"))

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, refs: tuple[str, ...]) -> tuple[str, ...]:
        if any(not _STRUCTURAL_REFERENCE_RE.fullmatch(reference) for reference in refs):
            raise ValueError("evidence_refs must contain structural identifiers")
        return refs

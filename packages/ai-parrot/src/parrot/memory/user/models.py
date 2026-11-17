"""Cross-session user knowledge, candidates, commands and durable receipts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_VALUE_CHARS = 2048
MAX_KEY_CHARS = 128
MAX_CONTEXT_ITEMS = 8
MAX_CONTEXT_CHARS = 128
MAX_EVIDENCE_REFS = 32
MAX_EVIDENCE_CHARS = 256


def _check_value(value: Any) -> Any:
    """Require a JSON-serializable value within the bounded size."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, default=None)
    except (TypeError, ValueError) as exc:
        raise ValueError("value must be JSON serializable") from exc
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError("value must not be empty")
    if len(encoded) > MAX_VALUE_CHARS:
        raise ValueError(f"value exceeds {MAX_VALUE_CHARS} serialized characters")
    return value


def _check_key(key: str | None) -> str | None:
    """Normalize and bound an optional key."""
    if key is None:
        return None
    normalized = " ".join(key.strip().lower().split())
    if not normalized or len(normalized) > MAX_KEY_CHARS:
        raise ValueError(f"normalized_key must be 1..{MAX_KEY_CHARS} characters")
    return normalized


def _check_context(context: dict[str, str]) -> dict[str, str]:
    """Bound context size and entry lengths."""
    if len(context) > MAX_CONTEXT_ITEMS:
        raise ValueError(f"context allows at most {MAX_CONTEXT_ITEMS} entries")
    for key, item in context.items():
        if not key.strip() or len(key) > MAX_CONTEXT_CHARS or len(item) > MAX_CONTEXT_CHARS:
            raise ValueError("context keys and values must be non-blank and bounded")
    return context


def _check_evidence(refs: tuple[str, ...]) -> tuple[str, ...]:
    """Bound evidence references and reject blank entries."""
    if len(refs) > MAX_EVIDENCE_REFS:
        raise ValueError(f"at most {MAX_EVIDENCE_REFS} evidence references are allowed")
    if any(not ref.strip() or len(ref) > MAX_EVIDENCE_CHARS for ref in refs):
        raise ValueError("evidence references must be non-blank and bounded")
    return refs


def _utc_exact(value: datetime | None) -> datetime | None:
    """Require an aware UTC datetime."""
    if value is None:
        return None
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError("timestamps must be aware UTC datetimes")
    return value


class UserKnowledge(BaseModel):
    """A scoped fact with independent provenance, revision and validity."""

    model_config = ConfigDict(extra="forbid")

    knowledge_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    kind: Literal["fact", "preference", "goal", "constraint"]
    normalized_key: str | None = None
    value: Any
    context: dict[str, str] = Field(default_factory=dict)
    provenance: Literal["explicit", "inferred"]
    evidence_refs: tuple[str, ...] = ()
    status: Literal["active", "pending", "superseded", "invalidated"]
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None = None
    valid_from: datetime | None = None
    expires_at: datetime | None = None
    revision: int = Field(ge=0)
    supersedes_id: str | None = None

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value: Any) -> Any:
        return _check_value(value)

    @field_validator("normalized_key")
    @classmethod
    def _validate_key(cls, key: str | None) -> str | None:
        return _check_key(key)

    @field_validator("context")
    @classmethod
    def _validate_context(cls, context: dict[str, str]) -> dict[str, str]:
        return _check_context(context)

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence(cls, refs: tuple[str, ...]) -> tuple[str, ...]:
        return _check_evidence(refs)

    @field_validator("created_at", "updated_at", "confirmed_at", "valid_from", "expires_at")
    @classmethod
    def _validate_utc(cls, value: datetime | None) -> datetime | None:
        return _utc_exact(value)

    @model_validator(mode="after")
    def _validate_consistency(self) -> UserKnowledge:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if self.valid_from and self.expires_at and self.expires_at <= self.valid_from:
            raise ValueError("expires_at must be after valid_from")
        if self.provenance == "inferred" and self.status == "active" and self.confirmed_at is None:
            raise ValueError("inferred knowledge stays pending until confirmed")
        return self


class UserKnowledgeCandidate(BaseModel):
    """A bounded extraction proposal; it cannot choose its trusted principal."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["fact", "preference", "goal", "constraint"]
    value: Any
    provenance: Literal["explicit", "inferred"]
    evidence_refs: tuple[str, ...]
    context: dict[str, str] = Field(default_factory=dict)
    normalized_key: str | None = None
    valid_from: datetime | None = None
    expires_at: datetime | None = None

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value: Any) -> Any:
        return _check_value(value)

    @field_validator("normalized_key")
    @classmethod
    def _validate_key(cls, key: str | None) -> str | None:
        return _check_key(key)

    @field_validator("context")
    @classmethod
    def _validate_context(cls, context: dict[str, str]) -> dict[str, str]:
        return _check_context(context)

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence(cls, refs: tuple[str, ...]) -> tuple[str, ...]:
        if not refs:
            raise ValueError("a candidate needs at least one evidence reference")
        return _check_evidence(refs)

    @field_validator("valid_from", "expires_at")
    @classmethod
    def _validate_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(timezone.utc) if value is not None else None

    @model_validator(mode="after")
    def _validate_window(self) -> UserKnowledgeCandidate:
        if self.valid_from and self.expires_at and self.expires_at <= self.valid_from:
            raise ValueError("expires_at must be after valid_from")
        return self

    @property
    def initial_status(self) -> Literal["active", "pending"]:
        """Return the admission status: explicit may be active, inferred is pending."""
        return "active" if self.provenance == "explicit" else "pending"


class UserKnowledgeCommand(BaseModel):
    """Idempotent revision-checked operation applied under a separate trusted scope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(min_length=1, max_length=256)
    knowledge_id: str | None = None
    expected_revision: int | None = Field(default=None, ge=0)
    candidate: UserKnowledgeCandidate | None = None
    operation: Literal["upsert", "correct", "forget"] = "upsert"
    evidence_refs: tuple[str, ...] = ()

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence(cls, refs: tuple[str, ...]) -> tuple[str, ...]:
        return _check_evidence(refs)

    @model_validator(mode="after")
    def _validate_operation(self) -> UserKnowledgeCommand:
        if not self.event_id.strip():
            raise ValueError("event_id must be non-blank")
        if self.operation == "upsert":
            if self.candidate is None or self.knowledge_id is not None:
                raise ValueError("upsert needs a candidate and no knowledge_id")
        else:
            if self.knowledge_id is None or self.expected_revision is None:
                raise ValueError(f"{self.operation} needs knowledge_id and expected_revision")
            if self.operation == "correct" and self.candidate is None:
                raise ValueError("correct needs a candidate")
            if self.operation == "forget" and self.candidate is not None:
                raise ValueError("forget takes no candidate")
        return self


class UserMemoryReceipt(BaseModel):
    """Acknowledge only committed changes; duplicate/conflict retain their identities."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    knowledge_id: str | None = None
    revision: int | None = None
    status: Literal["applied", "duplicate", "conflict", "ignored", "storage_unavailable"]

"""Independent persistent-memory configuration and trusted invocation data."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Literal
from urllib.parse import quote, unquote

from pydantic import BaseModel, ConfigDict, Field

CHAT_STORAGE_REF_PREFIX = "chatstorage/v1/"


class AgentMemoryConfig(BaseModel):
    """Configure capabilities without coupling user knowledge to episodes."""

    model_config = ConfigDict(extra="forbid")

    enable_episodic_memory: bool = False
    enable_user_memory: bool = False
    enable_brain: bool = False
    memory_dynamics: bool = False
    max_context_tokens: int = Field(default=2000, ge=0)
    episodic_context_tokens: int = Field(default=600, ge=0)
    user_context_tokens: int = Field(default=600, ge=0)
    user_memory_priority: Literal["high", "normal"] = "high"
    brain_context_tokens: int = Field(default=400, ge=0)
    skills_context_tokens: int = Field(default=400, ge=0)
    include_relevant_skills: bool = False
    episodic_backend: Literal["sqlite"] = "sqlite"
    storage_path: str | None = None
    enable_reflection: bool = True
    max_episodic_warnings: int = Field(default=3, ge=0)
    max_episodic_recall: int = Field(default=3, ge=0)
    max_user_records: int = Field(default=20, ge=0, le=100)
    suppress_trivial_tools: bool = True
    flush_on_startup: bool = False

    def __init__(self, **data: Any) -> None:
        """Reject removed flags with their explicit capability replacements."""
        if "enable_long_term_memory" in data:
            raise ValueError(
                "enable_long_term_memory is removed; use enable_episodic_memory and/or enable_user_memory instead"
            )
        super().__init__(**data)

    @property
    def effective_episodic_memory(self) -> bool:
        """Return whether episodic storage is required by enabled capabilities."""
        return self.enable_episodic_memory or self.enable_brain


class MemoryRequestScope(BaseModel):
    """Carry immutable runtime-derived identity; missing identity never names a profile."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    user_id: str | None = None
    session_id: str | None = None
    room_id: str | None = None
    crew_id: str | None = None
    model_id: str | None = None
    execution_id: str | None = None
    turn_id: str = Field(min_length=1)
    identity_provenance: Literal["server_resolved", "runtime_derived"]

    def __init__(self, **data: Any) -> None:
        """Reject blank trusted identity dimensions before they can name a scope."""
        super().__init__(**data)
        required_values = (self.tenant_id, self.agent_id, self.turn_id)
        optional_values = (
            self.user_id,
            self.session_id,
            self.room_id,
            self.crew_id,
            self.model_id,
            self.execution_id,
        )
        if any(not value.strip() for value in required_values) or any(
            value is not None and not value.strip() for value in optional_values
        ):
            raise ValueError("memory scope identifiers must be non-blank when present")

    def response_event_id(self) -> str:
        """Derive the retry-stable response event ID (spec F3).

        The ID is a pure function of ``(agent_id, user_id, session_id, turn_id)``, so a retried
        turn is the same event. Each field is length-prefixed and an absent ``user_id`` or
        ``session_id`` is encoded distinctly from an empty value, so no two tuples collide.
        """
        digest = hashlib.sha256()
        for value in (self.agent_id, self.user_id, self.session_id, self.turn_id):
            encoded = b"\x00" if value is None else b"\x01" + value.encode("utf-8")
            digest.update(len(encoded).to_bytes(4, "big"))
            digest.update(encoded)
        return f"resp-{digest.hexdigest()}"


class ChatStorageEvidenceRef(BaseModel):
    """Name one ChatStorage turn together with the tenant that owns it (spec F7)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str = Field(min_length=1)
    agent_name: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)

    def __init__(self, **data: Any) -> None:
        """Reject blank identity dimensions that could name another tenant's turn."""
        super().__init__(**data)
        if any(not value.strip() for value in self._parts()):
            raise ValueError("evidence reference identifiers must be non-blank")

    def _parts(self) -> tuple[str, ...]:
        return (self.tenant_id, self.agent_name, self.user_id, self.session_id, self.turn_id)

    def to_reference(self) -> str:
        """Render the reference string stored in ``MemoryEvent.evidence_refs``."""
        return CHAT_STORAGE_REF_PREFIX + "/".join(quote(part, safe="") for part in self._parts())

    @classmethod
    def parse(cls, reference: str) -> "ChatStorageEvidenceRef":
        """Parse a reference string; a missing tenant or wrong arity is an error."""
        if not reference.startswith(CHAT_STORAGE_REF_PREFIX):
            raise ValueError("not a ChatStorage evidence reference")
        parts = reference[len(CHAT_STORAGE_REF_PREFIX) :].split("/")
        if len(parts) != 5:
            raise ValueError("ChatStorage evidence reference must carry tenant, agent, user, session and turn")
        tenant_id, agent_name, user_id, session_id, turn_id = (unquote(part) for part in parts)
        return cls(tenant_id=tenant_id, agent_name=agent_name, user_id=user_id, session_id=session_id, turn_id=turn_id)


class MemoryEvent(BaseModel):
    """Identify one observed tool attempt, response or knowledge event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(min_length=1, max_length=256)
    kind: Literal["tool", "response", "user_knowledge"]
    scope: MemoryRequestScope
    observed_at: datetime
    evidence_refs: tuple[str, ...] = Field(default=(), max_length=32)
    payload: dict[str, Any] = Field(default_factory=dict, max_length=32)

    def __init__(self, **data: Any) -> None:
        """Validate retry identity and bounded event data after parsing."""
        super().__init__(**data)
        if not self.event_id.strip():
            raise ValueError("event_id must be non-blank")
        if any(not reference.strip() for reference in self.evidence_refs):
            raise ValueError("evidence references must be non-blank")
        for reference in self.evidence_refs:
            if reference.startswith(CHAT_STORAGE_REF_PREFIX):
                ChatStorageEvidenceRef.parse(reference)
        offset = self.observed_at.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("observed_at must be an aware UTC datetime")


class MemoryWriteReceipt(BaseModel):
    """Report committed effects and constituent failures without false acknowledgement."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(min_length=1, max_length=256)
    scope: MemoryRequestScope
    status: Literal["applied", "duplicate", "conflict", "ignored", "storage_unavailable"]
    episode_ids: tuple[str, ...] = ()
    knowledge_ids: tuple[str, ...] = ()
    review_ids: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()

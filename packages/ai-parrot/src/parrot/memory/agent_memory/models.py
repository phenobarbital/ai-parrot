"""Independent persistent-memory configuration and trusted invocation data."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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

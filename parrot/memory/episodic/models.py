"""Episodic Memory data models, enums, and namespace types.

This module defines the foundational types for the episodic memory system:
- Episode content and classification enums
- EpisodicMemory model (main entity)
- MemoryNamespace for hierarchical scoping
- EpisodeSearchResult for ranked search returns
- ReflectionResult for LLM-generated reflections
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EpisodeOutcome(str, Enum):
    """Outcome classification for an episode."""

    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    TIMEOUT = "timeout"


class EpisodeCategory(str, Enum):
    """Category classification for an episode."""

    TOOL_EXECUTION = "tool_execution"
    QUERY_RESOLUTION = "query_resolution"
    ERROR_RECOVERY = "error_recovery"
    USER_PREFERENCE = "user_preference"
    WORKFLOW_PATTERN = "workflow_pattern"
    DECISION = "decision"
    HANDOFF = "handoff"


class ReflectionResult(BaseModel):
    """Result of LLM or heuristic reflection on an episode."""

    reflection: str = Field(
        ..., description="Brief analysis of what happened"
    )
    lesson_learned: str = Field(
        ..., description="Concise actionable lesson (max ~100 chars)"
    )
    suggested_action: str = Field(
        ..., description="What to do differently next time"
    )


class EpisodicMemory(BaseModel):
    """A single episodic memory record.

    Captures what the agent did, what happened, and what it learned,
    with dimensional namespace fields for scoped retrieval.
    """

    # Identity
    episode_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique episode identifier (UUID)",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the episode was recorded",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the episode was last updated",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="When the episode expires (nullable, for TTL)",
    )

    # Namespace dimensions
    tenant_id: str = Field(
        default="default", description="Multi-tenant isolation"
    )
    agent_id: str = Field(
        ..., description="Agent that generated the episode"
    )
    user_id: str | None = Field(
        default=None, description="User the agent interacted with"
    )
    session_id: str | None = Field(
        default=None, description="Conversation session"
    )
    room_id: str | None = Field(
        default=None, description="Matrix/Telegram/Slack room or channel"
    )
    crew_id: str | None = Field(
        default=None, description="Crew this episode belongs to"
    )

    # Episode content
    situation: str = Field(
        ..., description="What was happening (context)"
    )
    action_taken: str = Field(
        ..., description="What the agent did"
    )
    outcome: EpisodeOutcome = Field(
        ..., description="Result classification"
    )
    outcome_details: str | None = Field(
        default=None, description="Detailed result description"
    )
    error_type: str | None = Field(
        default=None, description="Error type if outcome is failure"
    )
    error_message: str | None = Field(
        default=None, description="Error message if outcome is failure"
    )

    # Reflection (LLM-generated or heuristic)
    reflection: str | None = Field(
        default=None, description="Analysis of what happened"
    )
    lesson_learned: str | None = Field(
        default=None, description="Concise actionable lesson"
    )
    suggested_action: str | None = Field(
        default=None, description="What to do differently next time"
    )

    # Classification
    category: EpisodeCategory = Field(
        default=EpisodeCategory.TOOL_EXECUTION,
        description="Episode category",
    )
    importance: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Importance score (1=trivial, 10=critical)",
    )
    is_failure: bool = Field(
        default=False, description="Whether this episode is a failure"
    )
    related_tools: list[str] = Field(
        default_factory=list,
        description="Tool names involved in this episode",
    )
    related_entities: list[str] = Field(
        default_factory=list,
        description="Entities mentioned (users, tables, APIs, etc.)",
    )

    # Vector embedding
    embedding: list[float] | None = Field(
        default=None,
        description="Vector embedding for similarity search",
        exclude=True,
    )

    # Extensible metadata
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary additional data",
    )

    def searchable_text(self) -> str:
        """Build text for embedding generation.

        Concatenates situation, action, and lesson for optimal retrieval.
        """
        parts = [self.situation, self.action_taken]
        if self.lesson_learned:
            parts.append(self.lesson_learned)
        return " | ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage.

        Includes embedding (excluded from default model_dump).
        Converts datetimes to ISO strings and enums to values.
        """
        data = self.model_dump(mode="json")
        if self.embedding is not None:
            data["embedding"] = self.embedding
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EpisodicMemory:
        """Deserialize from a storage dict.

        Args:
            data: Dictionary with episode fields.

        Returns:
            EpisodicMemory instance.
        """
        return cls.model_validate(data)


class EpisodeSearchResult(EpisodicMemory):
    """An episodic memory with a similarity score from search."""

    score: float = Field(
        ...,
        ge=0.0,
        le=1.01,
        description="Similarity score (0=no match, ~1=exact). Slightly above 1.0 possible due to float precision.",
    )


class MemoryNamespace(BaseModel):
    """Hierarchical namespace for isolating episodes.

    Supports queries at different granularity levels:
    - Global agent: (tenant_id, agent_id)
    - Per-user: (tenant_id, agent_id, user_id)
    - Per-room: (tenant_id, agent_id, room_id)
    - Per-session: (tenant_id, agent_id, user_id, session_id)
    - Per-crew: (tenant_id, crew_id)
    """

    tenant_id: str = Field(
        default="default", description="Multi-tenant isolation"
    )
    agent_id: str = Field(
        ..., description="Agent identifier"
    )
    user_id: str | None = Field(
        default=None, description="User scope"
    )
    session_id: str | None = Field(
        default=None, description="Session scope"
    )
    room_id: str | None = Field(
        default=None, description="Room/channel scope"
    )
    crew_id: str | None = Field(
        default=None, description="Crew scope"
    )

    def build_filter(self) -> dict[str, Any]:
        """Generate a filter dict for backend queries.

        Only includes non-None dimension fields. Backends use this
        to build SQL WHERE clauses or post-search filters.

        Returns:
            Dict of field_name → value for filtering.
        """
        filters: dict[str, Any] = {
            "tenant_id": self.tenant_id,
            "agent_id": self.agent_id,
        }
        if self.user_id is not None:
            filters["user_id"] = self.user_id
        if self.session_id is not None:
            filters["session_id"] = self.session_id
        if self.room_id is not None:
            filters["room_id"] = self.room_id
        if self.crew_id is not None:
            filters["crew_id"] = self.crew_id
        return filters

    @property
    def scope_label(self) -> str:
        """Human-readable label for this namespace scope."""
        if self.session_id:
            return f"session:{self.session_id}"
        if self.room_id:
            return f"room:{self.room_id}"
        if self.user_id:
            return f"user:{self.user_id}"
        if self.crew_id:
            return f"crew:{self.crew_id}"
        return f"agent:{self.agent_id}"

    @property
    def redis_prefix(self) -> str:
        """Redis key prefix for this namespace."""
        parts = [self.tenant_id, self.agent_id]
        if self.room_id:
            parts.append(f"room:{self.room_id}")
        elif self.user_id:
            parts.append(f"user:{self.user_id}")
        return ":".join(parts)

"""Suspended-execution store for the stateless Web HITL suspend/resume path.

FEAT-204 / TASK-1380

When an agent tool raises :class:`~parrot.core.exceptions.HumanInteractionInterrupt`
in SUSPEND mode, the HTTP handler must serialise the in-flight tool-loop state
so a later ``hitl_response`` request can reload it and call ``agent.resume()``.

This module provides:

* :class:`SuspendedExecution` — Pydantic v2 model holding the tool-loop state
  blob (messages, tool_call_id, agent_name, session_id, user_id).
* :class:`SuspendedExecutionStore` — thin Redis-backed store that saves/loads
  blobs under ``hitl:suspended:{interaction_id}`` with a TTL aligned to the
  matching ``hitl:interaction:{id}`` key.

The ``delete`` method removes ONLY the suspended key — the interaction key is
left intact so that the escalation sweeper (future feature) can still observe
pending interactions via TTL expiry.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


__all__ = ["SuspendedExecution", "SuspendedExecutionStore"]


class SuspendedExecution(BaseModel):
    """Tool-loop state blob for a suspended HITL interaction.

    Persisted to ``hitl:suspended:{interaction_id}`` in Redis with a TTL
    aligned to ``hitl:interaction:{id}`` (via
    :meth:`HumanInteractionManager._compute_ttl`).  Rehydrated by the resume
    branch of ``AgentTalk.post`` so ``agent.resume()`` can inject the human's
    answer as the ``tool_result`` of the pending ``ask_human`` call.

    Attributes:
        interaction_id: UUID of the pending :class:`~parrot.human.models.HumanInteraction`.
        session_id: Agent session identifier (forwarded to ``agent.resume``).
        user_id: Authenticated user who initiated the chat request.
        agent_name: Name of the agent that was running when the interrupt fired.
        tool_call_id: LLM tool-call ID of the pending ``ask_human`` invocation.
        messages: Provider-shaped message history at the point of suspension.
            Stored as-is; ``agent.resume`` replays them without re-encoding.
        created_at: UTC timestamp of when this record was created.
    """

    interaction_id: str
    session_id: str
    user_id: str
    agent_name: str
    tool_call_id: str
    messages: list[dict[str, Any]]
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class SuspendedExecutionStore:
    """Redis-backed store for :class:`SuspendedExecution` blobs.

    Key format: ``hitl:suspended:{interaction_id}``

    TTL is caller-provided (use
    :meth:`~parrot.human.manager.HumanInteractionManager._compute_ttl` so
    the suspended blob expires coherently with the interaction).

    The ``delete`` method removes ONLY the suspended key — ``hitl:interaction:{id}``
    is deliberately left intact (escalation seam; TTL-owned expiry).

    Args:
        redis: An ``redis.asyncio`` client (``decode_responses=True`` recommended).

    Example::

        store = SuspendedExecutionStore(redis_client)
        await store.save(record, ttl=7260)
        loaded = await store.load(record.interaction_id)
        await store.delete(record.interaction_id)
    """

    def __init__(self, redis: Any) -> None:
        self.redis = redis
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _key(interaction_id: str) -> str:
        """Return the Redis key for a suspended execution.

        Args:
            interaction_id: UUID of the pending interaction.

        Returns:
            The Redis key string ``hitl:suspended:{interaction_id}``.
        """
        return f"hitl:suspended:{interaction_id}"

    async def save(self, record: SuspendedExecution, ttl: int) -> None:
        """Persist a suspended-execution record to Redis with TTL.

        Args:
            record: The :class:`SuspendedExecution` to persist.
            ttl: Time-to-live in seconds (should match the interaction TTL).
                Values <= 0 are replaced with a 7260-second (2h+60s) fallback
                to prevent ``redis.exceptions.ResponseError`` from ``SETEX``
                with a non-positive TTL.
        """
        if ttl <= 0:
            self.logger.warning(
                "SuspendedExecutionStore.save: non-positive ttl=%d for %s; "
                "using defensive fallback of 7260s",
                ttl,
                record.interaction_id,
            )
            ttl = 7260  # 2h + 60s defensive fallback
        key = self._key(record.interaction_id)
        payload = record.model_dump_json()
        await self.redis.setex(key, ttl, payload)
        self.logger.debug(
            "SuspendedExecutionStore: saved %s (ttl=%ds)", key, ttl
        )

    async def load(self, interaction_id: str) -> Optional[SuspendedExecution]:
        """Load a suspended-execution record from Redis.

        Args:
            interaction_id: UUID of the pending interaction.

        Returns:
            The :class:`SuspendedExecution` if found, ``None`` if expired or
            not yet saved.
        """
        key = self._key(interaction_id)
        raw = await self.redis.get(key)
        if raw is None:
            self.logger.debug(
                "SuspendedExecutionStore: %s not found (expired or missing)", key
            )
            return None
        record = SuspendedExecution.model_validate_json(raw)
        self.logger.debug("SuspendedExecutionStore: loaded %s", key)
        return record

    async def delete(self, interaction_id: str) -> None:
        """Remove the suspended-execution key from Redis.

        This removes ONLY ``hitl:suspended:{interaction_id}``.  The
        ``hitl:interaction:{id}`` key is left intact so the escalation sweeper
        (future feature) can still observe pending interactions via TTL expiry.

        Args:
            interaction_id: UUID of the pending interaction.
        """
        key = self._key(interaction_id)
        await self.redis.delete(key)
        self.logger.debug("SuspendedExecutionStore: deleted %s", key)

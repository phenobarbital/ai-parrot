"""Hydration protocol: source interface, typed outcomes and sequence allocation (FEAT-886 M13).

The bot consults an injected :class:`HydrationSource` on a history miss and never imports ``ChatStorage``.
This module defines no storage logic; ``parrot.storage.hydration.ChatStorageHydrationSource`` implements it.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from .abstract import ConversationTurn


class HydrationError(Exception):
    """Base class for hydration outcomes that are neither a hit nor an empty history."""


class HydrationUnavailableError(HydrationError):
    """The source could not be read (transport / backend failure). Retryable on a later round."""


class HydrationNotReadyError(HydrationError):
    """The chronological index is not backfilled yet. Retryable once the backfill completes."""


class SessionDeletedError(HydrationError):
    """The conversation identity is tombstoned. Terminal: never hydrate, never retry."""


class HydrationSource(ABC):
    """Where a bot fetches a budget-sized window of past turns on a history miss."""

    @abstractmethod
    async def load_turns(
        self, agent_name: str, user_id: str, session_id: str, max_turns: int
    ) -> Optional[List[ConversationTurn]]:
        """Newest ``max_turns`` turns, ascending. ``None`` = active session with no retained turns.

        Raises one of the three :class:`HydrationError` subclasses; never returns ``[]`` or ``None`` for a
        failure, a deleted session or an unready index.
        """

    @abstractmethod
    async def is_deleted(self, agent_name: str, user_id: str, session_id: str) -> bool:
        """Authoritative deletion guard. Raises :class:`HydrationUnavailableError` if it cannot be determined."""

    @abstractmethod
    async def max_sequence(self, agent_name: str, user_id: str, session_id: str) -> int:
        """Durable maximum sequence for the session (0 when none), for allocator recovery."""


class SequenceAllocator(ABC):
    """Monotonic per-``(agent, user, session)`` sequence shared by every worker."""

    @abstractmethod
    async def next(
        self,
        agent_name: str,
        user_id: str,
        session_id: str,
        *,
        floor: Optional[Callable[[], Awaitable[int]]] = None,
    ) -> int:
        """Next sequence, strictly greater than every value issued before.

        When the counter does not exist it is initialised from ``floor()`` (the durable maximum).
        """


class LocalSequenceAllocator(SequenceAllocator):
    """Per-process allocator for in-memory / file memory (no cross-worker guarantee)."""

    def __init__(self) -> None:
        self._counters: Dict[Tuple[str, str, str], int] = {}
        self._locks: Dict[Tuple[str, str, str], asyncio.Lock] = {}

    async def next(self, agent_name, user_id, session_id, *, floor=None) -> int:
        key = (agent_name, user_id, session_id)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            if key not in self._counters:
                self._counters[key] = max(0, int(await floor())) if floor is not None else 0
            self._counters[key] += 1
            return self._counters[key]


class RedisSequenceAllocator(SequenceAllocator):
    """``INCR``-based allocator shared across workers; recovers from the durable maximum after counter loss."""

    def __init__(self, redis_client: Any, *, key_prefix: str = "conversation") -> None:
        self._redis = redis_client
        self._key_prefix = key_prefix

    def _key(self, agent_name: str, user_id: str, session_id: str) -> str:
        return f"{self._key_prefix}:seq:{agent_name}:{user_id}:{session_id}"

    async def next(self, agent_name, user_id, session_id, *, floor=None) -> int:
        key = self._key(agent_name, user_id, session_id)
        if floor is not None and not await self._redis.exists(key):
            base = max(0, int(await floor()))
            await self._redis.set(key, base, nx=True)
        return int(await self._redis.incr(key))  # NO TTL: an expiring counter could re-issue an outboxed sequence

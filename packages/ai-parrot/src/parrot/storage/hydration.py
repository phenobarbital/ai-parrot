"""``HydrationSource`` over a ``ConversationBackend`` (FEAT-886 M14).

A pure translation layer: backend (storage) errors become hydration errors, stored rows become
``ConversationTurn`` through the tolerant reader. It never converts a failure, a deleted session or an
unready index into ``None`` / ``[]``.
"""
from __future__ import annotations

from typing import List, Optional

from navconfig.logging import logging

from parrot.memory.abstract import ConversationTurn
from parrot.memory.hydration import (
    HydrationNotReadyError,
    HydrationSource,
    HydrationUnavailableError,
    SessionDeletedError,
)
from parrot.storage.backends.base import ConversationBackend
from parrot.storage.errors import ConversationDeletedError, IndexNotReadyError, StorageError
from parrot.storage.models import ChatStorageTurn


class ChatStorageHydrationSource(HydrationSource):
    """Hydration source backed by the ChatStorage cold tier.

    Args:
        backend: The initialised cold-tier backend (the same one ``ChatStorage`` writes to).
    """

    def __init__(self, backend: ConversationBackend) -> None:
        self._backend = backend
        self.logger = logging.getLogger("parrot.storage.ChatStorageHydrationSource")

    async def load_turns(
        self, agent_name: str, user_id: str, session_id: str, max_turns: int
    ) -> Optional[List[ConversationTurn]]:
        """Newest ``max_turns`` turns, ascending; ``None`` when the session has none.

        Raises:
            ValueError: ``max_turns < 1``.
            HydrationNotReadyError: the chronological index is not ready.
            SessionDeletedError: the session is tombstoned.
            HydrationUnavailableError: the backend failed or a row could not be read.
        """
        if max_turns < 1:
            raise ValueError("max_turns must be >= 1")
        try:
            await self._require_ready(agent_name, user_id, session_id)
            rows = await self._backend.query_turn_window(user_id, agent_name, session_id, max_turns)
            if not rows:
                self.logger.debug("hydration: agent=%s session=%s has no retained turns", agent_name, session_id)
                return None
            turns = [
                ChatStorageTurn.from_row(
                    row, user_id=user_id, agent_id=agent_name, session_id=session_id
                ).to_conversation_turn()
                for row in rows
            ]
        except (ConversationDeletedError, IndexNotReadyError, StorageError) as exc:
            raise self._translate(exc, agent_name, session_id) from exc
        except (ValueError, TypeError, KeyError) as exc:  # a corrupt row must not be served truncated
            raise HydrationUnavailableError(
                f"a stored turn of session {session_id} (agent {agent_name}) could not be read"
            ) from exc
        self.logger.debug("hydration: agent=%s session=%s loaded %d turns", agent_name, session_id, len(turns))
        return turns

    async def is_deleted(self, agent_name: str, user_id: str, session_id: str) -> bool:
        """Authoritative deletion guard. Raises ``HydrationUnavailableError`` if it cannot be determined."""
        try:
            return bool(await self._backend.is_deleted(user_id, agent_name, session_id))
        except StorageError as exc:
            raise self._translate(exc, agent_name, session_id) from exc

    async def max_sequence(self, agent_name: str, user_id: str, session_id: str) -> int:
        """Durable maximum sequence for allocator recovery (0 when none)."""
        try:
            return int(await self._backend.max_sequence(user_id, agent_name, session_id))
        except StorageError as exc:
            raise self._translate(exc, agent_name, session_id) from exc

    async def _require_ready(self, agent_name: str, user_id: str, session_id: str) -> None:
        """Raise unless the session's chronological index is ``ready`` (deletion wins over not-ready)."""
        state = await self._backend.get_index_state(user_id, agent_name, session_id)
        if state == "ready":
            return
        if await self._backend.is_deleted(user_id, agent_name, session_id):
            raise ConversationDeletedError(f"session {session_id} is deleted")
        raise IndexNotReadyError(f"index for session {session_id} is {state!r}")

    def _translate(self, exc: Exception, agent_name: str, session_id: str) -> Exception:
        """Map a storage error to its hydration error (order matters: subclasses first)."""
        where = f"agent {agent_name}, session {session_id}"
        if isinstance(exc, ConversationDeletedError):
            return SessionDeletedError(f"conversation is deleted ({where})")
        if isinstance(exc, IndexNotReadyError):
            return HydrationNotReadyError(f"chronological index is not ready ({where})")
        return HydrationUnavailableError(f"hydration source unavailable ({where}): {type(exc).__name__}")

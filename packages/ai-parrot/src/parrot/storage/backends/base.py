"""Abstract ConversationBackend interface for pluggable storage.

All storage backends — DynamoDB, SQLite, Postgres, MongoDB — implement this
ABC. The shared contract test suite in tests/storage/test_backend_contract.py
validates that all backends exhibit identical observable behavior.

FEAT-116: dynamodb-fallback-redis — Module 1 (ConversationBackend ABC).
See wiki/stores/storage-backends.md for the backend selection matrix.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class BackfillBatch:
    """Result of one :meth:`ConversationBackend.backfill_batch` call."""

    processed: int
    next_cursor: Optional[str]      # None when the scan is complete
    invalid_sessions: Tuple[str, ...]


class ConversationBackend(ABC):
    """Abstract storage backend for conversations, threads, turns, and artifacts.

    All implementations MUST preserve the semantics of the DynamoDB reference
    implementation (see backends/dynamodb.py). Verified by the shared contract
    test suite in tests/storage/test_backend_contract.py.

    The ABC operates on plain ``dict`` payloads; Pydantic model
    serialization/deserialization is the responsibility of ``ChatStorage``
    and ``ArtifactStore``.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def initialize(self) -> None:
        """Open connections and create schema/indexes if needed (idempotent)."""

    @abstractmethod
    async def close(self) -> None:
        """Release all backend connections."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Return True when the backend is ready to accept requests."""

    # ------------------------------------------------------------------
    # Threads
    # ------------------------------------------------------------------

    @abstractmethod
    async def put_thread(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        metadata: dict,
    ) -> None:
        """Create or replace a thread metadata item."""

    @abstractmethod
    async def update_thread(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        **updates,
    ) -> None:
        """Update specific attributes on an existing thread metadata item."""

    @abstractmethod
    async def query_threads(
        self,
        user_id: str,
        agent_id: str,
        limit: int = 50,
    ) -> List[dict]:
        """List thread metadata items for a user+agent pair, newest first."""

    # ------------------------------------------------------------------
    # Turns
    # ------------------------------------------------------------------

    @abstractmethod
    async def put_turn(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        turn_id: str,
        data: dict,
    ) -> None:
        """Idempotent upsert by ``turn_id``, atomic with the deletion guard and the chronological entry.

        Ordering fields (timestamp, sequence) of an existing turn are never changed.

        Raises:
            StorageUnavailableError: When the backend is disconnected.
            StorageWriteError: When the durable write fails.
            ConversationDeletedError: When the session or the turn is tombstoned.
        """

    @abstractmethod
    async def query_turns(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        limit: int = 10,
        newest_first: bool = True,
    ) -> List[dict]:
        """Query conversation turns for a session.

        Raises:
            StorageUnavailableError: When disconnected or the read fails — never returns ``[]`` for a failure.
        """

    @abstractmethod
    async def delete_turn(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        turn_id: str,
    ) -> bool:
        """Delete a single conversation turn.

        Returns:
            True if the turn existed and was deleted, False otherwise.
        """

    @abstractmethod
    async def delete_thread_cascade(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
    ) -> int:
        """Delete all items for a session (thread metadata + turns + artifacts).

        Returns:
            Number of items deleted.
        """

    # ------------------------------------------------------------------
    # Durable conversation operations (FEAT-886)
    # ------------------------------------------------------------------

    @abstractmethod
    async def query_turn_window(
        self, user_id: str, agent_id: str, session_id: str, limit: int
    ) -> List[dict]:
        """The newest ``limit`` turns by ``(timestamp, sequence, turn_id)``.

        ``limit`` is applied DESCENDING at the backend; the window is returned ASCENDING.

        Raises:
            StorageUnavailableError: Disconnected or the read failed.
            ConversationDeletedError: The session is tombstoned.
            IndexNotReadyError: The chronological index is not ready (no full scan is performed).

        An active session with no turns returns ``[]``.
        """

    @abstractmethod
    async def max_sequence(self, user_id: str, agent_id: str, session_id: str) -> int:
        """Highest stored ``sequence`` for the session, ``0`` when none."""

    @abstractmethod
    async def put_tombstone(
        self, user_id: str, agent_id: str, session_id: str, turn_id: Optional[str] = None
    ) -> None:
        """Durably record a session (``turn_id=None``) or turn deletion. Idempotent.

        Not subject to transcript TTL or :meth:`delete_thread_cascade`.
        """

    @abstractmethod
    async def is_deleted(
        self, user_id: str, agent_id: str, session_id: str, turn_id: Optional[str] = None
    ) -> bool:
        """Whether the identity is tombstoned.

        Raises:
            StorageUnavailableError: If it cannot be determined — never returns ``False`` on failure.
        """

    @abstractmethod
    async def get_index_state(self, user_id: str, agent_id: str, session_id: str) -> str:
        """``'ready'`` | ``'pending'`` | ``'invalid'``. Sessions created after FEAT-886 are ``'ready'``."""

    @abstractmethod
    async def backfill_batch(self, cursor: Optional[str], batch_size: int) -> BackfillBatch:
        """Index up to ``batch_size`` legacy turns after ``cursor``; resumable and safe alongside new writes.

        Marks a session ``'ready'`` once all its turns are indexed, ``'invalid'`` when a turn has a
        missing or unparseable timestamp.
        """

    # ------------------------------------------------------------------
    # Artifacts
    # ------------------------------------------------------------------

    @abstractmethod
    async def put_artifact(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        artifact_id: str,
        data: dict,
    ) -> None:
        """Store an artifact item."""

    @abstractmethod
    async def get_artifact(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        artifact_id: str,
    ) -> Optional[dict]:
        """Get a single artifact by its key.

        Returns:
            Artifact dict or None if not found.
        """

    @abstractmethod
    async def query_artifacts(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
    ) -> List[dict]:
        """List all artifacts for a session."""

    @abstractmethod
    async def delete_artifact(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        artifact_id: str,
    ) -> None:
        """Delete a single artifact."""

    @abstractmethod
    async def delete_session_artifacts(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
    ) -> int:
        """Delete all artifacts for a session.

        Returns:
            Number of artifacts deleted.
        """

    # ------------------------------------------------------------------
    # Overflow key helper (concrete default — backends MAY override)
    # ------------------------------------------------------------------

    def build_overflow_prefix(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        artifact_id: str,
    ) -> str:
        """Return a stable key prefix for overflow storage.

        Default implementation yields a DynamoDB-compatible shape so existing
        S3 layouts do not change. Backends MAY override if they want a
        different overflow layout (e.g., filesystem-friendly paths).

        Args:
            user_id: User identifier.
            agent_id: Agent/bot identifier.
            session_id: Conversation session identifier.
            artifact_id: Artifact identifier.

        Returns:
            Key prefix string, e.g.
            ``"artifacts/USER#u#AGENT#a/THREAD#s/aid"``.
        """
        return (
            f"artifacts/USER#{user_id}#AGENT#{agent_id}"
            f"/THREAD#{session_id}/{artifact_id}"
        )

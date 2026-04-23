"""Abstract ConversationBackend interface for pluggable storage.

All storage backends — DynamoDB, SQLite, Postgres, MongoDB — implement this
ABC. The shared contract test suite in tests/storage/test_backend_contract.py
validates that all backends exhibit identical observable behavior.

FEAT-116: dynamodb-fallback-redis — Module 1 (ConversationBackend ABC).
See docs/storage-backends.md for the backend selection matrix.
"""

from abc import ABC, abstractmethod
from typing import List, Optional


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
        """Store a conversation turn."""

    @abstractmethod
    async def query_turns(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        limit: int = 10,
        newest_first: bool = True,
    ) -> List[dict]:
        """Query conversation turns for a session."""

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

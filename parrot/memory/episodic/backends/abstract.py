"""Abstract backend protocol for episodic memory storage."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from ..models import EpisodicMemory, EpisodeSearchResult


@runtime_checkable
class AbstractEpisodeBackend(Protocol):
    """Protocol defining the storage backend interface for episodes.

    Implementations must provide methods for storing, searching,
    retrieving, and maintaining episodic memory records.
    """

    async def store(self, episode: EpisodicMemory) -> str:
        """Store an episode. Returns the episode_id.

        Args:
            episode: The episode to store.

        Returns:
            The episode_id of the stored episode.
        """
        ...

    async def search_similar(
        self,
        embedding: list[float],
        namespace_filter: dict[str, Any],
        top_k: int = 5,
        score_threshold: float = 0.3,
        include_failures_only: bool = False,
    ) -> list[EpisodeSearchResult]:
        """Search episodes by vector similarity with dimensional filters.

        Args:
            embedding: Query embedding vector.
            namespace_filter: Dict of field_name -> value for WHERE filtering.
            top_k: Maximum results to return.
            score_threshold: Minimum similarity score (0-1).
            include_failures_only: If True, only return failure episodes.

        Returns:
            List of episodes ranked by similarity score.
        """
        ...

    async def get_recent(
        self,
        namespace_filter: dict[str, Any],
        limit: int = 10,
        since: datetime | None = None,
    ) -> list[EpisodicMemory]:
        """Get recent episodes by namespace, ordered by created_at DESC.

        Args:
            namespace_filter: Dict of field_name -> value for WHERE filtering.
            limit: Maximum results to return.
            since: Only return episodes created after this datetime.

        Returns:
            List of recent episodes.
        """
        ...

    async def get_failures(
        self,
        agent_id: str,
        tenant_id: str = "default",
        limit: int = 5,
    ) -> list[EpisodicMemory]:
        """Get recent failure episodes for an agent.

        Args:
            agent_id: Agent identifier.
            tenant_id: Tenant identifier.
            limit: Maximum results to return.

        Returns:
            List of failure episodes, most recent first.
        """
        ...

    async def delete_expired(self) -> int:
        """Delete episodes that have passed their expires_at timestamp.

        Returns:
            Number of episodes deleted.
        """
        ...

    async def count(self, namespace_filter: dict[str, Any]) -> int:
        """Count episodes matching a namespace filter.

        Args:
            namespace_filter: Dict of field_name -> value for WHERE filtering.

        Returns:
            Number of matching episodes.
        """
        ...

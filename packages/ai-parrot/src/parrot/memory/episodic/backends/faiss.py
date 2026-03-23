"""FAISS backend for episodic memory storage (local development).

In-memory FAISS index + dict storage with optional disk persistence.
Namespace filters are applied post-search since FAISS has no SQL.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ..models import (
    EpisodeSearchResult,
    EpisodicMemory,
)

logger = logging.getLogger(__name__)

try:
    import faiss

    _FAISS_AVAILABLE = True
except ImportError:
    _FAISS_AVAILABLE = False


def _ensure_faiss() -> None:
    """Raise ImportError with helpful message if faiss is not installed."""
    if not _FAISS_AVAILABLE:
        raise ImportError(
            "faiss-cpu is required for FAISSBackend. "
            "Install it with: uv pip install faiss-cpu"
        )


def _matches_filter(
    episode: EpisodicMemory, namespace_filter: dict[str, Any]
) -> bool:
    """Check if an episode matches all fields in the namespace filter."""
    for field, value in namespace_filter.items():
        if getattr(episode, field, None) != value:
            return False
    return True


class FAISSBackend:
    """FAISS-based backend for local development without PostgreSQL.

    Uses an in-memory FAISS IndexFlatIP (inner product on L2-normalized
    vectors = cosine similarity) with optional disk persistence.

    Args:
        dimension: Embedding vector dimension.
        persistence_path: Directory for saving index and episodes to disk.
            If None, runs purely in-memory.
        max_episodes: Maximum number of episodes to keep. When exceeded,
            the oldest episodes are removed.
        auto_save_interval: Save to disk every N store() calls.
            Only applies when persistence_path is set.
    """

    def __init__(
        self,
        dimension: int = 384,
        persistence_path: str | None = None,
        max_episodes: int = 10000,
        auto_save_interval: int = 100,
    ) -> None:
        _ensure_faiss()
        self._dimension = dimension
        self._persistence_path = Path(persistence_path) if persistence_path else None
        self._max_episodes = max_episodes
        self._auto_save_interval = auto_save_interval

        # Storage
        self._episodes: dict[str, EpisodicMemory] = {}
        self._id_order: list[str] = []  # Insertion order for FAISS index mapping
        self._index: faiss.IndexFlatIP = faiss.IndexFlatIP(dimension)
        self._store_count = 0

    async def configure(self) -> None:
        """Load persisted data if available."""
        if self._persistence_path:
            await self.load()
        logger.info(
            "FAISSBackend configured: dim=%d, episodes=%d",
            self._dimension,
            len(self._episodes),
        )

    async def close(self) -> None:
        """Save to disk if persistence is enabled."""
        if self._persistence_path:
            await self.save()

    async def __aenter__(self) -> FAISSBackend:
        await self.configure()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def store(self, episode: EpisodicMemory) -> str:
        """Store an episode in the FAISS index and dict.

        If the episode has an embedding, it's added to the FAISS index.
        Enforces max_episodes cap by removing oldest episodes.
        """
        # Skip duplicates
        if episode.episode_id in self._episodes:
            return episode.episode_id

        # Enforce cap
        while len(self._episodes) >= self._max_episodes:
            self._remove_oldest()

        self._episodes[episode.episode_id] = episode

        # Add to FAISS index if embedding exists
        if episode.embedding:
            vec = np.array([episode.embedding], dtype=np.float32)
            # L2-normalize for cosine similarity via inner product
            faiss.normalize_L2(vec)
            self._index.add(vec)
            self._id_order.append(episode.episode_id)

        self._store_count += 1
        if (
            self._persistence_path
            and self._store_count % self._auto_save_interval == 0
        ):
            await self.save()

        return episode.episode_id

    async def search_similar(
        self,
        embedding: list[float],
        namespace_filter: dict[str, Any],
        top_k: int = 5,
        score_threshold: float = 0.3,
        include_failures_only: bool = False,
    ) -> list[EpisodeSearchResult]:
        """Search by vector similarity with post-search namespace filtering.

        Since FAISS doesn't support SQL-like filters, we search a larger
        candidate set and filter afterwards.
        """
        if self._index.ntotal == 0:
            return []

        # Search more candidates than needed to account for filtering
        search_k = min(top_k * 10, self._index.ntotal)

        vec = np.array([embedding], dtype=np.float32)
        faiss.normalize_L2(vec)
        scores, indices = self._index.search(vec, search_k)

        results: list[EpisodeSearchResult] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._id_order):
                continue

            episode_id = self._id_order[idx]
            episode = self._episodes.get(episode_id)
            if episode is None:
                continue

            sim = float(score)
            if sim < score_threshold:
                continue

            if not _matches_filter(episode, namespace_filter):
                continue

            if include_failures_only and not episode.is_failure:
                continue

            results.append(
                EpisodeSearchResult(
                    **episode.model_dump(),
                    embedding=episode.embedding,
                    score=sim,
                )
            )
            if len(results) >= top_k:
                break

        return results

    async def get_recent(
        self,
        namespace_filter: dict[str, Any],
        limit: int = 10,
        since: datetime | None = None,
    ) -> list[EpisodicMemory]:
        """Get recent episodes matching the namespace filter."""
        matching = [
            ep
            for ep in self._episodes.values()
            if _matches_filter(ep, namespace_filter)
            and (since is None or ep.created_at > since)
        ]
        matching.sort(key=lambda ep: ep.created_at, reverse=True)
        return matching[:limit]

    async def get_failures(
        self,
        agent_id: str,
        tenant_id: str = "default",
        limit: int = 5,
    ) -> list[EpisodicMemory]:
        """Get recent failure episodes for an agent."""
        failures = [
            ep
            for ep in self._episodes.values()
            if ep.is_failure
            and ep.agent_id == agent_id
            and ep.tenant_id == tenant_id
        ]
        failures.sort(key=lambda ep: ep.created_at, reverse=True)
        return failures[:limit]

    async def delete_expired(self) -> int:
        """Delete episodes past their expires_at timestamp."""
        now = datetime.now(timezone.utc)
        expired_ids = [
            ep.episode_id
            for ep in self._episodes.values()
            if ep.expires_at is not None and ep.expires_at < now
        ]
        for eid in expired_ids:
            self._episodes.pop(eid, None)

        if expired_ids:
            self._rebuild_index()
            logger.info("Deleted %d expired episodes", len(expired_ids))

        return len(expired_ids)

    async def count(self, namespace_filter: dict[str, Any]) -> int:
        """Count episodes matching a namespace filter."""
        return sum(
            1
            for ep in self._episodes.values()
            if _matches_filter(ep, namespace_filter)
        )

    # ── Persistence ──

    async def save(self) -> None:
        """Save FAISS index and episodes to disk."""
        if not self._persistence_path:
            return

        self._persistence_path.mkdir(parents=True, exist_ok=True)

        # Save FAISS index
        index_path = str(self._persistence_path / "episodes.faiss")
        faiss.write_index(self._index, index_path)

        # Save episodes as JSONL + id_order
        jsonl_path = self._persistence_path / "episodes.jsonl"
        with open(jsonl_path, "w") as f:
            for episode in self._episodes.values():
                f.write(json.dumps(episode.to_dict()) + "\n")

        order_path = self._persistence_path / "id_order.json"
        with open(order_path, "w") as f:
            json.dump(self._id_order, f)

        logger.debug(
            "Saved %d episodes to %s", len(self._episodes), self._persistence_path
        )

    async def load(self) -> None:
        """Load FAISS index and episodes from disk."""
        if not self._persistence_path:
            return

        jsonl_path = self._persistence_path / "episodes.jsonl"
        index_path = self._persistence_path / "episodes.faiss"
        order_path = self._persistence_path / "id_order.json"

        if not jsonl_path.exists():
            return

        # Load episodes
        self._episodes.clear()
        with open(jsonl_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    data = json.loads(line)
                    ep = EpisodicMemory.from_dict(data)
                    self._episodes[ep.episode_id] = ep

        # Load FAISS index
        if index_path.exists():
            self._index = faiss.read_index(str(index_path))
        else:
            self._rebuild_index()

        # Load id_order
        if order_path.exists():
            with open(order_path) as f:
                self._id_order = json.load(f)
        else:
            # Reconstruct from episodes that have embeddings
            self._id_order = [
                eid for eid, ep in self._episodes.items() if ep.embedding
            ]

        logger.debug(
            "Loaded %d episodes from %s", len(self._episodes), self._persistence_path
        )

    # ── Internal helpers ──

    def _remove_oldest(self) -> None:
        """Remove the oldest episode by created_at."""
        if not self._episodes:
            return
        oldest = min(self._episodes.values(), key=lambda ep: ep.created_at)
        self._episodes.pop(oldest.episode_id, None)
        # Index will be stale but rebuilt on next delete_expired or save
        # For simplicity, rebuild now
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        """Rebuild the FAISS index from current episodes."""
        self._index = faiss.IndexFlatIP(self._dimension)
        self._id_order = []

        for eid, ep in self._episodes.items():
            if ep.embedding:
                vec = np.array([ep.embedding], dtype=np.float32)
                faiss.normalize_L2(vec)
                self._index.add(vec)
                self._id_order.append(eid)

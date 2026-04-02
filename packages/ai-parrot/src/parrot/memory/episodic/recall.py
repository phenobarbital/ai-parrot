"""Pluggable recall strategy protocol and implementations for episodic memory.

Defines the RecallStrategy protocol and provides two implementations:
- SemanticOnlyStrategy: delegates directly to backend.search_similar() (default behavior)
- HybridBM25Strategy: fuses BM25 lexical scores with semantic similarity
"""
from __future__ import annotations

import logging
import time
from typing import Any, Protocol, runtime_checkable

from parrot._imports import lazy_import

from .backends.abstract import AbstractEpisodeBackend
from .models import EpisodicMemory, EpisodeSearchResult

logger = logging.getLogger(__name__)


@runtime_checkable
class RecallStrategy(Protocol):
    """Protocol for pluggable recall strategies.

    Implementations define how to search for similar episodes given a query
    and its embedding. The strategy can use vector similarity alone (default)
    or fuse multiple signals (e.g., BM25 + semantic).
    """

    async def search(
        self,
        query: str,
        query_embedding: list[float],
        backend: AbstractEpisodeBackend,
        namespace_filter: dict[str, Any],
        top_k: int = 5,
        score_threshold: float = 0.3,
        include_failures_only: bool = False,
    ) -> list[EpisodeSearchResult]:
        """Search for relevant episodes.

        Args:
            query: Natural language query string.
            query_embedding: Pre-computed embedding vector for the query.
            backend: The storage backend to search against.
            namespace_filter: Dict of field_name -> value for WHERE filtering.
            top_k: Maximum number of results to return.
            score_threshold: Minimum similarity score (0-1).
            include_failures_only: If True, only return failure episodes.

        Returns:
            List of episodes ranked by relevance score.
        """
        ...


class SemanticOnlyStrategy:
    """Recall strategy that delegates directly to backend.search_similar().

    This is the default behavior — pure vector similarity search.
    Produces identical results to calling backend.search_similar() directly.
    """

    async def search(
        self,
        query: str,
        query_embedding: list[float],
        backend: AbstractEpisodeBackend,
        namespace_filter: dict[str, Any],
        top_k: int = 5,
        score_threshold: float = 0.3,
        include_failures_only: bool = False,
    ) -> list[EpisodeSearchResult]:
        """Search using pure vector similarity via backend.search_similar().

        Args:
            query: Natural language query string (not used directly).
            query_embedding: Pre-computed embedding vector for the query.
            backend: The storage backend to search against.
            namespace_filter: Dict of field_name -> value for WHERE filtering.
            top_k: Maximum number of results to return.
            score_threshold: Minimum similarity score (0-1).
            include_failures_only: If True, only return failure episodes.

        Returns:
            List of episodes ranked by vector similarity.
        """
        return await backend.search_similar(
            embedding=query_embedding,
            namespace_filter=namespace_filter,
            top_k=top_k,
            score_threshold=score_threshold,
            include_failures_only=include_failures_only,
        )


class _BM25IndexEntry:
    """Container for a lazily-built, namespace-scoped BM25 index."""

    def __init__(
        self,
        index: Any,
        texts: list[str],
        episodes: list[EpisodicMemory],
        built_at: float,
    ) -> None:
        self.index = index
        self.texts = texts
        self.episodes = episodes
        self.built_at = built_at


class HybridBM25Strategy:
    """Recall strategy that fuses BM25 lexical scores with semantic similarity.

    Maintains per-namespace in-memory BM25 indexes built lazily on first search.
    Fuses scores as: ``bm25_weight * bm25_score + semantic_weight * semantic_score``.
    Both score types are normalized to [0.0, 1.0] before fusion.

    The BM25 index is rebuilt from all episodes in the namespace via
    ``backend.get_recent()``. Stale indexes are rebuilt after ``max_index_age_seconds``.

    Args:
        bm25_weight: Weight for BM25 lexical score contribution. Default 0.4.
        semantic_weight: Weight for semantic (vector) score contribution. Default 0.6.
        max_episodes_for_index: Maximum episodes to load for BM25 indexing. Default 5000.
        max_index_age_seconds: Rebuild index after this many seconds. Default 3600.

    Raises:
        ImportError: If ``bm25s`` package is not installed (raised at first search, not at import).
    """

    def __init__(
        self,
        bm25_weight: float = 0.4,
        semantic_weight: float = 0.6,
        max_episodes_for_index: int = 5000,
        max_index_age_seconds: float = 3600.0,
    ) -> None:
        self.bm25_weight = bm25_weight
        self.semantic_weight = semantic_weight
        self.max_episodes_for_index = max_episodes_for_index
        self.max_index_age_seconds = max_index_age_seconds

        # Cache: namespace_key (frozenset of filter items) → _BM25IndexEntry
        self._cache: dict[str, _BM25IndexEntry] = {}

    def _namespace_key(self, namespace_filter: dict[str, Any]) -> str:
        """Build a stable cache key from a namespace filter dict.

        Args:
            namespace_filter: Dict of field_name -> value.

        Returns:
            A stable string key.
        """
        return "|".join(f"{k}={v}" for k, v in sorted(namespace_filter.items()))

    def _is_stale(self, entry: _BM25IndexEntry) -> bool:
        """Return True if the index entry is older than max_index_age_seconds.

        Args:
            entry: The index entry to check.

        Returns:
            True if stale.
        """
        return (time.monotonic() - entry.built_at) > self.max_index_age_seconds

    def invalidate(self, namespace_filter: dict[str, Any]) -> None:
        """Invalidate the BM25 index for a given namespace.

        Should be called after new episodes are stored in this namespace.

        Args:
            namespace_filter: The namespace whose index to invalidate.
        """
        key = self._namespace_key(namespace_filter)
        self._cache.pop(key, None)

    async def _build_index(
        self,
        backend: AbstractEpisodeBackend,
        namespace_filter: dict[str, Any],
    ) -> _BM25IndexEntry:
        """Fetch episodes and build a BM25 index for a namespace.

        Args:
            backend: The storage backend to fetch episodes from.
            namespace_filter: The namespace to index.

        Returns:
            A fresh _BM25IndexEntry.

        Raises:
            ImportError: If bm25s is not installed.
        """
        bm25s = lazy_import("bm25s", package_name="bm25s", extra="embeddings")

        episodes = await backend.get_recent(
            namespace_filter=namespace_filter,
            limit=self.max_episodes_for_index,
        )

        if not episodes:
            # Empty index — return a dummy entry
            return _BM25IndexEntry(
                index=None,
                texts=[],
                episodes=[],
                built_at=time.monotonic(),
            )

        texts = [ep.searchable_text() for ep in episodes]

        # Build BM25 index
        retriever = bm25s.BM25()
        tokenized = bm25s.tokenize(texts, stopwords="en")
        retriever.index(tokenized)

        return _BM25IndexEntry(
            index=retriever,
            texts=texts,
            episodes=episodes,
            built_at=time.monotonic(),
        )

    def _bm25_scores(
        self,
        query: str,
        entry: _BM25IndexEntry,
    ) -> list[float]:
        """Compute BM25 scores for query against the indexed corpus.

        Args:
            query: The natural language query.
            entry: The BM25 index entry.

        Returns:
            List of normalized [0.0, 1.0] scores, one per episode.
        """
        if entry.index is None or not entry.texts:
            return []

        bm25s = lazy_import("bm25s", package_name="bm25s", extra="embeddings")

        tokenized_query = bm25s.tokenize([query], stopwords="en")
        scores, _ = entry.index.retrieve(tokenized_query, k=len(entry.texts))

        # scores shape: (1, n_docs)
        raw: list[float] = scores[0].tolist() if hasattr(scores[0], "tolist") else list(scores[0])

        # Normalize to [0, 1]
        max_score = max(raw) if raw else 0.0
        if max_score > 0:
            return [s / max_score for s in raw]
        return [0.0] * len(raw)

    @staticmethod
    def _cosine_sim(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors.

        Args:
            a: First vector.
            b: Second vector.

        Returns:
            Cosine similarity in [-1.0, 1.0].
        """
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    async def search(
        self,
        query: str,
        query_embedding: list[float],
        backend: AbstractEpisodeBackend,
        namespace_filter: dict[str, Any],
        top_k: int = 5,
        score_threshold: float = 0.3,
        include_failures_only: bool = False,
    ) -> list[EpisodeSearchResult]:
        """Search using BM25 + semantic score fusion.

        On first call for a namespace, builds a BM25 index from all episodes.
        Subsequent calls reuse the cached index (rebuilt if stale).

        Fused score = bm25_weight * bm25_score + semantic_weight * semantic_score.
        Episodes below score_threshold (applied to semantic score) are excluded.

        Args:
            query: Natural language query string.
            query_embedding: Pre-computed embedding vector for the query.
            backend: The storage backend to search against.
            namespace_filter: Dict of field_name -> value for WHERE filtering.
            top_k: Maximum number of results to return.
            score_threshold: Minimum semantic similarity score (0-1).
            include_failures_only: If True, only return failure episodes.

        Returns:
            List of episodes ranked by fused BM25 + semantic score.
        """
        key = self._namespace_key(namespace_filter)

        # Get or build index
        entry = self._cache.get(key)
        if entry is None or self._is_stale(entry):
            try:
                entry = await self._build_index(backend, namespace_filter)
                self._cache[key] = entry
            except ImportError:
                logger.warning(
                    "bm25s not installed; falling back to semantic-only search. "
                    "Install with: pip install bm25s"
                )
                return await backend.search_similar(
                    embedding=query_embedding,
                    namespace_filter=namespace_filter,
                    top_k=top_k,
                    score_threshold=score_threshold,
                    include_failures_only=include_failures_only,
                )
            except Exception as e:
                logger.warning("BM25 index build failed (%s); falling back to semantic search", e)
                return await backend.search_similar(
                    embedding=query_embedding,
                    namespace_filter=namespace_filter,
                    top_k=top_k,
                    score_threshold=score_threshold,
                    include_failures_only=include_failures_only,
                )

        if not entry.episodes:
            # No episodes in namespace — fall back to backend
            return await backend.search_similar(
                embedding=query_embedding,
                namespace_filter=namespace_filter,
                top_k=top_k,
                score_threshold=score_threshold,
                include_failures_only=include_failures_only,
            )

        # Compute BM25 scores
        bm25_scores = self._bm25_scores(query, entry)

        # Compute semantic scores for each episode (cosine similarity)
        results: list[tuple[float, EpisodicMemory]] = []
        for i, ep in enumerate(entry.episodes):
            # Apply failure filter
            if include_failures_only and not ep.is_failure:
                continue
            # Apply namespace filter (should already be filtered by get_recent)
            for field, value in namespace_filter.items():
                if getattr(ep, field, None) != value:
                    break
            else:
                bm25_s = bm25_scores[i] if i < len(bm25_scores) else 0.0
                sem_s = self._cosine_sim(query_embedding, ep.embedding or [])

                # Clamp semantic score to [0, 1]
                sem_s = max(0.0, min(1.0, sem_s))

                # Apply score threshold on semantic score
                if sem_s < score_threshold and bm25_s < score_threshold:
                    continue

                fused = self.bm25_weight * bm25_s + self.semantic_weight * sem_s
                results.append((fused, ep))

        # Sort by fused score descending
        results.sort(key=lambda x: x[0], reverse=True)

        search_results = []
        for fused_score, ep in results[:top_k]:
            search_results.append(
                EpisodeSearchResult(
                    **ep.model_dump(),
                    embedding=ep.embedding,
                    score=min(fused_score, 1.0),
                )
            )

        return search_results

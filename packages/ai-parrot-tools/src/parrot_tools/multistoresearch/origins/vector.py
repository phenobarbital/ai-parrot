"""``VectorStoreOrigin`` — duck-typed vector-store adapter (FEAT-379).

Wraps a single duck-typed vector store (pgvector / FAISS / ArangoDB) via
its ``similarity_search(query, limit=...)`` method — never a concrete
store class, preserving the "no concrete store imports at load time"
convention from the pre-FEAT-379 single-tool implementation.
"""
from typing import Any, List, Optional

from parrot.models import OriginHit, SearchOriginKind
from parrot.models.stores import SearchResult

from .base import SearchOrigin


class VectorStoreOrigin(SearchOrigin):
    """Adapter wrapping one duck-typed vector store.

    Args:
        store: Any object exposing an async
            ``similarity_search(query, limit=...) -> list[SearchResult]``
            method (e.g. ``PgVectorStore``, ``FAISSStore``,
            ``ArangoDBStore``). Also detected for an optional callable
            ``fulltext_search`` attribute, which enables the FTS leg
            (ArangoDB case).
        name: Adapter name, e.g. ``"pgvector"``, ``"faiss"``, ``"arango"``.
        description: LLM-readable explanation of this origin. Defaults to
            a generic per-store description when omitted.
        timeout: Optional per-adapter timeout override in seconds.
    """

    kind = SearchOriginKind.VECTOR

    def __init__(
        self,
        store: Any,
        name: str,
        description: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self.store = store
        self.name = name
        self.description = description or (
            f"Vector-store origin '{name}' — semantic similarity search "
            "over embedded documents."
        )
        self.timeout = timeout
        self.supports_fts = callable(getattr(store, "fulltext_search", None))

    async def search(self, query: str, k: int) -> List[OriginHit]:
        """Run ``similarity_search`` against the wrapped store.

        Args:
            query: The search query text.
            k: Maximum number of hits to request from the store.

        Returns:
            Normalized :class:`~parrot.models.OriginHit` list, in the
            store's native return order.
        """
        results: List[SearchResult] = await self.store.similarity_search(
            query, limit=k
        )
        return self._normalize(results)

    async def fts_search(self, query: str, k: int) -> List[OriginHit]:
        """Run the wrapped store's ``fulltext_search``, when available.

        Args:
            query: The search query text.
            k: Maximum number of hits to request from the store.

        Returns:
            Normalized :class:`~parrot.models.OriginHit` list.

        Raises:
            NotImplementedError: When the wrapped store has no callable
                ``fulltext_search`` attribute.
        """
        if not self.supports_fts:
            raise NotImplementedError(
                f"{self.name!r} vector origin does not support fts_search "
                "(wrapped store exposes no fulltext_search)"
            )
        results: List[SearchResult] = await self.store.fulltext_search(
            query, limit=k
        )
        return self._normalize(results)

    def _normalize(self, results: List[SearchResult]) -> List[OriginHit]:
        """Normalize ``SearchResult`` rows into origin-tagged ``OriginHit``s."""
        return [
            OriginHit(
                id=getattr(result, "id", None),
                content=result.content,
                score=(
                    float(result.score) if result.score is not None else None
                ),
                metadata=dict(result.metadata or {}),
                origin=self.name,
                origin_kind=self.kind,
                native_rank=idx + 1,
            )
            for idx, result in enumerate(results)
        ]

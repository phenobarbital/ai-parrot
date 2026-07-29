"""``GraphIndexOrigin`` — 4-phase graph retrieval adapter (FEAT-379).

Wraps :class:`~parrot.knowledge.graphindex.retriever.GraphExpandedRetriever`
(seed → expand → community annotation → assembly). Optionally configured
with a :class:`~parrot.knowledge.graphindex.sqlite_reader.SQLiteGraphReader`
to enable a full-text-search leg via ``search_symbols`` (FTS5/BM25 over
title + summary) — ``supports_fts`` is ``True`` only when a reader is
provided; without one this origin is search-only.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from parrot.models import OriginHit, SearchOriginKind

from .base import SearchOrigin

if TYPE_CHECKING:  # pragma: no cover — type hints only
    from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever
    from parrot.knowledge.graphindex.sqlite_reader import SQLiteGraphReader


class GraphIndexOrigin(SearchOrigin):
    """Adapter wrapping the GraphIndex 4-phase retrieval pipeline.

    Args:
        retriever: A :class:`GraphExpandedRetriever` instance driving the
            seed → expand → community-annotation → assembly pipeline.
        reader: Optional :class:`SQLiteGraphReader` instance. When
            provided, enables the FTS leg via ``fts_search`` (delegates to
            ``search_symbols``); ``supports_fts`` reflects its presence.
        name: Adapter name. Defaults to ``"graphindex"``.
        description: LLM-readable explanation of this origin. Defaults to
            a description of graph-expanded retrieval + community context.
        timeout: Optional per-adapter timeout override in seconds.
        seed_top_k: Default number of seed nodes for Phase 1 seed search,
            forwarded to ``GraphExpandedRetriever.search`` unless
            overridden per call via ``k``.
    """

    kind = SearchOriginKind.GRAPHINDEX

    def __init__(
        self,
        retriever: "GraphExpandedRetriever",
        reader: Optional["SQLiteGraphReader"] = None,
        name: str = "graphindex",
        description: Optional[str] = None,
        timeout: Optional[float] = None,
        seed_top_k: int = 10,
    ) -> None:
        self._retriever = retriever
        self._reader = reader
        self.name = name
        self.description = description or (
            "GraphIndex origin — 4-phase graph-expanded retrieval "
            "(seed search, hop expansion, community annotation, budgeted "
            "assembly), ranked by combined score."
            + (
                " Also supports full-text symbol search."
                if reader is not None
                else ""
            )
        )
        self.timeout = timeout
        self.seed_top_k = seed_top_k
        self.supports_fts = reader is not None

    async def search(self, query: str, k: int) -> List[OriginHit]:
        """Run the 4-phase graph retrieval pipeline and flatten its result.

        Args:
            query: The search query text.
            k: Number of seed nodes for Phase 1 (forwarded as
                ``seed_top_k``); the final node list length depends on
                expansion + budget assembly, not solely on ``k``.

        Returns:
            Normalized hits, in the same best-first order as
            ``GraphRetrievalResult.nodes`` (sorted by ``combined_score``
            descending).
        """
        result = await self._retriever.search(query, seed_top_k=k)
        hits = []
        for idx, node in enumerate(result.nodes):
            content = node.title
            if node.summary:
                content = f"{node.title}\n{node.summary}"
            hits.append(
                OriginHit(
                    id=node.node_id,
                    content=content,
                    score=node.combined_score,
                    metadata={
                        "node_id": node.node_id,
                        "kind": node.kind,
                        "hop_distance": node.hop_distance,
                        "is_seed": node.is_seed,
                        "community_id": node.community_id,
                        "source_uri": node.source_uri,
                    },
                    origin=self.name,
                    origin_kind=self.kind,
                    native_rank=idx + 1,
                )
            )
        return hits

    async def fts_search(self, query: str, k: int) -> List[OriginHit]:
        """Run the configured reader's ``search_symbols`` FTS5/BM25 search.

        Args:
            query: FTS5 MATCH expression.
            k: Maximum number of hits to return.

        Returns:
            Normalized hits preserving the reader's best-first order.
            ``OriginHit.score`` carries the raw FTS5 BM25 score, which is
            **negative** (ascending = best match) — NOT normalized to a
            positive scale; see ``metadata["score_convention"]``.

        Raises:
            NotImplementedError: When no reader was configured
                (``supports_fts is False``).
        """
        if not self.supports_fts:
            raise NotImplementedError(
                f"{self.name!r} graphindex origin has no reader configured "
                "— fts_search is unavailable"
            )
        rows: List[dict] = await self._reader.search_symbols(query, limit=k)
        hits = []
        for idx, row in enumerate(rows):
            title = row.get("title") or ""
            summary = row.get("summary") or ""
            content = f"{title}\n{summary}".strip() if (title or summary) else row.get(
                "node_id", ""
            )
            hits.append(
                OriginHit(
                    id=row.get("node_id"),
                    content=content,
                    score=row.get("score"),
                    metadata={
                        "node_id": row.get("node_id"),
                        "kind": row.get("kind"),
                        "source_uri": row.get("source_uri"),
                        "domain_tags": row.get("domain_tags"),
                        "score_convention": (
                            "FTS5 BM25 raw score; NEGATIVE, ascending = best "
                            "match — not comparable to other origins"
                        ),
                    },
                    origin=self.name,
                    origin_kind=self.kind,
                    native_rank=idx + 1,
                )
            )
        return hits

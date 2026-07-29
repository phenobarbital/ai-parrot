"""``PageIndexOrigin`` — PageIndex (vectorless, tree-based) adapter (FEAT-379).

PageIndex offers three retrieval backends with very different cost/latency
profiles:

* ``hybrid`` (**default**) — :class:`~parrot.knowledge.pageindex.
  hybrid_search.HybridPageIndexSearch`. Combines BM25 + optional LLM-walk
  + optional dense-cosine signals via Reciprocal Rank Fusion. Balanced
  cost/quality tradeoff.
* ``llm`` — :class:`~parrot.knowledge.pageindex.retriever.
  PageIndexRetriever`. Asks an LLM to reason over the tree structure
  directly. **Spends LLM tokens on every call** — use sparingly.
* ``vector`` — :class:`~parrot.knowledge.pageindex.vector_walk.
  FlatMatrixSearch`. Brute-force cosine similarity over a pre-built node
  embedding matrix. Its ``search`` method is **synchronous**; this adapter
  offloads it to an executor so it never blocks the event loop (the one
  sanctioned exception to the no-``asyncio.to_thread`` decision, which
  governs ``batch_search`` semantics, not sync-backend wrapping — see
  spec §7 Known Risks).
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Awaitable, Callable, List, Optional

from parrot.models import OriginHit, SearchOriginKind

from .base import SearchOrigin

if TYPE_CHECKING:  # pragma: no cover — type hints only
    from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch
    from parrot.knowledge.pageindex.retriever import PageIndexRetriever
    from parrot.knowledge.pageindex.vector_walk import FlatMatrixSearch

_VALID_MODES = ("vector", "hybrid", "llm")


class PageIndexOrigin(SearchOrigin):
    """Adapter wrapping one of PageIndex's three retrieval backends.

    Exactly one of ``hybrid``, ``llm``, ``vector`` must be provided,
    matching the selected ``mode`` (validated at construction time).

    Args:
        hybrid: A :class:`HybridPageIndexSearch` instance. Required when
            ``mode="hybrid"``.
        llm: A :class:`PageIndexRetriever` instance. Required when
            ``mode="llm"`` — **this mode spends LLM tokens per call**.
        vector: A :class:`FlatMatrixSearch` instance. Required when
            ``mode="vector"``, together with ``embed_fn``.
        embed_fn: Async callable ``(query: str) -> embedding vector``,
            used to embed the query text before the ``vector`` mode's
            cosine-similarity search. Required when ``mode="vector"``.
        mode: One of ``"vector"``, ``"hybrid"``, ``"llm"``. Defaults to
            ``"hybrid"`` (resolved decision — balanced cost/quality).
        name: Adapter name. Defaults to ``"pageindex"``.
        description: LLM-readable explanation of this origin. Defaults to
            a mode-aware description of tree-based retrieval.
        timeout: Optional per-adapter timeout override in seconds.

    Raises:
        ValueError: When ``mode`` is not one of the three valid modes, or
            when the backend (and, for ``vector``, ``embed_fn``) required
            by the selected mode is not provided.
    """

    kind = SearchOriginKind.PAGEINDEX
    supports_fts = False

    def __init__(
        self,
        hybrid: Optional["HybridPageIndexSearch"] = None,
        llm: Optional["PageIndexRetriever"] = None,
        vector: Optional["FlatMatrixSearch"] = None,
        embed_fn: Optional[Callable[[str], Awaitable[Any]]] = None,
        mode: str = "hybrid",
        name: str = "pageindex",
        description: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        if mode not in _VALID_MODES:
            raise ValueError(
                f"Invalid PageIndex mode {mode!r}; expected one of {_VALID_MODES}"
            )
        if mode == "hybrid" and hybrid is None:
            raise ValueError("mode='hybrid' requires a `hybrid` backend instance")
        if mode == "llm" and llm is None:
            raise ValueError("mode='llm' requires an `llm` backend instance")
        if mode == "vector" and (vector is None or embed_fn is None):
            raise ValueError(
                "mode='vector' requires both a `vector` backend instance and `embed_fn`"
            )

        self.mode = mode
        self._hybrid = hybrid
        self._llm = llm
        self._vector = vector
        self._embed_fn = embed_fn

        self.name = name
        self.description = description or (
            "PageIndex origin — vectorless, tree-based reasoning RAG "
            f"(mode={mode}). 'llm' mode spends LLM tokens per call; "
            "'hybrid' (default) balances BM25 + optional LLM-walk + "
            "optional dense signals; 'vector' is brute-force cosine "
            "similarity over a node embedding matrix."
        )
        self.timeout = timeout

    async def search(self, query: str, k: int) -> List[OriginHit]:
        """Dispatch to the configured backend and normalize to ``OriginHit``.

        Args:
            query: The search query text.
            k: Maximum number of hits to return.

        Returns:
            Normalized hits, 1-based ``native_rank`` in the backend's own
            result order.
        """
        if self.mode == "hybrid":
            return await self._search_hybrid(query, k)
        if self.mode == "llm":
            return await self._search_llm(query, k)
        return await self._search_vector(query, k)

    async def _search_hybrid(self, query: str, k: int) -> List[OriginHit]:
        rows = await self._hybrid.search(query, top_k=k)
        hits = []
        for idx, row in enumerate(rows):
            title = row.get("title") or ""
            summary = row.get("summary") or ""
            content = f"{title}\n{summary}".strip() if (title or summary) else str(
                row.get("node_id", "")
            )
            hits.append(
                OriginHit(
                    id=row.get("node_id"),
                    content=content,
                    score=row.get("score"),
                    metadata={
                        "node_id": row.get("node_id"),
                        "title": title,
                        "source": row.get("source"),
                    },
                    origin=self.name,
                    origin_kind=self.kind,
                    native_rank=idx + 1,
                )
            )
        return hits

    async def _search_llm(self, query: str, k: int) -> List[OriginHit]:
        # Imported lazily to avoid a load-time dependency on the exact
        # PageIndex module layout; only needed to resolve node content.
        from parrot.knowledge.pageindex.utils import find_node_by_id

        result = await self._llm.search(query)
        node_ids = list(result.node_list or [])[:k]
        hits = []
        for idx, node_id in enumerate(node_ids):
            node = find_node_by_id(self._llm.structure, node_id) or {}
            title = node.get("title") or ""
            summary = node.get("summary") or node.get("prefix_summary") or ""
            content = f"{title}\n{summary}".strip() if (title or summary) else node_id
            hits.append(
                OriginHit(
                    id=node_id,
                    content=content,
                    score=None,
                    metadata={"node_id": node_id, "title": title, "thinking": result.thinking},
                    origin=self.name,
                    origin_kind=self.kind,
                    native_rank=idx + 1,
                )
            )
        return hits

    async def _search_vector(self, query: str, k: int) -> List[OriginHit]:
        query_vec = await self._embed_fn(query)
        loop = asyncio.get_running_loop()
        rows = await loop.run_in_executor(None, self._vector.search, query_vec, k)
        hits = []
        for idx, (node_id, score) in enumerate(rows):
            hits.append(
                OriginHit(
                    id=node_id,
                    content=node_id,
                    score=float(score),
                    metadata={"node_id": node_id},
                    origin=self.name,
                    origin_kind=self.kind,
                    native_rank=idx + 1,
                )
            )
        return hits

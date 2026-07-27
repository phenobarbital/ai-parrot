"""``MultiStoreSearchToolkit`` — multi-origin retrieval toolkit (FEAT-379).

Orchestrates an ordered registry of :class:`~parrot_tools.multistoresearch.
origins.base.SearchOrigin` adapters (vector stores, PageIndex, GraphIndex,
ParrotWiki) behind four agent-facing tools: ``store_search``,
``batch_search``, ``fts_search``, ``list_search_origins``.

Every response carries BOTH grouped-by-origin sections (native ranking +
an LLM-readable origin description — sections intentionally keep
cross-origin duplicates) AND a merged, deduped, BM25-reranked top-k
block. Origin-native scores are NOT cross-origin comparable (vector
distances, wiki FTS ranks, and graph scores live on different scales) —
the merged block ranks purely by BM25-over-content, never by raw score.

Per-origin failures and timeouts degrade to an ``OriginSection`` status
note; they never fail the whole call. Default per-origin timeout is
30s, overridable per adapter via ``SearchOrigin.timeout``.
"""
from __future__ import annotations

import asyncio
import hashlib
from typing import Any, Dict, List, Optional, Tuple

from rank_bm25 import BM25Okapi

from parrot.models import MultiSearchResponse, OriginHit, OriginSection
from parrot.tools.toolkit import AbstractToolkit

from .origins.base import SearchOrigin

_SCORE_CAVEAT_NOTE = (
    "Origin scores are native to each backend (vector distances, wiki FTS "
    "ranks, graph scores, ...) and are NOT cross-origin comparable. "
    "merged_top_k is ranked by BM25-over-content, not by raw score."
)


class MultiStoreSearchToolkit(AbstractToolkit):
    """Agent-facing toolkit fanning a query out across multiple origins.

    Args:
        origins: Ordered list of configured :class:`SearchOrigin` adapters
            (e.g. ``VectorStoreOrigin``, ``PageIndexOrigin``,
            ``GraphIndexOrigin``, ``ParrotWikiOrigin``). An empty list is
            valid — tools return a structured "no origins configured"
            response instead of raising.
        k: Default cap on the merged top-k block returned by
            ``store_search``/``batch_search``/``fts_search``.
        k_per_origin: Number of hits requested from EACH origin before
            merging (typically larger than ``k`` to give the BM25 rerank
            enough candidates).
        default_timeout: Default per-origin timeout in seconds, used
            whenever an origin does not set its own ``timeout``.
        bm25_weights: Optional per-origin multiplier applied to that
            origin's BM25 score when building the merged ranking (e.g.
            ``{"wiki": 0.8}`` to slightly de-prioritise wiki hits).
        **kwargs: Forwarded to :class:`AbstractToolkit`.
    """

    #: `search` satisfies the core `MultiSearch` protocol but is not a
    #: user-facing tool — only the four methods below are.
    exclude_tools: Tuple[str, ...] = ("search",)

    def __init__(
        self,
        origins: List[SearchOrigin],
        k: int = 10,
        k_per_origin: int = 20,
        default_timeout: float = 30.0,
        bm25_weights: Optional[Dict[str, float]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.origins = list(origins)
        self.k = k
        self.k_per_origin = k_per_origin
        self.default_timeout = default_timeout
        self.bm25_weights = bm25_weights or {}

    # ------------------------------------------------------------------
    # Agent-facing tools
    # ------------------------------------------------------------------

    async def store_search(
        self, query: str, k: Optional[int] = None
    ) -> MultiSearchResponse:
        """Search all enabled origins and return grouped + merged results.

        Runs every configured origin concurrently (each origin's own
        native ranking is preserved in its own section — this is
        deliberate, even when the same document appears in multiple
        origins), then produces a single deduped, BM25-reranked top-k
        list across all origins combined.

        Args:
            query: Natural-language search query.
            k: Maximum number of hits in the merged top-k block. Defaults
                to the toolkit's configured ``k``.

        Returns:
            A grouped-by-origin + merged-top-k response. Per-origin
            failures or timeouts degrade to a section status note rather
            than raising.
        """
        k = k or self.k
        if not self.origins:
            return self._no_origins_response(query)

        sections = await self._run_origins(query, self.k_per_origin, fts=False)
        return self._build_response(query, sections, k)

    async def batch_search(
        self, queries: List[str], k: Optional[int] = None
    ) -> List[MultiSearchResponse]:
        """Search all enabled origins for N queries in one batched pass.

        All ``len(queries) * len(origins)`` origin calls are dispatched
        through a single ``asyncio.gather`` (no per-query sequential
        loop, no thread offloading) — this is the efficient way to fan
        out many queries against the same origin registry.

        Args:
            queries: List of natural-language search queries. An empty
                list returns an empty list.
            k: Maximum number of hits in each query's merged top-k block.
                Defaults to the toolkit's configured ``k``.

        Returns:
            One :class:`~parrot.models.MultiSearchResponse` per input
            query, in the same shape as ``store_search``, in the same
            order as ``queries``.
        """
        if not queries:
            return []
        k = k or self.k
        if not self.origins:
            return [self._no_origins_response(query) for query in queries]

        # Build the full N (queries) x M (origins) task plan and dispatch
        # it through exactly ONE asyncio.gather call (decision).
        plan: List[Tuple[int, SearchOrigin]] = []
        coros = []
        for query_idx, query in enumerate(queries):
            for origin in self.origins:
                timeout = origin.timeout or self.default_timeout
                coros.append(
                    asyncio.wait_for(
                        origin.search(query, self.k_per_origin), timeout=timeout
                    )
                )
                plan.append((query_idx, origin))

        results = await asyncio.gather(*coros, return_exceptions=True)

        sections_by_query: List[List[OriginSection]] = [[] for _ in queries]
        for (query_idx, origin), result in zip(plan, results):
            sections_by_query[query_idx].append(
                self._section_from_result(origin, result)
            )

        return [
            self._build_response(query, sections_by_query[query_idx], k)
            for query_idx, query in enumerate(queries)
        ]

    async def fts_search(
        self, query: str, k: Optional[int] = None
    ) -> MultiSearchResponse:
        """Run full-text search on FTS-capable origins only.

        Origins without full-text support (``supports_fts=False``) are
        reported as skipped sections with a reason, rather than being
        silently omitted — the LLM can see which origins were consulted.

        Args:
            query: Full-text search query.
            k: Maximum number of hits in the merged top-k block. Defaults
                to the toolkit's configured ``k``.

        Returns:
            A grouped-by-origin + merged-top-k response. When no
            configured origin supports FTS, all sections are "skipped"
            and the merged block is empty.
        """
        k = k or self.k
        if not self.origins:
            return self._no_origins_response(query)

        sections = await self._run_origins(query, self.k_per_origin, fts=True)
        return self._build_response(query, sections, k)

    async def list_search_origins(self) -> List[Dict[str, Any]]:
        """List the statically configured search origins.

        Returns:
            One dict per configured origin with ``name``, ``kind``,
            ``description``, ``supports_fts``, ``timeout``, and any
            adapter-specific extra settings (e.g. PageIndex's ``mode``).
            This is a static configuration view only — no live
            health/staleness probing is performed.
        """
        entries = []
        for origin in self.origins:
            entry: Dict[str, Any] = {
                "name": origin.name,
                "kind": origin.kind.value,
                "description": origin.description,
                "supports_fts": origin.supports_fts,
                "timeout": origin.timeout or self.default_timeout,
            }
            # Duck-typed extra-settings probe (e.g. PageIndexOrigin.mode) —
            # avoids importing concrete adapter classes here.
            mode = getattr(origin, "mode", None)
            if mode is not None:
                entry["mode"] = mode
            entries.append(entry)
        return entries

    # ------------------------------------------------------------------
    # MultiSearch protocol satisfaction (excluded from tool generation)
    # ------------------------------------------------------------------

    async def search(self, query: str, k: Optional[int] = None, **kwargs: Any) -> Any:
        """Satisfy the core ``MultiSearch`` protocol; delegates to store_search.

        Not exposed as an agent tool (see ``exclude_tools``) — this is
        the seam ``StoreRouter``'s FAN_OUT fallback and
        ``AbstractBot.configure_store_router`` call against.
        """
        return await self.store_search(query, k=k)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _no_origins_response(self, query: str) -> MultiSearchResponse:
        """Structured response used when no origins are configured."""
        return MultiSearchResponse(
            query=query,
            sections=[],
            merged_top_k=[],
            notes=["No search origins configured — nothing to search."],
        )

    def _build_response(
        self, query: str, sections: List[OriginSection], k: int
    ) -> MultiSearchResponse:
        """Assemble a MultiSearchResponse from sections: rerank, dedupe, cap."""
        all_hits = [hit for section in sections for hit in section.hits]
        reranked = self._rerank_with_bm25(query, all_hits)
        deduped = self._deduplicate_hits(reranked)

        notes = [_SCORE_CAVEAT_NOTE]
        if sections and not any(s.status == "ok" for s in sections):
            notes.append(
                "No origin returned results for this query (see per-origin "
                "status/note in each section)."
            )

        return MultiSearchResponse(
            query=query,
            sections=sections,
            merged_top_k=deduped[:k],
            notes=notes,
        )

    async def _run_origins(
        self, query: str, k: int, fts: bool
    ) -> List[OriginSection]:
        """Run every origin (search or fts_search) with per-origin isolation.

        Origins that don't support FTS are reported as "skipped" sections
        without ever being called, when ``fts=True``. All other origins
        are dispatched concurrently via ``asyncio.gather`` with a
        per-origin ``asyncio.wait_for`` timeout; failures/timeouts
        degrade to a status note (never raised).
        """
        plan: List[Tuple[SearchOrigin, Optional[int]]] = []
        coros = []
        for origin in self.origins:
            if fts and not origin.supports_fts:
                plan.append((origin, None))
                continue
            method = origin.fts_search if fts else origin.search
            timeout = origin.timeout or self.default_timeout
            coros.append(asyncio.wait_for(method(query, k), timeout=timeout))
            plan.append((origin, len(coros) - 1))

        results = await asyncio.gather(*coros, return_exceptions=True) if coros else []

        sections = []
        for origin, idx in plan:
            if idx is None:
                sections.append(
                    self._skipped_section(
                        origin, "origin does not support full-text search"
                    )
                )
            else:
                sections.append(self._section_from_result(origin, results[idx]))
        return sections

    def _section_from_result(self, origin: SearchOrigin, result: Any) -> OriginSection:
        """Build an OriginSection from a gather()'d result/exception."""
        if isinstance(result, asyncio.TimeoutError):
            timeout_val = origin.timeout or self.default_timeout
            return OriginSection(
                origin=origin.name,
                origin_kind=origin.kind,
                description=origin.description,
                status="timeout",
                note=f"origin exceeded timeout of {timeout_val}s",
                hits=[],
            )
        if isinstance(result, Exception):
            return OriginSection(
                origin=origin.name,
                origin_kind=origin.kind,
                description=origin.description,
                status="error",
                note=repr(result),
                hits=[],
            )
        return OriginSection(
            origin=origin.name,
            origin_kind=origin.kind,
            description=origin.description,
            status="ok",
            note=None,
            hits=result,
        )

    def _skipped_section(self, origin: SearchOrigin, reason: str) -> OriginSection:
        """Build a "skipped" OriginSection (never actually called)."""
        return OriginSection(
            origin=origin.name,
            origin_kind=origin.kind,
            description=origin.description,
            status="skipped",
            note=reason,
            hits=[],
        )

    def _prepare_bm25_corpus(
        self, hits: List[OriginHit]
    ) -> Tuple[List[List[str]], List[OriginHit]]:
        """Tokenize hit content for BM25 indexing (lifted from the legacy tool)."""
        corpus = []
        valid_hits = []
        for hit in hits:
            if not hit.content:
                continue
            if tokens := hit.content.lower().split():
                corpus.append(tokens)
                valid_hits.append(hit)
        return corpus, valid_hits

    def _rerank_with_bm25(
        self, query: str, hits: List[OriginHit]
    ) -> List[OriginHit]:
        """Rerank hits by BM25-over-content (+ optional per-origin weight).

        Origin-native ``OriginHit.score`` values are left untouched —
        they are not cross-origin comparable. Only the RETURN ORDER is
        determined by BM25; ties/absence of a scorable corpus fall back
        to the original (origin-gather) order.
        """
        if not hits:
            return []

        corpus, valid_hits = self._prepare_bm25_corpus(hits)
        if not corpus:
            return hits

        query_tokens = query.lower().split()
        if not query_tokens:
            return hits

        bm25 = BM25Okapi(corpus)
        bm25_scores = bm25.get_scores(query_tokens)

        scored = [
            (float(bm25_scores[idx]) * self.bm25_weights.get(hit.origin, 1.0), hit)
            for idx, hit in enumerate(valid_hits)
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [hit for _, hit in scored]

    def _deduplicate_hits(self, hits: List[OriginHit]) -> List[OriginHit]:
        """Dedupe by exact ID match, then content hash (lifted from the legacy tool).

        Preserves the incoming order (post-BM25-rerank), so the
        highest-ranked occurrence of a duplicate wins.
        """
        if not hits:
            return []

        unique: List[OriginHit] = []
        seen_ids = set()
        seen_content_hashes = set()

        for hit in hits:
            if hit.id:
                if hit.id in seen_ids:
                    continue
                seen_ids.add(hit.id)

            if hit.content:
                content_sample = hit.content.strip()
                content_hash = hashlib.sha256(
                    content_sample.encode("utf-8")
                ).hexdigest()
                if content_hash in seen_content_hashes:
                    continue
                seen_content_hashes.add(content_hash)

            unique.append(hit)

        return unique

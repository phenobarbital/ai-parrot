"""Combined search across PageIndex and GraphIndex for the LLM Wiki (FEAT-260).

Implements unified search that merges results from:

- **PageIndex** ``HybridPageIndexSearch`` (BM25 + LLM walk) via
  ``PageIndexToolkit.search()``.
- **GraphIndex** ``GraphExpandedRetriever`` via
  ``GraphIndexToolkit.search_hybrid()``.

Results from each backend are min-max normalised to [0, 1], weighted by
the configurable ``search_weights`` dictionary, deduplicated by ``node_id``,
and returned as a sorted :class:`WikiSearchResult` list.

Search modes:
- ``"pageindex"`` — PageIndex only; GraphIndex is not called.
- ``"graphindex"`` — GraphIndex only; PageIndex is not called.
- ``"combined"`` (default) — both backends, weights applied.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from parrot.knowledge.wiki.models import WikiSearchResult


class WikiCombinedSearch:
    """Unified search across PageIndex and GraphIndex.

    Attributes:
        _pi: ``PageIndexToolkit`` instance for tree-based search.
        _gi: ``GraphIndexToolkit`` instance for graph-based search.
        _weights: Score weights for each backend (must sum to ~1.0).
        logger: Standard Python logger.

    Example::

        cs = WikiCombinedSearch(pi_toolkit, gi_toolkit)
        results = await cs.search("neural networks", mode="combined", top_k=10)
    """

    def __init__(
        self,
        pageindex_toolkit: Any,
        graphindex_toolkit: Any,
        default_weights: Optional[dict[str, float]] = None,
    ) -> None:
        """Initialise combined search with two toolkit backends.

        Args:
            pageindex_toolkit: A ``PageIndexToolkit`` instance.
            graphindex_toolkit: A ``GraphIndexToolkit`` instance.
            default_weights: Optional weighting dict with keys
                ``"pageindex"`` and ``"graphindex"``.  Defaults to
                ``{"pageindex": 0.6, "graphindex": 0.4}``.
        """
        self._pi = pageindex_toolkit
        self._gi = graphindex_toolkit
        self._weights: dict[str, float] = default_weights or {
            "pageindex": 0.6,
            "graphindex": 0.4,
        }
        self.logger: logging.Logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        mode: str = "combined",
        top_k: int = 10,
        tree_name: Optional[str] = None,
        weights: Optional[dict[str, float]] = None,
    ) -> list[WikiSearchResult]:
        """Search the wiki and return merged, ranked results.

        Args:
            query: Natural-language search query.
            mode: One of ``"combined"``, ``"pageindex"``, or
                ``"graphindex"``.  Unknown modes default to ``"combined"``.
            top_k: Maximum results to return per backend (before merging).
            tree_name: Optional PageIndex tree name to scope the search.
                When ``None``, the PageIndex toolkit searches all trees.
            weights: Optional per-call override for score weights.  Falls
                back to ``self._weights`` when ``None``.

        Returns:
            Sorted list of :class:`WikiSearchResult` objects (descending
            by score).  May be empty if no backends returned results.
        """
        effective_weights = weights or self._weights
        mode = mode.lower()

        pi_results: list[WikiSearchResult] = []
        gi_results: list[WikiSearchResult] = []

        if mode in ("pageindex", "combined"):
            pi_results = await self._search_pageindex(
                query, top_k, tree_name=tree_name
            )

        if mode in ("graphindex", "combined"):
            gi_results = await self._search_graphindex(query, top_k)

        if not pi_results and not gi_results:
            return []

        merged = self._merge_results(pi_results, gi_results, effective_weights)
        return merged[:top_k]

    async def find_related(
        self,
        page_id: str,
        depth: int = 2,
    ) -> list[dict[str, Any]]:
        """Discover pages related to a given wiki page via graph traversal.

        Delegates to ``GraphIndexToolkit.get_neighborhood(node_id, depth)``.

        Args:
            page_id: GraphIndex node ID of the page to explore from.
            depth: Maximum traversal depth (hops) from the seed node.

        Returns:
            A list of neighbour node dicts as returned by
            ``GraphIndexToolkit.get_neighborhood()``.  Returns an empty
            list on error.
        """
        try:
            result = await self._gi.get_neighborhood(page_id, depth=depth)
            neighbours = result.get("neighbours", result.get("nodes", []))
            return neighbours if isinstance(neighbours, list) else []
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "find_related: get_neighborhood(%s, depth=%d) failed: %s",
                page_id,
                depth,
                exc,
            )
            return []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _search_pageindex(
        self,
        query: str,
        top_k: int,
        tree_name: Optional[str] = None,
    ) -> list[WikiSearchResult]:
        """Delegate search to PageIndexToolkit and normalise results.

        Args:
            query: Natural-language search query.
            top_k: Maximum results to request.
            tree_name: Optional tree name scope.

        Returns:
            List of :class:`WikiSearchResult` with ``source="pageindex"``.
        """
        try:
            raw: list[dict] = await self._pi.search(
                tree_name or "wiki",
                query,
                top_k=top_k,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("PageIndex search failed: %s", exc)
            return []

        return [self._pi_result_to_wiki(r) for r in raw if isinstance(r, dict)]

    async def _search_graphindex(
        self,
        query: str,
        top_k: int,
    ) -> list[WikiSearchResult]:
        """Delegate search to GraphIndexToolkit and normalise results.

        Args:
            query: Natural-language search query.
            top_k: Maximum results to request.

        Returns:
            List of :class:`WikiSearchResult` with ``source="graphindex"``.
        """
        try:
            raw: list[dict] = await self._gi.search_hybrid(query, top_k=top_k)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("GraphIndex search failed: %s", exc)
            return []

        return [self._gi_result_to_wiki(r) for r in raw if isinstance(r, dict)]

    def _pi_result_to_wiki(self, raw: dict[str, Any]) -> WikiSearchResult:
        """Convert a PageIndex search result dict to WikiSearchResult.

        Args:
            raw: Raw result dict from PageIndexToolkit.search().

        Returns:
            A :class:`WikiSearchResult` with ``source="pageindex"``.
        """
        return WikiSearchResult(
            node_id=str(raw.get("node_id") or raw.get("id") or ""),
            title=str(raw.get("title") or raw.get("name") or ""),
            score=float(raw.get("score") or 0.0),
            source="pageindex",
            snippet=str(raw.get("summary") or raw.get("snippet") or ""),
        )

    def _gi_result_to_wiki(self, raw: dict[str, Any]) -> WikiSearchResult:
        """Convert a GraphIndex search result dict to WikiSearchResult.

        Args:
            raw: Raw result dict from GraphIndexToolkit.search_hybrid().

        Returns:
            A :class:`WikiSearchResult` with ``source="graphindex"``.
        """
        return WikiSearchResult(
            node_id=str(raw.get("node_id") or raw.get("id") or ""),
            title=str(raw.get("title") or raw.get("name") or ""),
            score=float(raw.get("score") or 0.0),
            source="graphindex",
            snippet=str(raw.get("summary") or raw.get("snippet") or ""),
        )

    def _merge_results(
        self,
        pi_results: list[WikiSearchResult],
        gi_results: list[WikiSearchResult],
        weights: dict[str, float],
    ) -> list[WikiSearchResult]:
        """Normalise, weight, deduplicate, and sort results from both backends.

        Score normalisation uses min-max scaling per backend (scores scaled to
        [0, 1]).  After scaling, each score is multiplied by its backend's
        weight.  When the same ``node_id`` appears in both backends, the entry
        with the higher weighted score is kept.

        Args:
            pi_results: PageIndex search results.
            gi_results: GraphIndex search results.
            weights: Weight mapping with keys ``"pageindex"`` and
                ``"graphindex"``.

        Returns:
            Deduplicated list sorted by weighted score (descending).
        """
        pi_weight = weights.get("pageindex", 0.6)
        gi_weight = weights.get("graphindex", 0.4)

        # Normalise each group and apply weight
        weighted_pi = self._apply_weight(pi_results, pi_weight)
        weighted_gi = self._apply_weight(gi_results, gi_weight)

        # Merge, keeping highest-scored duplicate by node_id
        seen: dict[str, WikiSearchResult] = {}
        for result in weighted_pi + weighted_gi:
            existing = seen.get(result.node_id)
            if existing is None or result.score > existing.score:
                seen[result.node_id] = result

        # Sort descending by weighted score
        merged = sorted(seen.values(), key=lambda r: r.score, reverse=True)
        return merged

    def _apply_weight(
        self,
        results: list[WikiSearchResult],
        weight: float,
    ) -> list[WikiSearchResult]:
        """Min-max normalise scores and multiply by the backend weight.

        Args:
            results: Raw results from a single backend.
            weight: Backend weight in [0, 1].

        Returns:
            New list of :class:`WikiSearchResult` with updated scores.
            Scores are clipped to [0, 1] after weighting.
        """
        if not results:
            return []

        raw_scores = [r.score for r in results]
        min_s = min(raw_scores)
        max_s = max(raw_scores)
        span = max_s - min_s

        weighted: list[WikiSearchResult] = []
        for r in results:
            if span > 0:
                normalised = (r.score - min_s) / span
            else:
                # All scores identical — treat as 1.0 after normalisation
                normalised = 1.0

            weighted_score = min(max(normalised * weight, 0.0), 1.0)
            weighted.append(
                WikiSearchResult(
                    node_id=r.node_id,
                    title=r.title,
                    score=weighted_score,
                    source=r.source,
                    snippet=r.snippet,
                    category=r.category,
                )
            )
        return weighted

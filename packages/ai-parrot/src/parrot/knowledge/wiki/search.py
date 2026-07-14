"""Combined search for the LLM Wiki (FEAT-260 + WikiStore plane).

Preferred path — when a :class:`WikiStore` is provided, every query is
answered directly from the single-file SQLite plane (no toolkit
fan-out, no markdown parsing at query time):

- **lexical** — FTS5/BM25 over title/summary/body.
- **vector** — cosine over stored page embeddings (requires an
  ``embedder`` callable).
- ``"combined"`` (default) merges both with configurable weights.
  Legacy mode names map onto the plane: ``"pageindex"`` → lexical,
  ``"graphindex"`` → vector.

Legacy path — without a store, results are merged from
``PageIndexToolkit.search()`` and ``GraphIndexToolkit.search_hybrid()``
exactly as before (kept for one release).

Results from each group are min-max normalised to [0, 1], weighted by
the configurable ``search_weights`` dictionary, deduplicated by
``node_id``, and returned as a sorted :class:`WikiSearchResult` list.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

from parrot.knowledge.wiki.models import WikiPageCategory, WikiSearchResult
from parrot.knowledge.wiki.store import WikiStore


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
        store: Optional[WikiStore] = None,
        embedder: Optional[Callable[[str], Awaitable[list[float]]]] = None,
    ) -> None:
        """Initialise combined search.

        Args:
            pageindex_toolkit: A ``PageIndexToolkit`` instance (legacy
                path only — unused when ``store`` is provided).
            graphindex_toolkit: A ``GraphIndexToolkit`` instance (legacy
                path only).
            default_weights: Optional weighting dict.  Accepts the new
                keys ``"lexical"`` / ``"vector"`` or the legacy aliases
                ``"pageindex"`` / ``"graphindex"``.  Defaults to
                ``{"pageindex": 0.6, "graphindex": 0.4}``.
            store: :class:`WikiStore` retrieval plane.  When provided,
                all searches run against it (preferred path).
            embedder: Optional async ``text -> vector`` callable used
                for the vector leg of store-backed search.
        """
        self._pi = pageindex_toolkit
        self._gi = graphindex_toolkit
        self._store = store
        self._embedder = embedder
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

        if self._store is not None:
            return await self._search_store(
                query, mode=mode, top_k=top_k, weights=effective_weights
            )

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

    async def _search_store(
        self,
        query: str,
        mode: str,
        top_k: int,
        weights: dict[str, float],
    ) -> list[WikiSearchResult]:
        """Answer a search entirely from the WikiStore SQLite plane.

        Args:
            query: Natural-language query.
            mode: ``"combined"``, ``"lexical"`` (alias ``"pageindex"``),
                or ``"vector"`` (alias ``"graphindex"``).
            top_k: Maximum merged results.
            weights: Weight mapping (new or legacy key names).

        Returns:
            Sorted, deduplicated :class:`WikiSearchResult` list.
        """
        lex_weight = weights.get("lexical", weights.get("pageindex", 0.6))
        vec_weight = weights.get("vector", weights.get("graphindex", 0.4))

        want_lexical = mode in ("combined", "lexical", "pageindex")
        want_vector = mode in ("combined", "vector", "graphindex")

        lexical_results: list[WikiSearchResult] = []
        if want_lexical:
            try:
                rows = await self._store.search_fts(query, limit=top_k)
                lexical_results = [
                    self._store_row_to_wiki(r, source="lexical")
                    for r in self._normalize_rows(rows)
                ]
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("WikiStore FTS search failed: %s", exc)

        vector_results: list[WikiSearchResult] = []
        if want_vector and self._embedder is not None:
            try:
                embedding = await self._embedder(query)
                rows = await self._store.search_vector(embedding, limit=top_k)
                vector_results = [
                    self._store_row_to_wiki(r, source="vector")
                    for r in self._normalize_rows(rows)
                ]
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("WikiStore vector search failed: %s", exc)

        # When only one leg produced results, give it full weight so
        # scores stay meaningful in [0, 1].
        if lexical_results and not vector_results:
            lex_weight = 1.0
        elif vector_results and not lexical_results:
            vec_weight = 1.0

        merged = self._merge_groups(
            [(lexical_results, lex_weight), (vector_results, vec_weight)]
        )
        return merged[:top_k]

    @staticmethod
    def _normalize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Min-max normalise raw store scores into [0, 1] per group.

        Raw scores (``-bm25`` or cosine) are unbounded / signed, but
        :class:`WikiSearchResult` enforces ``score ∈ [0, 1]`` — so the
        normalisation must happen before model construction.
        """
        if not rows:
            return []
        scores = [float(r.get("score") or 0.0) for r in rows]
        min_s, max_s = min(scores), max(scores)
        span = max_s - min_s
        out = []
        for row, raw in zip(rows, scores):
            item = dict(row)
            item["score"] = (raw - min_s) / span if span > 0 else 1.0
            out.append(item)
        return out

    @staticmethod
    def _store_row_to_wiki(
        row: dict[str, Any], source: str
    ) -> WikiSearchResult:
        """Convert a WikiStore result row to a :class:`WikiSearchResult`."""
        raw_category = row.get("category")
        try:
            category = WikiPageCategory(raw_category) if raw_category else None
        except ValueError:
            category = None
        return WikiSearchResult(
            node_id=str(row.get("concept_id") or row.get("node_id") or ""),
            title=str(row.get("title") or ""),
            score=min(max(float(row.get("score") or 0.0), 0.0), 1.0),
            source=source,
            snippet=str(row.get("summary") or ""),
            category=category,
        )

    async def find_related(
        self,
        page_id: str,
        depth: int = 2,
    ) -> list[dict[str, Any]]:
        """Discover pages related to a given wiki page via graph traversal.

        Prefers ``GraphIndexToolkit.get_neighborhood(node_id, depth)`` when
        available.  Falls back to ``search_hybrid(page_id)`` to approximate
        neighbourhood retrieval when ``get_neighborhood`` is absent — this
        guards against runtimes where the method has not been implemented yet.

        Args:
            page_id: GraphIndex node ID of the page to explore from.
            depth: Maximum traversal depth (hops) from the seed node.

        Returns:
            A list of neighbour node dicts.  Returns an empty list on error.
        """
        if self._store is not None:
            return await self._find_related_store(page_id, depth=depth)
        try:
            gn_method = getattr(self._gi, "get_neighborhood", None)
            if callable(gn_method):
                result = await self._gi.get_neighborhood(page_id, depth=depth)
                neighbours = result.get("neighbours", result.get("nodes", []))
                return neighbours if isinstance(neighbours, list) else []

            # Fallback: use search_hybrid with the page_id as a seed query.
            # This approximates neighbourhood by retrieving semantically related
            # nodes rather than hop-bounded graph neighbours.
            self.logger.debug(
                "get_neighborhood not available on %s; "
                "falling back to search_hybrid for find_related",
                type(self._gi).__name__,
            )
            raw = await self._gi.search_hybrid(page_id, top_k=depth * 5)
            return raw if isinstance(raw, list) else []
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "find_related(%s, depth=%d) failed: %s",
                page_id,
                depth,
                exc,
            )
            return []

    async def _find_related_store(
        self,
        page_id: str,
        depth: int = 2,
    ) -> list[dict[str, Any]]:
        """BFS over the WikiStore edges table up to ``depth`` hops.

        Args:
            page_id: Seed concept_id.
            depth: Maximum number of hops from the seed.

        Returns:
            Neighbour dicts (each includes ``concept_id``, ``rel``,
            ``direction``, ``hops``, and page stub fields when the
            target is a known page).  Empty list on error.
        """
        try:
            seen: set[str] = {page_id}
            frontier = [page_id]
            related: list[dict[str, Any]] = []
            for hop in range(1, max(1, depth) + 1):
                next_frontier: list[str] = []
                for cid in frontier:
                    for item in await self._store.neighbors(cid):
                        target = str(item.get("concept_id") or "")
                        if not target or target in seen:
                            continue
                        seen.add(target)
                        item["hops"] = hop
                        related.append(item)
                        next_frontier.append(target)
                frontier = next_frontier
                if not frontier:
                    break
            return related
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "find_related(%s) via WikiStore failed: %s", page_id, exc
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
        return self._merge_groups(
            [(pi_results, pi_weight), (gi_results, gi_weight)]
        )

    def _merge_groups(
        self,
        groups: list[tuple[list[WikiSearchResult], float]],
    ) -> list[WikiSearchResult]:
        """Weight, deduplicate, and sort result groups.

        Each group is min-max normalised and multiplied by its weight;
        when the same ``node_id`` appears in several groups the entry
        with the higher weighted score is kept.

        Args:
            groups: ``(results, weight)`` pairs.

        Returns:
            Deduplicated list sorted by weighted score (descending).
        """
        seen: dict[str, WikiSearchResult] = {}
        for results, weight in groups:
            for result in self._apply_weight(results, weight):
                existing = seen.get(result.node_id)
                if existing is None or result.score > existing.score:
                    seen[result.node_id] = result
        return sorted(seen.values(), key=lambda r: r.score, reverse=True)

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

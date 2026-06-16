"""Graph-Expanded Retrieval Pipeline.

Orchestrates a 4-phase retrieval pipeline over the assembled GraphIndex:

  Phase 1 — Seed Search:
    Selects initial candidate nodes via HybridPageIndexSearch (PageIndex path)
    or GraphIndexEmbedder.search_similar() (FAISS path). Scores normalised to
    ``[0, 1]``.

  Phase 2 — Graph Expansion:
    Starting from seed nodes, traverses the graph N hops outward using
    ``relevance_neighborhood()``.  Scores decay exponentially per hop:
    ``combined = parent_score * decay_base^hop * signal.combined``.  Nodes are
    deduplicated by ``node_id``, keeping the highest combined score.

  Phase 3 — Community Context:
    Annotates each expanded node with ``community_id`` and ``community_cohesion``
    from an optional ``CommunitiesResult``.  When ``CommunitiesResult`` is ``None``
    this phase is a no-op.

  Phase 4 — Result Assembly:
    Sorts nodes by ``combined_score`` (descending), applies a token budget, and
    returns a ``GraphRetrievalResult`` with decomposed scores and metadata.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Optional

import rustworkx
from pydantic import BaseModel, Field

from parrot.knowledge.graphindex.signals import relevance_neighborhood

if TYPE_CHECKING:
    from parrot.knowledge.graphindex.communities import CommunitiesResult
    from parrot.knowledge.graphindex.embed import GraphIndexEmbedder
    from parrot.knowledge.graphindex.schema import UniversalNode
    from parrot.knowledge.graphindex.signals import SignalRelevanceConfig
    from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch

# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


class ExpansionConfig(BaseModel):
    """Configuration for the graph expansion phase (Phase 2).

    Args:
        max_hops: Maximum number of hops to traverse outward from each seed.
            Must be between 1 and 4.
        decay_base: Multiplicative decay applied per hop.  A seed node at hop
            distance *h* has its parent's combined score multiplied by
            ``decay_base^h``.  Default ``0.7`` so hop 1 → 0.7, hop 2 → 0.49.
        min_signal_threshold: Neighbours with a ``SignalRelevance.combined``
            score strictly below this value are ignored during expansion.
        max_expanded_nodes: Hard cap on the total number of nodes (seeds +
            expanded) carried into Phase 3.  Expansion stops early when
            reached.
        include_community_centroids: When ``True`` and a ``CommunitiesResult``
            is available, add the centroid node of each touched community to
            the result set if not already present.
    """

    max_hops: int = Field(default=2, ge=1, le=4)
    decay_base: float = Field(default=0.7, gt=0.0, le=1.0)
    min_signal_threshold: float = Field(default=0.1, ge=0.0)
    max_expanded_nodes: int = Field(default=50, ge=1)
    include_community_centroids: bool = False


class BudgetConfig(BaseModel):
    """Token budget for Phase 4 result assembly.

    Args:
        max_tokens: Maximum total tokens to budget for the returned nodes.
        tokens_per_node_estimate: Rough heuristic for tokens consumed per
            node.  The actual count depends on content length; this is used
            only for truncation purposes.
    """

    max_tokens: int = Field(default=8000, ge=100)
    tokens_per_node_estimate: int = Field(default=200, ge=10)


class ScoredNode(BaseModel):
    """A retrieval candidate with decomposed scores.

    Args:
        node_id: Unique node identifier within the graph.
        title: Human-readable display name of the node.
        kind: Semantic category string (e.g. ``"document"``, ``"concept"``).
        search_score: Normalised score ``[0, 1]`` from the Phase 1 seed
            search (0.0 for expanded nodes that were not seeds).
        signal_score: ``SignalRelevance.combined`` value used during
            expansion (0.0 for seed nodes).
        decay_factor: Cumulative decay applied: ``decay_base^hop_distance``
            (1.0 for seeds).
        combined_score: Effective ranking score: the product of parent's
            combined score, decay, and signal.  For seeds this equals
            ``search_score``.
        hop_distance: Number of hops from the nearest seed (0 for seeds
            themselves).
        community_id: Community identifier assigned in Phase 3, or ``None``
            when Phase 3 is skipped.
        community_cohesion: Cohesion score of the node's community, or
            ``None``.
        is_seed: ``True`` if this node was returned by Phase 1 seed search.
        source_uri: Source URI of the underlying document or artefact.
        summary: Short textual summary of the node content, if available.
    """

    node_id: str
    title: str
    kind: str
    search_score: float = 0.0
    signal_score: float = 0.0
    decay_factor: float = 1.0
    combined_score: float = 0.0
    hop_distance: int = 0
    community_id: Optional[str] = None
    community_cohesion: Optional[float] = None
    is_seed: bool = False
    source_uri: Optional[str] = None
    summary: Optional[str] = None


class GraphRetrievalResult(BaseModel):
    """Complete result of a graph-expanded retrieval query.

    Args:
        query: The original query string passed to ``search()``.
        nodes: Ranked list of candidate nodes, sorted by ``combined_score``
            descending.
        total_candidates: Total nodes considered before budget truncation.
        nodes_expanded: Number of nodes added during Phase 2 (does not
            include seeds).
        communities_touched: Number of distinct community IDs present in the
            final node list.
        budget_used: Estimated tokens consumed by the returned nodes.
        budget_limit: ``BudgetConfig.max_tokens`` value used for this query.
        truncated: ``True`` if the result was cut short by the token budget.
    """

    query: str
    nodes: list[ScoredNode]
    total_candidates: int = 0
    nodes_expanded: int = 0
    communities_touched: int = 0
    budget_used: int = 0
    budget_limit: int = 0
    truncated: bool = False


# ---------------------------------------------------------------------------
# Retriever Class
# ---------------------------------------------------------------------------


class GraphExpandedRetriever:
    """4-phase graph-expanded retrieval pipeline.

    Composes existing search, signal-relevance, and community-detection
    components — never subclasses them.  At least one of ``hybrid_search``
    or ``embedder`` must be provided; both ``None`` raises ``ValueError``.

    Args:
        graph: Assembled ``rustworkx.PyDiGraph`` with node payloads.
        nodes: Full list of ``UniversalNode`` instances mirroring graph.
        embedder: Optional ``GraphIndexEmbedder`` for FAISS seed search.
        hybrid_search: Optional ``HybridPageIndexSearch`` for PageIndex seed
            search.  Preferred over ``embedder`` when both are provided.
        signal_config: Optional ``SignalRelevanceConfig`` forwarded to
            ``relevance_neighborhood()``.
        communities: Optional ``CommunitiesResult`` for Phase 3 annotation.
    """

    def __init__(
        self,
        graph: rustworkx.PyDiGraph,
        nodes: list["UniversalNode"],
        embedder: Optional["GraphIndexEmbedder"] = None,
        hybrid_search: Optional["HybridPageIndexSearch"] = None,
        signal_config: Optional["SignalRelevanceConfig"] = None,
        communities: Optional["CommunitiesResult"] = None,
    ) -> None:
        """Initialise the retriever with its component references.

        Raises:
            ValueError: If both ``embedder`` and ``hybrid_search`` are
                ``None``.
        """
        if embedder is None and hybrid_search is None:
            raise ValueError(
                "GraphExpandedRetriever requires at least one of 'embedder' "
                "or 'hybrid_search' — both are None."
            )
        self.graph = graph
        self.nodes = nodes
        self.embedder = embedder
        self.hybrid_search = hybrid_search
        self.signal_config = signal_config
        self.communities = communities
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Phase 1 — Seed Search
    # ------------------------------------------------------------------

    async def _seed_search(
        self,
        query: str,
        top_k: int = 10,
    ) -> list[ScoredNode]:
        """Run seed search and return normalised ``ScoredNode`` list.

        Prefers ``hybrid_search`` when both adapters are available.  Each
        returned node has ``is_seed=True``, ``hop_distance=0``, and
        ``search_score`` normalised to ``[0, 1]``.

        Args:
            query: Natural language query string.
            top_k: Maximum number of seed nodes to return.

        Returns:
            List of seed ``ScoredNode`` objects sorted by descending
            ``search_score``.
        """
        node_map: dict[str, "UniversalNode"] = {n.node_id: n for n in self.nodes}

        if self.hybrid_search is not None:
            return await self._seed_search_hybrid(query, top_k, node_map)
        # Fallback to FAISS embedder path
        return await self._seed_search_faiss(query, top_k, node_map)

    async def _seed_search_hybrid(
        self,
        query: str,
        top_k: int,
        node_map: dict[str, "UniversalNode"],
    ) -> list[ScoredNode]:
        """Seed search via HybridPageIndexSearch.

        Args:
            query: Natural language query string.
            top_k: Maximum results.
            node_map: Mapping ``node_id`` → ``UniversalNode`` for metadata.

        Returns:
            Normalised ``ScoredNode`` list.
        """
        raw: list[dict[str, Any]] = await self.hybrid_search.search(
            query, top_k=top_k
        )
        if not raw:
            return []

        # Normalise scores: top result → 1.0
        max_score = max(float(r.get("score", 0.0)) for r in raw)
        if max_score == 0.0:
            max_score = 1.0  # avoid division by zero

        seeds: list[ScoredNode] = []
        for r in raw:
            nid = r.get("node_id", "")
            if not nid:
                continue
            node_meta = node_map.get(nid)
            if node_meta is None:
                self.logger.warning(
                    "_seed_search_hybrid: node_id %r not found in nodes list; skipping.",
                    nid,
                )
                continue
            raw_score = float(r.get("score", 0.0))
            norm_score = raw_score / max_score
            seeds.append(
                ScoredNode(
                    node_id=nid,
                    title=node_meta.title,
                    kind=str(node_meta.kind.value)
                    if hasattr(node_meta.kind, "value")
                    else str(node_meta.kind),
                    search_score=norm_score,
                    combined_score=norm_score,
                    is_seed=True,
                    hop_distance=0,
                    source_uri=node_meta.source_uri,
                    summary=node_meta.summary,
                )
            )
        return seeds

    async def _seed_search_faiss(
        self,
        query: str,
        top_k: int,
        node_map: dict[str, "UniversalNode"],
    ) -> list[ScoredNode]:
        """Seed search via GraphIndexEmbedder (FAISS).

        L2 distances are converted to similarity via ``1 / (1 + distance)``
        so that smaller distance → higher score.

        Args:
            query: Natural language query string.
            top_k: Maximum results.
            node_map: Mapping ``node_id`` → ``UniversalNode`` for metadata.

        Returns:
            ``ScoredNode`` list sorted descending by similarity score.
        """
        raw: list[tuple[str, float]] = await self.embedder.search_similar(
            query, top_k=top_k
        )
        if not raw:
            return []

        seeds: list[ScoredNode] = []
        for nid, distance in raw:
            node_meta = node_map.get(nid)
            if node_meta is None:
                self.logger.warning(
                    "_seed_search_faiss: node_id %r not found in nodes list; skipping.",
                    nid,
                )
                continue
            # Convert L2 distance → similarity in (0, 1]
            similarity = 1.0 / (1.0 + distance)
            seeds.append(
                ScoredNode(
                    node_id=nid,
                    title=node_meta.title,
                    kind=str(node_meta.kind.value)
                    if hasattr(node_meta.kind, "value")
                    else str(node_meta.kind),
                    search_score=similarity,
                    combined_score=similarity,
                    is_seed=True,
                    hop_distance=0,
                    source_uri=node_meta.source_uri,
                    summary=node_meta.summary,
                )
            )
        # Sort descending by similarity (closest → highest score)
        seeds.sort(key=lambda n: n.search_score, reverse=True)
        return seeds

    # ------------------------------------------------------------------
    # Phase 2 — Graph Expansion
    # ------------------------------------------------------------------

    async def _expand(
        self,
        seeds: list[ScoredNode],
        config: ExpansionConfig,
    ) -> list[ScoredNode]:
        """Expand from seed nodes N hops outward using signal relevance.

        For each node on the frontier at hop ``h``, calls
        ``relevance_neighborhood()`` (sync) to score its neighbours and
        creates a ``ScoredNode`` with:

        .. code-block:: text

            combined = parent.combined_score * decay_base^h * signal.combined

        Nodes reachable via multiple paths keep the highest
        ``combined_score``.

        Args:
            seeds: Initial seed nodes from Phase 1.
            config: Expansion configuration (hops, decay, thresholds).

        Returns:
            Merged list of seed nodes plus all expanded nodes, deduplicated
            by ``node_id``.
        """
        # all_nodes: node_id → ScoredNode (best score wins on collision)
        all_nodes: dict[str, ScoredNode] = {s.node_id: s for s in seeds}
        frontier: list[ScoredNode] = list(seeds)

        # Build lookup maps once before the hop loop to avoid O(N) scans per parent.
        node_meta_map: dict[str, "UniversalNode"] = {n.node_id: n for n in self.nodes}
        graph_idx_map: dict[str, int] = {}
        for idx in self.graph.node_indices():
            payload = self.graph[idx]
            if isinstance(payload, dict) and payload.get("node_id"):
                graph_idx_map[payload["node_id"]] = idx

        for hop in range(1, config.max_hops + 1):
            decay = config.decay_base**hop
            next_frontier: list[ScoredNode] = []

            for parent in frontier:
                if len(all_nodes) >= config.max_expanded_nodes:
                    break

                # Cap candidate pool for high-degree nodes to avoid
                # O(N) signal_relevance calls on very connected nodes.
                candidate_pool: Optional[list[str]] = None
                parent_idx = graph_idx_map.get(parent.node_id)
                if parent_idx is None:
                    continue

                if parent_idx is not None:
                    out_neighbors = [
                        self.graph[t].get("node_id")
                        for _s, t, _ in self.graph.out_edges(parent_idx)
                        if isinstance(self.graph[t], dict)
                    ]
                    in_neighbors = [
                        self.graph[s].get("node_id")
                        for s, _t, _ in self.graph.in_edges(parent_idx)
                        if isinstance(self.graph[s], dict)
                    ]
                    all_adj = [nid for nid in (out_neighbors + in_neighbors) if nid]
                    if len(all_adj) > 100:
                        # Cap to first 100 neighbours to bound computation
                        candidate_pool = all_adj[:100]

                neighbors = await asyncio.to_thread(
                    relevance_neighborhood,
                    self.graph,
                    self.nodes,
                    parent.node_id,
                    top_k=20,
                    config=self.signal_config,
                    candidate_pool=candidate_pool,
                    embedder=self.embedder,
                )

                for sr in neighbors:
                    if sr.combined < config.min_signal_threshold:
                        continue
                    if len(all_nodes) >= config.max_expanded_nodes:
                        break

                    combined = parent.combined_score * decay * sr.combined
                    neighbor_id = sr.node_b

                    if neighbor_id in all_nodes:
                        # Keep the highest combined score (deduplication)
                        if combined > all_nodes[neighbor_id].combined_score:
                            existing = all_nodes[neighbor_id]
                            # Create updated node with new best score
                            updated = ScoredNode(
                                node_id=existing.node_id,
                                title=existing.title,
                                kind=existing.kind,
                                search_score=existing.search_score,
                                signal_score=sr.combined,
                                decay_factor=decay,
                                combined_score=combined,
                                hop_distance=hop,
                                community_id=existing.community_id,
                                community_cohesion=existing.community_cohesion,
                                is_seed=existing.is_seed,
                                source_uri=existing.source_uri,
                                summary=existing.summary,
                            )
                            all_nodes[neighbor_id] = updated
                            next_frontier.append(updated)  # re-queue for further expansion
                        continue

                    # New node — resolve metadata
                    node_meta = node_meta_map.get(neighbor_id)
                    if node_meta is None:
                        self.logger.debug(
                            "_expand: neighbor %r not in nodes list; skipping.",
                            neighbor_id,
                        )
                        continue

                    new_node = ScoredNode(
                        node_id=neighbor_id,
                        title=node_meta.title,
                        kind=str(node_meta.kind.value)
                        if hasattr(node_meta.kind, "value")
                        else str(node_meta.kind),
                        search_score=0.0,
                        signal_score=sr.combined,
                        decay_factor=decay,
                        combined_score=combined,
                        hop_distance=hop,
                        is_seed=False,
                        source_uri=node_meta.source_uri,
                        summary=node_meta.summary,
                    )
                    all_nodes[neighbor_id] = new_node
                    next_frontier.append(new_node)

            frontier = next_frontier
            if not frontier:
                break

        return list(all_nodes.values())

    # ------------------------------------------------------------------
    # Phase 3 — Community Annotation
    # ------------------------------------------------------------------

    def _annotate_communities(
        self,
        nodes: list[ScoredNode],
        config: ExpansionConfig,
    ) -> list[ScoredNode]:
        """Annotate nodes with community membership and optionally add centroids.

        When ``self.communities`` is ``None`` this method returns ``nodes``
        unchanged (Phase 3 graceful skip).

        When ``config.include_community_centroids`` is ``True``, the centroid
        node of each touched community is added to the result if not already
        present.

        Args:
            nodes: Expanded node list from Phase 2.
            config: Expansion config carrying the ``include_community_centroids``
                flag.

        Returns:
            Annotated node list (and optionally enriched with centroids).
        """
        if self.communities is None:
            return nodes

        community_map = {c.community_id: c for c in self.communities.communities}
        node_ids_present = {n.node_id for n in nodes}

        annotated: list[ScoredNode] = []
        for node in nodes:
            cid = self.communities.node_to_community.get(node.node_id)
            if cid:
                community = community_map.get(cid)
                cohesion = community.cohesion if community else None
                node = node.model_copy(update={"community_id": cid, "community_cohesion": cohesion})
            annotated.append(node)
        nodes = annotated

        if config.include_community_centroids:
            centroid_nodes: list[ScoredNode] = []
            touched_community_ids = {n.community_id for n in nodes if n.community_id}
            node_meta_map = {n.node_id: n for n in self.nodes}

            for cid in touched_community_ids:
                community = community_map.get(cid)
                if community is None:
                    continue
                centroid_id = community.centroid_node_id
                if centroid_id in node_ids_present:
                    continue
                meta = node_meta_map.get(centroid_id)
                if meta is None:
                    continue
                centroid_node = ScoredNode(
                    node_id=centroid_id,
                    title=meta.title,
                    kind=str(meta.kind.value)
                    if hasattr(meta.kind, "value")
                    else str(meta.kind),
                    search_score=0.0,
                    signal_score=0.0,
                    decay_factor=0.0,
                    combined_score=0.0,
                    hop_distance=-1,  # Sentinel: injected as centroid
                    is_seed=False,
                    community_id=cid,
                    community_cohesion=community.cohesion,
                    source_uri=meta.source_uri,
                    summary=meta.summary,
                )
                centroid_nodes.append(centroid_node)
                node_ids_present.add(centroid_id)

            nodes = nodes + centroid_nodes

        return nodes

    # ------------------------------------------------------------------
    # Phase 4 — Result Assembly
    # ------------------------------------------------------------------

    def _assemble_results(
        self,
        nodes: list[ScoredNode],
        seeds: list[ScoredNode],
        query: str,
        budget: BudgetConfig,
    ) -> GraphRetrievalResult:
        """Sort, budget-truncate, and package the final retrieval result.

        Args:
            nodes: Annotated node list from Phase 3.
            seeds: Original seed list (to compute ``nodes_expanded``).
            query: Original query string.
            budget: Token budget configuration.

        Returns:
            ``GraphRetrievalResult`` with sorted nodes and metadata.
        """
        total_candidates = len(nodes)
        seed_ids = {s.node_id for s in seeds}
        nodes_expanded = sum(1 for n in nodes if n.node_id not in seed_ids)

        sorted_nodes = sorted(nodes, key=lambda n: n.combined_score, reverse=True)
        max_nodes = budget.max_tokens // budget.tokens_per_node_estimate
        truncated = len(sorted_nodes) > max_nodes
        final_nodes = sorted_nodes[:max_nodes]

        communities_touched = len({n.community_id for n in final_nodes if n.community_id})
        budget_used = len(final_nodes) * budget.tokens_per_node_estimate

        return GraphRetrievalResult(
            query=query,
            nodes=final_nodes,
            total_candidates=total_candidates,
            nodes_expanded=nodes_expanded,
            communities_touched=communities_touched,
            budget_used=budget_used,
            budget_limit=budget.max_tokens,
            truncated=truncated,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        seed_top_k: int = 10,
        expansion: Optional[ExpansionConfig] = None,
        budget: Optional[BudgetConfig] = None,
    ) -> GraphRetrievalResult:
        """Run the full 4-phase retrieval pipeline.

        Phases:
            1. Seed search (``_seed_search``)
            2. Graph expansion (``_expand``)
            3. Community annotation (``_annotate_communities``)
            4. Result assembly (``_assemble_results``)

        Args:
            query: Natural language query string.
            seed_top_k: Number of seed nodes to select in Phase 1.
            expansion: Expansion configuration; defaults to
                ``ExpansionConfig()`` when not provided.
            budget: Token budget; defaults to ``BudgetConfig()`` when not
                provided.

        Returns:
            ``GraphRetrievalResult`` with ranked, annotated nodes.
        """
        if expansion is None:
            expansion = ExpansionConfig()
        if budget is None:
            budget = BudgetConfig()

        self.logger.debug(
            "search: query=%r seed_top_k=%d max_hops=%d",
            query,
            seed_top_k,
            expansion.max_hops,
        )

        # Phase 1
        seeds = await self._seed_search(query, top_k=seed_top_k)
        self.logger.debug("search: Phase 1 — %d seeds", len(seeds))

        # Phase 2
        expanded = await self._expand(seeds, config=expansion)
        self.logger.debug("search: Phase 2 — %d candidates after expansion", len(expanded))

        # Phase 3
        annotated = self._annotate_communities(expanded, config=expansion)
        self.logger.debug("search: Phase 3 — %d nodes after community annotation", len(annotated))

        # Phase 4
        result = self._assemble_results(annotated, seeds=seeds, query=query, budget=budget)
        self.logger.debug(
            "search: Phase 4 — %d final nodes (truncated=%s)",
            len(result.nodes),
            result.truncated,
        )
        return result

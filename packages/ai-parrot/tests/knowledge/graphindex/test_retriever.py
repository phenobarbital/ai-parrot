"""Tests for the Graph-Expanded Retrieval Pipeline (FEAT-217).

Coverage:
  TASK-1565 — Data models and retriever skeleton (init validation, model defaults)
  TASK-1566 — Phase 1 seed search adapters (hybrid + FAISS paths)
  TASK-1567 — Phase 2 graph expansion engine (multi-hop, decay, dedup, caps)
  TASK-1568 — Phase 3+4 community annotation and result assembly (full pipeline)
"""

from __future__ import annotations

import pytest
import rustworkx
from pydantic import ValidationError
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_nodes(count: int = 10):
    """Return a list of ``UniversalNode`` objects with ids ``n0`` .. ``n{count-1}``."""
    from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode

    return [
        UniversalNode(
            node_id=f"n{i}",
            title=f"Node {i}",
            kind=NodeKind.DOCUMENT,
            source_uri=f"file://node{i}.md",
            summary=f"Summary of node {i}",
        )
        for i in range(count)
    ]


def _make_graph_with_nodes(nodes):
    """Add nodes as payload dicts to a new PyDiGraph and return it."""
    from parrot.knowledge.graphindex.schema import NodeKind

    g = rustworkx.PyDiGraph()
    for node in nodes:
        g.add_node(
            {
                "node_id": node.node_id,
                "title": node.title,
                "kind": node.kind.value
                if hasattr(node.kind, "value")
                else str(node.kind),
                "source_uri": node.source_uri,
            }
        )
    return g


# ---------------------------------------------------------------------------
# TASK-1565: Data Models
# ---------------------------------------------------------------------------


class TestExpansionConfig:
    """Tests for ExpansionConfig Pydantic model."""

    def test_defaults(self):
        """Default config: max_hops=2, decay_base=0.7."""
        from parrot.knowledge.graphindex.retriever import ExpansionConfig

        cfg = ExpansionConfig()
        assert cfg.max_hops == 2
        assert cfg.decay_base == 0.7
        assert cfg.min_signal_threshold == 0.1
        assert cfg.max_expanded_nodes == 50
        assert cfg.include_community_centroids is False

    def test_validation_max_hops_too_low(self):
        """max_hops < 1 raises ValidationError."""
        from parrot.knowledge.graphindex.retriever import ExpansionConfig

        with pytest.raises(ValidationError):
            ExpansionConfig(max_hops=0)

    def test_validation_max_hops_too_high(self):
        """max_hops > 4 raises ValidationError."""
        from parrot.knowledge.graphindex.retriever import ExpansionConfig

        with pytest.raises(ValidationError):
            ExpansionConfig(max_hops=5)

    def test_custom_values(self):
        """Custom values accepted and stored."""
        from parrot.knowledge.graphindex.retriever import ExpansionConfig

        cfg = ExpansionConfig(max_hops=3, decay_base=0.5, max_expanded_nodes=20)
        assert cfg.max_hops == 3
        assert cfg.decay_base == 0.5
        assert cfg.max_expanded_nodes == 20


class TestBudgetConfig:
    """Tests for BudgetConfig Pydantic model."""

    def test_defaults(self):
        """Default budget: max_tokens=8000, tokens_per_node=200."""
        from parrot.knowledge.graphindex.retriever import BudgetConfig

        cfg = BudgetConfig()
        assert cfg.max_tokens == 8000
        assert cfg.tokens_per_node_estimate == 200

    def test_custom_budget(self):
        """Custom budget values accepted."""
        from parrot.knowledge.graphindex.retriever import BudgetConfig

        cfg = BudgetConfig(max_tokens=4000, tokens_per_node_estimate=100)
        assert cfg.max_tokens == 4000
        assert cfg.tokens_per_node_estimate == 100


class TestScoredNode:
    """Tests for ScoredNode Pydantic model."""

    def test_seed_node_defaults(self):
        """Seed node: is_seed=True, hop_distance=0."""
        from parrot.knowledge.graphindex.retriever import ScoredNode

        node = ScoredNode(
            node_id="n1", title="Test", kind="document", is_seed=True, search_score=0.9
        )
        assert node.is_seed is True
        assert node.hop_distance == 0
        assert node.signal_score == 0.0
        assert node.decay_factor == 1.0
        assert node.community_id is None

    def test_expanded_node_defaults(self):
        """Expanded node: is_seed=False, hop_distance set."""
        from parrot.knowledge.graphindex.retriever import ScoredNode

        node = ScoredNode(
            node_id="n2",
            title="Expanded",
            kind="concept",
            is_seed=False,
            hop_distance=1,
            signal_score=0.6,
            decay_factor=0.7,
            combined_score=0.42,
        )
        assert node.is_seed is False
        assert node.hop_distance == 1
        assert node.combined_score == pytest.approx(0.42)

    def test_optional_fields(self):
        """Optional fields default to None."""
        from parrot.knowledge.graphindex.retriever import ScoredNode

        node = ScoredNode(node_id="n3", title="X", kind="document")
        assert node.source_uri is None
        assert node.summary is None
        assert node.community_id is None
        assert node.community_cohesion is None


class TestGraphRetrievalResult:
    """Tests for GraphRetrievalResult Pydantic model."""

    def test_defaults(self):
        """Default metadata fields are zero/False."""
        from parrot.knowledge.graphindex.retriever import GraphRetrievalResult

        result = GraphRetrievalResult(query="test", nodes=[])
        assert result.total_candidates == 0
        assert result.nodes_expanded == 0
        assert result.communities_touched == 0
        assert result.budget_used == 0
        assert result.budget_limit == 0
        assert result.truncated is False

    def test_with_nodes(self):
        """Result carries nodes list."""
        from parrot.knowledge.graphindex.retriever import GraphRetrievalResult, ScoredNode

        nodes = [ScoredNode(node_id="n1", title="T", kind="document")]
        result = GraphRetrievalResult(query="q", nodes=nodes, total_candidates=1)
        assert len(result.nodes) == 1
        assert result.total_candidates == 1


# ---------------------------------------------------------------------------
# TASK-1565: Retriever init validation
# ---------------------------------------------------------------------------


class TestGraphExpandedRetrieverInit:
    """Tests for GraphExpandedRetriever.__init__."""

    def test_init_requires_at_least_one_source(self):
        """ValueError when neither embedder nor hybrid_search provided."""
        from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever

        graph = rustworkx.PyDiGraph()
        with pytest.raises(ValueError, match="at least one"):
            GraphExpandedRetriever(graph=graph, nodes=[])

    def test_init_with_embedder_only(self):
        """Init succeeds with embedder only."""
        from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever

        graph = rustworkx.PyDiGraph()
        embedder = MagicMock()
        retriever = GraphExpandedRetriever(graph=graph, nodes=[], embedder=embedder)
        assert retriever.embedder is embedder
        assert retriever.hybrid_search is None

    def test_init_with_hybrid_search_only(self):
        """Init succeeds with hybrid_search only."""
        from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever

        graph = rustworkx.PyDiGraph()
        hybrid = MagicMock()
        retriever = GraphExpandedRetriever(graph=graph, nodes=[], hybrid_search=hybrid)
        assert retriever.hybrid_search is hybrid
        assert retriever.embedder is None

    def test_init_with_both_sources(self):
        """Init succeeds when both sources provided."""
        from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever

        graph = rustworkx.PyDiGraph()
        retriever = GraphExpandedRetriever(
            graph=graph,
            nodes=[],
            embedder=MagicMock(),
            hybrid_search=MagicMock(),
        )
        assert retriever.embedder is not None
        assert retriever.hybrid_search is not None

    def test_init_stores_all_refs(self):
        """All constructor arguments are stored as attributes."""
        from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever

        graph = rustworkx.PyDiGraph()
        nodes = _make_nodes(3)
        embedder = MagicMock()
        signal_config = MagicMock()
        communities = MagicMock()
        retriever = GraphExpandedRetriever(
            graph=graph,
            nodes=nodes,
            embedder=embedder,
            signal_config=signal_config,
            communities=communities,
        )
        assert retriever.graph is graph
        assert retriever.nodes is nodes
        assert retriever.signal_config is signal_config
        assert retriever.communities is communities


# ---------------------------------------------------------------------------
# TASK-1566: Seed Search Adapters
# ---------------------------------------------------------------------------


class TestSeedSearch:
    """Tests for Phase 1 seed search."""

    @pytest.fixture
    def test_nodes(self):
        """Create test UniversalNode list."""
        return _make_nodes(10)

    @pytest.mark.asyncio
    async def test_seed_search_hybrid(self, test_nodes):
        """Phase 1 via HybridPageIndexSearch returns scored seed nodes."""
        from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever

        hybrid = MagicMock()
        hybrid.search = AsyncMock(
            return_value=[
                {"node_id": "n0", "score": 10.0},
                {"node_id": "n1", "score": 5.0},
            ]
        )
        graph = _make_graph_with_nodes(test_nodes)
        retriever = GraphExpandedRetriever(
            graph=graph, nodes=test_nodes, hybrid_search=hybrid
        )
        seeds = await retriever._seed_search("test query", top_k=10)
        assert len(seeds) == 2
        assert seeds[0].is_seed is True
        assert seeds[0].search_score == pytest.approx(1.0)  # normalised top score
        assert 0.0 <= seeds[1].search_score <= 1.0
        assert seeds[0].hop_distance == 0
        assert seeds[1].hop_distance == 0

    @pytest.mark.asyncio
    async def test_seed_search_hybrid_score_normalization(self, test_nodes):
        """Hybrid scores normalised so top result = 1.0."""
        from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever

        hybrid = MagicMock()
        hybrid.search = AsyncMock(
            return_value=[
                {"node_id": "n0", "score": 4.0},
                {"node_id": "n1", "score": 2.0},
                {"node_id": "n2", "score": 1.0},
            ]
        )
        graph = _make_graph_with_nodes(test_nodes)
        retriever = GraphExpandedRetriever(
            graph=graph, nodes=test_nodes, hybrid_search=hybrid
        )
        seeds = await retriever._seed_search("query", top_k=10)
        assert seeds[0].search_score == pytest.approx(1.0)
        assert seeds[1].search_score == pytest.approx(0.5)
        assert seeds[2].search_score == pytest.approx(0.25)

    @pytest.mark.asyncio
    async def test_seed_search_faiss(self, test_nodes):
        """Phase 1 via GraphIndexEmbedder returns scored seed nodes."""
        from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever

        embedder = MagicMock()
        embedder.search_similar = AsyncMock(
            return_value=[
                ("n0", 0.1),  # closest (smallest distance)
                ("n1", 0.5),
            ]
        )
        graph = _make_graph_with_nodes(test_nodes)
        retriever = GraphExpandedRetriever(
            graph=graph, nodes=test_nodes, embedder=embedder
        )
        seeds = await retriever._seed_search("test query", top_k=10)
        assert len(seeds) == 2
        assert seeds[0].is_seed is True
        # Closer (lower distance) → higher similarity score
        assert seeds[0].search_score > seeds[1].search_score
        assert seeds[0].hop_distance == 0

    @pytest.mark.asyncio
    async def test_seed_search_faiss_distance_to_similarity(self, test_nodes):
        """FAISS distance converted to similarity: 1/(1+d)."""
        from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever

        embedder = MagicMock()
        embedder.search_similar = AsyncMock(return_value=[("n0", 0.0)])
        graph = _make_graph_with_nodes(test_nodes)
        retriever = GraphExpandedRetriever(
            graph=graph, nodes=test_nodes, embedder=embedder
        )
        seeds = await retriever._seed_search("query", top_k=1)
        # distance=0 → similarity = 1/(1+0) = 1.0
        assert seeds[0].search_score == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_no_embedder_fallback(self, test_nodes):
        """When no embedder provided but hybrid_search exists, uses hybrid."""
        from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever

        hybrid = MagicMock()
        hybrid.search = AsyncMock(return_value=[{"node_id": "n0", "score": 1.0}])
        graph = _make_graph_with_nodes(test_nodes)
        retriever = GraphExpandedRetriever(
            graph=graph, nodes=test_nodes, hybrid_search=hybrid
        )
        seeds = await retriever._seed_search("query", top_k=5)
        assert len(seeds) == 1
        # hybrid_search.search should have been called
        hybrid.search.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_hybrid_preferred_over_embedder(self, test_nodes):
        """When both hybrid_search and embedder provided, hybrid_search is used."""
        from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever

        hybrid = MagicMock()
        hybrid.search = AsyncMock(return_value=[{"node_id": "n0", "score": 1.0}])
        embedder = MagicMock()
        embedder.search_similar = AsyncMock(return_value=[("n1", 0.1)])
        graph = _make_graph_with_nodes(test_nodes)
        retriever = GraphExpandedRetriever(
            graph=graph, nodes=test_nodes, hybrid_search=hybrid, embedder=embedder
        )
        seeds = await retriever._seed_search("query", top_k=5)
        hybrid.search.assert_awaited_once()
        embedder.search_similar.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_seed_search_empty_results(self, test_nodes):
        """Empty search results return empty seed list."""
        from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever

        hybrid = MagicMock()
        hybrid.search = AsyncMock(return_value=[])
        graph = _make_graph_with_nodes(test_nodes)
        retriever = GraphExpandedRetriever(
            graph=graph, nodes=test_nodes, hybrid_search=hybrid
        )
        seeds = await retriever._seed_search("query", top_k=5)
        assert seeds == []

    @pytest.mark.asyncio
    async def test_seed_search_node_metadata_resolved(self, test_nodes):
        """Seed nodes carry title, kind, source_uri from nodes list."""
        from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever

        hybrid = MagicMock()
        hybrid.search = AsyncMock(
            return_value=[{"node_id": "n0", "score": 1.0}]
        )
        graph = _make_graph_with_nodes(test_nodes)
        retriever = GraphExpandedRetriever(
            graph=graph, nodes=test_nodes, hybrid_search=hybrid
        )
        seeds = await retriever._seed_search("query", top_k=1)
        assert seeds[0].title == "Node 0"
        assert seeds[0].source_uri == "file://node0.md"
        assert seeds[0].summary == "Summary of node 0"


# ---------------------------------------------------------------------------
# TASK-1567: Graph Expansion Engine
# ---------------------------------------------------------------------------


@pytest.fixture
def small_graph_with_nodes():
    """Build a small graph with topology:

      n0 -> n1 -> n3
      n0 -> n2 -> n3   (n3 reachable via two paths)
      n1 -> n4
      n2 -> n5

    Returns (graph, nodes) tuple.
    """
    from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode

    node_ids = ["n0", "n1", "n2", "n3", "n4", "n5"]
    nodes = [
        UniversalNode(
            node_id=nid,
            title=f"Node {nid}",
            kind=NodeKind.DOCUMENT,
            source_uri=f"file://{nid}.md",
        )
        for nid in node_ids
    ]

    g = rustworkx.PyDiGraph()
    idx_map = {}
    for node in nodes:
        idx = g.add_node(
            {
                "node_id": node.node_id,
                "title": node.title,
                "kind": "document",
            }
        )
        idx_map[node.node_id] = idx

    # Add edges
    edges = [("n0", "n1"), ("n0", "n2"), ("n1", "n3"), ("n2", "n3"), ("n1", "n4"), ("n2", "n5")]
    for src, tgt in edges:
        g.add_edge(idx_map[src], idx_map[tgt], {"kind": "references"})

    return g, nodes


def _make_signal_relevance(node_a: str, node_b: str, combined: float):
    """Create a minimal SignalRelevance for mocking."""
    from parrot.knowledge.graphindex.signals import SignalRelevance

    return SignalRelevance(
        node_a=node_a,
        node_b=node_b,
        direct=combined,
        source_overlap=0.0,
        adamic_adar=0.0,
        type_affinity=0.0,
        embedding=0.0,
        combined=combined,
        direct_edges=[],
        shared_sources=[],
        aa_neighbours=[],
        embedding_available=False,
    )


class TestGraphExpansion:
    """Tests for Phase 2 graph expansion."""

    @pytest.mark.asyncio
    async def test_expansion_one_hop(self, small_graph_with_nodes):
        """Single-hop expansion finds direct neighbors."""
        from parrot.knowledge.graphindex.retriever import (
            ExpansionConfig,
            GraphExpandedRetriever,
            ScoredNode,
        )

        graph, nodes = small_graph_with_nodes
        # Create a seed node n0 with combined_score=1.0
        seed = ScoredNode(
            node_id="n0", title="Node n0", kind="document",
            search_score=1.0, combined_score=1.0, is_seed=True
        )

        # Mock relevance_neighborhood: n0's neighbors are n1 and n2
        sr_n1 = _make_signal_relevance("n0", "n1", 0.8)
        sr_n2 = _make_signal_relevance("n0", "n2", 0.6)

        with patch(
            "parrot.knowledge.graphindex.retriever.relevance_neighborhood",
            return_value=[sr_n1, sr_n2],
        ) as mock_nb:
            retriever = GraphExpandedRetriever(
                graph=graph, nodes=nodes, embedder=MagicMock()
            )
            config = ExpansionConfig(max_hops=1)
            expanded = await retriever._expand([seed], config)

        node_ids = {n.node_id for n in expanded}
        assert "n0" in node_ids
        assert "n1" in node_ids
        assert "n2" in node_ids

    @pytest.mark.asyncio
    async def test_expansion_two_hops(self):
        """Two-hop expansion applies decay: score * 0.7 * 0.7 for hop 2."""
        from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode
        from parrot.knowledge.graphindex.retriever import (
            ExpansionConfig,
            GraphExpandedRetriever,
            ScoredNode,
        )

        node_ids = ["n0", "n1", "n2"]
        nodes = [
            UniversalNode(
                node_id=nid, title=f"Node {nid}", kind=NodeKind.DOCUMENT, source_uri=f"f://{nid}"
            )
            for nid in node_ids
        ]
        g = rustworkx.PyDiGraph()
        idx_map = {}
        for node in nodes:
            idx = g.add_node({"node_id": node.node_id, "title": node.title, "kind": "document"})
            idx_map[node.node_id] = idx
        g.add_edge(idx_map["n0"], idx_map["n1"], {"kind": "references"})
        g.add_edge(idx_map["n1"], idx_map["n2"], {"kind": "references"})

        seed = ScoredNode(
            node_id="n0", title="Node n0", kind="document",
            search_score=1.0, combined_score=1.0, is_seed=True
        )
        sr_n1 = _make_signal_relevance("n0", "n1", 1.0)  # hop 1: 1.0 * 0.7 * 1.0 = 0.7
        sr_n2 = _make_signal_relevance("n1", "n2", 1.0)  # hop 2: 0.7 * 0.49 * 1.0 = 0.343

        call_count = 0

        def mock_nb(graph, nodes, node_id, **kwargs):
            nonlocal call_count
            call_count += 1
            if node_id == "n0":
                return [sr_n1]
            if node_id == "n1":
                return [sr_n2]
            return []

        with patch("parrot.knowledge.graphindex.retriever.relevance_neighborhood", side_effect=mock_nb):
            retriever = GraphExpandedRetriever(graph=g, nodes=nodes, embedder=MagicMock())
            config = ExpansionConfig(max_hops=2, decay_base=0.7, min_signal_threshold=0.0)
            expanded = await retriever._expand([seed], config)

        by_id = {n.node_id: n for n in expanded}
        assert "n1" in by_id
        assert by_id["n1"].combined_score == pytest.approx(0.7)
        assert "n2" in by_id
        # hop2_n2 combined = n1.combined_score * 0.7 * 1.0
        # n1.combined_score = 0.7, so n2 = 0.7 * 0.49 * 1.0 = 0.343
        assert by_id["n2"].combined_score == pytest.approx(0.343, rel=1e-3)

    @pytest.mark.asyncio
    async def test_expansion_deduplication(self, small_graph_with_nodes):
        """Same node reachable via two paths keeps highest combined score."""
        from parrot.knowledge.graphindex.retriever import (
            ExpansionConfig,
            GraphExpandedRetriever,
            ScoredNode,
        )

        graph, nodes = small_graph_with_nodes
        # Seed n0
        seed = ScoredNode(
            node_id="n0", title="Node n0", kind="document",
            search_score=1.0, combined_score=1.0, is_seed=True
        )
        # n1 (hop1) → n3 (hop2, score A)
        # n2 (hop1) → n3 (hop2, score B > A)
        # Expect n3.combined_score = max(A, B)
        sr_n1 = _make_signal_relevance("n0", "n1", 0.5)
        sr_n2 = _make_signal_relevance("n0", "n2", 0.9)
        # From n1: n3 with lower score
        sr_n3_from_n1 = _make_signal_relevance("n1", "n3", 0.3)
        # From n2: n3 with higher score
        sr_n3_from_n2 = _make_signal_relevance("n2", "n3", 0.9)

        def mock_nb(graph, nodes, node_id, **kwargs):
            if node_id == "n0":
                return [sr_n1, sr_n2]
            if node_id == "n1":
                return [sr_n3_from_n1]
            if node_id == "n2":
                return [sr_n3_from_n2]
            return []

        with patch("parrot.knowledge.graphindex.retriever.relevance_neighborhood", side_effect=mock_nb):
            retriever = GraphExpandedRetriever(graph=graph, nodes=nodes, embedder=MagicMock())
            config = ExpansionConfig(max_hops=2, min_signal_threshold=0.0)
            expanded = await retriever._expand([seed], config)

        by_id = {n.node_id: n for n in expanded}
        assert "n3" in by_id
        # n3 via n1: 1.0 * 0.7 * 0.5 * 0.49 * 0.3 ≈ 0.05145
        # n3 via n2: 1.0 * 0.7 * 0.9 * 0.49 * 0.9 ≈ 0.27783
        # higher wins → ~0.278
        n3_from_n2 = (1.0 * 0.7 * 0.9) * (0.7**2) * 0.9
        assert by_id["n3"].combined_score == pytest.approx(n3_from_n2, rel=1e-3)

    @pytest.mark.asyncio
    async def test_expansion_min_threshold(self, small_graph_with_nodes):
        """Nodes below min_signal_threshold are excluded."""
        from parrot.knowledge.graphindex.retriever import (
            ExpansionConfig,
            GraphExpandedRetriever,
            ScoredNode,
        )

        graph, nodes = small_graph_with_nodes
        seed = ScoredNode(
            node_id="n0", title="Node n0", kind="document",
            search_score=1.0, combined_score=1.0, is_seed=True
        )
        # n1 has signal < threshold → should be excluded
        sr_n1_low = _make_signal_relevance("n0", "n1", 0.05)
        sr_n2_ok = _make_signal_relevance("n0", "n2", 0.8)

        def mock_nb(graph, nodes, node_id, **kwargs):
            if node_id == "n0":
                return [sr_n1_low, sr_n2_ok]
            return []

        with patch("parrot.knowledge.graphindex.retriever.relevance_neighborhood", side_effect=mock_nb):
            retriever = GraphExpandedRetriever(graph=graph, nodes=nodes, embedder=MagicMock())
            config = ExpansionConfig(max_hops=1, min_signal_threshold=0.1)
            expanded = await retriever._expand([seed], config)

        node_ids = {n.node_id for n in expanded}
        assert "n1" not in node_ids  # below threshold
        assert "n2" in node_ids

    @pytest.mark.asyncio
    async def test_expansion_max_nodes_cap(self):
        """Expansion stops at max_expanded_nodes."""
        from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode
        from parrot.knowledge.graphindex.retriever import (
            ExpansionConfig,
            GraphExpandedRetriever,
            ScoredNode,
        )

        # Build a graph with many nodes
        node_ids = [f"n{i}" for i in range(20)]
        nodes = [
            UniversalNode(
                node_id=nid, title=f"Node {nid}", kind=NodeKind.DOCUMENT, source_uri=f"f://{nid}"
            )
            for nid in node_ids
        ]
        g = rustworkx.PyDiGraph()
        idx_map = {}
        for node in nodes:
            idx = g.add_node({"node_id": node.node_id, "title": node.title, "kind": "document"})
            idx_map[node.node_id] = idx
        # n0 has many neighbors
        for i in range(1, 20):
            g.add_edge(idx_map["n0"], idx_map[f"n{i}"], {"kind": "references"})

        seed = ScoredNode(
            node_id="n0", title="Node n0", kind="document",
            search_score=1.0, combined_score=1.0, is_seed=True
        )
        # Return many neighbors
        many_srs = [_make_signal_relevance("n0", f"n{i}", 0.5) for i in range(1, 20)]

        def mock_nb(graph, nodes, node_id, **kwargs):
            if node_id == "n0":
                return many_srs
            return []

        with patch("parrot.knowledge.graphindex.retriever.relevance_neighborhood", side_effect=mock_nb):
            retriever = GraphExpandedRetriever(graph=g, nodes=nodes, embedder=MagicMock())
            config = ExpansionConfig(max_hops=1, max_expanded_nodes=5, min_signal_threshold=0.0)
            expanded = await retriever._expand([seed], config)

        assert len(expanded) <= 5

    def test_decay_exponential(self):
        """Default decay: 0.7^1=0.7, 0.7^2=0.49, 0.7^3=0.343."""
        assert abs(0.7**1 - 0.7) < 1e-9
        assert abs(0.7**2 - 0.49) < 1e-9
        assert abs(0.7**3 - 0.343) < 1e-9

    @pytest.mark.asyncio
    async def test_decay_configurable(self, small_graph_with_nodes):
        """Custom decay_base=0.5 applied: hop1 score = seed * 0.5 * signal."""
        from parrot.knowledge.graphindex.retriever import (
            ExpansionConfig,
            GraphExpandedRetriever,
            ScoredNode,
        )

        graph, nodes = small_graph_with_nodes
        seed = ScoredNode(
            node_id="n0", title="Node n0", kind="document",
            search_score=1.0, combined_score=1.0, is_seed=True
        )
        sr_n1 = _make_signal_relevance("n0", "n1", 1.0)

        with patch(
            "parrot.knowledge.graphindex.retriever.relevance_neighborhood",
            return_value=[sr_n1],
        ):
            retriever = GraphExpandedRetriever(graph=graph, nodes=nodes, embedder=MagicMock())
            config = ExpansionConfig(max_hops=1, decay_base=0.5, min_signal_threshold=0.0)
            expanded = await retriever._expand([seed], config)

        by_id = {n.node_id: n for n in expanded}
        assert "n1" in by_id
        # combined = 1.0 * 0.5^1 * 1.0 = 0.5
        assert by_id["n1"].combined_score == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# TASK-1568: Community Context and Result Assembly
# ---------------------------------------------------------------------------


def _make_communities_result(node_community_map: dict[str, str]):
    """Create a CommunitiesResult with given node→community mapping."""
    from parrot.knowledge.graphindex.communities import Community, CommunitiesResult

    community_ids = list(set(node_community_map.values()))
    communities = []
    for cid in community_ids:
        members = [nid for nid, c in node_community_map.items() if c == cid]
        communities.append(
            Community(
                community_id=cid,
                size=len(members),
                member_node_ids=members,
                centroid_node_id=members[0],
                cohesion=0.8,
                modularity_contribution=0.1,
                top_titles=[f"Title {m}" for m in members[:5]],
            )
        )
    return CommunitiesResult(
        modularity=0.5,
        resolution=1.0,
        seed=42,
        weighted=False,
        communities=communities,
        node_to_community=node_community_map,
    )


class TestCommunityAnnotation:
    """Tests for Phase 3 community annotation."""

    def test_community_annotation(self):
        """Nodes annotated with community_id and cohesion."""
        from parrot.knowledge.graphindex.retriever import (
            ExpansionConfig,
            GraphExpandedRetriever,
            ScoredNode,
        )

        graph = rustworkx.PyDiGraph()
        nodes = _make_nodes(3)
        communities = _make_communities_result({"n0": "comm-A", "n1": "comm-A", "n2": "comm-B"})

        retriever = GraphExpandedRetriever(
            graph=graph, nodes=nodes, embedder=MagicMock(), communities=communities
        )
        scored = [
            ScoredNode(node_id="n0", title="Node 0", kind="document"),
            ScoredNode(node_id="n1", title="Node 1", kind="document"),
            ScoredNode(node_id="n2", title="Node 2", kind="document"),
        ]
        config = ExpansionConfig()
        annotated = retriever._annotate_communities(scored, config)

        assert annotated[0].community_id == "comm-A"
        assert annotated[0].community_cohesion == pytest.approx(0.8)
        assert annotated[1].community_id == "comm-A"
        assert annotated[2].community_id == "comm-B"

    def test_community_centroid_inclusion(self):
        """Centroid nodes added when include_community_centroids=True."""
        from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode
        from parrot.knowledge.graphindex.retriever import (
            ExpansionConfig,
            GraphExpandedRetriever,
            ScoredNode,
        )

        # n0 is in comm-A; centroid is n1 which is NOT in the result set
        nodes = [
            UniversalNode(
                node_id="n0", title="Node 0", kind=NodeKind.DOCUMENT, source_uri="f://n0"
            ),
            UniversalNode(
                node_id="n1", title="Centroid Node", kind=NodeKind.DOCUMENT, source_uri="f://n1"
            ),
        ]
        graph = rustworkx.PyDiGraph()
        communities = _make_communities_result({"n0": "comm-A", "n1": "comm-A"})
        # Override centroid to n1
        from parrot.knowledge.graphindex.communities import Community, CommunitiesResult
        comm_a = Community(
            community_id="comm-A",
            size=2,
            member_node_ids=["n0", "n1"],
            centroid_node_id="n1",  # n1 is the centroid
            cohesion=0.8,
            modularity_contribution=0.1,
            top_titles=["Node 0", "Centroid Node"],
        )
        communities = CommunitiesResult(
            modularity=0.5,
            resolution=1.0,
            seed=42,
            weighted=False,
            communities=[comm_a],
            node_to_community={"n0": "comm-A", "n1": "comm-A"},
        )

        retriever = GraphExpandedRetriever(
            graph=graph, nodes=nodes, embedder=MagicMock(), communities=communities
        )
        scored = [
            ScoredNode(node_id="n0", title="Node 0", kind="document"),
            # n1 NOT included initially
        ]
        config = ExpansionConfig(include_community_centroids=True)
        annotated = retriever._annotate_communities(scored, config)

        node_ids = {n.node_id for n in annotated}
        assert "n1" in node_ids  # centroid added

    def test_no_communities_graceful(self):
        """Phase 3 skipped gracefully when CommunitiesResult is None."""
        from parrot.knowledge.graphindex.retriever import (
            ExpansionConfig,
            GraphExpandedRetriever,
            ScoredNode,
        )

        graph = rustworkx.PyDiGraph()
        retriever = GraphExpandedRetriever(
            graph=graph, nodes=[], embedder=MagicMock(), communities=None
        )
        scored = [ScoredNode(node_id="n0", title="T", kind="document")]
        config = ExpansionConfig()
        result = retriever._annotate_communities(scored, config)
        assert len(result) == 1
        assert result[0].community_id is None


class TestResultAssembly:
    """Tests for Phase 4 result assembly."""

    def test_budget_truncation(self):
        """Results truncated when token budget exceeded."""
        from parrot.knowledge.graphindex.retriever import (
            BudgetConfig,
            ExpansionConfig,
            GraphExpandedRetriever,
            ScoredNode,
        )

        graph = rustworkx.PyDiGraph()
        retriever = GraphExpandedRetriever(graph=graph, nodes=[], embedder=MagicMock())
        nodes = [
            ScoredNode(node_id=f"n{i}", title=f"T{i}", kind="document", combined_score=float(i))
            for i in range(10)
        ]
        seeds = [nodes[0]]
        budget = BudgetConfig(max_tokens=400, tokens_per_node_estimate=200)  # max 2 nodes
        result = retriever._assemble_results(nodes, seeds=seeds, query="q", budget=budget)
        assert result.truncated is True
        assert len(result.nodes) <= 2

    def test_budget_no_truncation(self):
        """All results returned when within budget."""
        from parrot.knowledge.graphindex.retriever import (
            BudgetConfig,
            GraphExpandedRetriever,
            ScoredNode,
        )

        graph = rustworkx.PyDiGraph()
        retriever = GraphExpandedRetriever(graph=graph, nodes=[], embedder=MagicMock())
        nodes = [
            ScoredNode(node_id=f"n{i}", title=f"T{i}", kind="document", combined_score=float(i))
            for i in range(3)
        ]
        seeds = [nodes[0]]
        budget = BudgetConfig(max_tokens=8000, tokens_per_node_estimate=200)
        result = retriever._assemble_results(nodes, seeds=seeds, query="q", budget=budget)
        assert result.truncated is False
        assert len(result.nodes) == 3

    def test_result_sorting(self):
        """Results sorted by combined_score descending."""
        from parrot.knowledge.graphindex.retriever import (
            BudgetConfig,
            GraphExpandedRetriever,
            ScoredNode,
        )

        graph = rustworkx.PyDiGraph()
        retriever = GraphExpandedRetriever(graph=graph, nodes=[], embedder=MagicMock())
        nodes = [
            ScoredNode(node_id="a", title="A", kind="document", combined_score=0.3),
            ScoredNode(node_id="b", title="B", kind="document", combined_score=0.9),
            ScoredNode(node_id="c", title="C", kind="document", combined_score=0.6),
        ]
        seeds = [nodes[0]]
        budget = BudgetConfig(max_tokens=8000, tokens_per_node_estimate=200)
        result = retriever._assemble_results(nodes, seeds=seeds, query="q", budget=budget)
        # Expected order: b (0.9), c (0.6), a (0.3)
        assert result.nodes[0].node_id == "b"
        assert result.nodes[1].node_id == "c"
        assert result.nodes[2].node_id == "a"

    def test_result_metadata_populated(self):
        """GraphRetrievalResult metadata fields populated correctly."""
        from parrot.knowledge.graphindex.retriever import (
            BudgetConfig,
            GraphExpandedRetriever,
            ScoredNode,
        )

        graph = rustworkx.PyDiGraph()
        retriever = GraphExpandedRetriever(graph=graph, nodes=[], embedder=MagicMock())
        seed = ScoredNode(node_id="n0", title="S", kind="document", combined_score=0.9, is_seed=True)
        expanded = ScoredNode(node_id="n1", title="E", kind="document", combined_score=0.6)
        community_node = ScoredNode(
            node_id="n2", title="C", kind="document", combined_score=0.5, community_id="comm-A"
        )
        nodes = [seed, expanded, community_node]
        budget = BudgetConfig(max_tokens=8000, tokens_per_node_estimate=200)
        result = retriever._assemble_results(nodes, seeds=[seed], query="test", budget=budget)
        assert result.query == "test"
        assert result.total_candidates == 3
        assert result.nodes_expanded == 2  # n1 and n2 are not seeds
        assert result.communities_touched == 1  # only "comm-A"
        assert result.budget_limit == 8000


class TestFullPipeline:
    """End-to-end pipeline tests."""

    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        """End-to-end: query -> seed -> expand -> community -> result."""
        from parrot.knowledge.graphindex.retriever import (
            BudgetConfig,
            ExpansionConfig,
            GraphExpandedRetriever,
        )
        from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode

        node_ids = ["n0", "n1", "n2"]
        nodes = [
            UniversalNode(
                node_id=nid, title=f"Node {nid}", kind=NodeKind.DOCUMENT, source_uri=f"f://{nid}"
            )
            for nid in node_ids
        ]
        g = rustworkx.PyDiGraph()
        idx_map = {}
        for node in nodes:
            idx = g.add_node({"node_id": node.node_id, "title": node.title, "kind": "document"})
            idx_map[node.node_id] = idx
        g.add_edge(idx_map["n0"], idx_map["n1"], {"kind": "references"})
        g.add_edge(idx_map["n1"], idx_map["n2"], {"kind": "references"})

        hybrid = MagicMock()
        hybrid.search = AsyncMock(return_value=[{"node_id": "n0", "score": 1.0}])

        sr_n1 = _make_signal_relevance("n0", "n1", 0.8)

        with patch(
            "parrot.knowledge.graphindex.retriever.relevance_neighborhood",
            return_value=[sr_n1],
        ):
            retriever = GraphExpandedRetriever(graph=g, nodes=nodes, hybrid_search=hybrid)
            result = await retriever.search(
                "test query",
                seed_top_k=5,
                expansion=ExpansionConfig(max_hops=1, min_signal_threshold=0.0),
                budget=BudgetConfig(max_tokens=8000),
            )

        assert result.query == "test query"
        assert len(result.nodes) >= 1
        assert result.total_candidates >= 1
        # Sorted descending by combined_score
        scores = [n.combined_score for n in result.nodes]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_full_pipeline_no_communities(self):
        """Full pipeline without communities (Phase 3 is no-op)."""
        from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever, ExpansionConfig
        from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode

        nodes = [
            UniversalNode(
                node_id="n0", title="Node 0", kind=NodeKind.DOCUMENT, source_uri="f://n0"
            )
        ]
        g = rustworkx.PyDiGraph()
        g.add_node({"node_id": "n0", "title": "Node 0", "kind": "document"})

        hybrid = MagicMock()
        hybrid.search = AsyncMock(return_value=[{"node_id": "n0", "score": 1.0}])

        with patch(
            "parrot.knowledge.graphindex.retriever.relevance_neighborhood",
            return_value=[],
        ):
            retriever = GraphExpandedRetriever(
                graph=g, nodes=nodes, hybrid_search=hybrid, communities=None
            )
            result = await retriever.search(
                "test", seed_top_k=1, expansion=ExpansionConfig(max_hops=1)
            )

        assert result.query == "test"
        for n in result.nodes:
            assert n.community_id is None

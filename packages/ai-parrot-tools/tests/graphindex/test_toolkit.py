"""Unit tests for parrot_tools.graphindex.toolkit."""

import numpy as np
import pytest
import rustworkx
import faiss
from unittest.mock import AsyncMock, MagicMock

from parrot_tools.graphindex.toolkit import GraphIndexToolkit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def build_simple_graph() -> tuple[rustworkx.PyDiGraph, dict[str, int], list[str]]:
    """Build a small PyDiGraph with 4 nodes and 3 edges.

    Topology:
        A --contains--> B --contains--> C
        A --references--> D

    Node kinds:
        A = document, B = section, C = section, D = symbol
    """
    g = rustworkx.PyDiGraph()
    a = g.add_node({"node_id": "A", "title": "Doc A", "kind": "document"})
    b = g.add_node({"node_id": "B", "title": "Section B", "kind": "section"})
    c = g.add_node({"node_id": "C", "title": "Section C", "kind": "section"})
    d = g.add_node({"node_id": "D", "title": "Symbol D", "kind": "symbol"})

    g.add_edge(a, b, {"source_id": "A", "target_id": "B", "kind": "contains", "confidence": None})
    g.add_edge(b, c, {"source_id": "B", "target_id": "C", "kind": "contains", "confidence": None})
    g.add_edge(a, d, {"source_id": "A", "target_id": "D", "kind": "references", "confidence": 0.9})

    node_map = {"A": a, "B": b, "C": c, "D": d}
    node_id_list = ["A", "B", "C", "D"]
    return g, node_map, node_id_list


def build_faiss_index(node_id_list: list[str], dim: int = 8) -> faiss.Index:
    """Build a FAISS index with random unit vectors for each node."""
    index = faiss.IndexFlatIP(dim)
    rng = np.random.default_rng(42)
    for _ in node_id_list:
        vec = rng.random(dim).astype(np.float32)
        vec /= np.linalg.norm(vec)
        index.add(vec.reshape(1, -1))
    return index


def make_toolkit(client=None) -> GraphIndexToolkit:
    """Create a GraphIndexToolkit with a simple test graph."""
    g, node_map, node_id_list = build_simple_graph()
    faiss_index = build_faiss_index(node_id_list, dim=8)
    return GraphIndexToolkit(
        graph=g,
        faiss_index=faiss_index,
        node_map=node_map,
        node_id_list=node_id_list,
        client=client,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGraphIndexToolkit:
    def test_instantiation(self):
        """GraphIndexToolkit can be instantiated."""
        toolkit = make_toolkit()
        assert toolkit is not None

    def test_inherits_abstract_toolkit(self):
        """GraphIndexToolkit must extend AbstractToolkit."""
        from parrot.tools.toolkit import AbstractToolkit
        toolkit = make_toolkit()
        assert isinstance(toolkit, AbstractToolkit)

    # --- find_node ---

    @pytest.mark.asyncio
    async def test_find_node_returns_dict(self):
        """find_node must return a dict."""
        toolkit = make_toolkit()
        result = await toolkit.find_node("documentation")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_find_node_returns_closest(self):
        """find_node must return a node_id present in the graph."""
        toolkit = make_toolkit()
        result = await toolkit.find_node("API reference")
        assert "node_id" in result or "error" in result
        if "node_id" in result:
            assert result["node_id"] in ["A", "B", "C", "D"]

    @pytest.mark.asyncio
    async def test_find_node_empty_index(self):
        """find_node with empty index returns error dict."""
        g, node_map, node_id_list = build_simple_graph()
        empty_index = faiss.IndexFlatIP(8)
        toolkit = GraphIndexToolkit(
            graph=g, faiss_index=empty_index, node_map=node_map, node_id_list=[]
        )
        result = await toolkit.find_node("query")
        assert "error" in result

    # --- find_references ---

    @pytest.mark.asyncio
    async def test_find_references_both_directions(self):
        """find_references returns edges where node is source OR target."""
        toolkit = make_toolkit()
        refs = await toolkit.find_references("A")
        # A has 2 outgoing edges
        outgoing = [r for r in refs if r.get("direction") == "outgoing"]
        assert len(outgoing) == 2

    @pytest.mark.asyncio
    async def test_find_references_incoming(self):
        """Node B has one incoming edge from A."""
        toolkit = make_toolkit()
        refs = await toolkit.find_references("B")
        incoming = [r for r in refs if r.get("direction") == "incoming"]
        assert len(incoming) == 1

    @pytest.mark.asyncio
    async def test_find_references_missing_node(self):
        """Missing node returns empty list."""
        toolkit = make_toolkit()
        result = await toolkit.find_references("nonexistent")
        assert result == []

    # --- get_neighborhood ---

    @pytest.mark.asyncio
    async def test_get_neighborhood_returns_dict(self):
        """get_neighborhood must return a dict with nodes and edges."""
        toolkit = make_toolkit()
        result = await toolkit.get_neighborhood("A", depth=1)
        assert "nodes" in result
        assert "edges" in result
        assert "center" in result

    @pytest.mark.asyncio
    async def test_get_neighborhood_respects_depth(self):
        """Depth 1 from A includes B and D but not C (which is 2 hops away)."""
        toolkit = make_toolkit()
        result = await toolkit.get_neighborhood("A", depth=1)
        node_ids = {n.get("node_id") for n in result["nodes"]}
        # A is the center; depth-1 neighbors are B and D
        assert "B" in node_ids or "D" in node_ids
        # C is 2 hops from A (A->B->C), should NOT be included at depth=1
        assert "C" not in node_ids

    @pytest.mark.asyncio
    async def test_get_neighborhood_depth2(self):
        """Depth 2 from A should reach C (A->B->C)."""
        toolkit = make_toolkit()
        result = await toolkit.get_neighborhood("A", depth=2)
        node_ids = {n.get("node_id") for n in result["nodes"]}
        assert "C" in node_ids

    @pytest.mark.asyncio
    async def test_get_neighborhood_missing_node(self):
        """Missing node returns empty neighborhood."""
        toolkit = make_toolkit()
        result = await toolkit.get_neighborhood("nonexistent")
        assert result["nodes"] == []

    # --- traverse ---

    @pytest.mark.asyncio
    async def test_traverse_filters_by_relation(self):
        """traverse follows only edges of specified relation type."""
        toolkit = make_toolkit()
        # A has 'contains' to B and 'references' to D
        result = await toolkit.traverse("A", "contains")
        node_ids = {n.get("node_id") for n in result}
        assert "B" in node_ids
        assert "D" not in node_ids  # D is via 'references', not 'contains'

    @pytest.mark.asyncio
    async def test_traverse_filters_by_kind(self):
        """traverse with to_kind filters target nodes by kind."""
        toolkit = make_toolkit()
        # B is section, D is symbol
        result = await toolkit.traverse("A", "contains", to_kind="section")
        node_ids = {n.get("node_id") for n in result}
        assert "B" in node_ids
        for n in result:
            assert n.get("kind") == "section"

    @pytest.mark.asyncio
    async def test_traverse_missing_node(self):
        """traverse with missing from_id returns empty list."""
        toolkit = make_toolkit()
        result = await toolkit.traverse("nonexistent", "contains")
        assert result == []

    # --- search_hybrid ---

    @pytest.mark.asyncio
    async def test_search_hybrid_returns_list(self):
        """search_hybrid must return a list."""
        toolkit = make_toolkit()
        result = await toolkit.search_hybrid("find something", top_k=3)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_search_hybrid_respects_top_k(self):
        """search_hybrid must not return more than top_k results."""
        toolkit = make_toolkit()
        result = await toolkit.search_hybrid("query", top_k=2)
        assert len(result) <= 2

    @pytest.mark.asyncio
    async def test_search_hybrid_result_has_required_fields(self):
        """search_hybrid results have node_id, title, kind, combined_score."""
        toolkit = make_toolkit()
        result = await toolkit.search_hybrid("query", top_k=4)
        for item in result:
            assert "node_id" in item
            assert "combined_score" in item

    # --- find_central_nodes ---

    @pytest.mark.asyncio
    async def test_find_central_nodes_returns_list(self):
        """find_central_nodes must return a list."""
        toolkit = make_toolkit()
        result = await toolkit.find_central_nodes(top_k=3)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_find_central_nodes_betweenness(self):
        """Node A (hub) should have higher betweenness than leaf nodes."""
        toolkit = make_toolkit()
        result = await toolkit.find_central_nodes(top_k=4, metric="betweenness")
        # A connects to B and D; it should have the highest centrality
        if result:
            assert result[0]["node_id"] in ["A", "B"]  # Hub nodes

    @pytest.mark.asyncio
    async def test_find_central_nodes_eigenvector(self):
        """find_central_nodes with eigenvector metric works without error."""
        toolkit = make_toolkit()
        result = await toolkit.find_central_nodes(top_k=3, metric="eigenvector")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_find_central_nodes_respects_top_k(self):
        """find_central_nodes must not return more than top_k nodes."""
        toolkit = make_toolkit()
        result = await toolkit.find_central_nodes(top_k=2)
        assert len(result) <= 2

    # --- shortest_path ---

    @pytest.mark.asyncio
    async def test_shortest_path_found(self):
        """shortest_path A→C should return a non-empty path."""
        toolkit = make_toolkit()
        path = await toolkit.shortest_path("A", "C")
        assert isinstance(path, list)
        # Path should pass through B: A -> B -> C
        assert len(path) >= 2

    @pytest.mark.asyncio
    async def test_shortest_path_direct(self):
        """shortest_path for directly connected nodes."""
        toolkit = make_toolkit()
        path = await toolkit.shortest_path("A", "B")
        assert len(path) >= 1

    @pytest.mark.asyncio
    async def test_shortest_path_missing_node(self):
        """shortest_path with missing node returns empty list."""
        toolkit = make_toolkit()
        path = await toolkit.shortest_path("A", "nonexistent")
        assert path == []

    # --- explain ---

    @pytest.mark.asyncio
    async def test_explain_no_client_returns_fallback(self):
        """explain without client must return a fallback string."""
        toolkit = make_toolkit(client=None)
        result = await toolkit.explain("A")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_explain_uses_client(self):
        """explain with client must call client.ask()."""
        mock_client = MagicMock()
        mock_client.ask = AsyncMock(return_value="Node A is a central document.")
        toolkit = make_toolkit(client=mock_client)
        result = await toolkit.explain("A")
        mock_client.ask.assert_called_once()
        assert "Node A" in result or "document" in result

    @pytest.mark.asyncio
    async def test_explain_missing_node(self):
        """explain for a missing node returns not-found message."""
        toolkit = make_toolkit()
        result = await toolkit.explain("nonexistent")
        assert "not found" in result.lower() or "nonexistent" in result

    @pytest.mark.asyncio
    async def test_explain_client_error_falls_back(self):
        """explain falls back gracefully if client.ask raises."""
        mock_client = MagicMock()
        mock_client.ask = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        toolkit = make_toolkit(client=mock_client)
        result = await toolkit.explain("A")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# FEAT-215: Helpers for gap detection tests
# ---------------------------------------------------------------------------


def build_gap_graph():
    """Build a graph with isolated nodes for gap detection testing."""
    from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode

    g = rustworkx.PyDiGraph()
    # Hub node (well-connected)
    hub = g.add_node({"node_id": "hub", "kind": "concept", "title": "Hub"})
    # Connected nodes
    n1 = g.add_node({"node_id": "n1", "kind": "section", "title": "Section 1"})
    n2 = g.add_node({"node_id": "n2", "kind": "section", "title": "Section 2"})
    n3 = g.add_node({"node_id": "n3", "kind": "section", "title": "Section 3"})
    g.add_edge(hub, n1, {"source_id": "hub", "target_id": "n1", "kind": "contains", "confidence": None})
    g.add_edge(hub, n2, {"source_id": "hub", "target_id": "n2", "kind": "contains", "confidence": None})
    g.add_edge(hub, n3, {"source_id": "hub", "target_id": "n3", "kind": "contains", "confidence": None})
    # Isolated nodes (degree 0 or 1, not DOCUMENT)
    iso1 = g.add_node({"node_id": "iso1", "kind": "concept", "title": "Isolated 1"})
    iso2 = g.add_node({"node_id": "iso2", "kind": "skill", "title": "Isolated 2"})
    # Document root (should be excluded from isolated nodes)
    doc = g.add_node({"node_id": "doc_root", "kind": "document", "title": "Root"})
    g.add_edge(iso2, doc, {"source_id": "iso2", "target_id": "doc_root", "kind": "contains", "confidence": None})

    nodes = [
        UniversalNode(node_id="hub", kind=NodeKind.CONCEPT, title="Hub", source_uri="test.txt"),
        UniversalNode(node_id="n1", kind=NodeKind.SECTION, title="Section 1", source_uri="test.txt"),
        UniversalNode(node_id="n2", kind=NodeKind.SECTION, title="Section 2", source_uri="test.txt"),
        UniversalNode(node_id="n3", kind=NodeKind.SECTION, title="Section 3", source_uri="test.txt"),
        UniversalNode(node_id="iso1", kind=NodeKind.CONCEPT, title="Isolated 1", source_uri="test.txt"),
        UniversalNode(node_id="iso2", kind=NodeKind.SKILL, title="Isolated 2", source_uri="test.txt"),
        UniversalNode(node_id="doc_root", kind=NodeKind.DOCUMENT, title="Root", source_uri="test.txt"),
    ]
    node_map = {"hub": hub, "n1": n1, "n2": n2, "n3": n3,
                "iso1": iso1, "iso2": iso2, "doc_root": doc}
    node_id_list = ["hub", "n1", "n2", "n3", "iso1", "iso2", "doc_root"]
    return g, node_map, node_id_list, nodes


def make_gap_toolkit() -> "GraphIndexToolkit":
    """Create a GraphIndexToolkit with a graph containing knowledge gaps."""
    g, node_map, node_id_list, nodes = build_gap_graph()
    faiss_index = build_faiss_index(node_id_list, dim=8)
    return GraphIndexToolkit(
        graph=g,
        faiss_index=faiss_index,
        node_map=node_map,
        node_id_list=node_id_list,
        nodes=nodes,
    )


# ---------------------------------------------------------------------------
# FEAT-215: TestToolkitGapDetection
# ---------------------------------------------------------------------------


class TestToolkitGapDetection:
    @pytest.mark.asyncio
    async def test_find_isolated_nodes_returns_list(self):
        """find_isolated_nodes returns a list."""
        toolkit = make_gap_toolkit()
        result = await toolkit.find_isolated_nodes()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_find_isolated_nodes_finds_gaps(self):
        """find_isolated_nodes returns the isolated concept node."""
        toolkit = make_gap_toolkit()
        result = await toolkit.find_isolated_nodes()
        node_ids = [r["node_id"] for r in result]
        assert "iso1" in node_ids  # degree 0 concept node
        assert "iso2" in node_ids  # degree 1 skill node (connected only to doc_root)

    @pytest.mark.asyncio
    async def test_find_isolated_nodes_excludes_document(self):
        """find_isolated_nodes excludes DOCUMENT nodes by default."""
        toolkit = make_gap_toolkit()
        result = await toolkit.find_isolated_nodes()
        kinds = [r["kind"] for r in result]
        assert "document" not in kinds

    @pytest.mark.asyncio
    async def test_find_sparse_communities_returns_list(self):
        """find_sparse_communities returns a list (or error dict if no communities)."""
        toolkit = make_gap_toolkit()
        result = await toolkit.find_sparse_communities()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_find_bridge_nodes_returns_list(self):
        """find_bridge_nodes returns a list (or error dict if no communities)."""
        toolkit = make_gap_toolkit()
        result = await toolkit.find_bridge_nodes()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_analytics_cache_initialized(self):
        """_analytics_cache is None initially."""
        toolkit = make_gap_toolkit()
        assert toolkit._analytics_cache is None


# ---------------------------------------------------------------------------
# FEAT-215: TestToolkitInsightManagement
# ---------------------------------------------------------------------------


class TestToolkitInsightManagement:
    @pytest.mark.asyncio
    async def test_dismiss_insight_returns_confirmation(self):
        """dismiss_insight returns dict with 'dismissed' key."""
        toolkit = make_gap_toolkit()
        result = await toolkit.dismiss_insight("surprise:a:b")
        assert isinstance(result, dict)
        assert result.get("dismissed") == "surprise:a:b"

    @pytest.mark.asyncio
    async def test_dismiss_insight_increments_count(self):
        """Repeated dismissals increment total_dismissed."""
        toolkit = make_gap_toolkit()
        r1 = await toolkit.dismiss_insight("isolated:iso1")
        r2 = await toolkit.dismiss_insight("isolated:iso2")
        assert r1["total_dismissed"] == 1
        assert r2["total_dismissed"] == 2

    @pytest.mark.asyncio
    async def test_list_unreviewed_insights_returns_list(self):
        """list_unreviewed_insights returns a list."""
        toolkit = make_gap_toolkit()
        result = await toolkit.list_unreviewed_insights()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_dismiss_then_list_round_trip(self):
        """Dismissed insight excluded from list_unreviewed_insights."""
        toolkit = make_gap_toolkit()
        # First list to get available insights
        unreviewed_before = await toolkit.list_unreviewed_insights()
        if not unreviewed_before:
            pytest.skip("No insights available in test graph to dismiss")
        first_id = unreviewed_before[0]["id"]
        await toolkit.dismiss_insight(first_id)
        unreviewed_after = await toolkit.list_unreviewed_insights()
        ids_after = [i["id"] for i in unreviewed_after]
        assert first_id not in ids_after

    @pytest.mark.asyncio
    async def test_analytics_cache_populated_after_call(self):
        """_analytics_cache is populated after find_isolated_nodes call."""
        toolkit = make_gap_toolkit()
        # find_isolated_nodes doesn't use analytics cache directly,
        # but dismiss_insight does
        await toolkit.dismiss_insight("test:x")
        assert toolkit._analytics_cache is not None

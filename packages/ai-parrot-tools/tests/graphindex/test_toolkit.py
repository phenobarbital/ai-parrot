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
# TASK-1569: search_with_expansion integration tests
# ---------------------------------------------------------------------------


class TestSearchWithExpansion:
    """Integration tests for GraphIndexToolkit.search_with_expansion (FEAT-217)."""

    @pytest.mark.asyncio
    async def test_toolkit_search_with_expansion_returns_dict(self):
        """Toolkit tool returns a dict matching GraphRetrievalResult schema."""
        from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode
        from unittest.mock import AsyncMock, MagicMock, patch

        g, node_map, node_id_list = build_simple_graph()
        faiss_index = build_faiss_index(node_id_list, dim=8)

        # Build UniversalNode objects to mirror the graph
        nodes = [
            UniversalNode(
                node_id=nid,
                title=f"Title {nid}",
                kind=NodeKind.DOCUMENT,
                source_uri=f"file://{nid}.md",
            )
            for nid in node_id_list
        ]

        embedder = MagicMock()
        embedder.search_similar = AsyncMock(
            return_value=[("A", 0.1), ("B", 0.3)]
        )

        toolkit = GraphIndexToolkit(
            graph=g,
            faiss_index=faiss_index,
            node_map=node_map,
            node_id_list=node_id_list,
            embedder=embedder,
            nodes=nodes,
        )

        with patch(
            "parrot.knowledge.graphindex.retriever.relevance_neighborhood",
            return_value=[],
        ):
            result = await toolkit.search_with_expansion("test query", seed_top_k=2)

        assert isinstance(result, dict)
        # Verify GraphRetrievalResult keys present
        assert "query" in result
        assert "nodes" in result
        assert "total_candidates" in result
        assert "nodes_expanded" in result
        assert "communities_touched" in result
        assert "budget_used" in result
        assert "budget_limit" in result
        assert "truncated" in result
        assert result["query"] == "test query"
        assert isinstance(result["nodes"], list)
        assert isinstance(result["truncated"], bool)

    @pytest.mark.asyncio
    async def test_search_with_expansion_no_embedder_returns_error(self):
        """Returns error dict when no embedder provided."""
        toolkit = make_toolkit()  # no embedder
        result = await toolkit.search_with_expansion("query")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_search_with_expansion_custom_params(self):
        """Custom max_hops and decay_base accepted."""
        from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode
        from unittest.mock import AsyncMock, MagicMock, patch

        g, node_map, node_id_list = build_simple_graph()
        faiss_index = build_faiss_index(node_id_list, dim=8)
        nodes = [
            UniversalNode(
                node_id=nid, title=f"T{nid}", kind=NodeKind.DOCUMENT, source_uri=f"f://{nid}"
            )
            for nid in node_id_list
        ]
        embedder = MagicMock()
        embedder.search_similar = AsyncMock(return_value=[("A", 0.2)])

        toolkit = GraphIndexToolkit(
            graph=g,
            faiss_index=faiss_index,
            node_map=node_map,
            node_id_list=node_id_list,
            embedder=embedder,
            nodes=nodes,
        )

        with patch(
            "parrot.knowledge.graphindex.retriever.relevance_neighborhood",
            return_value=[],
        ):
            result = await toolkit.search_with_expansion(
                "query", max_hops=1, decay_base=0.5, max_tokens=4000
            )

        assert result["budget_limit"] == 4000
        assert isinstance(result["nodes"], list)


class TestExportGraphHtml:
    @pytest.mark.asyncio
    async def test_export_writes_html_and_json(self, tmp_path):
        tk = make_toolkit()
        result = await tk.export_graph_html(str(tmp_path))
        assert "error" not in result
        assert (tmp_path / "graph.html").exists()
        assert (tmp_path / "graph.json").exists()
        assert result["node_count"] == 4
        assert result["edge_count"] == 3

    @pytest.mark.asyncio
    async def test_export_empty_graph_returns_error(self, tmp_path):
        import rustworkx
        import faiss
        tk = GraphIndexToolkit(
            graph=rustworkx.PyDiGraph(),
            faiss_index=faiss.IndexFlatIP(8),
            node_map={},
            node_id_list=[],
        )
        result = await tk.export_graph_html(str(tmp_path))
        assert "error" in result

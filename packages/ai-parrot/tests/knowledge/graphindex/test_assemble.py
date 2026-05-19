"""Unit tests for parrot.knowledge.graphindex.assemble."""

import pytest

from parrot.knowledge.graphindex.assemble import GraphAssembler
from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    Provenance,
    UniversalEdge,
    UniversalNode,
)


def make_node(node_id: str, title: str, kind: NodeKind = NodeKind.DOCUMENT) -> UniversalNode:
    """Create a minimal test node."""
    return UniversalNode(
        node_id=node_id, kind=kind, title=title, source_uri="test.txt"
    )


def make_edge(
    source_id: str, target_id: str, kind: EdgeKind = EdgeKind.CONTAINS
) -> UniversalEdge:
    """Create a minimal test edge."""
    return UniversalEdge(source_id=source_id, target_id=target_id, kind=kind)


class TestGraphAssembler:
    @pytest.fixture
    def assembler(self):
        return GraphAssembler(tenant_id="test-tenant")

    def test_add_node(self, assembler):
        idx = assembler.add_node(make_node("n1", "Node 1"))
        assert isinstance(idx, int)
        assert assembler.node_count == 1

    def test_add_edge(self, assembler):
        assembler.add_node(make_node("n1", "Node 1"))
        assembler.add_node(make_node("n2", "Node 2"))
        idx = assembler.add_edge(make_edge("n1", "n2"))
        assert isinstance(idx, int)
        assert assembler.edge_count == 1

    def test_get_node(self, assembler):
        assembler.add_node(make_node("n1", "Node 1"))
        payload = assembler.get_node("n1")
        assert payload is not None
        assert payload["node_id"] == "n1"
        assert payload["title"] == "Node 1"

    def test_get_node_missing(self, assembler):
        assert assembler.get_node("nonexistent") is None

    def test_get_neighbors_outgoing(self, assembler):
        assembler.add_node(make_node("n1", "Node 1"))
        assembler.add_node(make_node("n2", "Node 2"))
        assembler.add_node(make_node("n3", "Node 3"))
        assembler.add_edge(make_edge("n1", "n2"))
        assembler.add_edge(make_edge("n1", "n3"))
        neighbors = assembler.get_neighbors("n1", direction="outgoing")
        assert len(neighbors) == 2
        neighbor_ids = {n["node_id"] for n in neighbors}
        assert "n2" in neighbor_ids
        assert "n3" in neighbor_ids

    def test_get_neighbors_incoming(self, assembler):
        assembler.add_node(make_node("n1", "Node 1"))
        assembler.add_node(make_node("n2", "Node 2"))
        assembler.add_edge(make_edge("n1", "n2"))
        neighbors = assembler.get_neighbors("n2", direction="incoming")
        assert len(neighbors) == 1
        assert neighbors[0]["node_id"] == "n1"

    def test_get_neighbors_both(self, assembler):
        assembler.add_node(make_node("a", "A"))
        assembler.add_node(make_node("b", "B"))
        assembler.add_node(make_node("c", "C"))
        assembler.add_edge(make_edge("a", "b"))
        assembler.add_edge(make_edge("c", "b"))
        neighbors = assembler.get_neighbors("b", direction="both")
        ids = {n["node_id"] for n in neighbors}
        assert "a" in ids
        assert "c" in ids

    def test_get_edges_for_node(self, assembler):
        assembler.add_node(make_node("n1", "Node 1"))
        assembler.add_node(make_node("n2", "Node 2"))
        assembler.add_edge(make_edge("n1", "n2", EdgeKind.CONTAINS))
        edges = assembler.get_edges_for_node("n1")
        assert len(edges) == 1
        assert edges[0]["kind"] == EdgeKind.CONTAINS.value

    def test_duplicate_node_updates(self, assembler):
        assembler.add_node(make_node("n1", "Original"))
        assembler.add_node(make_node("n1", "Updated"))
        assert assembler.node_count == 1
        payload = assembler.get_node("n1")
        assert payload["title"] == "Updated"

    def test_edge_missing_source_skipped(self, assembler):
        assembler.add_node(make_node("n2", "Node 2"))
        idx = assembler.add_edge(make_edge("missing", "n2"))
        assert idx is None
        assert assembler.edge_count == 0

    def test_edge_missing_target_skipped(self, assembler):
        assembler.add_node(make_node("n1", "Node 1"))
        idx = assembler.add_edge(make_edge("n1", "missing"))
        assert idx is None
        assert assembler.edge_count == 0

    def test_per_tenant_isolation(self):
        a1 = GraphAssembler(tenant_id="tenant-a")
        a2 = GraphAssembler(tenant_id="tenant-b")
        a1.add_node(make_node("n1", "A's node"))
        a2.add_node(make_node("n1", "B's node"))
        assert a1.get_node("n1")["title"] == "A's node"
        assert a2.get_node("n1")["title"] == "B's node"
        assert a1.node_count == 1
        assert a2.node_count == 1

    def test_batch_add(self, assembler):
        nodes = [make_node(f"n{i}", f"Node {i}") for i in range(5)]
        assembler.add_nodes(nodes)
        assert assembler.node_count == 5

    def test_batch_add_edges(self, assembler):
        assembler.add_nodes([make_node("a", "A"), make_node("b", "B"), make_node("c", "C")])
        edges = [make_edge("a", "b"), make_edge("b", "c")]
        result = assembler.add_edges(edges)
        assert assembler.edge_count == 2
        assert all(r is not None for r in result)

    def test_node_payload_contains_kind(self, assembler):
        assembler.add_node(make_node("n1", "Node 1", kind=NodeKind.SYMBOL))
        payload = assembler.get_node("n1")
        assert payload["kind"] == NodeKind.SYMBOL.value

    def test_node_payload_no_source_body(self, assembler):
        """Source body must NOT be stored inline — only content_ref."""
        assembler.add_node(make_node("n1", "Node 1"))
        payload = assembler.get_node("n1")
        assert "content_ref" in payload
        # The full text body is not in the payload
        assert "page_content" not in payload

    def test_get_neighbors_missing_node(self, assembler):
        result = assembler.get_neighbors("nonexistent")
        assert result == []

    def test_get_edges_missing_node(self, assembler):
        result = assembler.get_edges_for_node("nonexistent")
        assert result == []

    def test_edge_payload_has_kind(self, assembler):
        assembler.add_node(make_node("a", "A"))
        assembler.add_node(make_node("b", "B"))
        assembler.add_edge(make_edge("a", "b", EdgeKind.REFERENCES))
        edges = assembler.get_edges_for_node("a", direction="outgoing")
        assert edges[0]["kind"] == EdgeKind.REFERENCES.value

    def test_inferred_edge_with_confidence(self, assembler):
        assembler.add_node(make_node("a", "A"))
        assembler.add_node(make_node("b", "B"))
        inferred_edge = UniversalEdge(
            source_id="a",
            target_id="b",
            kind=EdgeKind.MENTIONS,
            provenance=Provenance.INFERRED,
            confidence=0.87,
        )
        assembler.add_edge(inferred_edge)
        edges = assembler.get_edges_for_node("a", direction="outgoing")
        assert edges[0]["confidence"] == 0.87

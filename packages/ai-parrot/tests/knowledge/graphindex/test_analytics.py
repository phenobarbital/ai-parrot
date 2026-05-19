"""Unit tests for parrot.knowledge.graphindex.analytics."""

import pytest
import rustworkx
from pathlib import Path

from parrot.knowledge.graphindex.analytics import (
    AnalyticsResult,
    compute_analytics,
    generate_report,
    _compute_god_nodes,
    _rank_surprising_connections,
    _generate_suggested_questions,
    REPORT_FILENAME,
)
from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    Provenance,
    UniversalEdge,
    UniversalNode,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_node(
    node_id: str,
    kind: NodeKind = NodeKind.DOCUMENT,
    title: str | None = None,
) -> UniversalNode:
    """Create a minimal UniversalNode."""
    return UniversalNode(
        node_id=node_id,
        kind=kind,
        title=title or f"Node {node_id}",
        source_uri="test.txt",
    )


def make_edge(
    source_id: str,
    target_id: str,
    kind: EdgeKind = EdgeKind.CONTAINS,
    provenance: Provenance = Provenance.EXTRACTED,
    confidence: float | None = None,
) -> UniversalEdge:
    """Create a minimal UniversalEdge."""
    return UniversalEdge(
        source_id=source_id,
        target_id=target_id,
        kind=kind,
        provenance=provenance,
        confidence=confidence,
    )


def build_graph_with_nodes(payloads: list[dict]) -> rustworkx.PyDiGraph:
    """Build a PyDiGraph from a list of node payload dicts."""
    g = rustworkx.PyDiGraph()
    indices = [g.add_node(p) for p in payloads]
    return g, indices


# ---------------------------------------------------------------------------
# TestGodNodes
# ---------------------------------------------------------------------------


class TestGodNodes:
    def test_empty_graph_returns_empty(self):
        g = rustworkx.PyDiGraph()
        result = _compute_god_nodes(g, top_k=10)
        assert result == []

    def test_single_node_returned(self):
        g = rustworkx.PyDiGraph()
        g.add_node({"node_id": "n1", "title": "Node 1", "kind": "document"})
        result = _compute_god_nodes(g, top_k=10)
        assert len(result) == 1
        assert result[0]["node_id"] == "n1"

    def test_top_k_limits_results(self):
        g = rustworkx.PyDiGraph()
        for i in range(10):
            g.add_node({"node_id": f"n{i}", "title": f"Node {i}", "kind": "document"})
        result = _compute_god_nodes(g, top_k=3)
        assert len(result) <= 3

    def test_god_nodes_ranked_by_betweenness(self):
        """Hub node should have higher betweenness than leaf nodes."""
        g = rustworkx.PyDiGraph()
        hub_idx = g.add_node({"node_id": "hub", "title": "Hub", "kind": "concept"})
        leaf_indices = []
        for i in range(4):
            idx = g.add_node({"node_id": f"leaf{i}", "title": f"Leaf {i}", "kind": "document"})
            leaf_indices.append(idx)
        # Connect all leaves through hub
        for li in leaf_indices:
            g.add_edge(li, hub_idx, {})
            g.add_edge(hub_idx, li, {})

        result = _compute_god_nodes(g, top_k=10)
        # Hub should be first (highest betweenness)
        assert result[0]["node_id"] == "hub"

    def test_result_contains_required_keys(self):
        g = rustworkx.PyDiGraph()
        g.add_node({"node_id": "n1", "title": "Title", "kind": "document"})
        result = _compute_god_nodes(g, top_k=10)
        assert "node_id" in result[0]
        assert "title" in result[0]
        assert "kind" in result[0]
        assert "betweenness" in result[0]
        assert "eigenvector" in result[0]


# ---------------------------------------------------------------------------
# TestSurprisingConnections
# ---------------------------------------------------------------------------


class TestSurprisingConnections:
    def test_empty_edges_returns_empty(self):
        result = _rank_surprising_connections([], [], top_k=10)
        assert result == []

    def test_only_mentions_inferred_selected(self):
        """Non-MENTIONS and non-INFERRED edges must not appear."""
        nodes = [make_node("a"), make_node("b")]
        edges = [
            make_edge("a", "b", EdgeKind.CONTAINS, Provenance.EXTRACTED),
            make_edge("a", "b", EdgeKind.DEFINES, Provenance.EXTRACTED),
        ]
        result = _rank_surprising_connections(edges, nodes, top_k=10)
        assert result == []

    def test_inferred_mentions_included(self):
        nodes = [make_node("a", NodeKind.SYMBOL), make_node("b", NodeKind.DOCUMENT)]
        edges = [
            make_edge("a", "b", EdgeKind.MENTIONS, Provenance.INFERRED, confidence=0.85)
        ]
        result = _rank_surprising_connections(edges, nodes, top_k=10)
        assert len(result) == 1
        assert result[0]["source_id"] == "a"
        assert result[0]["confidence"] == 0.85

    def test_ranked_by_confidence_descending(self):
        nodes = [make_node("a"), make_node("b"), make_node("c")]
        edges = [
            make_edge("a", "b", EdgeKind.MENTIONS, Provenance.INFERRED, confidence=0.70),
            make_edge("a", "c", EdgeKind.MENTIONS, Provenance.INFERRED, confidence=0.95),
        ]
        result = _rank_surprising_connections(edges, nodes, top_k=10)
        assert result[0]["confidence"] == 0.95
        assert result[1]["confidence"] == 0.70

    def test_top_k_limits_results(self):
        nodes = [make_node(f"n{i}") for i in range(10)]
        edges = [
            make_edge(f"n{i}", f"n{9-i}", EdgeKind.MENTIONS, Provenance.INFERRED, confidence=float(i) / 10)
            for i in range(9)
        ]
        result = _rank_surprising_connections(edges, nodes, top_k=3)
        assert len(result) <= 3

    def test_result_contains_kind_info(self):
        nodes = [make_node("a", NodeKind.SYMBOL), make_node("b", NodeKind.SECTION)]
        edges = [make_edge("a", "b", EdgeKind.MENTIONS, Provenance.INFERRED, confidence=0.8)]
        result = _rank_surprising_connections(edges, nodes, top_k=10)
        assert result[0]["source_kind"] == NodeKind.SYMBOL.value
        assert result[0]["target_kind"] == NodeKind.SECTION.value


# ---------------------------------------------------------------------------
# TestSuggestedQuestions
# ---------------------------------------------------------------------------


class TestSuggestedQuestions:
    def test_empty_input_returns_empty(self):
        result = _generate_suggested_questions([], [], [])
        assert result == []

    def test_cross_domain_question_pattern(self):
        """Pattern 1: How does {A} relate to {B}?"""
        nodes = [
            make_node("sym", NodeKind.SYMBOL, "my_function"),
            make_node("doc", NodeKind.DOCUMENT, "API Guide"),
        ]
        connections = [
            {"source_id": "sym", "target_id": "doc", "confidence": 0.9,
             "source_kind": "symbol", "target_kind": "document"}
        ]
        result = _generate_suggested_questions(nodes, [], connections)
        assert any("How does" in q and "relate to" in q for q in result)

    def test_rationale_question_pattern(self):
        """Pattern 2: What rationale exists for {function}?"""
        nodes = [
            make_node("rat", NodeKind.RATIONALE, "Rationale for do_thing"),
            make_node("sym", NodeKind.SYMBOL, "do_thing"),
        ]
        edges = [make_edge("rat", "sym", EdgeKind.EXPLAINS)]
        result = _generate_suggested_questions(nodes, edges, [])
        assert any("What rationale exists for" in q for q in result)

    def test_section_mention_question_pattern(self):
        """Pattern 3: Which sections mention {symbol}?"""
        nodes = [
            make_node("sym", NodeKind.SYMBOL, "MyClass"),
            make_node("sec", NodeKind.SECTION, "API Reference"),
        ]
        edges = [make_edge("sym", "sec", EdgeKind.MENTIONS)]
        result = _generate_suggested_questions(nodes, edges, [])
        assert any("Which sections mention" in q for q in result)


# ---------------------------------------------------------------------------
# TestComputeAnalytics
# ---------------------------------------------------------------------------


class TestComputeAnalytics:
    def test_returns_analytics_result(self):
        g = rustworkx.PyDiGraph()
        result = compute_analytics(g, [], [], top_k=5)
        assert isinstance(result, AnalyticsResult)

    def test_empty_graph_returns_empty_result(self):
        g = rustworkx.PyDiGraph()
        result = compute_analytics(g, [], [], top_k=10)
        assert result.god_nodes == []
        assert result.surprising_connections == []
        assert result.suggested_questions == []

    def test_graph_with_nodes_produces_god_nodes(self):
        g = rustworkx.PyDiGraph()
        for i in range(3):
            g.add_node({"node_id": f"n{i}", "title": f"N{i}", "kind": "document"})
        nodes = [make_node(f"n{i}") for i in range(3)]
        result = compute_analytics(g, nodes, [], top_k=10)
        assert len(result.god_nodes) == 3


# ---------------------------------------------------------------------------
# TestGenerateReport
# ---------------------------------------------------------------------------


class TestGenerateReport:
    def test_report_file_created(self, tmp_path):
        analytics = AnalyticsResult()
        path = generate_report(analytics, tmp_path)
        assert path.exists()
        assert path.name == REPORT_FILENAME

    def test_report_contains_sections(self, tmp_path):
        analytics = AnalyticsResult()
        path = generate_report(analytics, tmp_path)
        content = path.read_text()
        assert "# Knowledge Graph Report" in content
        assert "## God-Nodes" in content
        assert "## Surprising Connections" in content
        assert "## Suggested Questions" in content

    def test_report_contains_god_node_data(self, tmp_path):
        analytics = AnalyticsResult(
            god_nodes=[
                {"node_id": "n1", "title": "My Node", "kind": "concept",
                 "betweenness": 0.75, "eigenvector": 0.33}
            ]
        )
        path = generate_report(analytics, tmp_path)
        content = path.read_text()
        assert "My Node" in content
        assert "0.7500" in content

    def test_report_contains_connections(self, tmp_path):
        analytics = AnalyticsResult(
            surprising_connections=[
                {"source_id": "src1", "target_id": "tgt1", "confidence": 0.88,
                 "source_kind": "symbol", "target_kind": "document"}
            ]
        )
        path = generate_report(analytics, tmp_path)
        content = path.read_text()
        assert "src1" in content
        assert "0.8800" in content

    def test_report_is_deterministic(self, tmp_path):
        """Same input must produce identical report text."""
        analytics = AnalyticsResult(
            god_nodes=[
                {"node_id": "n1", "title": "Hub", "kind": "concept",
                 "betweenness": 0.5, "eigenvector": 0.5}
            ],
            surprising_connections=[
                {"source_id": "a", "target_id": "b", "confidence": 0.9,
                 "source_kind": "symbol", "target_kind": "document"}
            ],
            suggested_questions=["How does X relate to Y?"],
        )
        path1 = generate_report(analytics, tmp_path / "run1")
        path2 = generate_report(analytics, tmp_path / "run2")
        assert path1.read_text() == path2.read_text()

    def test_llm_polish_is_noop(self, tmp_path):
        """llm_polish=True must not change the output in v1."""
        analytics = AnalyticsResult(
            suggested_questions=["Is this a test?"]
        )
        path_false = generate_report(analytics, tmp_path / "no_polish", llm_polish=False)
        path_true = generate_report(analytics, tmp_path / "with_polish", llm_polish=True)
        assert path_false.read_text() == path_true.read_text()

    def test_creates_output_dir_if_missing(self, tmp_path):
        """output_dir must be created if it does not exist."""
        analytics = AnalyticsResult()
        nested = tmp_path / "a" / "b" / "c"
        path = generate_report(analytics, nested)
        assert path.exists()

    def test_suggested_questions_in_report(self, tmp_path):
        analytics = AnalyticsResult(
            suggested_questions=["What is the meaning of life?", "How does A relate to B?"]
        )
        path = generate_report(analytics, tmp_path)
        content = path.read_text()
        assert "What is the meaning of life?" in content
        assert "How does A relate to B?" in content

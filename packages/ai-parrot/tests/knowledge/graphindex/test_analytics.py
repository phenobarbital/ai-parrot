"""Unit tests for parrot.knowledge.graphindex.analytics."""

import pytest
import rustworkx
from pathlib import Path

from parrot.knowledge.graphindex.analytics import (
    AnalyticsResult,
    KnowledgeGaps,
    compute_analytics,
    generate_report,
    find_isolated_nodes,
    find_sparse_communities,
    find_bridge_nodes,
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


# ---------------------------------------------------------------------------
# FEAT-215: graph_with_gaps fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def graph_with_gaps():
    """Graph with isolated nodes, sparse communities, and bridge nodes.

    Topology:
        - Communities A (tight), B (sparse), C (tight)
        - 1 bridge node "bridge" connecting all three communities
        - 2 isolated nodes: "iso0" (degree 0), "iso1" (degree 1, CONCEPT kind)
        - DOCUMENT node "doc_root" (excluded by default in find_isolated_nodes)

    The CommunitiesResult is built directly (not via Louvain) to give
    deterministic cohesion values for testing.
    """
    from parrot.knowledge.graphindex.communities import Community, CommunitiesResult

    g = rustworkx.PyDiGraph()

    # Community A — tight (3 members, well-connected)
    a1 = g.add_node({"node_id": "a1", "kind": "concept", "title": "A1"})
    a2 = g.add_node({"node_id": "a2", "kind": "concept", "title": "A2"})
    a3 = g.add_node({"node_id": "a3", "kind": "symbol", "title": "A3"})

    # Community B — sparse (3 members, barely connected)
    b1 = g.add_node({"node_id": "b1", "kind": "section", "title": "B1"})
    b2 = g.add_node({"node_id": "b2", "kind": "section", "title": "B2"})
    b3 = g.add_node({"node_id": "b3", "kind": "section", "title": "B3"})

    # Community C — tight (3 members)
    c1 = g.add_node({"node_id": "c1", "kind": "skill", "title": "C1"})
    c2 = g.add_node({"node_id": "c2", "kind": "skill", "title": "C2"})
    c3 = g.add_node({"node_id": "c3", "kind": "skill", "title": "C3"})

    # Bridge node connecting A, B, C
    bridge = g.add_node({"node_id": "bridge", "kind": "concept", "title": "Bridge"})

    # Isolated nodes
    iso0 = g.add_node({"node_id": "iso0", "kind": "concept", "title": "Isolated0"})
    iso1 = g.add_node({"node_id": "iso1", "kind": "concept", "title": "Isolated1"})

    # DOCUMENT root (should be excluded by default)
    doc_root = g.add_node({"node_id": "doc_root", "kind": "document", "title": "Root"})

    # Community A — internal edges (tight: many internal edges)
    g.add_edge(a1, a2, {})
    g.add_edge(a2, a3, {})
    g.add_edge(a3, a1, {})

    # Community B — sparse: only one internal edge
    g.add_edge(b1, b2, {})

    # Community C — internal edges
    g.add_edge(c1, c2, {})
    g.add_edge(c2, c3, {})
    g.add_edge(c3, c1, {})

    # Bridge node connects to members in all three communities
    g.add_edge(bridge, a1, {})
    g.add_edge(bridge, b1, {})
    g.add_edge(bridge, c1, {})

    # iso1 has degree 1 (one edge to doc_root)
    g.add_edge(iso1, doc_root, {})

    # Build UniversalNode list
    nodes = [
        make_node("a1", NodeKind.CONCEPT, "A1"),
        make_node("a2", NodeKind.CONCEPT, "A2"),
        make_node("a3", NodeKind.SYMBOL, "A3"),
        make_node("b1", NodeKind.SECTION, "B1"),
        make_node("b2", NodeKind.SECTION, "B2"),
        make_node("b3", NodeKind.SECTION, "B3"),
        make_node("c1", NodeKind.SKILL, "C1"),
        make_node("c2", NodeKind.SKILL, "C2"),
        make_node("c3", NodeKind.SKILL, "C3"),
        make_node("bridge", NodeKind.CONCEPT, "Bridge"),
        make_node("iso0", NodeKind.CONCEPT, "Isolated0"),
        make_node("iso1", NodeKind.CONCEPT, "Isolated1"),
        make_node("doc_root", NodeKind.DOCUMENT, "Root"),
    ]

    # Manually build CommunitiesResult with controlled cohesion values
    comm_a = Community(
        community_id="comm_a",
        size=3,
        member_node_ids=["a1", "a2", "a3"],
        centroid_node_id="a1",
        cohesion=0.80,  # tight
        modularity_contribution=0.3,
        top_titles=["A1", "A2", "A3"],
    )
    comm_b = Community(
        community_id="comm_b",
        size=3,
        member_node_ids=["b1", "b2", "b3"],
        centroid_node_id="b1",
        cohesion=0.05,  # sparse (< 0.15)
        modularity_contribution=0.1,
        top_titles=["B1", "B2", "B3"],
    )
    comm_c = Community(
        community_id="comm_c",
        size=3,
        member_node_ids=["c1", "c2", "c3"],
        centroid_node_id="c1",
        cohesion=0.75,  # tight
        modularity_contribution=0.3,
        top_titles=["C1", "C2", "C3"],
    )
    communities = CommunitiesResult(
        modularity=0.7,
        resolution=1.0,
        seed=42,
        weighted=False,
        communities=[comm_a, comm_b, comm_c],
        node_to_community={
            "a1": "comm_a", "a2": "comm_a", "a3": "comm_a",
            "b1": "comm_b", "b2": "comm_b", "b3": "comm_b",
            "c1": "comm_c", "c2": "comm_c", "c3": "comm_c",
            "bridge": "comm_a",  # bridge belongs to A but connects to all
        },
    )

    return {
        "graph": g,
        "nodes": nodes,
        "communities": communities,
    }


# ---------------------------------------------------------------------------
# FEAT-215: TestFindIsolatedNodes
# ---------------------------------------------------------------------------


class TestFindIsolatedNodes:
    def test_basic(self, graph_with_gaps):
        """Nodes with degree <= 1 are returned (DOCUMENT excluded by default)."""
        result = find_isolated_nodes(
            graph_with_gaps["graph"], graph_with_gaps["nodes"]
        )
        # iso0 (degree 0) and iso1 (degree 1) should be returned
        # doc_root (DOCUMENT) is excluded by default
        node_ids = [r["node_id"] for r in result]
        assert "iso0" in node_ids
        assert "iso1" in node_ids
        assert len(result) >= 2

    def test_excludes_document_kind(self, graph_with_gaps):
        """DOCUMENT root nodes excluded by default."""
        result = find_isolated_nodes(
            graph_with_gaps["graph"], graph_with_gaps["nodes"]
        )
        assert all(r["kind"] != "document" for r in result)

    def test_custom_exclude_kinds(self, graph_with_gaps):
        """Custom exclude_kinds is respected."""
        result = find_isolated_nodes(
            graph_with_gaps["graph"],
            graph_with_gaps["nodes"],
            exclude_kinds={NodeKind.SKILL},
        )
        assert all(r["kind"] != "skill" for r in result)

    def test_result_contains_degree(self, graph_with_gaps):
        """Each result dict contains a 'degree' field."""
        result = find_isolated_nodes(
            graph_with_gaps["graph"], graph_with_gaps["nodes"]
        )
        assert all("degree" in r for r in result)

    def test_empty_graph_returns_empty(self):
        """Empty graph returns empty list."""
        g = rustworkx.PyDiGraph()
        result = find_isolated_nodes(g, [])
        assert result == []

    def test_no_exclusion(self, graph_with_gaps):
        """exclude_kinds=set() includes DOCUMENT nodes."""
        result = find_isolated_nodes(
            graph_with_gaps["graph"],
            graph_with_gaps["nodes"],
            exclude_kinds=set(),
        )
        # doc_root has degree 1 — should be included with no exclusion
        node_ids = [r["node_id"] for r in result]
        assert "doc_root" in node_ids


# ---------------------------------------------------------------------------
# FEAT-215: TestFindSparseCommunities
# ---------------------------------------------------------------------------


class TestFindSparseCommunities:
    def test_sparse_flagged(self, graph_with_gaps):
        """Low-cohesion communities (< 0.15) are returned."""
        result = find_sparse_communities(graph_with_gaps["communities"])
        assert len(result) >= 1
        assert all(c["cohesion"] < 0.15 for c in result)

    def test_tight_communities_excluded(self, graph_with_gaps):
        """Communities with cohesion >= threshold are not returned."""
        result = find_sparse_communities(graph_with_gaps["communities"])
        community_ids = [c["community_id"] for c in result]
        assert "comm_a" not in community_ids
        assert "comm_c" not in community_ids

    def test_min_size_filter(self, graph_with_gaps):
        """Communities below min_size not flagged."""
        result = find_sparse_communities(graph_with_gaps["communities"], min_size=100)
        assert len(result) == 0

    def test_none_communities_returns_empty(self):
        """None CommunitiesResult returns empty list."""
        result = find_sparse_communities(None)
        assert result == []

    def test_result_contains_required_keys(self, graph_with_gaps):
        """Each result dict has community_id, size, cohesion, top_titles."""
        result = find_sparse_communities(graph_with_gaps["communities"])
        for r in result:
            assert "community_id" in r
            assert "size" in r
            assert "cohesion" in r
            assert "top_titles" in r


# ---------------------------------------------------------------------------
# FEAT-215: TestFindBridgeNodes
# ---------------------------------------------------------------------------


class TestFindBridgeNodes:
    def test_bridge_found(self, graph_with_gaps):
        """Node connecting 3+ communities identified."""
        result = find_bridge_nodes(
            graph_with_gaps["graph"],
            graph_with_gaps["nodes"],
            graph_with_gaps["communities"],
            min_communities=3,
        )
        assert len(result) >= 1
        node_ids = [r["node_id"] for r in result]
        assert "bridge" in node_ids

    def test_two_community_skipped(self, graph_with_gaps):
        """Nodes in only 2 communities not returned when min_communities=3."""
        result = find_bridge_nodes(
            graph_with_gaps["graph"],
            graph_with_gaps["nodes"],
            graph_with_gaps["communities"],
            min_communities=3,
        )
        assert all(r["community_count"] >= 3 for r in result)

    def test_none_communities_returns_empty(self, graph_with_gaps):
        """None CommunitiesResult returns empty list."""
        result = find_bridge_nodes(
            graph_with_gaps["graph"],
            graph_with_gaps["nodes"],
            None,
        )
        assert result == []

    def test_result_contains_required_keys(self, graph_with_gaps):
        """Each result dict has node_id, title, kind, community_count."""
        result = find_bridge_nodes(
            graph_with_gaps["graph"],
            graph_with_gaps["nodes"],
            graph_with_gaps["communities"],
        )
        for r in result:
            assert "node_id" in r
            assert "community_count" in r
            assert "neighbor_community_ids" in r


# ---------------------------------------------------------------------------
# FEAT-215: TestKnowledgeGapsModel
# ---------------------------------------------------------------------------


class TestKnowledgeGapsModel:
    def test_knowledge_gaps_default_empty(self):
        """KnowledgeGaps defaults to empty lists."""
        kg = KnowledgeGaps()
        assert kg.isolated_nodes == []
        assert kg.sparse_communities == []
        assert kg.bridge_nodes == []

    def test_analytics_result_has_knowledge_gaps_field(self):
        """AnalyticsResult has knowledge_gaps field defaulting to None."""
        ar = AnalyticsResult()
        assert ar.knowledge_gaps is None

    def test_compute_analytics_populates_knowledge_gaps(self):
        """compute_analytics populates knowledge_gaps with at least isolated_nodes."""
        g = rustworkx.PyDiGraph()
        g.add_node({"node_id": "n1", "kind": "concept", "title": "N1"})
        g.add_node({"node_id": "n2", "kind": "concept", "title": "N2"})
        nodes = [make_node("n1", NodeKind.CONCEPT), make_node("n2", NodeKind.CONCEPT)]
        result = compute_analytics(g, nodes, [], top_k=5)
        assert result.knowledge_gaps is not None
        assert isinstance(result.knowledge_gaps, KnowledgeGaps)

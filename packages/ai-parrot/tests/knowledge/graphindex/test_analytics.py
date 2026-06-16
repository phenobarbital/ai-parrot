"""Unit tests for parrot.knowledge.graphindex.analytics."""

import pytest
import rustworkx
from pathlib import Path

from parrot.knowledge.graphindex.analytics import (
    AnalyticsResult,
    KnowledgeGaps,
    SurpriseFactors,
    DismissedInsights,
    compute_analytics,
    generate_report,
    find_isolated_nodes,
    find_sparse_communities,
    find_bridge_nodes,
    dismiss_insight,
    list_unreviewed_insights,
    _compute_god_nodes,
    _rank_surprising_connections,
    _generate_suggested_questions,
    _render_report,
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
        # FEAT-215: Use SKILL<->DOCUMENT (distant cross-type +2) + high_confidence +1 = 3
        nodes = [make_node("a", NodeKind.SKILL), make_node("b", NodeKind.DOCUMENT)]
        edges = [
            make_edge("a", "b", EdgeKind.MENTIONS, Provenance.INFERRED, confidence=0.85)
        ]
        result = _rank_surprising_connections(edges, nodes, top_k=10)
        assert len(result) == 1
        assert result[0]["source_id"] == "a"
        assert result[0]["confidence"] == 0.85

    def test_ranked_by_composite_score_descending(self):
        """FEAT-215: Results sorted by composite_score (then confidence) descending."""
        from parrot.knowledge.graphindex.communities import CommunitiesResult
        # "b" and "c" are in different communities from "a"
        nodes = [
            make_node("a", NodeKind.SKILL, "Skill A"),
            make_node("b", NodeKind.DOCUMENT, "Doc B"),
            make_node("c", NodeKind.DOCUMENT, "Doc C"),
        ]
        # a->b: cross_community(+3) + distant_cross_type(+2) + high_conf(+1) = 6
        # a->c: distant_cross_type(+2) + high_conf(+1) = 3 (no cross community)
        communities = CommunitiesResult(
            modularity=0.5, resolution=1.0, seed=42, weighted=False,
            communities=[],
            node_to_community={"a": "comm_1", "b": "comm_2"},
        )
        edges = [
            make_edge("a", "b", EdgeKind.MENTIONS, Provenance.INFERRED, confidence=0.70),
            make_edge("a", "c", EdgeKind.MENTIONS, Provenance.INFERRED, confidence=0.95),
        ]
        result = _rank_surprising_connections(edges, nodes, top_k=10, communities_result=communities)
        # a->b has higher composite score (6) vs a->c (3)
        assert result[0]["source_id"] == "a"
        assert result[0]["target_id"] == "b"

    def test_top_k_limits_results(self):
        # FEAT-215: Use SKILL and DOCUMENT kinds to ensure composite score >= 3
        # (distant cross-type +2 + high_confidence +1 = 3)
        nodes = [make_node(f"sk{i}", NodeKind.SKILL) for i in range(5)] + \
                [make_node(f"doc{i}", NodeKind.DOCUMENT) for i in range(5)]
        edges = [
            make_edge(f"sk{i}", f"doc{i}", EdgeKind.MENTIONS, Provenance.INFERRED, confidence=0.8)
            for i in range(5)
        ]
        result = _rank_surprising_connections(edges, nodes, top_k=3)
        assert len(result) <= 3

    def test_result_contains_kind_info(self):
        # FEAT-215: Use SYMBOL<->RATIONALE (distant pair +2) + high_conf (+1) = 3
        nodes = [make_node("a", NodeKind.SYMBOL), make_node("b", NodeKind.RATIONALE)]
        edges = [make_edge("a", "b", EdgeKind.MENTIONS, Provenance.INFERRED, confidence=0.8)]
        result = _rank_surprising_connections(edges, nodes, top_k=10)
        assert len(result) >= 1
        assert result[0]["source_kind"] == NodeKind.SYMBOL.value
        assert result[0]["target_kind"] == NodeKind.RATIONALE.value


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


# ---------------------------------------------------------------------------
# FEAT-215 TASK-1566: TestCompositeSurpriseScoring
# ---------------------------------------------------------------------------


class TestCompositeSurpriseScoring:
    def test_surprise_factors_model_defaults(self):
        """SurpriseFactors defaults are all False/0."""
        sf = SurpriseFactors()
        assert sf.cross_community is False
        assert sf.cross_type is False
        assert sf.type_distance == 0
        assert sf.peripheral_hub is False
        assert sf.weak_but_present is False
        assert sf.high_confidence is False
        assert sf.composite_score == 0

    def test_cross_community_score(self, graph_with_gaps):
        """Cross-community edge gets +3."""
        from parrot.knowledge.graphindex.communities import Community, CommunitiesResult

        nodes = [
            make_node("x", NodeKind.CONCEPT, "X"),
            make_node("y", NodeKind.CONCEPT, "Y"),
        ]
        # Create an INFERRED MENTIONS edge
        edges = [
            make_edge("x", "y", EdgeKind.MENTIONS, Provenance.INFERRED, confidence=0.8)
        ]
        # x and y in different communities → cross_community +3, high_confidence +1 = 4
        communities = CommunitiesResult(
            modularity=0.5, resolution=1.0, seed=42, weighted=False,
            communities=[],
            node_to_community={"x": "comm_1", "y": "comm_2"},
        )
        result = _rank_surprising_connections(edges, nodes, 10, communities_result=communities)
        assert len(result) == 1
        assert result[0]["composite_score"] >= 3
        assert result[0]["surprise_factors"]["cross_community"] is True

    def test_cross_type_distant_score(self):
        """Distant NodeKind pair (SKILL<->DOCUMENT) gets +2."""
        nodes = [
            make_node("sk", NodeKind.SKILL, "My Skill"),
            make_node("doc", NodeKind.DOCUMENT, "My Doc"),
        ]
        edges = [
            make_edge("sk", "doc", EdgeKind.MENTIONS, Provenance.INFERRED, confidence=0.8)
        ]
        # cross-type distant +2, high-confidence +1 = 3
        result = _rank_surprising_connections(edges, nodes, 10)
        assert len(result) == 1
        assert result[0]["surprise_factors"]["cross_type"] is True
        assert result[0]["surprise_factors"]["type_distance"] == 2
        assert result[0]["composite_score"] >= 3

    def test_cross_type_adjacent_score(self):
        """Adjacent NodeKind pair (CONCEPT<->SECTION) gets +1."""
        nodes = [
            make_node("c", NodeKind.CONCEPT, "My Concept"),
            make_node("s", NodeKind.SECTION, "My Section"),
        ]
        # concept<->section: cross_type adjacent +1, high-confidence 0.8 → +1 = 2 total
        # With only those two signals, score = 2 → should NOT surface (< 3)
        edges = [
            make_edge("c", "s", EdgeKind.MENTIONS, Provenance.INFERRED, confidence=0.8)
        ]
        result = _rank_surprising_connections(edges, nodes, 10)
        # Score = cross_type_adjacent(1) + high_confidence(1) = 2 < 3, filtered out
        assert len(result) == 0

    def test_peripheral_hub_coupling(self):
        """Low-degree node linked to high-degree hub gets +2."""
        g = rustworkx.PyDiGraph()
        # Create a hub (many connections) and a peripheral (few connections)
        hub_idx = g.add_node({"node_id": "hub", "kind": "concept", "title": "Hub"})
        for i in range(10):
            leaf_idx = g.add_node({"node_id": f"leaf{i}", "kind": "section", "title": f"Leaf{i}"})
            g.add_edge(hub_idx, leaf_idx, {})
        peri_idx = g.add_node({"node_id": "peri", "kind": "skill", "title": "Peripheral"})
        # peri has degree 0, hub has degree 10
        # Add a MENTIONS INFERRED edge between peri and hub
        nodes_list = [
            make_node("hub", NodeKind.CONCEPT, "Hub"),
            make_node("peri", NodeKind.SKILL, "Peripheral"),
        ]
        edges = [
            make_edge("peri", "hub", EdgeKind.MENTIONS, Provenance.INFERRED, confidence=0.8)
        ]
        result = _rank_surprising_connections(edges, nodes_list, 10, graph=g)
        # cross_type: SKILL<->CONCEPT = distant +2, peripheral_hub +2, high_conf +1 = 5
        assert len(result) == 1
        assert result[0]["surprise_factors"]["peripheral_hub"] is True

    def test_threshold_filtering(self):
        """Only connections with composite_score >= 3 are surfaced."""
        # CONCEPT<->SECTION with confidence=0.3 → cross_type_adj(1) + weak(1) = 2 → filtered
        nodes = [make_node("a", NodeKind.CONCEPT), make_node("b", NodeKind.SECTION)]
        edges = [
            make_edge("a", "b", EdgeKind.MENTIONS, Provenance.INFERRED, confidence=0.3)
        ]
        result = _rank_surprising_connections(edges, nodes, 10)
        assert len(result) == 0

    def test_factors_decomposed_in_result(self):
        """Each connection carries surprise_factors dict."""
        nodes = [
            make_node("sk", NodeKind.SKILL, "My Skill"),
            make_node("doc", NodeKind.DOCUMENT, "My Doc"),
        ]
        edges = [
            make_edge("sk", "doc", EdgeKind.MENTIONS, Provenance.INFERRED, confidence=0.8)
        ]
        result = _rank_surprising_connections(edges, nodes, 10)
        assert len(result) >= 1
        conn = result[0]
        assert "surprise_factors" in conn
        assert "composite_score" in conn
        sf = conn["surprise_factors"]
        assert "cross_community" in sf
        assert "cross_type" in sf
        assert "type_distance" in sf
        assert "peripheral_hub" in sf
        assert "weak_but_present" in sf
        assert "high_confidence" in sf
        assert "composite_score" in sf

    def test_backward_compat_no_communities(self):
        """Without CommunitiesResult, scoring works (skips cross-community)."""
        nodes = [
            make_node("sk", NodeKind.SKILL, "My Skill"),
            make_node("doc", NodeKind.DOCUMENT, "My Doc"),
        ]
        edges = [
            make_edge("sk", "doc", EdgeKind.MENTIONS, Provenance.INFERRED, confidence=0.8)
        ]
        # Should not raise even without communities_result
        result = _rank_surprising_connections(edges, nodes, 10)
        assert isinstance(result, list)

    def test_existing_fields_preserved(self):
        """source_id, target_id, confidence, source_kind, target_kind still present."""
        nodes = [
            make_node("sk", NodeKind.SKILL, "My Skill"),
            make_node("doc", NodeKind.DOCUMENT, "My Doc"),
        ]
        edges = [
            make_edge("sk", "doc", EdgeKind.MENTIONS, Provenance.INFERRED, confidence=0.8)
        ]
        result = _rank_surprising_connections(edges, nodes, 10)
        assert len(result) >= 1
        conn = result[0]
        assert conn["source_id"] == "sk"
        assert conn["target_id"] == "doc"
        assert conn["confidence"] == 0.8
        assert conn["source_kind"] == "skill"
        assert conn["target_kind"] == "document"

    def test_sorted_by_composite_score_desc(self):
        """Results sorted by composite_score descending."""
        from parrot.knowledge.graphindex.communities import CommunitiesResult

        nodes = [
            make_node("sk", NodeKind.SKILL, "Skill"),
            make_node("doc", NodeKind.DOCUMENT, "Doc"),
            make_node("rat", NodeKind.RATIONALE, "Rat"),
            make_node("sym", NodeKind.SYMBOL, "Sym"),
        ]
        # sk->doc: distant +2, high_conf +1 = 3
        # rat->sym: SYMBOL<->RATIONALE = distant +2, high_conf +1 = 3, plus cross_community +3 = 6
        communities = CommunitiesResult(
            modularity=0.5, resolution=1.0, seed=42, weighted=False,
            communities=[],
            node_to_community={"rat": "comm_1", "sym": "comm_2"},
        )
        edges = [
            make_edge("sk", "doc", EdgeKind.MENTIONS, Provenance.INFERRED, confidence=0.8),
            make_edge("rat", "sym", EdgeKind.MENTIONS, Provenance.INFERRED, confidence=0.8),
        ]
        result = _rank_surprising_connections(edges, nodes, 10, communities_result=communities)
        assert len(result) == 2
        # rat->sym should have higher composite score
        assert result[0]["source_id"] == "rat"


# ---------------------------------------------------------------------------
# FEAT-215 TASK-1567: TestInsightDismissal
# ---------------------------------------------------------------------------


class TestInsightDismissal:
    def test_dismiss_insight_stores_id(self):
        """dismiss_insight adds ID to dismissed set."""
        analytics = AnalyticsResult(
            surprising_connections=[
                {"source_id": "a", "target_id": "b", "confidence": 0.9,
                 "source_kind": "concept", "target_kind": "symbol",
                 "composite_score": 4, "surprise_factors": {}},
            ]
        )
        dismiss_insight(analytics, "surprise:a:b")
        assert analytics.dismissed is not None
        assert "surprise:a:b" in analytics.dismissed.dismissed_ids

    def test_dismiss_insight_creates_dismissed_if_none(self):
        """dismiss_insight creates DismissedInsights when analytics.dismissed is None."""
        analytics = AnalyticsResult()
        assert analytics.dismissed is None
        dismiss_insight(analytics, "isolated:x")
        assert analytics.dismissed is not None

    def test_dismiss_insight_multiple_ids(self):
        """Multiple insight IDs can be dismissed."""
        analytics = AnalyticsResult()
        dismiss_insight(analytics, "surprise:a:b")
        dismiss_insight(analytics, "isolated:n1")
        dismiss_insight(analytics, "sparse:comm_b")
        assert len(analytics.dismissed.dismissed_ids) == 3

    def test_list_unreviewed_excludes_dismissed(self):
        """list_unreviewed_insights excludes dismissed IDs."""
        analytics = AnalyticsResult(
            surprising_connections=[
                {"source_id": "a", "target_id": "b", "confidence": 0.9,
                 "source_kind": "concept", "target_kind": "symbol",
                 "composite_score": 4, "surprise_factors": {}},
                {"source_id": "c", "target_id": "d", "confidence": 0.8,
                 "source_kind": "section", "target_kind": "skill",
                 "composite_score": 3, "surprise_factors": {}},
            ]
        )
        dismiss_insight(analytics, "surprise:a:b")
        unreviewed = list_unreviewed_insights(analytics)
        ids = [i["id"] for i in unreviewed]
        assert "surprise:a:b" not in ids
        assert "surprise:c:d" in ids

    def test_list_unreviewed_returns_all_when_none_dismissed(self):
        """list_unreviewed_insights returns all insights when none dismissed."""
        analytics = AnalyticsResult(
            surprising_connections=[
                {"source_id": "a", "target_id": "b", "confidence": 0.9,
                 "source_kind": "concept", "target_kind": "symbol",
                 "composite_score": 4, "surprise_factors": {}},
            ]
        )
        unreviewed = list_unreviewed_insights(analytics)
        assert len(unreviewed) == 1

    def test_list_unreviewed_includes_gap_insights(self):
        """list_unreviewed_insights includes knowledge gap insights."""
        analytics = AnalyticsResult(
            knowledge_gaps=KnowledgeGaps(
                isolated_nodes=[{"node_id": "iso1", "kind": "concept", "title": "Iso1", "degree": 0}],
                sparse_communities=[{"community_id": "sp1", "size": 3, "cohesion": 0.05,
                                     "top_titles": ["A"], "centroid_node_id": "a"}],
                bridge_nodes=[{"node_id": "br1", "kind": "concept", "title": "Br1",
                                "community_count": 3, "neighbor_community_ids": []}],
            )
        )
        unreviewed = list_unreviewed_insights(analytics)
        ids = [i["id"] for i in unreviewed]
        assert "isolated:iso1" in ids
        assert "sparse:sp1" in ids
        assert "bridge:br1" in ids


# ---------------------------------------------------------------------------
# FEAT-215 TASK-1567: TestReportKnowledgeGaps
# ---------------------------------------------------------------------------


class TestReportKnowledgeGaps:
    def test_report_includes_knowledge_gaps_section(self):
        """GRAPH_REPORT.md contains Knowledge Gaps section when knowledge_gaps set."""
        analytics = AnalyticsResult(
            knowledge_gaps=KnowledgeGaps(
                isolated_nodes=[{"node_id": "iso1", "kind": "concept", "title": "Iso1", "degree": 0}],
                sparse_communities=[{"community_id": "sp1", "size": 3, "cohesion": 0.05,
                                     "top_titles": ["A"], "centroid_node_id": "a"}],
                bridge_nodes=[{"node_id": "br1", "kind": "concept", "title": "Br1",
                               "community_count": 3, "neighbor_community_ids": []}],
            )
        )
        report = _render_report(analytics)
        assert "## Knowledge Gaps" in report
        assert "### Isolated Nodes" in report
        assert "### Sparse Communities" in report
        assert "### Bridge Nodes" in report

    def test_report_omits_gaps_when_none(self):
        """No Knowledge Gaps section when knowledge_gaps is None."""
        analytics = AnalyticsResult()
        report = _render_report(analytics)
        assert "## Knowledge Gaps" not in report

    def test_report_omits_gaps_when_all_empty(self):
        """No Knowledge Gaps section when knowledge_gaps has empty lists."""
        analytics = AnalyticsResult(knowledge_gaps=KnowledgeGaps())
        report = _render_report(analytics)
        assert "## Knowledge Gaps" not in report

    def test_dismissed_connections_filtered_in_report(self):
        """Dismissed surprising connections not in report output."""
        analytics = AnalyticsResult(
            surprising_connections=[
                {"source_id": "src1", "target_id": "tgt1", "confidence": 0.9,
                 "source_kind": "skill", "target_kind": "document",
                 "composite_score": 3, "surprise_factors": {}},
                {"source_id": "src2", "target_id": "tgt2", "confidence": 0.8,
                 "source_kind": "symbol", "target_kind": "rationale",
                 "composite_score": 3, "surprise_factors": {}},
            ]
        )
        dismiss_insight(analytics, "surprise:src1:tgt1")
        report = _render_report(analytics)
        assert "src1" not in report
        assert "src2" in report

    def test_dismissed_isolated_node_filtered_in_report(self):
        """Dismissed isolated node not shown in Knowledge Gaps section."""
        analytics = AnalyticsResult(
            knowledge_gaps=KnowledgeGaps(
                isolated_nodes=[
                    {"node_id": "iso1", "kind": "concept", "title": "Iso1", "degree": 0},
                    {"node_id": "iso2", "kind": "concept", "title": "Iso2", "degree": 1},
                ]
            )
        )
        dismiss_insight(analytics, "isolated:iso1")
        report = _render_report(analytics)
        assert "Iso1" not in report
        assert "Iso2" in report

    def test_report_shows_composite_score_column(self):
        """Surprising Connections table shows composite_score when present."""
        analytics = AnalyticsResult(
            surprising_connections=[
                {"source_id": "sk", "target_id": "doc", "confidence": 0.8,
                 "source_kind": "skill", "target_kind": "document",
                 "composite_score": 5, "surprise_factors": {}},
            ]
        )
        report = _render_report(analytics)
        assert "5" in report  # composite score value present
        assert "Score" in report

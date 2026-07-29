"""Tests for parrot.knowledge.graphindex.export_html.

Covers the interactive HTML / JSON graph exporter: payload construction,
deterministic community colouring, god-node sizing/highlighting, the
unclustered bin, offline asset inlining, and the CDN fallback.
"""
from __future__ import annotations

import json

import pytest

from parrot.knowledge.graphindex.analytics import compute_analytics
from parrot.knowledge.graphindex.assemble import GraphAssembler
from parrot.knowledge.graphindex.communities import detect_communities
from parrot.knowledge.graphindex import export_html as EH
from parrot.knowledge.graphindex.export_html import (
    GraphExportPayload,
    build_export_payload,
    community_color,
    export_graph,
    write_graph_html,
    write_graph_json,
)
from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    UniversalEdge,
    UniversalNode,
)

FAKE_ECHARTS = "/*FAKE_ECHARTS*/window.echarts={init:function(){}};"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _two_cluster_graph() -> tuple[GraphAssembler, list[UniversalNode], list[UniversalEdge]]:
    """Two 4-node rings joined by a single bridge edge (n3 → n4)."""
    nodes: list[UniversalNode] = [
        UniversalNode(
            node_id=f"n{i}",
            kind=NodeKind.SYMBOL,
            title=f"Payment {i}" if i < 4 else f"Shipping {i}",
            source_uri=f"file{i}.py",
            summary=f"summary for node {i}",
        )
        for i in range(8)
    ]
    ring = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (3, 4)]
    edges = [
        UniversalEdge(source_id=f"n{a}", target_id=f"n{b}", kind=EdgeKind.REFERENCES)
        for a, b in ring
    ]
    asm = GraphAssembler(tenant_id="t")
    asm.add_nodes(nodes)
    asm.add_edges(edges)
    return asm, nodes, edges


@pytest.fixture
def graph_bundle():
    asm, nodes, edges = _two_cluster_graph()
    communities = detect_communities(asm.graph, nodes, write_back_to_nodes=False)
    analytics = compute_analytics(asm.graph, nodes, edges)
    return asm, nodes, edges, communities, analytics


# ---------------------------------------------------------------------------
# community_color
# ---------------------------------------------------------------------------


class TestCommunityColor:
    def test_deterministic(self):
        assert community_color(0) == community_color(0)
        assert community_color(0) != community_color(1)

    def test_wraps_around_palette(self):
        assert community_color(0) == community_color(len(EH._PALETTE))

    def test_all_hex(self):
        for i in range(len(EH._PALETTE)):
            assert community_color(i).startswith("#") and len(community_color(i)) == 7


# ---------------------------------------------------------------------------
# build_export_payload
# ---------------------------------------------------------------------------


class TestBuildPayload:
    def test_counts_match_graph(self, graph_bundle):
        asm, nodes, edges, comm, ana = graph_bundle
        p = build_export_payload(
            asm.graph,
            node_to_community=comm.node_to_community,
            community_order=[c.community_id for c in comm.communities],
        )
        assert isinstance(p, GraphExportPayload)
        assert len(p.nodes) == asm.graph.num_nodes() == 8
        assert len(p.edges) == asm.graph.num_edges() == 9

    def test_categories_have_deterministic_colors(self, graph_bundle):
        asm, nodes, edges, comm, ana = graph_bundle
        order = [c.community_id for c in comm.communities]
        p = build_export_payload(
            asm.graph, node_to_community=comm.node_to_community, community_order=order
        )
        colors = [c.color for c in p.categories if c.community_id is not None]
        assert colors == [community_color(i) for i in range(len(order))]

    def test_every_node_has_valid_category_index(self, graph_bundle):
        asm, nodes, edges, comm, ana = graph_bundle
        order = [c.community_id for c in comm.communities]
        p = build_export_payload(
            asm.graph, node_to_community=comm.node_to_community, community_order=order
        )
        for n in p.nodes:
            assert 0 <= n.category < len(p.categories)

    def test_unclustered_bin_created_for_orphans(self):
        # A lone node with no community assignment lands in the unclustered bin.
        node = UniversalNode(
            node_id="solo", kind=NodeKind.CONCEPT, title="Solo", source_uri="x"
        )
        asm = GraphAssembler(tenant_id="t")
        asm.add_nodes([node])
        p = build_export_payload(asm.graph)  # no communities supplied
        assert len(p.categories) == 1
        assert p.categories[0].community_id is None
        assert p.categories[0].label == EH._UNCLUSTERED_LABEL
        assert p.nodes[0].community_id is None

    def test_god_nodes_flagged_and_sized_larger(self, graph_bundle):
        asm, nodes, edges, comm, ana = graph_bundle
        # n3 and n4 are the bridge endpoints — highest betweenness.
        god_scores = {"n3": 0.9, "n4": 0.8}
        p = build_export_payload(
            asm.graph,
            node_to_community=comm.node_to_community,
            god_scores=god_scores,
            god_node_ids=["n3", "n4"],
        )
        by_id = {n.id: n for n in p.nodes}
        assert by_id["n3"].is_god and by_id["n4"].is_god
        assert set(p.god_node_ids) == {"n3", "n4"}
        # A god node is drawn larger than a zero-score non-god node.
        assert by_id["n3"].symbolSize > by_id["n0"].symbolSize

    def test_falls_back_to_degree_when_no_god_scores(self, graph_bundle):
        asm, nodes, edges, comm, ana = graph_bundle
        p = build_export_payload(asm.graph, node_to_community=comm.node_to_community)
        # Sizing uses degree; every node keeps a positive size.
        assert all(n.symbolSize >= EH._MIN_SYMBOL_SIZE for n in p.nodes)


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


class TestWriters:
    def test_write_graph_json_roundtrips(self, graph_bundle, tmp_path):
        asm, nodes, edges, comm, ana = graph_bundle
        p = build_export_payload(asm.graph, node_to_community=comm.node_to_community)
        path = write_graph_json(p, tmp_path)
        assert path.name == "graph.json"
        data = json.loads(path.read_text())
        assert len(data["nodes"]) == 8
        assert len(data["edges"]) == 9
        assert "categories" in data and "god_node_ids" in data

    def test_write_graph_html_inlines_offline_asset(self, graph_bundle, tmp_path):
        asm, nodes, edges, comm, ana = graph_bundle
        p = build_export_payload(asm.graph, node_to_community=comm.node_to_community)
        path = write_graph_html(p, tmp_path, echarts_js=FAKE_ECHARTS)
        html = path.read_text()
        assert path.name == "graph.html"
        assert "/*FAKE_ECHARTS*/" in html          # runtime inlined
        assert "cdn.jsdelivr.net" not in html       # no network dependency
        assert '"nodes"' in html                    # payload embedded
        assert "echarts.init" in html               # chart bootstrapped

    def test_write_graph_html_escapes_script_in_payload(self, tmp_path):
        # A node summary containing "</script>" must NOT close the inline
        # <script> early (regression: page rendered as raw text otherwise).
        node = UniversalNode(
            node_id="danger",
            kind=NodeKind.SYMBOL,
            title="Renderer",
            source_uri="x.py",
            summary="Builds a </script><h1>pwned</h1> tag & more",
        )
        asm = GraphAssembler(tenant_id="t")
        asm.add_nodes([node])
        p = build_export_payload(asm.graph)
        html = write_graph_html(p, tmp_path, echarts_js=FAKE_ECHARTS).read_text()
        # The raw breakout sequence must be gone; the payload occurrence is
        # escaped to </script...
        assert "</script><h1>" not in html
        assert "\\u003c/script" in html
        # Exactly two real closers: the echarts runtime and the main script.
        assert html.count("</script>") == 2

    def test_write_graph_html_escapes_line_separators(self, tmp_path):
        node = UniversalNode(
            node_id="ls",
            kind=NodeKind.SYMBOL,
            title="Sep",
            source_uri="x.py",
            summary="line1 line2 line3",
        )
        asm = GraphAssembler(tenant_id="t")
        asm.add_nodes([node])
        p = build_export_payload(asm.graph)
        html = write_graph_html(p, tmp_path, echarts_js=FAKE_ECHARTS).read_text()
        assert " " not in html and " " not in html
        assert "\\u2028" in html and "\\u2029" in html

    def test_write_graph_html_cdn_fallback(self, graph_bundle, tmp_path, monkeypatch):
        asm, nodes, edges, comm, ana = graph_bundle
        p = build_export_payload(asm.graph)
        monkeypatch.setattr(EH, "_locate_echarts_asset", lambda: None)
        path = write_graph_html(p, tmp_path, allow_cdn_fallback=True)
        assert EH.ECHARTS_CDN_URL in path.read_text()

    def test_write_graph_html_raises_without_asset_when_fallback_disabled(
        self, graph_bundle, tmp_path, monkeypatch
    ):
        asm, nodes, edges, comm, ana = graph_bundle
        p = build_export_payload(asm.graph)
        monkeypatch.setattr(EH, "_locate_echarts_asset", lambda: None)
        with pytest.raises(RuntimeError):
            write_graph_html(p, tmp_path, allow_cdn_fallback=False)


# ---------------------------------------------------------------------------
# export_graph (high-level convenience)
# ---------------------------------------------------------------------------


class TestExportGraph:
    def test_writes_both_artifacts(self, graph_bundle, tmp_path):
        asm, nodes, edges, comm, ana = graph_bundle
        html_path, json_path = export_graph(
            asm.graph,
            tmp_path,
            communities=comm,
            analytics=ana,
            echarts_js=FAKE_ECHARTS,
        )
        assert html_path.exists() and json_path.exists()
        data = json.loads(json_path.read_text())
        # Community labels flow from CommunitiesResult into the categories.
        labels = {c["label"] for c in data["categories"] if c["community_id"]}
        assert labels  # non-empty, LLM-free labels present
        assert data["modularity"] == pytest.approx(comm.modularity)

    def test_deterministic_across_runs(self, graph_bundle, tmp_path):
        asm, nodes, edges, comm, ana = graph_bundle
        _, j1 = export_graph(asm.graph, tmp_path / "a", communities=comm,
                             analytics=ana, echarts_js=FAKE_ECHARTS)
        _, j2 = export_graph(asm.graph, tmp_path / "b", communities=comm,
                             analytics=ana, echarts_js=FAKE_ECHARTS)
        assert j1.read_text() == j2.read_text()

"""Unit + integration tests for parrot.knowledge.graphindex.communities (FEAT-191)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import networkx as nx
import pytest
import rustworkx

from parrot.knowledge.graphindex.communities import (
    Community,
    CommunitiesResult,
    _centroid_for_community,
    _community_modularity_contribution,
    _order_members,
    _stable_community_id,
    _to_undirected_networkx,
    _total_edge_weight,
    cohesion_for_community,
    detect_communities,
)
from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    UniversalEdge,
    UniversalNode,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node(node_id: str, kind: NodeKind = NodeKind.SECTION,
          title: str = "", source_uri: str = "d.md") -> UniversalNode:
    return UniversalNode(
        node_id=node_id, kind=kind,
        title=title or node_id, source_uri=source_uri,
    )


def _add(graph: rustworkx.PyDiGraph, n: UniversalNode) -> int:
    return graph.add_node({
        "node_id": n.node_id,
        "kind": n.kind.value,
        "title": n.title,
        "source_uri": n.source_uri,
        "domain_tags": dict(n.domain_tags),
    })


def _build_two_cliques() -> tuple[rustworkx.PyDiGraph, list[UniversalNode]]:
    """Two K5 cliques (A0..A4, B0..B4) joined by a single bridge A0↔B0."""
    g = rustworkx.PyDiGraph()
    nodes = []
    idxs: dict[str, int] = {}
    for cluster in ("A", "B"):
        for i in range(5):
            nid = f"{cluster}{i}"
            n = _node(nid, source_uri=f"{cluster.lower()}.md")
            nodes.append(n)
            idxs[nid] = _add(g, n)
    # Two cliques.
    for cluster in ("A", "B"):
        members = [f"{cluster}{i}" for i in range(5)]
        for i in range(5):
            for j in range(i + 1, 5):
                g.add_edge(idxs[members[i]], idxs[members[j]],
                           {"kind": EdgeKind.REFERENCES.value})
    # Bridge.
    g.add_edge(idxs["A0"], idxs["B0"], {"kind": EdgeKind.REFERENCES.value})
    return g, nodes


# ---------------------------------------------------------------------------
# Module 1 — pydantic + stable ids
# ---------------------------------------------------------------------------


class TestStableCommunityId:
    def test_deterministic_same_members(self):
        assert _stable_community_id(["a", "b", "c"]) == _stable_community_id(["a", "b", "c"])

    def test_order_independent(self):
        a = _stable_community_id(["a", "b", "c"])
        b = _stable_community_id(["c", "a", "b"])
        assert a == b

    def test_different_members_different_id(self):
        a = _stable_community_id(["a", "b"])
        b = _stable_community_id(["a", "b", "c"])
        assert a != b

    def test_length_16(self):
        assert len(_stable_community_id(["a"])) == 16


class TestPydanticModels:
    def test_community_frozen(self):
        c = Community(
            community_id="x", size=1, member_node_ids=["a"],
            centroid_node_id="a", cohesion=0.0,
            modularity_contribution=0.0, top_titles=["a"],
        )
        with pytest.raises(Exception):
            c.size = 99

    def test_communities_result_frozen(self):
        r = CommunitiesResult(
            modularity=0.5, resolution=1.0, seed=42,
            weighted=False, communities=[], node_to_community={},
        )
        with pytest.raises(Exception):
            r.modularity = 0.99


# ---------------------------------------------------------------------------
# Module 2 — networkx conversion
# ---------------------------------------------------------------------------


class TestNetworkxConversion:
    def test_unweighted_edges_have_weight_one(self):
        g, nodes = _build_two_cliques()
        nx_graph = _to_undirected_networkx(g, nodes, signal_config=None)
        for _u, _v, data in nx_graph.edges(data=True):
            assert data["weight"] == 1.0

    def test_isolated_nodes_included(self):
        g = rustworkx.PyDiGraph()
        nodes = [_node("alone")]
        _add(g, nodes[0])
        nx_graph = _to_undirected_networkx(g, nodes)
        assert "alone" in nx_graph

    def test_directed_collapses_to_one_undirected_edge(self):
        g = rustworkx.PyDiGraph()
        n1, n2 = _node("a"), _node("b")
        i1, i2 = _add(g, n1), _add(g, n2)
        g.add_edge(i1, i2, {"kind": EdgeKind.REFERENCES.value})
        g.add_edge(i2, i1, {"kind": EdgeKind.CONTAINS.value})
        nx_graph = _to_undirected_networkx(g, [n1, n2])
        assert nx_graph.number_of_edges() == 1
        assert nx_graph.has_edge("a", "b")

    def test_signal_weighted_uses_signal_relevance(self):
        # Mock the lazy signal_relevance call so we don't depend on the
        # full FEAT-190 stack semantics in a unit test.
        g, nodes = _build_two_cliques()
        from parrot.knowledge.graphindex.signals import SignalRelevanceConfig
        cfg = SignalRelevanceConfig()
        nx_graph = _to_undirected_networkx(
            g, nodes, signal_config=cfg, embedder=None,
        )
        # Bridge edge A0-B0 should have a weight (could be small but
        # never zero — _build_weight_fn clamps to >= 0.001).
        assert nx_graph.has_edge("A0", "B0")
        bridge_weight = nx_graph["A0"]["B0"]["weight"]
        assert bridge_weight > 0


# ---------------------------------------------------------------------------
# Module 4 — cohesion + centroid
# ---------------------------------------------------------------------------


class TestCohesion:
    def test_pure_clique_one(self):
        g = nx.complete_graph(["a", "b", "c", "d"])
        members = {"a", "b", "c", "d"}
        assert cohesion_for_community(g, members) == 1.0

    def test_isolated_singleton_zero(self):
        g = nx.Graph()
        g.add_node("a")
        assert cohesion_for_community(g, {"a"}) == 0.0

    def test_partial_boundary(self):
        # Triangle a-b-c plus boundary edge a-x.
        g = nx.Graph()
        g.add_edges_from([("a", "b"), ("b", "c"), ("a", "c"), ("a", "x")])
        # Community {a, b, c}: internal=3, boundary=1, cohesion=3/4
        assert cohesion_for_community(g, {"a", "b", "c"}) == pytest.approx(0.75)

    def test_empty_members_zero(self):
        g = nx.Graph()
        g.add_node("a")
        assert cohesion_for_community(g, set()) == 0.0


class TestCentroid:
    def test_highest_in_community_degree_wins(self):
        # b connects to a and c; a only to b; c only to b
        g = nx.Graph()
        g.add_edges_from([("a", "b"), ("b", "c")])
        assert _centroid_for_community(g, ["a", "b", "c"]) == "b"

    def test_lexicographic_tiebreak(self):
        g = nx.complete_graph(["a", "b", "c"])
        # All have in-community degree 2; lex tiebreak picks 'a'
        assert _centroid_for_community(g, ["a", "b", "c"]) == "a"

    def test_order_members_centroid_first(self):
        g = nx.Graph()
        g.add_edges_from([("a", "b"), ("b", "c"), ("b", "d")])
        ordered = _order_members(g, ["a", "b", "c", "d"], centroid="b")
        assert ordered[0] == "b"


class TestModularityContribution:
    def test_contributions_sum_to_global_q(self):
        # Two cliques + bridge.
        g, nodes = _build_two_cliques()
        result = detect_communities(g, nodes, write_back_to_nodes=False)
        total = sum(c.modularity_contribution for c in result.communities)
        assert total == pytest.approx(result.modularity, abs=1e-6)

    def test_zero_total_weight_returns_zero(self):
        g = nx.Graph()
        g.add_node("a")
        assert _community_modularity_contribution(g, {"a"}, 0.0, 1.0) == 0.0


# ---------------------------------------------------------------------------
# Module 5 — public API + write-back
# ---------------------------------------------------------------------------


class TestDetectCommunities:
    def test_two_cliques_yields_two_communities(self):
        g, nodes = _build_two_cliques()
        result = detect_communities(g, nodes, write_back_to_nodes=False)
        assert len(result.communities) == 2
        # Each community is the right clique.
        sizes = sorted(c.size for c in result.communities)
        assert sizes == [5, 5]
        # Modularity > 0.4 — strong partition.
        assert result.modularity > 0.4

    def test_deterministic_with_seed(self):
        g, nodes = _build_two_cliques()
        r1 = detect_communities(g, nodes, seed=42, write_back_to_nodes=False)
        # Need a fresh graph because write_back mutation could differ; build twice.
        g2, nodes2 = _build_two_cliques()
        r2 = detect_communities(g2, nodes2, seed=42, write_back_to_nodes=False)
        ids1 = sorted(c.community_id for c in r1.communities)
        ids2 = sorted(c.community_id for c in r2.communities)
        assert ids1 == ids2

    def test_modularity_in_range(self):
        g, nodes = _build_two_cliques()
        result = detect_communities(g, nodes, write_back_to_nodes=False)
        assert -1.0 < result.modularity < 1.0

    def test_writeback_sets_community_id_on_every_node(self):
        g, nodes = _build_two_cliques()
        result = detect_communities(g, nodes, write_back_to_nodes=True)
        for n in nodes:
            assert "community_id" in n.domain_tags
            assert n.domain_tags["community_id"] == result.node_to_community[n.node_id]

    def test_writeback_centroid_flag(self):
        g, nodes = _build_two_cliques()
        result = detect_communities(g, nodes, write_back_to_nodes=True)
        centroid_ids = {c.centroid_node_id for c in result.communities}
        for n in nodes:
            if n.node_id in centroid_ids:
                assert n.domain_tags.get("community_centroid") is True
            else:
                assert "community_centroid" not in n.domain_tags

    def test_writeback_disabled_does_not_mutate(self):
        g, nodes = _build_two_cliques()
        detect_communities(g, nodes, write_back_to_nodes=False)
        for n in nodes:
            assert "community_id" not in n.domain_tags
            assert "community_centroid" not in n.domain_tags

    def test_communities_sorted_by_size_desc(self):
        # Build an unbalanced graph: 6-clique + 3-clique + 2-clique
        g = rustworkx.PyDiGraph()
        nodes: list[UniversalNode] = []
        all_idxs: dict[str, int] = {}
        for cluster, n_members in [("A", 6), ("B", 3), ("C", 2)]:
            members = [f"{cluster}{i}" for i in range(n_members)]
            for m in members:
                node = _node(m, source_uri=f"{cluster.lower()}.md")
                nodes.append(node)
                all_idxs[m] = _add(g, node)
            for i in range(n_members):
                for j in range(i + 1, n_members):
                    g.add_edge(all_idxs[members[i]], all_idxs[members[j]],
                               {"kind": EdgeKind.REFERENCES.value})
        result = detect_communities(g, nodes, write_back_to_nodes=False)
        sizes = [c.size for c in result.communities]
        assert sizes == sorted(sizes, reverse=True)

    def test_empty_partition_returns_empty_result(self):
        g = rustworkx.PyDiGraph()
        result = detect_communities(g, [], write_back_to_nodes=False)
        assert result.communities == []
        assert result.node_to_community == {}
        assert result.modularity == 0.0

    def test_weighted_flag_reflects_signal_config(self):
        g, nodes = _build_two_cliques()
        from parrot.knowledge.graphindex.signals import SignalRelevanceConfig
        cfg = SignalRelevanceConfig()
        result = detect_communities(g, nodes, signal_config=cfg,
                                    write_back_to_nodes=False)
        assert result.weighted is True

    def test_unweighted_flag_when_no_signal_config(self):
        g, nodes = _build_two_cliques()
        result = detect_communities(g, nodes, write_back_to_nodes=False)
        assert result.weighted is False

    def test_top_titles_capped_at_five(self):
        g, nodes = _build_two_cliques()
        result = detect_communities(g, nodes, write_back_to_nodes=False)
        for c in result.communities:
            assert len(c.top_titles) <= 5


# ---------------------------------------------------------------------------
# Module 6 — builder integration
# ---------------------------------------------------------------------------


class TestBuilderIntegration:
    def test_builder_flag_default_off(self, tmp_path):
        from parrot.knowledge.graphindex.builder import GraphIndexBuilder
        builder = GraphIndexBuilder(
            persistence=MagicMock(),
            embedder=MagicMock(),
            output_dir=tmp_path,
        )
        assert builder.detect_communities_enabled is False
        assert builder.last_community_result is None

    def test_builder_accepts_detect_communities_kwarg(self, tmp_path):
        from parrot.knowledge.graphindex.builder import GraphIndexBuilder
        builder = GraphIndexBuilder(
            persistence=MagicMock(),
            embedder=MagicMock(),
            output_dir=tmp_path,
            detect_communities_enabled=True,
            community_resolution=1.5,
        )
        assert builder.detect_communities_enabled is True
        assert builder.community_resolution == 1.5


# ---------------------------------------------------------------------------
# Module 7 — analytics report extension
# ---------------------------------------------------------------------------


class TestAnalyticsReport:
    def test_render_with_communities_section(self, tmp_path):
        from parrot.knowledge.graphindex.analytics import (
            AnalyticsResult, _render_report,
        )
        g, nodes = _build_two_cliques()
        comm_result = detect_communities(g, nodes, write_back_to_nodes=False)
        analytics = AnalyticsResult()
        analytics.communities = comm_result
        report = _render_report(analytics)
        assert "## Communities" in report
        assert "Global modularity" in report
        assert "Centroid" in report

    def test_render_without_communities_no_section(self):
        from parrot.knowledge.graphindex.analytics import (
            AnalyticsResult, _render_report,
        )
        analytics = AnalyticsResult()
        report = _render_report(analytics)
        assert "## Communities" not in report


# ---------------------------------------------------------------------------
# Persistence round-trip
# ---------------------------------------------------------------------------


class TestPersistRoundTrip:
    def test_community_id_in_dumped_node(self):
        from parrot.knowledge.graphindex.persist import _node_to_doc

        g, nodes = _build_two_cliques()
        detect_communities(g, nodes, write_back_to_nodes=True)
        # Pick any node and run it through the persist dumper.
        sample = nodes[0]
        doc = _node_to_doc(sample)
        assert "community_id" in doc["domain_tags"]
        assert doc["domain_tags"]["community_id"] == sample.domain_tags["community_id"]


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_louvain_on_two_cliques(self):
        g, nodes = _build_two_cliques()
        result = detect_communities(g, nodes, write_back_to_nodes=False)
        assert len(result.communities) == 2
        for c in result.communities:
            assert c.cohesion >= 0.9
        assert result.modularity > 0.4

    def test_signal_weighted_louvain_finds_concept_clusters(self):
        """Sections sharing a source_uri should cluster even without
        direct edges between them, because the signal-weighted graph
        introduces strong AA + source-overlap weights."""
        pytest.importorskip("parrot.knowledge.graphindex.signals")
        from parrot.knowledge.graphindex.signals import SignalRelevanceConfig

        g = rustworkx.PyDiGraph()
        all_nodes: list[UniversalNode] = []
        idxs: dict[str, int] = {}

        # Cluster 1: concept C1 + sections S1, S2 sharing doc1.md
        for nid, kind, src in [
            ("C1", NodeKind.CONCEPT, "doc1.md"),
            ("S1", NodeKind.SECTION, "doc1.md"),
            ("S2", NodeKind.SECTION, "doc1.md"),
            ("C2", NodeKind.CONCEPT, "doc2.md"),
            ("S3", NodeKind.SECTION, "doc2.md"),
            ("S4", NodeKind.SECTION, "doc2.md"),
        ]:
            n = _node(nid, kind=kind, source_uri=src)
            all_nodes.append(n)
            idxs[nid] = _add(g, n)

        # Add CONTAINS edges so AA picks up shared neighbour patterns.
        g.add_edge(idxs["C1"], idxs["S1"], {"kind": EdgeKind.REFERENCES.value})
        g.add_edge(idxs["C1"], idxs["S2"], {"kind": EdgeKind.REFERENCES.value})
        g.add_edge(idxs["C2"], idxs["S3"], {"kind": EdgeKind.REFERENCES.value})
        g.add_edge(idxs["C2"], idxs["S4"], {"kind": EdgeKind.REFERENCES.value})

        cfg = SignalRelevanceConfig()
        result = detect_communities(
            g, all_nodes, signal_config=cfg, write_back_to_nodes=False,
        )
        # We expect 2 communities, one per source.
        community_of = result.node_to_community
        assert community_of["C1"] == community_of["S1"] == community_of["S2"]
        assert community_of["C2"] == community_of["S3"] == community_of["S4"]
        assert community_of["C1"] != community_of["C2"]

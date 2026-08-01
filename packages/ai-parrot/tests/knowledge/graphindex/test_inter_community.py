"""Unit tests for parrot.knowledge.graphindex.inter_community (FEAT-401)."""
from __future__ import annotations

import pytest
import rustworkx
from parrot.knowledge.graphindex.communities import CommunitiesResult, Community
from parrot.knowledge.graphindex.inter_community import (
    InterCommunityGraph,
    InterCommunityRelation,
    compute_inter_community_graph,
)
from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node(node_id: str, title: str = "") -> UniversalNode:
    return UniversalNode(
        node_id=node_id, kind=NodeKind.SECTION,
        title=title or node_id, source_uri="d.md",
    )


def _add(graph: rustworkx.PyDiGraph, node_id: str) -> int:
    return graph.add_node({"node_id": node_id, "kind": "section", "title": node_id})


def _community(community_id: str, members: list[str], label: str = "") -> Community:
    return Community(
        community_id=community_id,
        size=len(members),
        member_node_ids=members,
        centroid_node_id=members[0],
        cohesion=1.0,
        modularity_contribution=0.0,
        top_titles=members[:5],
        label=label,
    )


def _communities_result(*communities: Community) -> CommunitiesResult:
    node_to_community = {
        nid: c.community_id for c in communities for nid in c.member_node_ids
    }
    return CommunitiesResult(
        modularity=0.5, resolution=1.0, seed=42, weighted=False,
        communities=list(communities), node_to_community=node_to_community,
    )


def _two_triangles_with_cross_edges() -> tuple[rustworkx.PyDiGraph, CommunitiesResult]:
    """Two 3-node triangles (community A: a1,a2,a3 — community B:
    b1,b2,b3), joined by two directed cross-edges: a1→b1 and b2→a2.

    Hand-computed expectations:
      - directed A→B count = 1 (a1→b1), B→A count = 1 (b2→a2)
      - incident(A) = 3 internal + 1 (a1→b1) + 1 (b2→a2) = 5
      - incident(B) = 3 internal + 1 (a1→b1) + 1 (b2→a2) = 5
      - cross_total = 2; union incident = incident(A) + incident(B)
        - cross_total = 5 + 5 - 2 = 8 (each A-B edge counted once,
        not once per side)
      - coupling_ratio = cross_total(2) / union_incident(8) = 0.25
    """
    g = rustworkx.PyDiGraph()
    idxs: dict[str, int] = {}
    for nid in ["a1", "a2", "a3", "b1", "b2", "b3"]:
        idxs[nid] = _add(g, nid)

    for cluster in (["a1", "a2", "a3"], ["b1", "b2", "b3"]):
        for i in range(3):
            for j in range(i + 1, 3):
                g.add_edge(idxs[cluster[i]], idxs[cluster[j]], {"kind": "references"})

    g.add_edge(idxs["a1"], idxs["b1"], {"kind": "references"})
    g.add_edge(idxs["b2"], idxs["a2"], {"kind": "references"})

    comm_a = _community("cid_a", ["a1", "a2", "a3"], label="A")
    comm_b = _community("cid_b", ["b1", "b2", "b3"], label="B")
    return g, _communities_result(comm_a, comm_b)


def _two_disjoint_triangles() -> tuple[rustworkx.PyDiGraph, CommunitiesResult]:
    """Two 3-node triangles with NO edges between them."""
    g = rustworkx.PyDiGraph()
    idxs: dict[str, int] = {}
    for nid in ["a1", "a2", "a3", "b1", "b2", "b3"]:
        idxs[nid] = _add(g, nid)
    for cluster in (["a1", "a2", "a3"], ["b1", "b2", "b3"]):
        for i in range(3):
            for j in range(i + 1, 3):
                g.add_edge(idxs[cluster[i]], idxs[cluster[j]], {"kind": "references"})
    comm_a = _community("cid_a", ["a1", "a2", "a3"])
    comm_b = _community("cid_b", ["b1", "b2", "b3"])
    return g, _communities_result(comm_a, comm_b)


def _three_communities_one_connected_pair() -> tuple[rustworkx.PyDiGraph, CommunitiesResult]:
    """3 singleton-ish communities (2 nodes each); only community A and
    B share an edge. C(3,2) = 3 possible pairs, 1 connected → density
    should be 1/3."""
    g = rustworkx.PyDiGraph()
    idxs: dict[str, int] = {}
    for nid in ["a1", "a2", "b1", "b2", "c1", "c2"]:
        idxs[nid] = _add(g, nid)
    for cluster in (["a1", "a2"], ["b1", "b2"], ["c1", "c2"]):
        g.add_edge(idxs[cluster[0]], idxs[cluster[1]], {"kind": "references"})
    # Single cross edge between A and B only.
    g.add_edge(idxs["a1"], idxs["b1"], {"kind": "references"})

    comm_a = _community("cid_a", ["a1", "a2"])
    comm_b = _community("cid_b", ["b1", "b2"])
    comm_c = _community("cid_c", ["c1", "c2"])
    return g, _communities_result(comm_a, comm_b, comm_c)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPydanticModels:
    def test_relation_frozen(self):
        rel = InterCommunityRelation(
            source_community_id="a", target_community_id="b",
            source_label="A", target_label="B",
            directed_edge_count=1, reverse_edge_count=0,
            total_weight=1.0, reverse_weight=0.0, coupling_ratio=0.5,
        )
        with pytest.raises(Exception, match="frozen|immutable"):
            rel.coupling_ratio = 0.9

    def test_graph_frozen(self):
        graph = InterCommunityGraph(
            relations=[], community_count=0, connected_pairs=0,
            total_possible_pairs=0, density=0.0,
        )
        with pytest.raises(Exception, match="frozen|immutable"):
            graph.density = 1.0


class TestInterCommunityGraph:
    def test_basic_relation(self):
        """Two communities with cross-edges produce exactly one relation."""
        graph, communities = _two_triangles_with_cross_edges()
        result = compute_inter_community_graph(graph, communities)
        assert isinstance(result, InterCommunityGraph)
        assert len(result.relations) == 1
        assert result.community_count == 2
        assert result.connected_pairs == 1
        assert result.total_possible_pairs == 1

    def test_directed_counts_distinguish_direction(self):
        """A→B and B→A are tracked separately."""
        graph, communities = _two_triangles_with_cross_edges()
        result = compute_inter_community_graph(graph, communities)
        rel = result.relations[0]
        assert {rel.source_community_id, rel.target_community_id} == {"cid_a", "cid_b"}
        if rel.source_community_id == "cid_a":
            assert rel.directed_edge_count == 1  # a1 -> b1
            assert rel.reverse_edge_count == 1   # b2 -> a2
        else:
            assert rel.directed_edge_count == 1
            assert rel.reverse_edge_count == 1

    def test_labels_populated_from_communities(self):
        graph, communities = _two_triangles_with_cross_edges()
        result = compute_inter_community_graph(graph, communities)
        rel = result.relations[0]
        assert {rel.source_label, rel.target_label} == {"A", "B"}

    def test_coupling_ratio_known_topology(self):
        """Hand-computed: cross_total=2, union_incident=8 → 0.25 (each
        A-B edge counted once in the union, not once per side)."""
        graph, communities = _two_triangles_with_cross_edges()
        result = compute_inter_community_graph(graph, communities)
        rel = result.relations[0]
        assert rel.coupling_ratio == pytest.approx(0.25)

    def test_coupling_ratio_never_exceeds_one(self):
        """coupling_ratio is a proper [0, 1] ratio — reaches (but never
        exceeds) 1.0 when every edge touching either community is one
        of the A-B cross edges (no internal edges, no third-community
        edges)."""
        g = rustworkx.PyDiGraph()
        idxs = {nid: _add(g, nid) for nid in ["a1", "b1"]}
        g.add_edge(idxs["a1"], idxs["b1"], {"kind": "references"})
        comm_a = _community("cid_a", ["a1"])
        comm_b = _community("cid_b", ["b1"])
        result = compute_inter_community_graph(g, _communities_result(comm_a, comm_b))
        rel = result.relations[0]
        assert rel.coupling_ratio == pytest.approx(1.0)

    def test_weights_default_to_one_per_edge(self):
        graph, communities = _two_triangles_with_cross_edges()
        result = compute_inter_community_graph(graph, communities)
        rel = result.relations[0]
        assert rel.total_weight == pytest.approx(1.0)
        assert rel.reverse_weight == pytest.approx(1.0)

    def test_weighted_edges_summed(self):
        g = rustworkx.PyDiGraph()
        idxs = {nid: _add(g, nid) for nid in ["a1", "a2", "b1", "b2"]}
        g.add_edge(idxs["a1"], idxs["a2"], {"kind": "references", "weight": 1.0})
        g.add_edge(idxs["b1"], idxs["b2"], {"kind": "references", "weight": 1.0})
        g.add_edge(idxs["a1"], idxs["b1"], {"kind": "references", "weight": 2.5})
        g.add_edge(idxs["a2"], idxs["b2"], {"kind": "references", "weight": 0.5})
        comm_a = _community("cid_a", ["a1", "a2"])
        comm_b = _community("cid_b", ["b1", "b2"])
        result = compute_inter_community_graph(g, _communities_result(comm_a, comm_b))
        rel = result.relations[0]
        assert rel.total_weight == pytest.approx(3.0)
        assert rel.reverse_weight == pytest.approx(0.0)

    def test_isolated_communities_no_relations(self):
        """Communities with no cross-edges produce no relations and
        zero density."""
        graph, communities = _two_disjoint_triangles()
        result = compute_inter_community_graph(graph, communities)
        assert result.relations == []
        assert result.connected_pairs == 0
        assert result.community_count == 2
        assert result.total_possible_pairs == 1
        assert result.density == 0.0

    def test_density_one_third(self):
        """3 communities, only 1 of the 3 possible pairs connected."""
        graph, communities = _three_communities_one_connected_pair()
        result = compute_inter_community_graph(graph, communities)
        assert result.community_count == 3
        assert result.total_possible_pairs == 3
        assert result.connected_pairs == 1
        assert result.density == pytest.approx(1 / 3)

    def test_single_community_zero_density(self):
        g = rustworkx.PyDiGraph()
        idxs = {nid: _add(g, nid) for nid in ["a1", "a2"]}
        g.add_edge(idxs["a1"], idxs["a2"], {"kind": "references"})
        comm_a = _community("cid_a", ["a1", "a2"])
        result = compute_inter_community_graph(g, _communities_result(comm_a))
        assert result.community_count == 1
        assert result.total_possible_pairs == 0
        assert result.density == 0.0

    def test_empty_graph_no_communities(self):
        g = rustworkx.PyDiGraph()
        result = compute_inter_community_graph(
            g, CommunitiesResult(
                modularity=0.0, resolution=1.0, seed=42, weighted=False,
                communities=[], node_to_community={},
            ),
        )
        assert result.relations == []
        assert result.community_count == 0
        assert result.density == 0.0

    def test_relations_sorted_deterministically(self):
        """Relation pair ordering is deterministic across runs."""
        graph, communities = _two_triangles_with_cross_edges()
        r1 = compute_inter_community_graph(graph, communities)
        r2 = compute_inter_community_graph(graph, communities)
        assert [
            (r.source_community_id, r.target_community_id) for r in r1.relations
        ] == [
            (r.source_community_id, r.target_community_id) for r in r2.relations
        ]

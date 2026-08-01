"""Inter-community relations for GraphIndex (FEAT-401).

Models the meta-graph of relationships *between* the communities detected
by :func:`parrot.knowledge.graphindex.communities.detect_communities`
(Leiden or Louvain, FEAT-191/FEAT-401): which community pairs are
connected, how tightly coupled they are (coupling ratio), and in which
direction information flows between them (directed edge counts +
weights).

The meta-graph is computed in-memory from the assembled
``rustworkx.PyDiGraph`` + the ``CommunitiesResult`` partition — it is
not persisted separately; callers render it into reports/exports
(FEAT-401 Modules 3-4) or query it on demand via the CLI (Module 5).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import rustworkx
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from parrot.knowledge.graphindex.communities import CommunitiesResult


class InterCommunityRelation(BaseModel):
    """A directed relationship between two communities.

    ``source_community_id`` / ``target_community_id`` are the pair in
    deterministic (lexicographically sorted) order; the directed counts
    and weights distinguish traffic in each direction between them.

    Args:
        source_community_id: The lexicographically smaller
            ``community_id`` of the pair.
        target_community_id: The lexicographically larger
            ``community_id`` of the pair.
        source_label: ``Community.label`` for the source community.
        target_label: ``Community.label`` for the target community.
        directed_edge_count: Number of graph edges from source →
            target.
        reverse_edge_count: Number of graph edges from target →
            source.
        total_weight: Sum of edge weights for source → target edges
            (defaults to 1.0 per edge when the graph carries no
            ``"weight"`` payload).
        reverse_weight: Sum of edge weights for target → source edges.
        coupling_ratio: Cross-edges between this pair (both directions)
            divided by the union of all edges incident to either
            community (internal + cross to any other community; each
            A-B edge is counted once, not once per side), in
            ``[0, 1]``. Reaches ``1.0`` only when every edge touching
            either community is one of the A-B cross edges (no
            internal edges, no cross-edges to any third community).
    """

    source_community_id: str
    target_community_id: str
    source_label: str
    target_label: str
    directed_edge_count: int
    reverse_edge_count: int
    total_weight: float
    reverse_weight: float
    coupling_ratio: float

    model_config = ConfigDict(frozen=True)


class InterCommunityGraph(BaseModel):
    """Meta-graph of community-to-community relationships.

    Args:
        relations: One :class:`InterCommunityRelation` per community
            pair with at least one cross-community edge. Pairs with
            zero edges between them are omitted entirely.
        community_count: Total number of communities in the partition.
        connected_pairs: Number of community pairs with >= 1 edge
            between them (``len(relations)``).
        total_possible_pairs: ``C(community_count, 2)``.
        density: ``connected_pairs / total_possible_pairs``. ``0.0``
            when there are fewer than 2 communities.
    """

    relations: list[InterCommunityRelation]
    community_count: int
    connected_pairs: int
    total_possible_pairs: int
    density: float

    model_config = ConfigDict(frozen=True)


def compute_inter_community_graph(
    graph: rustworkx.PyDiGraph,
    communities_result: CommunitiesResult,
) -> InterCommunityGraph:
    """Compute the inter-community meta-graph for a partition.

    Iterates every edge in ``graph``; edges whose endpoints fall in
    different communities are accumulated per (source_community,
    target_community) pair — directed counts and weights are kept
    separate per direction so callers can see asymmetric information
    flow. Edges whose endpoints share a community are internal and only
    contribute to that community's incident-edge total (used for the
    coupling ratio denominator).

    Args:
        graph: The assembled PyDiGraph the partition was computed over.
        communities_result: A :class:`CommunitiesResult` from
            :func:`parrot.knowledge.graphindex.communities.detect_communities`
            (Leiden or Louvain — the algorithm that produced it is
            irrelevant here, only the partition matters).

    Returns:
        :class:`InterCommunityGraph` with one relation per connected
        community pair, plus summary density statistics.
    """
    node_to_community = communities_result.node_to_community
    label_by_community = {
        c.community_id: c.label for c in communities_result.communities
    }
    community_ids = sorted(label_by_community)

    idx_to_node_id: dict[int, str] = {}
    for idx in graph.node_indices():
        payload = graph[idx]
        if isinstance(payload, dict) and payload.get("node_id"):
            idx_to_node_id[idx] = payload["node_id"]

    # directed_count/-weight keyed by (src_community_id, tgt_community_id)
    # for CROSS-community edges only (src_cid != tgt_cid).
    directed_count: dict[tuple[str, str], int] = {}
    directed_weight: dict[tuple[str, str], float] = {}
    # incident_edges[cid]: count of edges touching cid — internal edges
    # contribute once to their own community; a cross edge contributes
    # once to EACH of the two communities it touches.
    incident_edges: dict[str, int] = dict.fromkeys(community_ids, 0)

    for src_idx, tgt_idx, payload in graph.edge_index_map().values():
        src_node = idx_to_node_id.get(src_idx)
        tgt_node = idx_to_node_id.get(tgt_idx)
        if not src_node or not tgt_node:
            continue
        src_cid = node_to_community.get(src_node)
        tgt_cid = node_to_community.get(tgt_node)
        if src_cid is None or tgt_cid is None:
            continue

        weight = 1.0
        if isinstance(payload, dict):
            weight = float(payload.get("weight", 1.0))

        if src_cid == tgt_cid:
            incident_edges[src_cid] = incident_edges.get(src_cid, 0) + 1
            continue

        key = (src_cid, tgt_cid)
        directed_count[key] = directed_count.get(key, 0) + 1
        directed_weight[key] = directed_weight.get(key, 0.0) + weight
        incident_edges[src_cid] = incident_edges.get(src_cid, 0) + 1
        incident_edges[tgt_cid] = incident_edges.get(tgt_cid, 0) + 1

    # Collapse directed keys into unordered (lexicographically sorted) pairs.
    pairs: set[tuple[str, str]] = set()
    for a, b in directed_count:
        pairs.add((a, b) if a < b else (b, a))

    relations: list[InterCommunityRelation] = []
    for a, b in sorted(pairs):
        fwd_count = directed_count.get((a, b), 0)
        rev_count = directed_count.get((b, a), 0)
        fwd_weight = directed_weight.get((a, b), 0.0)
        rev_weight = directed_weight.get((b, a), 0.0)
        cross_total = fwd_count + rev_count
        # incident_edges[a] + incident_edges[b] double-counts every A-B
        # cross edge (once from each side) — subtract cross_total once to
        # get the true union of edges incident to either community, so
        # coupling_ratio is a proper [0, 1] ratio (1.0 only when every
        # edge touching A or B is one of the A-B cross edges).
        incident_total = (
            incident_edges.get(a, 0) + incident_edges.get(b, 0) - cross_total
        )
        coupling_ratio = (
            cross_total / incident_total if incident_total > 0 else 0.0
        )
        relations.append(InterCommunityRelation(
            source_community_id=a,
            target_community_id=b,
            source_label=label_by_community.get(a, ""),
            target_label=label_by_community.get(b, ""),
            directed_edge_count=fwd_count,
            reverse_edge_count=rev_count,
            total_weight=fwd_weight,
            reverse_weight=rev_weight,
            coupling_ratio=coupling_ratio,
        ))

    community_count = len(community_ids)
    connected_pairs = len(relations)
    total_possible_pairs = community_count * (community_count - 1) // 2
    density = (
        connected_pairs / total_possible_pairs if total_possible_pairs > 0 else 0.0
    )

    return InterCommunityGraph(
        relations=relations,
        community_count=community_count,
        connected_pairs=connected_pairs,
        total_possible_pairs=total_possible_pairs,
        density=density,
    )

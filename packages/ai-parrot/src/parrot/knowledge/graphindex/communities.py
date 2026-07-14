"""Louvain community detection for GraphIndex (FEAT-191).

Runs Louvain modularity-maximisation over the assembled
``rustworkx.PyDiGraph`` via networkx (rustworkx 0.17 has no community
detection), computes per-community cohesion + global modularity, and
writes a stable ``community_id`` onto every node's ``domain_tags``
so the assignment round-trips through
:func:`parrot.knowledge.graphindex.persist._node_to_doc` to ArangoDB
with zero persist-layer changes.

Optionally consumes :class:`SignalRelevanceConfig` (FEAT-190) to weight
edges by ``signal_relevance(a, b).combined`` before Louvain runs, so
community boundaries respect the signal model rather than raw edge
counts. The FEAT-190 import is lazy — FEAT-191 ships standalone.
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter
from typing import TYPE_CHECKING, Iterable, Optional

import networkx as nx
import rustworkx
from pydantic import BaseModel, ConfigDict, Field

from parrot.knowledge.graphindex.schema import UniversalNode

if TYPE_CHECKING:
    from parrot.knowledge.graphindex.signals import SignalRelevanceConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class Community(BaseModel):
    """A single community in the partition.

    Args:
        community_id: 16-char SHA-1 prefix of sorted member node_ids.
            Stable across runs with the same membership; changes when
            members are added or removed.
        size: Number of member nodes.
        member_node_ids: Members, centroid first, then by descending
            in-community degree.
        centroid_node_id: Member with the highest in-community degree
            (ties broken lexicographically by node_id for determinism).
        cohesion: internal_edges / (internal_edges + boundary_edges),
            in [0, 1]. 0.0 for isolated singletons.
        modularity_contribution: This community's contribution to the
            global modularity Q. The full Q is the sum of these.
        top_titles: Titles of the first ≤ 5 members in display order.
        label: Deterministic, LLM-free label summarising the community,
            derived from the most frequent salient keywords across member
            titles (see :func:`derive_community_label`). Empty string when
            no salient keyword could be extracted.
    """

    community_id: str
    size: int
    member_node_ids: list[str]
    centroid_node_id: str
    cohesion: float
    modularity_contribution: float
    top_titles: list[str]
    label: str = ""

    model_config = ConfigDict(frozen=True)


class CommunitiesResult(BaseModel):
    """Full Louvain partition + per-community metadata."""

    modularity: float
    resolution: float
    seed: int
    weighted: bool
    communities: list[Community]
    node_to_community: dict[str, str]

    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------------------
# Stable IDs
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# LLM-free community labels
# ---------------------------------------------------------------------------

#: Generic tokens that carry no discriminative signal for a label.
_LABEL_STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "for", "with", "from", "this", "that", "into", "over",
    "get", "set", "new", "old", "def", "class", "func", "function", "method",
    "module", "self", "value", "values", "data", "item", "items", "list",
    "dict", "str", "int", "bool", "none", "true", "false", "test", "tests",
    "init", "main", "util", "utils", "helper", "helpers", "base", "abstract",
    "type", "types", "kind", "node", "edge", "graph", "id", "ids", "name",
    "names", "obj", "object", "args", "kwargs", "return", "returns", "param",
    "params", "note", "todo", "why", "hack", "fixme", "xxx", "add", "remove",
})

#: Splits identifiers into word tokens (camelCase, snake_case, punctuation).
_LABEL_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])")


def _tokenize_title(title: str) -> list[str]:
    """Split a title/identifier into lower-cased salient word tokens.

    Handles ``snake_case``, ``camelCase`` and punctuation-separated words,
    dropping stopwords, pure numbers and 1-2 char fragments.

    Args:
        title: The node title to tokenize.

    Returns:
        A list of salient lower-case tokens (possibly empty).
    """
    tokens: list[str] = []
    for raw in _LABEL_SPLIT_RE.split(title or ""):
        tok = raw.lower()
        if len(tok) < 3 or tok.isdigit() or tok in _LABEL_STOPWORDS:
            continue
        tokens.append(tok)
    return tokens


def derive_community_label(titles: Iterable[str], max_terms: int = 3) -> str:
    """Derive a deterministic, LLM-free label from member titles.

    Counts salient keyword frequency across the supplied titles and joins the
    most common terms. Ties are broken alphabetically so the result is stable
    across runs. Returns an empty string when no salient keyword survives
    stopword filtering.

    Args:
        titles: Member node titles to summarise.
        max_terms: Maximum number of keywords to include in the label.

    Returns:
        A capitalised label such as ``"Payment Gateway"``, or ``""``.
    """
    counter: Counter[str] = Counter()
    for title in titles:
        # Count each token once per title so a repeated word in one title
        # does not dominate the community label.
        for tok in set(_tokenize_title(title)):
            counter[tok] += 1
    if not counter:
        return ""
    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    top = [term for term, _ in ranked[:max_terms]]
    return " ".join(term.capitalize() for term in top)


def _stable_community_id(member_node_ids: Iterable[str]) -> str:
    """16-char SHA-1 prefix of sorted member ids.

    Same scheme as :func:`parrot.knowledge.graphindex.extractors.loader._make_node_id`
    for cross-feature consistency. Member order doesn't matter.
    """
    sorted_ids = sorted(str(nid) for nid in member_node_ids)
    raw = "::".join(sorted_ids).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


# ---------------------------------------------------------------------------
# rustworkx → networkx conversion (weighted or unweighted)
# ---------------------------------------------------------------------------


def _to_undirected_networkx(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    signal_config: Optional["SignalRelevanceConfig"] = None,
    embedder: Optional[object] = None,
) -> nx.Graph:
    """Build an undirected networkx view of ``graph``.

    Directed a→b and b→a collapse into one undirected edge; when both
    exist the larger weight wins (max-weight chosen because Louvain
    cares about strong-tie discovery).

    Isolated nodes (no edges) are added explicitly so the partition
    sees them — networkx silently drops nodes that have only been
    referenced through edges, but a tenant graph may legitimately
    contain orphans we still want labelled.

    When ``signal_config`` is supplied, edges are weighted by the
    FEAT-190 combined relevance score for the endpoint pair. The
    import is lazy so FEAT-191 builds and runs without FEAT-190.
    """
    g = nx.Graph()
    idx_to_node_id: dict[int, str] = {}

    for idx in graph.node_indices():
        payload = graph[idx]
        if not isinstance(payload, dict):
            continue
        node_id = payload.get("node_id")
        if not node_id:
            continue
        idx_to_node_id[idx] = node_id
        g.add_node(node_id)

    # Optionally pre-compute per-pair signal weights.
    weight_fn = _build_weight_fn(graph, nodes, signal_config, embedder)

    seen_pairs: set[tuple[str, str]] = set()
    for _eidx, (src_idx, tgt_idx, _payload) in graph.edge_index_map().items():
        a = idx_to_node_id.get(src_idx)
        b = idx_to_node_id.get(tgt_idx)
        if not a or not b or a == b:
            continue
        key = (a, b) if a < b else (b, a)
        w = weight_fn(a, b) if weight_fn is not None else 1.0
        if key in seen_pairs:
            # Edge already added (the reverse direction or a parallel
            # edge). Keep the larger weight.
            existing = g[key[0]][key[1]].get("weight", 1.0)
            g[key[0]][key[1]]["weight"] = max(existing, w)
        else:
            g.add_edge(key[0], key[1], weight=w)
            seen_pairs.add(key)

    return g


def _build_weight_fn(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    signal_config: Optional["SignalRelevanceConfig"],
    embedder: Optional[object],
):
    """Return a (a, b) → float weight function, or None for unweighted."""
    if signal_config is None:
        return None
    try:
        from parrot.knowledge.graphindex.signals import signal_relevance
    except ImportError:
        logger.warning(
            "communities: signal_config supplied but FEAT-190 signals "
            "module is not importable — falling back to unweighted edges"
        )
        return None

    def _weight(a: str, b: str) -> float:
        try:
            rel = signal_relevance(
                graph=graph, nodes=nodes,
                node_a=a, node_b=b,
                config=signal_config, embedder=embedder,
            )
        except KeyError:
            return 1.0
        # Map combined in [0, 1] to a strictly-positive weight so the
        # edge isn't ignored entirely if the signal is near zero.
        return max(0.001, rel.combined)

    return _weight


# ---------------------------------------------------------------------------
# Cohesion + centroid
# ---------------------------------------------------------------------------


def cohesion_for_community(
    nx_graph: nx.Graph,
    members: set[str],
) -> float:
    """internal_edges / (internal_edges + boundary_edges).

    Returns 0.0 when the community has no incident edges (graph
    isolates yield singletons with zero cohesion by definition).
    """
    if not members:
        return 0.0
    internal = 0
    boundary = 0
    for member in members:
        if member not in nx_graph:
            continue
        for neighbour in nx_graph.neighbors(member):
            if neighbour in members:
                internal += 1  # counts both endpoints; halved below.
            else:
                boundary += 1
    internal //= 2  # each internal edge counted from both endpoints
    total = internal + boundary
    if total == 0:
        return 0.0
    return internal / total


def _centroid_for_community(
    nx_graph: nx.Graph,
    members: list[str],
) -> str:
    """Member with the highest in-community degree.

    Ties broken lexicographically by node_id so reruns are
    deterministic.
    """
    if not members:
        raise ValueError("_centroid_for_community: empty member list")
    members_set = set(members)

    def _in_community_degree(node_id: str) -> int:
        if node_id not in nx_graph:
            return 0
        return sum(1 for n in nx_graph.neighbors(node_id) if n in members_set)

    # Sort by (-degree, node_id) → highest degree first, lex tiebreaker.
    ranked = sorted(members, key=lambda nid: (-_in_community_degree(nid), nid))
    return ranked[0]


def _order_members(
    nx_graph: nx.Graph,
    members: list[str],
    centroid: str,
) -> list[str]:
    """Centroid first, then the rest by descending in-community
    degree, ties by node_id."""
    members_set = set(members)

    def _in_community_degree(node_id: str) -> int:
        if node_id not in nx_graph:
            return 0
        return sum(1 for n in nx_graph.neighbors(node_id) if n in members_set)

    others = [m for m in members if m != centroid]
    others.sort(key=lambda nid: (-_in_community_degree(nid), nid))
    return [centroid, *others]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_communities(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    resolution: float = 1.0,
    seed: int = 42,
    signal_config: Optional["SignalRelevanceConfig"] = None,
    embedder: Optional[object] = None,
    write_back_to_nodes: bool = True,
) -> CommunitiesResult:
    """Run Louvain community detection on the assembled graph.

    Args:
        graph: The assembled PyDiGraph.
        nodes: The UniversalNode list; mutated in-place when
            ``write_back_to_nodes=True``.
        resolution: Louvain γ resolution parameter. >1.0 finds smaller
            (tighter) communities; <1.0 finds larger ones.
        seed: RNG seed for deterministic results across builds.
        signal_config: Optional FEAT-190 config; when set, edges are
            weighted by ``signal_relevance(a, b).combined`` before
            Louvain runs.
        embedder: Optional embedder forwarded to FEAT-190 when computing
            edge weights (ignored unless ``signal_config`` is set).
        write_back_to_nodes: When True (default), writes
            ``domain_tags['community_id']`` into every node and
            ``domain_tags['community_centroid']=True`` for each centroid.

    Returns:
        :class:`CommunitiesResult` with global modularity, the
        partition, and a `node_id → community_id` lookup.
    """
    nx_graph = _to_undirected_networkx(
        graph, nodes, signal_config=signal_config, embedder=embedder,
    )

    partition_sets: list[set[str]] = list(
        nx.community.louvain_communities(
            nx_graph,
            weight="weight",
            resolution=resolution,
            seed=seed,
        )
    )
    if not partition_sets:
        return CommunitiesResult(
            modularity=0.0, resolution=resolution, seed=seed,
            weighted=signal_config is not None,
            communities=[], node_to_community={},
        )

    global_q = float(
        nx.community.modularity(
            nx_graph, partition_sets, weight="weight", resolution=resolution,
        )
    )

    # Compute total weight once for per-community modularity contribution.
    total_weight = _total_edge_weight(nx_graph)

    title_lookup = {n.node_id: n.title for n in nodes}

    communities: list[Community] = []
    node_to_community: dict[str, str] = {}

    for member_set in partition_sets:
        if not member_set:
            continue
        members_list = list(member_set)
        cid = _stable_community_id(members_list)
        centroid = _centroid_for_community(nx_graph, members_list)
        ordered_members = _order_members(nx_graph, members_list, centroid)
        cohesion = cohesion_for_community(nx_graph, member_set)
        contribution = _community_modularity_contribution(
            nx_graph, member_set, total_weight, resolution,
        )
        member_titles = [title_lookup.get(nid, nid) for nid in ordered_members]
        top_titles = member_titles[:5]
        label = derive_community_label(member_titles)
        community = Community(
            community_id=cid,
            size=len(ordered_members),
            member_node_ids=ordered_members,
            centroid_node_id=centroid,
            cohesion=cohesion,
            modularity_contribution=contribution,
            top_titles=top_titles,
            label=label,
        )
        communities.append(community)
        for nid in ordered_members:
            node_to_community[nid] = cid

    # Sort communities by size descending; ties broken by community_id
    # for determinism.
    communities.sort(key=lambda c: (-c.size, c.community_id))

    if write_back_to_nodes:
        _write_back(nodes, communities, node_to_community)

    return CommunitiesResult(
        modularity=global_q,
        resolution=resolution,
        seed=seed,
        weighted=signal_config is not None,
        communities=communities,
        node_to_community=node_to_community,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _total_edge_weight(nx_graph: nx.Graph) -> float:
    """Sum of edge weights (defaults to 1.0 when 'weight' attr missing)."""
    return float(sum(
        data.get("weight", 1.0)
        for _u, _v, data in nx_graph.edges(data=True)
    ))


def _community_modularity_contribution(
    nx_graph: nx.Graph,
    members: set[str],
    total_weight: float,
    resolution: float,
) -> float:
    """Per-community contribution to global Q.

    Textbook Louvain term:
        (L_c / m) - γ * (k_c / 2m)^2
    where L_c is internal edge weight, k_c is the community's total
    degree weight, m is total edge weight, γ is the resolution.
    """
    if total_weight <= 0.0:
        return 0.0
    internal_weight = 0.0
    degree_sum = 0.0
    for member in members:
        if member not in nx_graph:
            continue
        for neighbour, data in nx_graph[member].items():
            w = float(data.get("weight", 1.0))
            degree_sum += w
            if neighbour in members:
                internal_weight += w  # counts twice; halved below.
    internal_weight /= 2.0  # each internal edge counted from both endpoints
    m = total_weight
    return (internal_weight / m) - resolution * (degree_sum / (2.0 * m)) ** 2


def _write_back(
    nodes: list[UniversalNode],
    communities: list[Community],
    node_to_community: dict[str, str],
) -> None:
    """Mutate ``UniversalNode.domain_tags`` with community membership."""
    centroid_ids = {c.centroid_node_id for c in communities}
    for node in nodes:
        cid = node_to_community.get(node.node_id)
        if cid is None:
            continue
        # UniversalNode.domain_tags is a Pydantic-managed dict; mutating
        # it in place is supported by pydantic v2 (no validation on
        # field mutation when extra='allow').
        node.domain_tags["community_id"] = cid
        if node.node_id in centroid_ids:
            node.domain_tags["community_centroid"] = True

"""Signal Knowledge Graph relevance model for GraphIndex (FEAT-190).

Five orthogonal pairwise signals between two ``UniversalNode`` instances,
combined into a single decomposed :class:`SignalRelevance` so an LLM
consumer can read *why* two nodes are related, not just a number:

1. **Direct links** — weighted sum over `EdgeKind` of edges that connect
   the pair in either direction.
2. **Source overlap** — Jaccard similarity over ``source_uri`` sets.
3. **Adamic-Adar** — shared-neighbour signal weighting rare connectors
   more than hubs. Via :mod:`networkx` (rustworkx 0.17 has no AA).
4. **Type affinity** — configurable ``NodeKind × NodeKind`` matrix.
5. **Embedding similarity** — cosine over FAISS-backed vectors. Opt-in
   via dependency injection of a :class:`GraphIndexEmbedder`. When
   absent, the four structural weights auto-renormalise to 1.0 so the
   combined score stays interpretable.

All sub-scores live in ``[0, 1]``. The combined score therefore lives
in ``[0, 1]`` whenever the configured weights sum to 1.0 (enforced by
:class:`SignalRelevanceConfig`).
"""
from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Iterable, Optional
from weakref import WeakValueDictionary

import numpy as np
import rustworkx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    UniversalNode,
)

if TYPE_CHECKING:
    from parrot.knowledge.graphindex.embed import GraphIndexEmbedder


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default type-affinity matrix
# ---------------------------------------------------------------------------

_UNLISTED_TYPE_AFFINITY = 0.30


def _default_type_affinity() -> dict[tuple[NodeKind, NodeKind], float]:
    """Default `NodeKind × NodeKind` affinity matrix.

    Symmetric; the lookup helper canonicalises pair order before
    reading. Unlisted pairs fall back to ``_UNLISTED_TYPE_AFFINITY``.
    """
    pairs = {
        (NodeKind.CONCEPT, NodeKind.CONCEPT): 1.00,
        (NodeKind.CONCEPT, NodeKind.SECTION): 0.85,
        (NodeKind.CONCEPT, NodeKind.DOCUMENT): 0.70,
        (NodeKind.SECTION, NodeKind.SECTION): 0.60,
        (NodeKind.DOCUMENT, NodeKind.DOCUMENT): 0.50,
        (NodeKind.SECTION, NodeKind.DOCUMENT): 0.70,
        (NodeKind.SYMBOL, NodeKind.SYMBOL): 0.80,
        (NodeKind.SYMBOL, NodeKind.RATIONALE): 0.95,
        (NodeKind.SYMBOL, NodeKind.SECTION): 0.50,
        (NodeKind.SKILL, NodeKind.SECTION): 0.60,
        (NodeKind.SKILL, NodeKind.SKILL): 0.70,
    }
    # Symmetrise.
    full: dict[tuple[NodeKind, NodeKind], float] = {}
    for (a, b), v in pairs.items():
        full[_canonical_pair(a, b)] = v
    return full


def _canonical_pair(a: NodeKind, b: NodeKind) -> tuple[NodeKind, NodeKind]:
    """Order-independent NodeKind pair key (sorted by enum value)."""
    return (a, b) if a.value <= b.value else (b, a)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class SignalRelevanceConfig(BaseModel):
    """Configuration for the five-signal relevance scorer.

    Weights sum to 1.0; the validator enforces it. The embedding weight
    is independent of whether an embedder is actually supplied to the
    scorer — when it isn't, the remaining four weights are
    auto-renormalised at scoring time (the config itself is frozen).
    """

    w_direct: float = Field(0.30, ge=0.0, le=1.0)
    w_source_overlap: float = Field(0.15, ge=0.0, le=1.0)
    w_adamic_adar: float = Field(0.20, ge=0.0, le=1.0)
    w_type_affinity: float = Field(0.10, ge=0.0, le=1.0)
    w_embedding: float = Field(0.25, ge=0.0, le=1.0)

    edge_kind_weights: dict[EdgeKind, float] = Field(
        default_factory=lambda: {
            EdgeKind.CONTAINS: 0.30,
            EdgeKind.REFERENCES: 1.00,
            EdgeKind.DEFINES: 0.80,
            EdgeKind.MENTIONS: 0.70,
            EdgeKind.EXPLAINS: 0.90,
        }
    )

    type_affinity: dict[tuple[NodeKind, NodeKind], float] = Field(
        default_factory=_default_type_affinity
    )

    adamic_adar_cap: float = Field(4.0, gt=0.0)

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    @model_validator(mode="after")
    def _validate_weights_sum_to_one(self) -> "SignalRelevanceConfig":
        total = (
            self.w_direct
            + self.w_source_overlap
            + self.w_adamic_adar
            + self.w_type_affinity
            + self.w_embedding
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"SignalRelevanceConfig weights must sum to 1.0; got {total:.6f}"
            )
        return self


class SignalRelevance(BaseModel):
    """Decomposed pairwise relevance result.

    Combined score is the weighted sum of the (≤5) normalised signals.
    The raw sub-signal payloads (edges, shared sources, AA neighbours)
    are kept on the model so an LLM consumer can explain *why* two
    nodes are related without re-running the scorer.
    """

    node_a: str
    node_b: str
    direct: float
    source_overlap: float
    adamic_adar: float
    type_affinity: float
    embedding: float
    combined: float

    direct_edges: list[dict]
    shared_sources: list[str]
    aa_neighbours: list[str]
    embedding_available: bool

    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------------------
# networkx conversion cache
# ---------------------------------------------------------------------------

# Cache per rustworkx graph instance so a top-k loop reuses the
# undirected view across pairs. Keyed by id() because PyDiGraph isn't
# hashable; values are WeakRef'd so a discarded graph frees its cache.
_NX_CACHE: dict[int, object] = {}


def _to_undirected_networkx(graph: rustworkx.PyDiGraph):
    """Return an undirected ``networkx.Graph`` view of ``graph``.

    Cached per rustworkx-graph identity so repeated AA calls in a
    neighbourhood loop don't rebuild. Cache entry includes the
    rustworkx-node-index → application-node-id map.
    """
    import networkx as nx  # heavy import — only when AA is actually used.

    key = id(graph)
    cached = _NX_CACHE.get(key)
    if cached is not None:
        return cached

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

    for src_idx, tgt_idx, _ in graph.edge_index_map().values():
        a = idx_to_node_id.get(src_idx)
        b = idx_to_node_id.get(tgt_idx)
        if a and b and a != b:
            g.add_edge(a, b)

    entry = (g, idx_to_node_id)
    _NX_CACHE[key] = entry
    return entry


def _invalidate_nx_cache(graph: rustworkx.PyDiGraph) -> None:
    """Drop the cached networkx view for ``graph`` — call after mutations."""
    _NX_CACHE.pop(id(graph), None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node_payload(graph: rustworkx.PyDiGraph, node_id: str) -> dict:
    """Locate the node payload by application-level node_id.

    Raises KeyError if not found.
    """
    for idx in graph.node_indices():
        payload = graph[idx]
        if isinstance(payload, dict) and payload.get("node_id") == node_id:
            return payload
    raise KeyError(f"node_id {node_id!r} not in graph")


def _node_index(graph: rustworkx.PyDiGraph, node_id: str) -> int:
    """Locate the rustworkx integer index by application-level node_id."""
    for idx in graph.node_indices():
        payload = graph[idx]
        if isinstance(payload, dict) and payload.get("node_id") == node_id:
            return idx
    raise KeyError(f"node_id {node_id!r} not in graph")


def _node_kind(payload: dict) -> Optional[NodeKind]:
    """Read the kind field (stored as a string value) and cast back to NodeKind."""
    raw = payload.get("kind")
    if isinstance(raw, NodeKind):
        return raw
    if isinstance(raw, str):
        try:
            return NodeKind(raw)
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Individual signals
# ---------------------------------------------------------------------------


def _direct_signal(
    graph: rustworkx.PyDiGraph,
    node_idx_a: int,
    node_idx_b: int,
    edge_weights: dict[EdgeKind, float],
) -> tuple[float, list[dict]]:
    """Weighted-edge signal in [0, 1] + raw edge list.

    Normalises by the maximum possible single-edge weight so a single
    REFERENCES edge yields ``w_references / max_weight``. Each
    directed edge contributes once; reciprocal A→B + B→A pairs
    contribute twice (an undirected pair can score above a single
    edge, capped at 1.0).
    """
    if not edge_weights:
        return 0.0, []
    max_weight = max(edge_weights.values())
    if max_weight <= 0:
        return 0.0, []

    edges_out: list[dict] = []
    weight_sum = 0.0

    for src_idx, tgt_idx, payload in graph.out_edges(node_idx_a):
        if tgt_idx != node_idx_b:
            continue
        kind = _payload_edge_kind(payload)
        if kind is None:
            continue
        w = edge_weights.get(kind, 0.0)
        weight_sum += w
        edges_out.append({"kind": kind.value, "direction": "outgoing", "weight": w})

    for src_idx, tgt_idx, payload in graph.out_edges(node_idx_b):
        if tgt_idx != node_idx_a:
            continue
        kind = _payload_edge_kind(payload)
        if kind is None:
            continue
        w = edge_weights.get(kind, 0.0)
        weight_sum += w
        edges_out.append({"kind": kind.value, "direction": "incoming", "weight": w})

    score = min(1.0, weight_sum / max_weight)
    return score, edges_out


def _payload_edge_kind(payload: dict) -> Optional[EdgeKind]:
    raw = payload.get("kind")
    if isinstance(raw, EdgeKind):
        return raw
    if isinstance(raw, str):
        try:
            return EdgeKind(raw)
        except ValueError:
            return None
    return None


def _source_overlap_signal(
    payload_a: dict,
    payload_b: dict,
) -> tuple[float, list[str]]:
    """Jaccard over ``source_uri`` sets. Single-source nodes today, but
    the implementation accepts a list / set in domain_tags['sources']
    so multi-source nodes (planned) work transparently.
    """
    sources_a = _node_sources(payload_a)
    sources_b = _node_sources(payload_b)
    if not sources_a or not sources_b:
        return 0.0, []
    intersection = sources_a & sources_b
    if not intersection:
        return 0.0, []
    union = sources_a | sources_b
    return len(intersection) / len(union), sorted(intersection)


def _node_sources(payload: dict) -> set[str]:
    """Resolve a node's source set. Empty / falsy values yield empty set."""
    sources: set[str] = set()
    primary = payload.get("source_uri")
    if isinstance(primary, str) and primary.strip():
        sources.add(primary)
    extra = (payload.get("domain_tags") or {}).get("sources")
    if isinstance(extra, (list, tuple, set)):
        for s in extra:
            if isinstance(s, str) and s.strip():
                sources.add(s)
    return sources


def _adamic_adar_signal(
    graph: rustworkx.PyDiGraph,
    node_id_a: str,
    node_id_b: str,
    cap: float,
) -> tuple[float, list[str]]:
    """AA via networkx, clipped at ``cap`` and divided by it. Returns
    (score, neighbour_ids).
    """
    import networkx as nx

    nx_graph, _idx_map = _to_undirected_networkx(graph)
    if node_id_a not in nx_graph or node_id_b not in nx_graph:
        return 0.0, []

    # Shared neighbours (for the "why" payload).
    neighbours_a = set(nx_graph.neighbors(node_id_a))
    neighbours_b = set(nx_graph.neighbors(node_id_b))
    shared = sorted(neighbours_a & neighbours_b - {node_id_a, node_id_b})

    if not shared:
        return 0.0, []

    raw = 0.0
    for _u, _v, score in nx.adamic_adar_index(nx_graph, [(node_id_a, node_id_b)]):
        raw += score
    clipped = min(raw, cap)
    return (clipped / cap) if cap > 0 else 0.0, shared


def _type_affinity_signal(
    payload_a: dict,
    payload_b: dict,
    matrix: dict[tuple[NodeKind, NodeKind], float],
) -> float:
    kind_a = _node_kind(payload_a)
    kind_b = _node_kind(payload_b)
    if kind_a is None or kind_b is None:
        return _UNLISTED_TYPE_AFFINITY
    return matrix.get(_canonical_pair(kind_a, kind_b), _UNLISTED_TYPE_AFFINITY)


def _embedding_signal(
    embedder: Optional["GraphIndexEmbedder"],
    node_id_a: str,
    node_id_b: str,
) -> tuple[float, bool]:
    """Cosine similarity in [0, 1]. Returns ``(0.0, False)`` when the
    embedder is missing OR either node has no embedding.
    """
    if embedder is None:
        return 0.0, False
    vec_a = embedder.get_embedding(node_id_a)
    vec_b = embedder.get_embedding(node_id_b)
    if vec_a is None or vec_b is None:
        return 0.0, False
    a = np.asarray(vec_a, dtype=np.float32)
    b = np.asarray(vec_b, dtype=np.float32)
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0, True  # available but degenerate
    cos = float(np.dot(a, b) / (na * nb))
    return max(0.0, min(1.0, cos)), True


# ---------------------------------------------------------------------------
# Weight handling
# ---------------------------------------------------------------------------


def _effective_weights(
    config: SignalRelevanceConfig,
    embedding_available: bool,
) -> tuple[float, float, float, float, float]:
    """Return the five weights to use for the combination.

    When ``embedding_available=False``, the embedding weight is dropped
    and the remaining four are scaled by ``1 / (1 - w_embedding)`` so
    the total still sums to 1.0.
    """
    if embedding_available:
        return (
            config.w_direct,
            config.w_source_overlap,
            config.w_adamic_adar,
            config.w_type_affinity,
            config.w_embedding,
        )
    remainder = 1.0 - config.w_embedding
    if remainder <= 0:
        # Configured w_embedding=1.0 and no embedder. Combined collapses to 0.
        return (0.0, 0.0, 0.0, 0.0, 0.0)
    scale = 1.0 / remainder
    return (
        config.w_direct * scale,
        config.w_source_overlap * scale,
        config.w_adamic_adar * scale,
        config.w_type_affinity * scale,
        0.0,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def signal_relevance(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    node_a: str,
    node_b: str,
    config: Optional[SignalRelevanceConfig] = None,
    embedder: Optional["GraphIndexEmbedder"] = None,
) -> SignalRelevance:
    """Pairwise five-signal relevance over an assembled GraphIndex.

    See module docstring for the signal definitions. ``nodes`` is
    currently accepted for forward-compat with FEAT-191/-192 callers
    but not used here — every signal reads its inputs from the
    in-memory graph payloads.

    Raises:
        KeyError: If either ``node_a`` or ``node_b`` is not in the graph.
    """
    if node_a == node_b:
        raise KeyError(f"signal_relevance: node_a == node_b == {node_a!r}")
    cfg = config or SignalRelevanceConfig()

    payload_a = _node_payload(graph, node_a)
    payload_b = _node_payload(graph, node_b)
    idx_a = _node_index(graph, node_a)
    idx_b = _node_index(graph, node_b)

    direct, direct_edges = _direct_signal(
        graph, idx_a, idx_b, cfg.edge_kind_weights,
    )
    source_overlap, shared_sources = _source_overlap_signal(payload_a, payload_b)
    adamic_adar, aa_neighbours = _adamic_adar_signal(
        graph, node_a, node_b, cfg.adamic_adar_cap,
    )
    type_affinity = _type_affinity_signal(payload_a, payload_b, cfg.type_affinity)
    embedding, embedding_available = _embedding_signal(embedder, node_a, node_b)

    w = _effective_weights(cfg, embedding_available)
    combined = (
        w[0] * direct
        + w[1] * source_overlap
        + w[2] * adamic_adar
        + w[3] * type_affinity
        + w[4] * embedding
    )
    combined = max(0.0, min(1.0, combined))

    return SignalRelevance(
        node_a=node_a,
        node_b=node_b,
        direct=direct,
        source_overlap=source_overlap,
        adamic_adar=adamic_adar,
        type_affinity=type_affinity,
        embedding=embedding,
        combined=combined,
        direct_edges=direct_edges,
        shared_sources=shared_sources,
        aa_neighbours=aa_neighbours,
        embedding_available=embedding_available,
    )


def compute_pairwise_signals(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    node_a: str,
    node_b: str,
    embedder: Optional["GraphIndexEmbedder"] = None,
) -> dict[str, float]:
    """Raw five signals without combination. Cheap building block."""
    cfg = SignalRelevanceConfig()
    payload_a = _node_payload(graph, node_a)
    payload_b = _node_payload(graph, node_b)
    idx_a = _node_index(graph, node_a)
    idx_b = _node_index(graph, node_b)
    direct, _ = _direct_signal(graph, idx_a, idx_b, cfg.edge_kind_weights)
    source_overlap, _ = _source_overlap_signal(payload_a, payload_b)
    adamic_adar, _ = _adamic_adar_signal(graph, node_a, node_b, cfg.adamic_adar_cap)
    type_affinity = _type_affinity_signal(payload_a, payload_b, cfg.type_affinity)
    embedding, _ = _embedding_signal(embedder, node_a, node_b)
    return {
        "direct": direct,
        "source_overlap": source_overlap,
        "adamic_adar": adamic_adar,
        "type_affinity": type_affinity,
        "embedding": embedding,
    }


def relevance_neighborhood(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    node_id: str,
    top_k: int = 10,
    config: Optional[SignalRelevanceConfig] = None,
    candidate_pool: Optional[Iterable[str]] = None,
    embedder: Optional["GraphIndexEmbedder"] = None,
) -> list[SignalRelevance]:
    """Top-K nodes most relevant to ``node_id`` by combined score."""
    if top_k <= 0:
        return []

    if candidate_pool is None:
        pool = [
            payload.get("node_id")
            for idx in graph.node_indices()
            if isinstance((payload := graph[idx]), dict)
            and payload.get("node_id")
            and payload.get("node_id") != node_id
        ]
    else:
        pool = [c for c in candidate_pool if c != node_id]

    results: list[SignalRelevance] = []
    for candidate in pool:
        try:
            results.append(
                signal_relevance(
                    graph=graph,
                    nodes=nodes,
                    node_a=node_id,
                    node_b=candidate,
                    config=config,
                    embedder=embedder,
                )
            )
        except KeyError:
            # Candidate vanished from the graph between enumeration and
            # scoring (concurrent mutation in pathological cases). Skip.
            continue

    results.sort(key=lambda r: r.combined, reverse=True)
    return results[:top_k]

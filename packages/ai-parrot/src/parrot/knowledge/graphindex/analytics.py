"""Analytics + Report stage for GraphIndex.

Computes centrality metrics to identify "god-nodes", ranks cross-domain
``mentions`` edges by confidence to surface surprising connections, and
generates a deterministic ``GRAPH_REPORT.md`` for agent consumption.

v1 uses deterministic templates only.  The ``llm_polish`` flag is accepted
but is a no-op; LLM-polished reports are planned for v1.5.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import rustworkx
from pydantic import BaseModel, Field, field_serializer

from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    Provenance,
    UniversalEdge,
    UniversalNode,
)

# FEAT-191 — optional, lazy-typed; the field is `Optional` so analytics
# stays usable even when communities aren't computed.
try:
    from parrot.knowledge.graphindex.communities import CommunitiesResult
except ImportError:  # pragma: no cover — communities ships with FEAT-191
    CommunitiesResult = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Report file name
# ---------------------------------------------------------------------------
REPORT_FILENAME = "GRAPH_REPORT.md"


# ---------------------------------------------------------------------------
# Pydantic models (FEAT-215)
# ---------------------------------------------------------------------------


class KnowledgeGaps(BaseModel):
    """Aggregated knowledge gap report.

    Args:
        isolated_nodes: Nodes with degree <= max_degree (few connections).
        sparse_communities: Communities with low cohesion and sufficient size.
        bridge_nodes: Nodes that connect many distinct communities.
    """

    isolated_nodes: list[dict] = Field(
        default_factory=list,
        description="Nodes with very few connections (degree <= threshold), indicating under-explored concepts.",
    )
    sparse_communities: list[dict] = Field(
        default_factory=list,
        description="Communities with low internal cohesion, suggesting weakly-connected topic clusters.",
    )
    bridge_nodes: list[dict] = Field(
        default_factory=list,
        description="Nodes connecting many distinct communities; high-value linking concepts.",
    )


class SurpriseFactors(BaseModel):
    """Decomposed explanation of why a connection is surprising.

    Args:
        cross_community: Source and target in different Louvain communities.
        cross_type: Source and target have different NodeKind values.
        type_distance: Distance between node kinds (1 = adjacent, 2 = distant).
        peripheral_hub: Low-degree node connected to a high-degree hub.
        weak_but_present: Edge confidence below 0.5.
        high_confidence: Edge confidence >= 0.7.
        composite_score: Sum of all contributing signals.
    """

    cross_community: bool = Field(
        default=False,
        description="True when source and target belong to different Louvain communities (+3 score).",
    )
    cross_type: bool = Field(
        default=False,
        description="True when source and target have different NodeKind values.",
    )
    type_distance: int = Field(
        default=0,
        description="Distance between node kinds: 1 = adjacent pair, 2 = distant pair.",
    )
    peripheral_hub: bool = Field(
        default=False,
        description="True when a low-degree peripheral node is connected to a high-degree hub (+2 score).",
    )
    weak_but_present: bool = Field(
        default=False,
        description="True when edge confidence is below 0.5 — surprising given low certainty (+1 score).",
    )
    high_confidence: bool = Field(
        default=False,
        description="True when edge confidence is >= 0.7 — a confident inferred cross-domain link (+1 score).",
    )
    composite_score: int = Field(
        default=0,
        description="Sum of all contributing signal scores; connections with score < 3 are filtered out.",
    )


class DismissedInsights(BaseModel):
    """Tracks dismissed insight IDs. Session-scoped (not persisted to DB).

    Args:
        dismissed_ids: Set of insight IDs that have been marked as reviewed/dismissed.
    """

    dismissed_ids: set[str] = Field(
        default_factory=set,
        description="Set of insight IDs that have been marked as reviewed/dismissed by the user.",
    )

    @field_serializer("dismissed_ids")
    def serialize_dismissed_ids(self, v: set[str]) -> list[str]:
        """Serialize dismissed_ids as a sorted list for JSON compatibility."""
        return sorted(v)


# ---------------------------------------------------------------------------
# FEAT-215: Type distance matrix for composite surprise scoring
# ---------------------------------------------------------------------------

# "Distant" type pairs — nodes from fundamentally different domains.
# Pairs listed once; checked as frozenset for symmetry.
_DISTANT_TYPE_PAIRS: frozenset[frozenset] = frozenset(
    [
        frozenset({NodeKind.SKILL, NodeKind.DOCUMENT}),
        frozenset({NodeKind.SYMBOL, NodeKind.RATIONALE}),
        frozenset({NodeKind.CONCEPT, NodeKind.SKILL}),
    ]
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AnalyticsResult:
    """Results from graph analytics computation.

    Args:
        god_nodes: Top-K nodes by centrality.  Each dict contains
            ``node_id``, ``title``, ``kind``, ``betweenness``,
            ``eigenvector``.
        surprising_connections: Cross-domain ``mentions`` edges ranked by
            confidence (descending).  Each dict contains ``source_id``,
            ``target_id``, ``confidence``, ``source_kind``, ``target_kind``.
        suggested_questions: Generated question strings derived from
            templates.
        communities: Optional FEAT-191 Louvain partition result. When
            set, ``generate_report`` renders an additional
            ``## Communities`` section.
        knowledge_gaps: Optional FEAT-215 knowledge gap detection result.
            When set, ``generate_report`` renders an additional
            ``## Knowledge Gaps`` section.
    """

    god_nodes: list[dict] = field(default_factory=list)
    surprising_connections: list[dict] = field(default_factory=list)
    suggested_questions: list[str] = field(default_factory=list)
    communities: Optional["CommunitiesResult"] = None
    knowledge_gaps: Optional[KnowledgeGaps] = None
    dismissed: Optional[DismissedInsights] = None


# ---------------------------------------------------------------------------
# Core analytics
# ---------------------------------------------------------------------------


def compute_analytics(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    edges: list[UniversalEdge],
    top_k: int = 10,
) -> AnalyticsResult:
    """Compute centrality metrics and rank cross-domain connections.

    Args:
        graph: The assembled ``rustworkx.PyDiGraph`` instance.  Node
            payloads must be dicts with at least ``node_id``, ``kind``,
            and ``title`` keys.
        nodes: All ``UniversalNode`` objects in the graph (used for
            question generation).
        edges: All ``UniversalEdge`` objects (used to rank surprising
            connections from ``mentions`` edges).
        top_k: Number of top results to return for god-nodes and
            surprising connections.

    Returns:
        An ``AnalyticsResult`` with god-nodes, surprising connections,
        suggested questions, and knowledge gaps.
    """
    god_nodes = _compute_god_nodes(graph, top_k)

    # FEAT-215: Pass graph for peripheral-hub scoring. communities_result is
    # intentionally None here; callers that have communities (e.g.
    # toolkit._get_or_compute_analytics) re-run _rank_surprising_connections
    # after attaching communities so the cross-community signal (+3) applies.
    surprising_connections = _rank_surprising_connections(
        edges, nodes, top_k, graph=graph, communities_result=None
    )
    suggested_questions = _generate_suggested_questions(
        nodes, edges, surprising_connections
    )

    # FEAT-215: Knowledge gap detection — always compute isolated nodes;
    # sparse_communities and bridge_nodes require CommunitiesResult.
    isolated = find_isolated_nodes(graph, nodes)
    knowledge_gaps = KnowledgeGaps(isolated_nodes=isolated)

    return AnalyticsResult(
        god_nodes=god_nodes,
        surprising_connections=surprising_connections,
        suggested_questions=suggested_questions,
        knowledge_gaps=knowledge_gaps,
    )


def _compute_god_nodes(
    graph: rustworkx.PyDiGraph, top_k: int
) -> list[dict]:
    """Compute and rank nodes by betweenness and eigenvector centrality.

    Args:
        graph: The assembled PyDiGraph.
        top_k: Number of top nodes to return.

    Returns:
        List of top-K god-node dicts sorted by betweenness centrality
        descending.
    """
    if graph.num_nodes() == 0:
        return []

    try:
        _bc = rustworkx.betweenness_centrality(graph)
        betweenness: dict[int, float] = dict(_bc.items())
    except Exception as exc:
        logger.warning("Could not compute betweenness centrality: %s", exc)
        betweenness = {}

    try:
        _ec = rustworkx.eigenvector_centrality(graph, max_iter=1000)
        eigenvector: dict[int, float] = dict(_ec.items())
    except Exception as exc:
        logger.warning("Could not compute eigenvector centrality: %s", exc)
        eigenvector = {}

    result: list[dict] = []
    for idx in graph.node_indices():
        payload = graph[idx]
        if not isinstance(payload, dict):
            continue
        result.append(
            {
                "node_id": payload.get("node_id", str(idx)),
                "title": payload.get("title", ""),
                "kind": payload.get("kind", ""),
                "betweenness": betweenness.get(idx, 0.0),
                "eigenvector": eigenvector.get(idx, 0.0),
            }
        )

    result.sort(key=lambda x: x["betweenness"], reverse=True)
    return result[:top_k]


def _rank_surprising_connections(
    edges: list[UniversalEdge],
    nodes: list[UniversalNode],
    top_k: int,
    graph: Optional[rustworkx.PyDiGraph] = None,
    communities_result: Optional["CommunitiesResult"] = None,
) -> list[dict]:
    """Rank inferred cross-domain ``mentions`` edges by composite surprise score.

    FEAT-215: Enhanced with composite scoring. Each connection is scored on
    5 signals (cross-community +3, cross-type +1/+2, peripheral-hub +2,
    weak-but-present +1, high-confidence +1). Only connections with
    composite_score >= 3 are surfaced. Results are sorted by composite_score
    descending, with confidence as a tie-breaker.

    When ``graph`` and/or ``communities_result`` are None the corresponding
    signals are gracefully skipped (backward-compatible).

    Args:
        edges: All edges; only ``MENTIONS`` edges with
            ``provenance=INFERRED`` are considered.
        nodes: All nodes — used to look up kind information.
        top_k: Maximum number of connections to return.
        graph: Optional PyDiGraph for degree-based peripheral-hub scoring.
        communities_result: Optional CommunitiesResult for cross-community scoring.

    Returns:
        List of surprising connection dicts sorted by composite_score descending,
        each containing the original fields plus ``composite_score`` and
        ``surprise_factors``.
    """
    node_kind: dict[str, str] = {n.node_id: n.kind.value for n in nodes}
    node_kind_enum: dict[str, NodeKind] = {n.node_id: n.kind for n in nodes}

    # Build degree map for peripheral-hub scoring.
    degrees: dict[str, int] = {}
    degree_threshold: Optional[float] = None
    if graph is not None and graph.num_nodes() > 0:
        # Build node_id → graph index for degree lookup.
        nid_to_idx: dict[str, int] = {}
        for idx in graph.node_indices():
            payload = graph[idx]
            if isinstance(payload, dict) and "node_id" in payload:
                nid_to_idx[payload["node_id"]] = idx
        for nid, idx in nid_to_idx.items():
            degrees[nid] = graph.in_degree(idx) + graph.out_degree(idx)
        if degrees:
            try:
                degree_threshold = statistics.median(degrees.values())
            except statistics.StatisticsError:
                degree_threshold = None

    # Community membership map.
    node_to_community: dict[str, str] = (
        communities_result.node_to_community if communities_result is not None else {}
    )

    connections: list[dict] = []
    for edge in edges:
        if edge.kind != EdgeKind.MENTIONS or edge.provenance != Provenance.INFERRED:
            continue

        confidence = edge.confidence or 0.0
        src_id = edge.source_id
        tgt_id = edge.target_id
        src_kind_str = node_kind.get(src_id, "unknown")
        tgt_kind_str = node_kind.get(tgt_id, "unknown")
        src_kind = node_kind_enum.get(src_id)
        tgt_kind = node_kind_enum.get(tgt_id)

        # --- Compute composite score ---
        factors = SurpriseFactors()

        # Signal 1: Cross-community (+3)
        if node_to_community:
            src_comm = node_to_community.get(src_id)
            tgt_comm = node_to_community.get(tgt_id)
            if src_comm is not None and tgt_comm is not None and src_comm != tgt_comm:
                factors.cross_community = True
                factors.composite_score += 3

        # Signal 2: Cross-type (+1 or +2)
        if src_kind is not None and tgt_kind is not None and src_kind != tgt_kind:
            factors.cross_type = True
            pair = frozenset({src_kind, tgt_kind})
            if pair in _DISTANT_TYPE_PAIRS:
                factors.type_distance = 2
                factors.composite_score += 2
            else:
                factors.type_distance = 1
                factors.composite_score += 1

        # Signal 3: Peripheral-to-hub coupling (+2)
        if degree_threshold is not None:
            src_deg = degrees.get(src_id, 0)
            tgt_deg = degrees.get(tgt_id, 0)
            src_peripheral = src_deg <= 2
            tgt_peripheral = tgt_deg <= 2
            src_hub = src_deg >= degree_threshold
            tgt_hub = tgt_deg >= degree_threshold
            if (src_peripheral and tgt_hub) or (tgt_peripheral and src_hub):
                factors.peripheral_hub = True
                factors.composite_score += 2

        # Signal 4: Weak-but-present (+1)
        if confidence < 0.5:
            factors.weak_but_present = True
            factors.composite_score += 1

        # Signal 5: High confidence inferred (+1)
        if confidence >= 0.7:
            factors.high_confidence = True
            factors.composite_score += 1

        # Only surface connections that meet the threshold.
        if factors.composite_score < 3:
            continue

        connections.append(
            {
                "source_id": src_id,
                "target_id": tgt_id,
                "confidence": confidence,
                "source_kind": src_kind_str,
                "target_kind": tgt_kind_str,
                "composite_score": factors.composite_score,
                "surprise_factors": factors.model_dump(),
            }
        )

    # Sort by composite_score desc, confidence as tie-breaker.
    connections.sort(key=lambda x: (x["composite_score"], x["confidence"]), reverse=True)
    return connections[:top_k]


def _generate_suggested_questions(
    nodes: list[UniversalNode],
    edges: list[UniversalEdge],
    surprising_connections: list[dict],
) -> list[str]:
    """Generate suggested questions from templated patterns.

    Three patterns are used:
    1. "How does {A} relate to {B}?" — from high-confidence cross-domain edges.
    2. "What rationale exists for {function}?" — for rationale→symbol links.
    3. "Which sections mention {symbol}?" — for symbol nodes with section edges.

    Args:
        nodes: All nodes in the graph.
        edges: All edges in the graph.
        surprising_connections: Pre-ranked surprising connections list.

    Returns:
        List of question strings.
    """
    node_map: dict[str, UniversalNode] = {n.node_id: n for n in nodes}
    questions: list[str] = []

    # Pattern 1: cross-domain connections
    for conn in surprising_connections:
        src = node_map.get(conn["source_id"])
        tgt = node_map.get(conn["target_id"])
        if src and tgt:
            questions.append(f"How does {src.title} relate to {tgt.title}?")

    # Pattern 2: rationale → symbol
    for edge in edges:
        if edge.kind == EdgeKind.EXPLAINS:
            rationale = node_map.get(edge.source_id)
            symbol = node_map.get(edge.target_id)
            if (
                rationale
                and symbol
                and rationale.kind == NodeKind.RATIONALE
                and symbol.kind == NodeKind.SYMBOL
            ):
                questions.append(
                    f"What rationale exists for {symbol.title}?"
                )

    # Pattern 3: symbol → section (via MENTIONS)
    for edge in edges:
        if edge.kind == EdgeKind.MENTIONS:
            symbol = node_map.get(edge.source_id)
            section = node_map.get(edge.target_id)
            if (
                symbol
                and section
                and symbol.kind == NodeKind.SYMBOL
                and section.kind == NodeKind.SECTION
            ):
                questions.append(
                    f"Which sections mention {symbol.title}?"
                )

    return questions


# ---------------------------------------------------------------------------
# FEAT-215: Knowledge gap detection functions
# ---------------------------------------------------------------------------


def find_isolated_nodes(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    max_degree: int = 1,
    exclude_kinds: Optional[set[NodeKind]] = None,
) -> list[dict]:
    """Find nodes with few connections (potential knowledge gaps).

    Nodes with total degree (in + out) <= max_degree are considered
    isolated. By default, DOCUMENT nodes are excluded because they are
    structural root nodes expected to have low out-degree.

    Args:
        graph: The assembled PyDiGraph. Node payloads must contain
            ``node_id``, ``kind``, and ``title`` keys.
        nodes: All ``UniversalNode`` objects in the graph.
        max_degree: Maximum total degree (in + out) for a node to be
            considered isolated. Defaults to 1.
        exclude_kinds: Set of ``NodeKind`` values to skip. Defaults to
            ``{NodeKind.DOCUMENT}`` when not supplied.

    Returns:
        List of dicts, each containing ``node_id``, ``title``, ``kind``,
        and ``degree`` for isolated nodes.
    """
    if exclude_kinds is None:
        exclude_kinds = {NodeKind.DOCUMENT}

    # Build node_id → NodeKind map from the UniversalNode list.
    node_kind_map: dict[str, NodeKind] = {n.node_id: n.kind for n in nodes}

    result: list[dict] = []
    for idx in graph.node_indices():
        payload = graph[idx]
        if not isinstance(payload, dict):
            continue
        node_id = payload.get("node_id", "")
        kind_value = payload.get("kind", "")

        # Resolve kind — try UniversalNode list first, then payload string.
        node_kind = node_kind_map.get(node_id)
        if node_kind is None:
            # Try to resolve from the string value in payload.
            try:
                node_kind = NodeKind(kind_value)
            except ValueError:
                node_kind = None

        # Skip excluded kinds.
        if node_kind in exclude_kinds:
            continue

        degree = graph.in_degree(idx) + graph.out_degree(idx)
        if degree <= max_degree:
            result.append(
                {
                    "node_id": node_id,
                    "title": payload.get("title", ""),
                    "kind": kind_value,
                    "degree": degree,
                }
            )

    return result


def find_sparse_communities(
    communities_result: Optional["CommunitiesResult"],
    min_size: int = 3,
    max_cohesion: float = 0.15,
) -> list[dict]:
    """Find communities with low internal cohesion (sparse communities).

    A community is considered sparse when it has enough members to be
    meaningful (>= min_size) but low internal cohesion (< max_cohesion).
    These represent areas where knowledge is disconnected.

    Args:
        communities_result: A ``CommunitiesResult`` from FEAT-191 Louvain
            community detection.
        min_size: Minimum number of members for a community to be
            considered. Communities smaller than this are skipped.
        max_cohesion: Maximum cohesion threshold. Communities with
            cohesion >= this value are considered tight (not sparse).

    Returns:
        List of dicts, each containing ``community_id``, ``size``,
        ``cohesion``, and ``top_titles`` for sparse communities.
    """
    if communities_result is None:
        return []

    result: list[dict] = []
    for community in communities_result.communities:
        if community.size < min_size:
            continue
        if community.cohesion < max_cohesion:
            result.append(
                {
                    "community_id": community.community_id,
                    "size": community.size,
                    "cohesion": community.cohesion,
                    "top_titles": community.top_titles,
                    "centroid_node_id": community.centroid_node_id,
                }
            )

    return result


def find_bridge_nodes(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    communities_result: Optional["CommunitiesResult"],
    min_communities: int = 3,
) -> list[dict]:
    """Find nodes that bridge multiple distinct communities.

    A bridge node is one whose neighbors span at least ``min_communities``
    distinct Louvain communities. These nodes are critical connectors
    and represent important cross-domain knowledge links.

    Args:
        graph: The assembled PyDiGraph.
        nodes: All ``UniversalNode`` objects in the graph.
        communities_result: A ``CommunitiesResult`` from FEAT-191 Louvain
            community detection.
        min_communities: Minimum number of distinct neighbor communities
            required to classify a node as a bridge. Defaults to 3.

    Returns:
        List of dicts, each containing ``node_id``, ``title``, ``kind``,
        ``community_count``, and ``neighbor_community_ids`` for bridge nodes.
    """
    if communities_result is None:
        return []

    node_to_community = communities_result.node_to_community
    node_kind_map: dict[str, str] = {}
    node_title_map: dict[str, str] = {}

    for idx in graph.node_indices():
        payload = graph[idx]
        if isinstance(payload, dict) and "node_id" in payload:
            nid = payload["node_id"]
            node_kind_map[nid] = payload.get("kind", "")
            node_title_map[nid] = payload.get("title", "")

    result: list[dict] = []
    for idx in graph.node_indices():
        payload = graph[idx]
        if not isinstance(payload, dict):
            continue
        node_id = payload.get("node_id", "")

        # Collect all neighbor node_ids (both in and out edges).
        neighbor_ids: set[str] = set()
        for neighbor_idx in graph.predecessor_indices(idx):
            nbr_payload = graph[neighbor_idx]
            if isinstance(nbr_payload, dict) and "node_id" in nbr_payload:
                neighbor_ids.add(nbr_payload["node_id"])
        for neighbor_idx in graph.successor_indices(idx):
            nbr_payload = graph[neighbor_idx]
            if isinstance(nbr_payload, dict) and "node_id" in nbr_payload:
                neighbor_ids.add(nbr_payload["node_id"])

        # Determine distinct communities among neighbors.
        neighbor_communities: set[str] = set()
        for nbr_id in neighbor_ids:
            cid = node_to_community.get(nbr_id)
            if cid is not None:
                neighbor_communities.add(cid)

        if len(neighbor_communities) >= min_communities:
            result.append(
                {
                    "node_id": node_id,
                    "title": node_title_map.get(node_id, ""),
                    "kind": node_kind_map.get(node_id, ""),
                    "community_count": len(neighbor_communities),
                    "neighbor_community_ids": sorted(neighbor_communities),
                }
            )

    return result


# ---------------------------------------------------------------------------
# FEAT-215: Insight dismissal functions
# ---------------------------------------------------------------------------


def dismiss_insight(analytics: AnalyticsResult, insight_id: str) -> None:
    """Mark an insight as dismissed.

    Creates a ``DismissedInsights`` container if one does not yet exist on
    the analytics result, then adds ``insight_id`` to the dismissed set.

    Insight IDs follow these conventions:
    - Surprising connections: ``f"surprise:{conn['source_id']}:{conn['target_id']}"``
    - Isolated nodes: ``f"isolated:{node['node_id']}"``
    - Sparse communities: ``f"sparse:{community['community_id']}"``
    - Bridge nodes: ``f"bridge:{node['node_id']}"``

    Args:
        analytics: The ``AnalyticsResult`` to update in place.
        insight_id: The stable ID of the insight to dismiss.
    """
    if analytics.dismissed is None:
        analytics.dismissed = DismissedInsights()
    analytics.dismissed.dismissed_ids.add(insight_id)


def list_unreviewed_insights(analytics: AnalyticsResult) -> list[dict]:
    """Return all insights not yet dismissed.

    Aggregates surprising connections and knowledge gap entries (isolated
    nodes, sparse communities, bridge nodes) into a flat list, assigns
    each a stable ``id`` field, and filters out any IDs in
    ``analytics.dismissed.dismissed_ids``.

    Args:
        analytics: The ``AnalyticsResult`` to inspect.

    Returns:
        List of insight dicts, each containing at minimum an ``id`` field
        (the stable insight ID) and the original insight data. The list
        is NOT sorted.
    """
    dismissed_ids: set[str] = (
        analytics.dismissed.dismissed_ids if analytics.dismissed else set()
    )

    insights: list[dict] = []

    # Surprising connections
    for conn in analytics.surprising_connections:
        iid = f"surprise:{conn['source_id']}:{conn['target_id']}"
        if iid not in dismissed_ids:
            insights.append({"id": iid, **conn})

    # Knowledge gap entries
    if analytics.knowledge_gaps is not None:
        for node in analytics.knowledge_gaps.isolated_nodes:
            iid = f"isolated:{node['node_id']}"
            if iid not in dismissed_ids:
                insights.append({"id": iid, **node})

        for community in analytics.knowledge_gaps.sparse_communities:
            iid = f"sparse:{community['community_id']}"
            if iid not in dismissed_ids:
                insights.append({"id": iid, **community})

        for node in analytics.knowledge_gaps.bridge_nodes:
            iid = f"bridge:{node['node_id']}"
            if iid not in dismissed_ids:
                insights.append({"id": iid, **node})

    return insights


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_report(
    analytics: AnalyticsResult,
    output_dir: Path,
    llm_polish: bool = False,  # noqa: FBT001 — stubbed for v1.5
    tenant_id: str = "default",
) -> Path:
    """Generate ``GRAPH_REPORT.md`` from analytics results.

    The report is deterministic: identical inputs produce identical output.
    The ``llm_polish`` parameter is accepted but is a no-op in v1.

    FEAT-239: The report now starts with OKF-compatible YAML frontmatter
    prepended before the Markdown body.

    Args:
        analytics: Pre-computed ``AnalyticsResult``.
        output_dir: Directory where ``GRAPH_REPORT.md`` will be written.
        llm_polish: Reserved for v1.5.  Currently ignored.
        tenant_id: Tenant identifier used in the frontmatter resource URI.

    Returns:
        Path to the written report file.
    """
    # Deferred to avoid a circular import: projection → schema → analytics.
    from parrot.knowledge.graphindex.projection import project_report_frontmatter  # noqa: PLC0415

    if llm_polish:
        logger.info("llm_polish=True is not yet implemented; using deterministic template.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report_path = output_dir / REPORT_FILENAME
    content = _render_report(analytics)
    # Prepend OKF frontmatter (FEAT-239)
    try:
        fm = project_report_frontmatter(analytics, tenant_id)
        content = fm + "\n" + content
    except Exception as exc:
        logger.warning("Failed to generate report frontmatter: %s", exc)

    report_path.write_text(content, encoding="utf-8")

    logger.info("Written GRAPH_REPORT.md to %s", report_path)
    return report_path


def _render_report(analytics: AnalyticsResult) -> str:
    """Render the report Markdown string from an ``AnalyticsResult``.

    Args:
        analytics: Pre-computed analytics results.

    Returns:
        Complete Markdown string for the report.
    """
    lines: list[str] = ["# Knowledge Graph Report", ""]

    # Collect dismissed IDs for filtering.
    dismissed_ids: set[str] = (
        analytics.dismissed.dismissed_ids if analytics.dismissed else set()
    )

    # --- God-Nodes ---
    lines.append("## God-Nodes (Most Central)")
    lines.append("")
    lines.append("| Rank | Node | Kind | Betweenness | Eigenvector |")
    lines.append("|------|------|------|-------------|-------------|")
    for rank, node in enumerate(analytics.god_nodes, start=1):
        lines.append(
            f"| {rank} | {node['title']} | {node['kind']} "
            f"| {node['betweenness']:.4f} | {node['eigenvector']:.4f} |"
        )
    lines.append("")

    # --- Surprising Connections (FEAT-215: filter dismissed) ---
    lines.append("## Surprising Connections")
    lines.append("")
    lines.append("| Source | Target | Confidence | Score | Why Interesting |")
    lines.append("|--------|--------|------------|-------|-----------------|")
    for conn in analytics.surprising_connections:
        conn_id = f"surprise:{conn['source_id']}:{conn['target_id']}"
        if conn_id in dismissed_ids:
            continue
        why = f"Cross-domain: {conn['source_kind']} <-> {conn['target_kind']}"
        score = conn.get("composite_score", "")
        lines.append(
            f"| {conn['source_id']} | {conn['target_id']} "
            f"| {conn['confidence']:.4f} | {score} | {why} |"
        )
    lines.append("")

    # --- Suggested Questions ---
    lines.append("## Suggested Questions")
    lines.append("")
    for question in analytics.suggested_questions:
        lines.append(f"- {question}")
    lines.append("")

    # --- Communities (FEAT-191, only when present) ---
    if analytics.communities is not None:
        lines.append("## Communities")
        lines.append("")
        lines.append(
            f"Global modularity: **{analytics.communities.modularity:.4f}** "
            f"(resolution={analytics.communities.resolution}, "
            f"weighted={analytics.communities.weighted})"
        )
        lines.append("")
        lines.append("| Rank | Community | Size | Centroid | Cohesion | Top Members |")
        lines.append("|------|-----------|------|----------|----------|-------------|")
        for rank, comm in enumerate(analytics.communities.communities, start=1):
            top = ", ".join(comm.top_titles)
            lines.append(
                f"| {rank} | `{comm.community_id}` | {comm.size} "
                f"| {comm.centroid_node_id} | {comm.cohesion:.4f} | {top} |"
            )
        lines.append("")

    # --- Knowledge Gaps (FEAT-215, only when present and non-empty) ---
    if analytics.knowledge_gaps is not None:
        kg = analytics.knowledge_gaps
        has_content = (
            kg.isolated_nodes or kg.sparse_communities or kg.bridge_nodes
        )
        if has_content:
            lines.append("## Knowledge Gaps")
            lines.append("")

            # --- Isolated Nodes ---
            lines.append("### Isolated Nodes")
            lines.append("")
            lines.append("| Node | Kind | Degree |")
            lines.append("|------|------|--------|")
            for node in kg.isolated_nodes:
                iid = f"isolated:{node['node_id']}"
                if iid in dismissed_ids:
                    continue
                lines.append(
                    f"| {node.get('title', node['node_id'])} "
                    f"| {node['kind']} | {node['degree']} |"
                )
            lines.append("")

            # --- Sparse Communities ---
            lines.append("### Sparse Communities")
            lines.append("")
            lines.append("| Community | Size | Cohesion | Top Members |")
            lines.append("|-----------|------|----------|-------------|")
            for comm in kg.sparse_communities:
                cid = f"sparse:{comm['community_id']}"
                if cid in dismissed_ids:
                    continue
                top = ", ".join(comm.get("top_titles", []))
                lines.append(
                    f"| `{comm['community_id']}` | {comm['size']} "
                    f"| {comm['cohesion']:.4f} | {top} |"
                )
            lines.append("")

            # --- Bridge Nodes ---
            lines.append("### Bridge Nodes")
            lines.append("")
            lines.append("| Node | Kind | Communities Connected |")
            lines.append("|------|------|-----------------------|")
            for node in kg.bridge_nodes:
                bid = f"bridge:{node['node_id']}"
                if bid in dismissed_ids:
                    continue
                lines.append(
                    f"| {node.get('title', node['node_id'])} "
                    f"| {node['kind']} | {node['community_count']} |"
                )
            lines.append("")

    return "\n".join(lines)

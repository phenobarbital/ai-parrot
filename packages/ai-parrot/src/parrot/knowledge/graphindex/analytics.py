"""Analytics + Report stage for GraphIndex.

Computes centrality metrics to identify "god-nodes", ranks cross-domain
``mentions`` edges by confidence to surface surprising connections, and
generates a deterministic ``GRAPH_REPORT.md`` for agent consumption.

v1 uses deterministic templates only.  The ``llm_polish`` flag is accepted
but is a no-op; LLM-polished reports are planned for v1.5.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import rustworkx
from pydantic import BaseModel, Field

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

    isolated_nodes: list[dict] = Field(default_factory=list)
    sparse_communities: list[dict] = Field(default_factory=list)
    bridge_nodes: list[dict] = Field(default_factory=list)


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
    surprising_connections = _rank_surprising_connections(edges, nodes, top_k)
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
        _ec = rustworkx.eigenvector_centrality(graph)
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
) -> list[dict]:
    """Rank inferred cross-domain ``mentions`` edges by confidence.

    Args:
        edges: All edges; only ``MENTIONS`` edges with
            ``provenance=INFERRED`` are considered.
        nodes: All nodes — used to look up kind information.
        top_k: Maximum number of connections to return.

    Returns:
        List of surprising connection dicts sorted by confidence descending.
    """
    node_kind: dict[str, str] = {n.node_id: n.kind.value for n in nodes}

    connections: list[dict] = []
    for edge in edges:
        if edge.kind != EdgeKind.MENTIONS or edge.provenance != Provenance.INFERRED:
            continue
        connections.append(
            {
                "source_id": edge.source_id,
                "target_id": edge.target_id,
                "confidence": edge.confidence or 0.0,
                "source_kind": node_kind.get(edge.source_id, "unknown"),
                "target_kind": node_kind.get(edge.target_id, "unknown"),
            }
        )

    connections.sort(key=lambda x: x["confidence"], reverse=True)
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

    # Build node_id → graph index map from graph payloads.
    node_id_to_idx: dict[str, int] = {}
    for idx in graph.node_indices():
        payload = graph[idx]
        if isinstance(payload, dict) and "node_id" in payload:
            node_id_to_idx[payload["node_id"]] = idx

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
    communities_result: "CommunitiesResult",
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
    communities_result: "CommunitiesResult",
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
# Report generation
# ---------------------------------------------------------------------------


def generate_report(
    analytics: AnalyticsResult,
    output_dir: Path,
    llm_polish: bool = False,  # noqa: FBT001 — stubbed for v1.5
) -> Path:
    """Generate ``GRAPH_REPORT.md`` from analytics results.

    The report is deterministic: identical inputs produce identical output.
    The ``llm_polish`` parameter is accepted but is a no-op in v1.

    Args:
        analytics: Pre-computed ``AnalyticsResult``.
        output_dir: Directory where ``GRAPH_REPORT.md`` will be written.
        llm_polish: Reserved for v1.5.  Currently ignored.

    Returns:
        Path to the written report file.
    """
    if llm_polish:
        logger.info("llm_polish=True is not yet implemented; using deterministic template.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report_path = output_dir / REPORT_FILENAME
    content = _render_report(analytics)
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

    # --- Surprising Connections ---
    lines.append("## Surprising Connections")
    lines.append("")
    lines.append("| Source | Target | Confidence | Why Interesting |")
    lines.append("|--------|--------|------------|-----------------|")
    for conn in analytics.surprising_connections:
        why = f"Cross-domain: {conn['source_kind']} <-> {conn['target_kind']}"
        lines.append(
            f"| {conn['source_id']} | {conn['target_id']} "
            f"| {conn['confidence']:.4f} | {why} |"
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

    return "\n".join(lines)

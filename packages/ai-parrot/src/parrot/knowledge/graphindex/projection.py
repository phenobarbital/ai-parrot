"""GraphIndex OKF Projection Layer (FEAT-239).

Projects every ``UniversalNode`` as an OKF-compatible ``.md`` sidecar file
with YAML frontmatter.  Also provides the frontmatter string for
``GRAPH_REPORT.md``.

Key design decisions:
- ``node_to_frontmatter_dict()`` and ``project_node_sidecar()`` are pure
  functions (no I/O) for easy unit testing.
- ``project_graph_sidecars()`` is async because resolving ``content_ref``
  via ``NodeContentStore.load()`` may involve I/O.
- Sidecars are written to ``output_dir/nodes/<filename>.md``.
- Sidecar filenames use ``flatten_concept_id_for_filename(node_id)`` —
  slashes become ``--``.
- Byte-determinism: same input → identical sidecar every time.
- If ``content_store`` is not provided (or a content_ref fails to resolve),
  the body falls back gracefully to ``summary`` or ``title``.
- Projection failures do NOT propagate as exceptions; callers are expected
  to wrap the async call in a try/except.

Mapping tables:
    NODE_KIND_TO_CONCEPT_TYPE: GraphIndex NodeKind → OKF ConceptType
    EDGE_KIND_TO_RELATION_TYPE: GraphIndex EdgeKind → OKF RelationType
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from parrot.knowledge.graphindex.analytics import AnalyticsResult
from parrot.knowledge.graphindex.schema import EdgeKind, NodeKind, UniversalEdge, UniversalNode
from parrot.knowledge.okf.frontmatter import project_frontmatter
from parrot.knowledge.okf.ontology import ConceptType, RelationType
from parrot.knowledge.okf.uri import parse_uri
from parrot.knowledge.pageindex.okf.projection import flatten_concept_id_for_filename

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mapping tables
# ---------------------------------------------------------------------------

NODE_KIND_TO_CONCEPT_TYPE: dict[NodeKind, ConceptType] = {
    NodeKind.DOCUMENT: ConceptType.DOCUMENT_NODE,
    NodeKind.SECTION: ConceptType.SECTION,
    NodeKind.SYMBOL: ConceptType.SYMBOL,
    NodeKind.CONCEPT: ConceptType.CONCEPT_NODE,
    NodeKind.RATIONALE: ConceptType.RATIONALE,
    NodeKind.SKILL: ConceptType.SKILL,
}

EDGE_KIND_TO_RELATION_TYPE: dict[EdgeKind, RelationType] = {
    EdgeKind.CONTAINS: RelationType.CONTAINS,
    EdgeKind.REFERENCES: RelationType.REFERENCES,
    EdgeKind.DEFINES: RelationType.DEFINES,
    EdgeKind.MENTIONS: RelationType.MENTIONS,
    EdgeKind.EXPLAINS: RelationType.EXPLAINS,
}

# ---------------------------------------------------------------------------
# Report model
# ---------------------------------------------------------------------------

_GRAPHINDEX_TREE = "graphindex"


class GraphProjectionReport(BaseModel):
    """Summary of a completed GraphIndex projection run.

    Attributes:
        output_dir: Directory where sidecars were written.
        nodes_projected: Count of nodes successfully projected.
        files_written: List of absolute file paths written.
        report_frontmatter_added: Whether GRAPH_REPORT.md received frontmatter.
    """

    output_dir: str
    nodes_projected: int = 0
    files_written: list[str] = Field(default_factory=list)
    report_frontmatter_added: bool = False


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


def node_to_frontmatter_dict(
    node: UniversalNode,
    edges: list[UniversalEdge],
) -> dict:
    """Convert a UniversalNode + its outgoing edges into a project_frontmatter() dict.

    The returned dict conforms to the contract expected by
    ``project_frontmatter(node_dict, tree_name)``.  It is a pure function
    with no I/O — the same inputs always produce the same output.

    Args:
        node: The GraphIndex node to project.
        edges: All edges in the graph.  Only outgoing edges from ``node``
            are included in ``relates_to``.

    Returns:
        Dict suitable for ``project_frontmatter(dict, "graphindex")``.
    """
    outgoing = [e for e in edges if e.source_id == node.node_id]
    relates_to = [
        {
            "concept": e.target_id,
            "rel": EDGE_KIND_TO_RELATION_TYPE[e.kind].value,
        }
        for e in outgoing
        if e.kind in EDGE_KIND_TO_RELATION_TYPE
    ]
    return {
        "concept_id": node.node_id,
        "type": NODE_KIND_TO_CONCEPT_TYPE[node.kind].value,
        "title": node.title,
        "node_id": node.node_id,
        "summary": node.summary or node.title,
        "categories": sorted(node.domain_tags.get("categories", [])),
        "timestamp": str(node.domain_tags.get("timestamp", "")),
        "relates_to": relates_to,
        "source": {"document": node.source_uri} if node.source_uri else None,
    }


def project_node_sidecar(
    node: UniversalNode,
    edges: list[UniversalEdge],
    body: str,
) -> str:
    """Return the complete sidecar text: YAML frontmatter + body.

    The output is byte-deterministic: the same ``node``, ``edges``, and
    ``body`` always produce the same result.

    Args:
        node: The GraphIndex node to project.
        edges: All edges (outgoing edges from node become ``relates_to``).
        body: Full text body for the sidecar (may be full content or summary).

    Returns:
        Complete sidecar string starting with ``---\\n`` frontmatter.
    """
    node_dict = node_to_frontmatter_dict(node, edges)
    fm_str = project_frontmatter(node_dict, _GRAPHINDEX_TREE)
    return f"{fm_str}\n{body}"


def project_report_frontmatter(
    analytics: AnalyticsResult,
    tenant_id: str,
) -> str:
    """Generate OKF YAML frontmatter string for GRAPH_REPORT.md.

    Args:
        analytics: The analytics result from the graph build.
        tenant_id: Tenant identifier used in the resource URI.

    Returns:
        YAML frontmatter string delimited by ``---\\n``.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    report_id = f"graph-report-{tenant_id}"
    node_dict = {
        "concept_id": report_id,
        "type": ConceptType.DOCUMENT_NODE.value,
        "title": "Knowledge Graph Report",
        "node_id": report_id,
        "summary": (
            f"Analytics report for tenant {tenant_id}: "
            f"{len(analytics.god_nodes)} central nodes, "
            f"{len(analytics.surprising_connections)} surprising connections."
        ),
        "categories": [],
        "timestamp": timestamp,
        "relates_to": [],
        "source": None,
    }
    # Override the resource to use knowledge:// scheme
    # project_frontmatter builds resource as pageindex://graphindex/..., but
    # for the graph report we pass a pre-built node dict with the right concept_id.
    fm = project_frontmatter(node_dict, _GRAPHINDEX_TREE)
    return fm


# ---------------------------------------------------------------------------
# Content-ref resolution helper
# ---------------------------------------------------------------------------


def _resolve_body(
    node: UniversalNode,
    content_store: Optional[object],
) -> str:
    """Resolve full body from content_ref or fall back to summary/title.

    Args:
        node: The node whose ``content_ref`` may point to PageIndex storage.
        content_store: Optional ``NodeContentStore`` instance.

    Returns:
        Body string (full text, summary, or title as fallback).
    """
    if node.content_ref and content_store is not None:
        try:
            idx_type, rest = parse_uri(node.content_ref)
            if idx_type == "pageindex":
                tree_name, node_id = rest.split("/", 1)
                body = content_store.load(tree_name, node_id)  # type: ignore[union-attr]
                if body:
                    return body
                logger.warning(
                    "content_ref %r resolved to None for node %r",
                    node.content_ref,
                    node.node_id,
                )
        except Exception as exc:
            logger.warning(
                "Failed to resolve content_ref %r for node %r: %s",
                node.content_ref,
                node.node_id,
                exc,
            )
    return node.summary or node.title or ""


# ---------------------------------------------------------------------------
# Async file-writing projection
# ---------------------------------------------------------------------------


async def project_graph_sidecars(
    nodes: list[UniversalNode],
    edges: list[UniversalEdge],
    output_dir: Path,
    content_store: Optional[object] = None,
    pageindex_toolkit: Optional[object] = None,
) -> GraphProjectionReport:
    """Write per-node ``.md`` sidecars to ``output_dir/nodes/``.

    For each node:
    1. Resolves body from ``content_ref`` if content_store is available.
    2. Projects YAML frontmatter + body via ``project_node_sidecar()``.
    3. Writes to ``output_dir/nodes/<flattened_node_id>.md``.

    Args:
        nodes: All ``UniversalNode`` objects to project.
        edges: All ``UniversalEdge`` objects in the graph.
        output_dir: Base directory for output.  A ``nodes/`` subdirectory
            is created automatically.
        content_store: Optional ``NodeContentStore`` for body resolution.
        pageindex_toolkit: Unused in the current implementation; reserved
            for future direct-toolkit body resolution.

    Returns:
        A ``GraphProjectionReport`` summarising the projection run.
    """
    nodes_dir = output_dir / "nodes"
    nodes_dir.mkdir(parents=True, exist_ok=True)

    report = GraphProjectionReport(output_dir=str(output_dir))

    for node in nodes:
        try:
            body = _resolve_body(node, content_store)
            sidecar = project_node_sidecar(node, edges, body)
            filename = flatten_concept_id_for_filename(node.node_id) + ".md"
            dest = nodes_dir / filename
            dest.write_text(sidecar, encoding="utf-8")
            report.nodes_projected += 1
            report.files_written.append(str(dest))
            logger.debug("Projected node %r → %s", node.node_id, dest)
        except Exception as exc:
            logger.error(
                "Failed to project node %r: %s", node.node_id, exc
            )

    return report


__all__ = [
    "NODE_KIND_TO_CONCEPT_TYPE",
    "EDGE_KIND_TO_RELATION_TYPE",
    "GraphProjectionReport",
    "node_to_frontmatter_dict",
    "project_node_sidecar",
    "project_report_frontmatter",
    "project_graph_sidecars",
]

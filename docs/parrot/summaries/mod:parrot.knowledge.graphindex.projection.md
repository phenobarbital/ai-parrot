---
type: Wiki Summary
title: parrot.knowledge.graphindex.projection
id: mod:parrot.knowledge.graphindex.projection
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: GraphIndex OKF Projection Layer (FEAT-239).
relates_to:
- concept: func:parrot.knowledge.graphindex.projection.node_to_frontmatter_dict
  rel: defines
- concept: func:parrot.knowledge.graphindex.projection.project_graph_sidecars
  rel: defines
- concept: func:parrot.knowledge.graphindex.projection.project_node_sidecar
  rel: defines
- concept: func:parrot.knowledge.graphindex.projection.project_report_frontmatter
  rel: defines
- concept: mod:parrot.knowledge.graphindex.analytics
  rel: references
- concept: mod:parrot.knowledge.graphindex.schema
  rel: references
- concept: mod:parrot.knowledge.okf.frontmatter
  rel: references
- concept: mod:parrot.knowledge.okf.ontology
  rel: references
- concept: mod:parrot.knowledge.okf.uri
  rel: references
- concept: mod:parrot.knowledge.okf.utils
  rel: references
---

# `parrot.knowledge.graphindex.projection`

GraphIndex OKF Projection Layer (FEAT-239).

Projects every ``UniversalNode`` as an OKF-compatible ``.md`` sidecar file
with YAML frontmatter.  Also provides the frontmatter string for
``GRAPH_REPORT.md``.

Key design decisions:
- ``node_to_frontmatter_dict()`` and ``project_node_sidecar()`` are pure
  functions (no I/O) for easy unit testing.
- ``project_graph_sidecars()`` is async; all disk I/O runs via
  ``asyncio.to_thread()`` to avoid blocking the event loop.
- Sidecars are written to ``output_dir/nodes/<filename>.md``.
- Sidecar filenames use ``flatten_concept_id_for_filename(node_id)`` —
  slashes become ``--``.
- Byte-determinism: ``project_node_sidecar()`` produces identical bytes for
  the same inputs.  ``project_report_frontmatter()`` is deterministic when
  an explicit ``timestamp`` is passed; without one it uses the current UTC
  time (non-deterministic by definition).
- If ``content_store`` is not provided (or a content_ref fails to resolve),
  the body falls back gracefully to ``summary`` or ``title``.
- Projection failures do NOT propagate as exceptions; callers are expected
  to wrap the async call in a try/except.

Mapping tables:
    NODE_KIND_TO_CONCEPT_TYPE: GraphIndex NodeKind → OKF ConceptType
    EDGE_KIND_TO_RELATION_TYPE: GraphIndex EdgeKind → OKF RelationType

## Functions

- `def node_to_frontmatter_dict(node: UniversalNode, edges: list[UniversalEdge]) -> dict` — Convert a UniversalNode + its outgoing edges into a project_frontmatter() dict.
- `def project_node_sidecar(node: UniversalNode, edges: list[UniversalEdge], body: str) -> str` — Return the complete sidecar text: YAML frontmatter + body.
- `def project_report_frontmatter(analytics: AnalyticsResult, tenant_id: str, timestamp: Optional[str]=None) -> str` — Generate OKF YAML frontmatter string for GRAPH_REPORT.md.
- `async def project_graph_sidecars(nodes: list[UniversalNode], edges: list[UniversalEdge], output_dir: Path, content_store: Optional[object]=None, pageindex_toolkit: Optional[object]=None) -> GraphProjectionReport` — Write per-node ``.md`` sidecars to ``output_dir/nodes/``.

---
type: Concept
title: project_graph_sidecars()
id: func:parrot.knowledge.graphindex.projection.project_graph_sidecars
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Write per-node ``.md`` sidecars to ``output_dir/nodes/``.
---

# project_graph_sidecars

```python
async def project_graph_sidecars(nodes: list[UniversalNode], edges: list[UniversalEdge], output_dir: Path, content_store: Optional[object]=None, pageindex_toolkit: Optional[object]=None) -> GraphProjectionReport
```

Write per-node ``.md`` sidecars to ``output_dir/nodes/``.

All disk I/O runs via ``asyncio.to_thread()`` to avoid blocking the
event loop.  For each node:

1. Resolves body from ``content_ref`` (via thread) if content_store is available.
2. Projects YAML frontmatter + body via ``project_node_sidecar()`` (CPU-only).
3. Writes to ``output_dir/nodes/<flattened_node_id>.md`` (via thread).

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

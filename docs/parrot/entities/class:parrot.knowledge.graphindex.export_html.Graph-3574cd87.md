---
type: Wiki Entity
title: GraphExportEdge
id: class:parrot.knowledge.graphindex.export_html.GraphExportEdge
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single directed edge in the export payload / ECharts ``links``.
---

# GraphExportEdge

Defined in [`parrot.knowledge.graphindex.export_html`](../summaries/mod:parrot.knowledge.graphindex.export_html.md).

```python
class GraphExportEdge(BaseModel)
```

A single directed edge in the export payload / ECharts ``links``.

Args:
    source: Tail ``node_id``.
    target: Head ``node_id``.
    kind: :class:`EdgeKind` value (e.g. ``"references"``).
    provenance: How the edge was created.
    confidence: Cosine similarity for inferred edges, else ``None``.

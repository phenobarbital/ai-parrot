---
type: Wiki Entity
title: GraphExportPayload
id: class:parrot.knowledge.graphindex.export_html.GraphExportPayload
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: The complete, serializable graph export.
---

# GraphExportPayload

Defined in [`parrot.knowledge.graphindex.export_html`](../summaries/mod:parrot.knowledge.graphindex.export_html.md).

```python
class GraphExportPayload(BaseModel)
```

The complete, serializable graph export.

Serialized verbatim to ``graph.json`` and embedded into ``graph.html``.

Args:
    title: Human-readable graph title shown in the page header.
    nodes: All exported nodes.
    edges: All exported edges.
    categories: Community categories in display order.
    god_node_ids: Ids of the highlighted god nodes (most connected).
    modularity: Global modularity Q of the partition, if known.
    meta: Free-form metadata (counts, generator, etc.).

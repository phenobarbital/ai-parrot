---
type: Wiki Entity
title: GraphExportCategory
id: class:parrot.knowledge.graphindex.export_html.GraphExportCategory
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A community category (an ECharts legend entry + colour).
---

# GraphExportCategory

Defined in [`parrot.knowledge.graphindex.export_html`](../summaries/mod:parrot.knowledge.graphindex.export_html.md).

```python
class GraphExportCategory(BaseModel)
```

A community category (an ECharts legend entry + colour).

Args:
    index: Display index (also the value stored on member nodes).
    community_id: Stable community id, or ``None`` for the unclustered bin.
    label: Human-readable legend label.
    color: Hex colour shared by the legend swatch and member nodes.
    size: Number of member nodes.

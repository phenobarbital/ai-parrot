---
type: Wiki Entity
title: GraphExportNode
id: class:parrot.knowledge.graphindex.export_html.GraphExportNode
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single node in the export payload / ECharts ``graph`` series.
---

# GraphExportNode

Defined in [`parrot.knowledge.graphindex.export_html`](../summaries/mod:parrot.knowledge.graphindex.export_html.md).

```python
class GraphExportNode(BaseModel)
```

A single node in the export payload / ECharts ``graph`` series.

Field names ``id``/``name``/``category``/``symbolSize``/``value`` match the
ECharts graph-series schema so the payload can be handed to ECharts with no
remapping. The remaining fields feed the click-through detail panel.

Args:
    id: The graph ``node_id``.
    name: Human-readable title shown as the node label.
    kind: :class:`NodeKind` value (e.g. ``"symbol"``, ``"concept"``).
    category: Index into the payload's ``categories`` list (community).
    symbolSize: Rendered node diameter in pixels (centrality-scaled).
    value: Ranking score (centrality when available, else degree).
    community_id: Stable id of the owning community, if any.
    community_label: Human-readable community label, if any.
    source_uri: Source artefact URI for the detail panel.
    summary: Optional short summary for the detail panel.
    provenance: How the node was created (``extracted``/``inferred``/...).
    degree: Total (in + out) degree in the graph.
    is_god: True when the node ranks among the top god nodes.

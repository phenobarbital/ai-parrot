---
type: Concept
title: export_graph()
id: func:parrot.knowledge.graphindex.export_html.export_graph
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build the payload and write both ``graph.json`` and ``graph.html``.
---

# export_graph

```python
def export_graph(graph: 'rustworkx.PyDiGraph', output_dir: Path, *, communities: Optional[Any]=None, analytics: Optional[Any]=None, god_top_k: int=15, title: str='GraphIndex Knowledge Map', echarts_js: Optional[str]=None, allow_cdn_fallback: bool=True) -> tuple[Path, Path]
```

Build the payload and write both ``graph.json`` and ``graph.html``.

Adapts a ``CommunitiesResult`` and an ``AnalyticsResult`` into the plain
lookups :func:`build_export_payload` consumes, then writes both artefacts.

Args:
    graph: The assembled ``rustworkx.PyDiGraph``.
    output_dir: Destination directory.
    communities: Optional ``CommunitiesResult`` for node colouring/labels.
    analytics: Optional ``AnalyticsResult`` whose ``god_nodes`` drive node
        sizing and highlighting.
    god_top_k: Number of top god nodes to highlight.
    title: Graph title for the page header.
    echarts_js: Explicit ECharts runtime to inline (else auto-located).
    allow_cdn_fallback: See :func:`write_graph_html`.

Returns:
    ``(html_path, json_path)``.

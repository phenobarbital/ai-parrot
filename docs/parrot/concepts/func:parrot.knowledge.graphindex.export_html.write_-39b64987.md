---
type: Concept
title: write_graph_html()
id: func:parrot.knowledge.graphindex.export_html.write_graph_html
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Write a self-contained ``graph.html`` to ``output_dir``.
---

# write_graph_html

```python
def write_graph_html(payload: GraphExportPayload, output_dir: Path, *, echarts_js: Optional[str]=None, allow_cdn_fallback: bool=True) -> Path
```

Write a self-contained ``graph.html`` to ``output_dir``.

Args:
    payload: The export payload.
    output_dir: Destination directory (created if missing).
    echarts_js: Explicit ECharts runtime JavaScript to inline. When
        ``None``, the vendored asset is located automatically.
    allow_cdn_fallback: When the asset cannot be located and this is True,
        reference the ECharts CDN and log a warning (the page then needs
        network access). When False, raise instead.

Returns:
    The path to the written ``graph.html``.

Raises:
    RuntimeError: When no ECharts runtime is available and CDN fallback is
        disabled.

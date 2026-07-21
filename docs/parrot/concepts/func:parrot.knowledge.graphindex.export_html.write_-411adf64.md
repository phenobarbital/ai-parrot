---
type: Concept
title: write_graph_json()
id: func:parrot.knowledge.graphindex.export_html.write_graph_json
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Write ``graph.json`` to ``output_dir``.
---

# write_graph_json

```python
def write_graph_json(payload: GraphExportPayload, output_dir: Path) -> Path
```

Write ``graph.json`` to ``output_dir``.

Args:
    payload: The export payload.
    output_dir: Destination directory (created if missing).

Returns:
    The path to the written ``graph.json``.

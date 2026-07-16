---
type: Wiki Entity
title: JSONRenderer
id: class:parrot.outputs.formats.json.JSONRenderer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Renderer for JSON output.
relates_to:
- concept: class:parrot.outputs.formats.base.BaseRenderer
  rel: extends
---

# JSONRenderer

Defined in [`parrot.outputs.formats.json`](../summaries/mod:parrot.outputs.formats.json.md).

```python
class JSONRenderer(BaseRenderer)
```

Renderer for JSON output.
Handles PandasAgentResponse, DataFrames, Pydantic models, and generic content.
Adapts output format to Terminal (Rich), HTML (Pygments), and Jupyter (Widgets).

## Methods

- `async def render(self, response: Any, environment: str='default', **kwargs) -> Tuple[Any, Optional[Any]]` — Render response as JSON.

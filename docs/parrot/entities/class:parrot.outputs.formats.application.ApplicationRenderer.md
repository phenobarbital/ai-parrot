---
type: Wiki Entity
title: ApplicationRenderer
id: class:parrot.outputs.formats.application.ApplicationRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Renderer that wraps the Agent Response into a standalone Application.
relates_to:
- concept: class:parrot.outputs.formats.base.BaseRenderer
  rel: extends
---

# ApplicationRenderer

Defined in [`parrot.outputs.formats.application`](../summaries/mod:parrot.outputs.formats.application.md).

```python
class ApplicationRenderer(BaseRenderer)
```

Renderer that wraps the Agent Response into a standalone Application.
Supports: Streamlit, Panel.

## Methods

- `async def render(self, response: Any, environment: str='terminal', app_type: str='streamlit', **kwargs) -> Tuple[Any, Any]` — Render response using the requested Application Generator.

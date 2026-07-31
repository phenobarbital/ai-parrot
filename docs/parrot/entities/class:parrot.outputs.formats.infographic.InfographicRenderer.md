---
type: Wiki Entity
title: InfographicRenderer
id: class:parrot.outputs.formats.infographic.InfographicRenderer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Renderer for structured infographic output.
relates_to:
- concept: class:parrot.outputs.formats.base.BaseRenderer
  rel: extends
---

# InfographicRenderer

Defined in [`parrot.outputs.formats.infographic`](../summaries/mod:parrot.outputs.formats.infographic.md).

```python
class InfographicRenderer(BaseRenderer)
```

Renderer for structured infographic output.

Validates and serializes InfographicResponse blocks as JSON.
The frontend is responsible for visual rendering.

## Methods

- `async def render(self, response: Any, environment: str='default', **kwargs) -> Tuple[str, Optional[Any]]` — Render infographic response as structured JSON.

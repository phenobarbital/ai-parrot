---
type: Wiki Entity
title: Jinja2Renderer
id: class:parrot.outputs.formats.jinja2.Jinja2Renderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Renders the output using a Jinja2 template.
relates_to:
- concept: class:parrot.outputs.formats.base.BaseRenderer
  rel: extends
---

# Jinja2Renderer

Defined in [`parrot.outputs.formats.jinja2`](../summaries/mod:parrot.outputs.formats.jinja2.md).

```python
class Jinja2Renderer(BaseRenderer)
```

Renders the output using a Jinja2 template.

## Methods

- `async def render(self, data: Any, **kwargs: Any) -> Tuple[str, str]` — Renders data using a Jinja2 template asynchronously.

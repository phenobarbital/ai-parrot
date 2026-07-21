---
type: Wiki Entity
title: HTMLRenderer
id: class:parrot.outputs.formats.html.HTMLRenderer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Renderer for HTML output using Panel or simple HTML fallback
relates_to:
- concept: class:parrot.outputs.formats.base.BaseRenderer
  rel: extends
---

# HTMLRenderer

Defined in [`parrot.outputs.formats.html`](../summaries/mod:parrot.outputs.formats.html.md).

```python
class HTMLRenderer(BaseRenderer)
```

Renderer for HTML output using Panel or simple HTML fallback

## Methods

- `async def render(self, response: Any, **kwargs) -> Tuple[Any, Optional[str]]` — Render response as HTML, returning a primary content object and a wrapped HTML string.

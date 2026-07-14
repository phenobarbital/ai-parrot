---
type: Wiki Entity
title: AbstractFormRenderer
id: class:parrot.forms.renderers.base.AbstractFormRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base for form renderers.
---

# AbstractFormRenderer

Defined in [`parrot.forms.renderers.base`](../summaries/mod:parrot.forms.renderers.base.md).

```python
class AbstractFormRenderer(ABC)
```

Abstract base for form renderers.

Subclasses implement render() to convert a FormSchema into a
platform-specific representation (Adaptive Card, HTML5, JSON Schema, etc.).

The render() method is async to support renderers that may need
to fetch dynamic options or perform I/O.

## Methods

- `async def render(self, form: FormSchema, style: StyleSchema | None=None, *, locale: str='en', prefilled: dict[str, Any] | None=None, errors: dict[str, str] | None=None) -> RenderedForm` — Render a FormSchema into the target format.

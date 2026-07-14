---
type: Wiki Entity
title: FallbackRenderer
id: class:parrot_formdesigner.renderers.base.FallbackRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Concrete fallback emitter — degraded representation.
---

# FallbackRenderer

Defined in [`parrot_formdesigner.renderers.base`](../summaries/mod:parrot_formdesigner.renderers.base.md).

```python
class FallbackRenderer
```

Concrete fallback emitter — degraded representation.

Each renderer subclasses or instantiates this to define what 'degraded'
means for its target. The base implementation returns None — subclasses
must override render() to emit target-appropriate content.

Warning appending is the renderer's responsibility (it has access to
RenderedForm.warnings once Module 8 is merged).

## Methods

- `async def render(self, field: FormField, *, locale: str='en', prefilled: Any=None, error: str | None=None) -> Any` — Return None as placeholder. Override in renderer-specific subclasses.

---
type: Wiki Entity
title: AbstractA2UIRenderer
id: class:parrot.outputs.a2ui.renderers.AbstractA2UIRenderer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract base for every A2UI renderer (spec §2 New Public Interfaces).
---

# AbstractA2UIRenderer

Defined in [`parrot.outputs.a2ui.renderers`](../summaries/mod:parrot.outputs.a2ui.renderers.md).

```python
class AbstractA2UIRenderer(ABC)
```

Abstract base for every A2UI renderer (spec §2 New Public Interfaces).

Subclasses MUST declare a :class:`RendererCapabilities` class attribute
``capabilities`` and implement the async :meth:`render`.

## Methods

- `async def render(self, envelope: CreateSurface, *, bake: bool=True) -> 'Any | str'` — Render an envelope to a ``RenderedArtifact`` (baked) or a string.

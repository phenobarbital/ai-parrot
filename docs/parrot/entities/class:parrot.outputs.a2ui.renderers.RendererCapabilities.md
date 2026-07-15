---
type: Wiki Entity
title: RendererCapabilities
id: class:parrot.outputs.a2ui.renderers.RendererCapabilities
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Declared capabilities of an A2UI renderer (spec §2 Data Models).
---

# RendererCapabilities

Defined in [`parrot.outputs.a2ui.renderers`](../summaries/mod:parrot.outputs.a2ui.renderers.md).

```python
class RendererCapabilities(BaseModel)
```

Declared capabilities of an A2UI renderer (spec §2 Data Models).

Attributes:
    interactive: Whether the surface supports live interaction.
    supports_actions: Whether the renderer can dispatch component actions.
    supports_updates: Whether the renderer supports incremental updates.
    output: The output mime type (e.g. ``"text/html"``, ``"application/pdf"``)
        or the literal ``"live"`` for interactive live surfaces.

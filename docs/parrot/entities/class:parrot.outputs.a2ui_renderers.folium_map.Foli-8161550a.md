---
type: Wiki Entity
title: FoliumMapRenderer
id: class:parrot.outputs.a2ui_renderers.folium_map.FoliumMapRenderer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Deterministic Map-component → folium HTML renderer.
relates_to:
- concept: class:parrot.outputs.a2ui.renderers.AbstractA2UIRenderer
  rel: extends
---

# FoliumMapRenderer

Defined in [`parrot.outputs.a2ui_renderers.folium_map`](../summaries/mod:parrot.outputs.a2ui_renderers.folium_map.md).

```python
class FoliumMapRenderer(AbstractA2UIRenderer)
```

Deterministic Map-component → folium HTML renderer.

## Methods

- `async def render(self, envelope: CreateSurface, *, bake: bool=True) -> RenderedArtifact` — Render the first Map component to a folium HTML ``RenderedArtifact``.

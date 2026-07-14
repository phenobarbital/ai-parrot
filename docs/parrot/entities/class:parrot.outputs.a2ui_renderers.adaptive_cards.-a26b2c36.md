---
type: Wiki Entity
title: AdaptiveCardsRenderer
id: class:parrot.outputs.a2ui_renderers.adaptive_cards.AdaptiveCardsRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Basic-tree → Adaptive Card JSON renderer (display subset, no actions).
relates_to:
- concept: class:parrot.outputs.a2ui.renderers.AbstractA2UIRenderer
  rel: extends
---

# AdaptiveCardsRenderer

Defined in [`parrot.outputs.a2ui_renderers.adaptive_cards`](../summaries/mod:parrot.outputs.a2ui_renderers.adaptive_cards.md).

```python
class AdaptiveCardsRenderer(AbstractA2UIRenderer)
```

Basic-tree → Adaptive Card JSON renderer (display subset, no actions).

## Methods

- `async def render(self, envelope: CreateSurface, *, bake: bool=True, deep_links: Optional[list[DeepLink]]=None) -> RenderedArtifact` — Render an envelope to a baked Adaptive Card ``RenderedArtifact``.

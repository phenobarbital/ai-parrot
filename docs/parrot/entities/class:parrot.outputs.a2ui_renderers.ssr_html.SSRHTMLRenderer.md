---
type: Wiki Entity
title: SSRHTMLRenderer
id: class:parrot.outputs.a2ui_renderers.ssr_html.SSRHTMLRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Static, self-contained HTML renderer for A2UI envelopes.
relates_to:
- concept: class:parrot.outputs.a2ui.renderers.AbstractA2UIRenderer
  rel: extends
---

# SSRHTMLRenderer

Defined in [`parrot.outputs.a2ui_renderers.ssr_html`](../summaries/mod:parrot.outputs.a2ui_renderers.ssr_html.md).

```python
class SSRHTMLRenderer(AbstractA2UIRenderer)
```

Static, self-contained HTML renderer for A2UI envelopes.

## Methods

- `async def render(self, envelope: CreateSurface, *, bake: bool=True, deep_links: Optional[list[DeepLink]]=None) -> RenderedArtifact` — Render an envelope to a baked, self-contained HTML ``RenderedArtifact``.

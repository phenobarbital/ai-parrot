---
type: Wiki Entity
title: PDFRenderer
id: class:parrot.outputs.a2ui_renderers.pdf.PDFRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: weasyprint-backed PDF renderer (SSR-HTML → static SVG charts → PDF).
relates_to:
- concept: class:parrot.outputs.a2ui.renderers.AbstractA2UIRenderer
  rel: extends
---

# PDFRenderer

Defined in [`parrot.outputs.a2ui_renderers.pdf`](../summaries/mod:parrot.outputs.a2ui_renderers.pdf.md).

```python
class PDFRenderer(AbstractA2UIRenderer)
```

weasyprint-backed PDF renderer (SSR-HTML → static SVG charts → PDF).

## Methods

- `async def render(self, envelope: CreateSurface, *, bake: bool=True, deep_links=None) -> RenderedArtifact` — Render an envelope to a PDF ``RenderedArtifact`` (weasyprint).

---
type: Wiki Summary
title: parrot.outputs.a2ui_renderers.ssr_html
id: mod:parrot.outputs.a2ui_renderers.ssr_html
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: SSR-HTML renderer (Module 5, satellite).
relates_to:
- concept: class:parrot.outputs.a2ui_renderers.ssr_html.SSRHTMLRenderer
  rel: defines
- concept: mod:parrot.outputs.a2ui.artifacts
  rel: references
- concept: mod:parrot.outputs.a2ui.baking
  rel: references
- concept: mod:parrot.outputs.a2ui.catalog
  rel: references
- concept: mod:parrot.outputs.a2ui.catalog.base
  rel: references
- concept: mod:parrot.outputs.a2ui.catalog.components
  rel: references
- concept: mod:parrot.outputs.a2ui.models
  rel: references
- concept: mod:parrot.outputs.a2ui.renderers
  rel: references
---

# `parrot.outputs.a2ui_renderers.ssr_html`

SSR-HTML renderer (Module 5, satellite).

Turns a validated ``CreateSurface`` envelope into a single self-contained, baked HTML
document. It is the backbone of static delivery (G5): the PDF renderer rasterizes its
output and email attaches it directly.

Security invariants (spec G1):

* Subclasses the core :class:`AbstractA2UIRenderer` — never the legacy ``BaseRenderer``
  (which holds the arbitrary-code sink FEAT-273 exists to kill).
* Every data value is HTML-escaped — envelope data is data, never markup/JS.
* Output is self-contained — all CSS inline, no external CDN/script/style/font refs.

## Classes

- **`SSRHTMLRenderer(AbstractA2UIRenderer)`** — Static, self-contained HTML renderer for A2UI envelopes.

---
type: Wiki Summary
title: parrot.outputs.formats.infographic_html
id: mod:parrot.outputs.formats.infographic_html
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Infographic HTML Renderer for AI-Parrot.
relates_to:
- concept: class:parrot.outputs.formats.infographic_html.InfographicHTMLRenderer
  rel: defines
- concept: mod:parrot.models.infographic
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
- concept: mod:parrot.outputs.formats
  rel: references
- concept: mod:parrot.outputs.formats.base
  rel: references
- concept: mod:parrot.outputs.formats.infographic
  rel: references
---

# `parrot.outputs.formats.infographic_html`

Infographic HTML Renderer for AI-Parrot.

Renders InfographicResponse structured output as a self-contained HTML5
document with inline CSS and (optionally) inline ECharts JS for charts.

This renderer is a sibling to InfographicRenderer (JSON); content
negotiation in get_infographic() decides which one to use.

## Classes

- **`InfographicHTMLRenderer(BaseRenderer)`** — Renders InfographicResponse as a self-contained HTML5 document.

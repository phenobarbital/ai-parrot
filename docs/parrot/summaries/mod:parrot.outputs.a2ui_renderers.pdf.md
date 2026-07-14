---
type: Wiki Summary
title: parrot.outputs.a2ui_renderers.pdf
id: mod:parrot.outputs.a2ui_renderers.pdf
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: PDF renderer (Module 5, satellite) — SPK-1 backend = weasyprint.
relates_to:
- concept: class:parrot.outputs.a2ui_renderers.pdf.PDFRenderer
  rel: defines
- concept: mod:parrot.outputs.a2ui.artifacts
  rel: references
- concept: mod:parrot.outputs.a2ui.baking
  rel: references
- concept: mod:parrot.outputs.a2ui.catalog.components
  rel: references
- concept: mod:parrot.outputs.a2ui.models
  rel: references
- concept: mod:parrot.outputs.a2ui.renderers
  rel: references
- concept: mod:parrot.outputs.a2ui_renderers.ssr_html
  rel: references
---

# `parrot.outputs.a2ui_renderers.pdf`

PDF renderer (Module 5, satellite) — SPK-1 backend = weasyprint.

Closes the G5 static-delivery chain: envelope → baked SSR-HTML (TASK-1729) → static-SVG
chart pre-render → weasyprint rasterization → ``RenderedArtifact`` (PDF) suitable as a
``send_notification`` email attachment.

SPK-1 (TASK-1722) confirmed **weasyprint** as the default for all static artifact
classes (deterministic, no browser). weasyprint runs no JavaScript, so Chart components
are pre-rendered to **static SVG** (deterministic data→SVG) before rasterization — no
JS, no ``exec``. No playwright path is shipped (SPK-1 did not require a per-class split).

## Classes

- **`PDFRenderer(AbstractA2UIRenderer)`** — weasyprint-backed PDF renderer (SSR-HTML → static SVG charts → PDF).

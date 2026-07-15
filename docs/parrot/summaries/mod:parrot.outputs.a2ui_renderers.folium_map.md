---
type: Wiki Summary
title: parrot.outputs.a2ui_renderers.folium_map
id: mod:parrot.outputs.a2ui_renderers.folium_map
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Folium map renderer (Module 5, satellite).
relates_to:
- concept: class:parrot.outputs.a2ui_renderers.folium_map.FoliumMapRenderer
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
---

# `parrot.outputs.a2ui_renderers.folium_map`

Folium map renderer (Module 5, satellite).

Deterministic replacement for the legacy ``formats/map.py`` ``FoliumRenderer`` (which
executed LLM-generated Python via the arbitrary-code sink). This renderer builds the map
**only through folium's Python API from the baked Map component's data** — no code
strings, no ``exec``, nothing LLM-authored.

``folium`` is imported lazily with an actionable error. Note: folium's own generated
HTML references tile-server URLs at *view* time (a runtime map-tile concern, not a
render dependency); the PDF path uses SSR alternatives (TASK-1732).

## Classes

- **`FoliumMapRenderer(AbstractA2UIRenderer)`** — Deterministic Map-component → folium HTML renderer.

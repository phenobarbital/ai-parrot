---
type: Wiki Summary
title: parrot.outputs.a2ui.catalog.components.map
id: mod:parrot.outputs.a2ui.catalog.components.map
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: A2UI ``Map`` catalog component (Module 3).
relates_to:
- concept: class:parrot.outputs.a2ui.catalog.components.map.MapComponent
  rel: defines
- concept: mod:parrot.outputs.a2ui.catalog
  rel: references
- concept: mod:parrot.outputs.a2ui.catalog.base
  rel: references
- concept: mod:parrot.outputs.a2ui.models
  rel: references
---

# `parrot.outputs.a2ui.catalog.components.map`

A2UI ``Map`` catalog component (Module 3).

Schema vocabulary is adapted from ``StructuredMapConfig``/``MapLayer``/``MapViewport``
(``parrot.models.outputs``): ``layers``, ``viewport``, ``baseLayer``, ``title``,
``description``. The INPUT-ONLY ``data`` array is replaced by a data-model binding.

``lower()`` degrades a Map to a static-friendly Basic tree (title/description Text
plus a layer-summary Column). Interactive tiles are the folium-map renderer's native
path (Module 5, satellite) — no geo/folium markup appears in the lowered tree.

## Classes

- **`MapComponent`** — The ``Map`` catalog component (display-only, ``requires_actions=False``).

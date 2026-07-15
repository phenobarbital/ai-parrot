---
type: Wiki Summary
title: parrot.outputs.a2ui.catalog.components.timeline
id: mod:parrot.outputs.a2ui.catalog.components.timeline
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: A2UI ``Timeline`` catalog component (Module 3).
relates_to:
- concept: class:parrot.outputs.a2ui.catalog.components.timeline.TimelineComponent
  rel: defines
- concept: mod:parrot.outputs.a2ui.catalog
  rel: references
- concept: mod:parrot.outputs.a2ui.catalog.base
  rel: references
- concept: mod:parrot.outputs.a2ui.models
  rel: references
---

# `parrot.outputs.a2ui.catalog.components.timeline`

A2UI ``Timeline`` catalog component (Module 3).

Net-new vocabulary: an ordered list of ``events`` each with ``timestamp``, ``title``,
``description``. Lowering keeps events in INPUT order (never re-sorted — determinism
and author intent). Display-only (``requires_actions=False``).

## Classes

- **`TimelineComponent`** — The ``Timeline`` catalog component (display-only).

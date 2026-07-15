---
type: Wiki Summary
title: parrot.outputs.a2ui_renderers.adaptive_cards
id: mod:parrot.outputs.a2ui_renderers.adaptive_cards
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Adaptive Cards renderer (Module 5, satellite).
relates_to:
- concept: class:parrot.outputs.a2ui_renderers.adaptive_cards.AdaptiveCardsRenderer
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

# `parrot.outputs.a2ui_renderers.adaptive_cards`

Adaptive Cards renderer (Module 5, satellite).

Transcodes A2UI envelopes into Adaptive Card JSON for Teams-style surfaces. It is the
"AC fallback transcode" lane: it consumes LOWERED Basic Catalog trees only — mandatory
lowering (G4) guarantees every Parrot component has one, so this renderer needs no
per-component knowledge of the custom catalog.

v1 is a **display subset**: display elements only (TextBlock / Container / ColumnSet /
Image). NO ``Action.*`` elements are ever emitted — action dispatch is FEAT-B, and
static-surface actions degrade via deep links rendered as display text (G6).

## Classes

- **`AdaptiveCardsRenderer(AbstractA2UIRenderer)`** — Basic-tree → Adaptive Card JSON renderer (display subset, no actions).

---
type: Wiki Summary
title: parrot.outputs.a2ui.catalog.components.form
id: mod:parrot.outputs.a2ui.catalog.components.form
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: A2UI ``Form`` catalog component (Module 3) — the one ``requires_actions=True``
relates_to:
- concept: class:parrot.outputs.a2ui.catalog.components.form.FormComponent
  rel: defines
- concept: mod:parrot.outputs.a2ui.catalog
  rel: references
- concept: mod:parrot.outputs.a2ui.catalog.base
  rel: references
- concept: mod:parrot.outputs.a2ui.models
  rel: references
---

# `parrot.outputs.a2ui.catalog.components.form`

A2UI ``Form`` catalog component (Module 3) — the one ``requires_actions=True``
component in v1 (resolved OQ-B, spec §8).

Form ships **schema + instructions** for the complete v1.0 message set, but no
renderer supports it in v1. Because TASK-1721's registry enforces the mandatory
``lower()`` contract (G4, literal), Form ships a minimal read-only degraded
lowering: a Column of field-label Texts plus a "form not available on this surface"
notice (spec §7 "Known Risks" — actions stripped + visible notice). Submission,
`action`/`actionResponse` dispatch, and rendering are FEAT-B territory.

## Classes

- **`FormComponent`** — The ``Form`` catalog component (action-bearing; schema-only in v1).

---
id: F012
query_id: Q011
type: read
intent: Prior scope of the Adaptive Card renderer task
executed_at: 2026-09-10T22:27:13Z
duration_ms: 0
parent_id: null
depth: 0
---

# F012 — TASK-524 — original AdaptiveCardRenderer scope

## Summary
TASK-524 (form-abstraction-layer, Module 7) migrated `AdaptiveCardBuilder` from `msteams/dialogs/card_builder.py` into `AdaptiveCardRenderer`, targeting Bot Framework/Teams AC v1.5 with wizard/summary/error cards and i18n. Its "NOT in scope" excluded Teams dialog presets (TASK-532). Nothing about a standalone submit target or upload was in scope; the renderer was designed for the in-dialog flow where the Teams bot owns state.

## Citations
- path: `sdd/tasks/completed/TASK-524-adaptive-card-renderer.md`
  lines: 15-30
  excerpt: |
    Migrates AdaptiveCardBuilder from parrot/integrations/msteams/dialogs/card_builder.py ...
    Map StyleSchema.layout to rendering mode: WIZARD → section-by-section, SINGLE_COLUMN → complete form
    NOT in scope: HTML5 renderer (TASK-525), JSON Schema renderer (TASK-526), Teams dialog presets (TASK-532).
- path: `sdd/tasks/completed/TASK-524-adaptive-card-renderer.md`
  lines: 55-62
  excerpt: |
    Output must be compatible with MS Teams Bot Framework Adaptive Card schema v1.5

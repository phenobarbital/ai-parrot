---
type: Wiki Summary
title: parrot_formdesigner.renderers.adaptive_card
id: mod:parrot_formdesigner.renderers.adaptive_card
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Adaptive Card renderer for FormSchema.
relates_to:
- concept: class:parrot_formdesigner.renderers.adaptive_card.AdaptiveCardRenderer
  rel: defines
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.core.style
  rel: references
- concept: mod:parrot_formdesigner.core.types
  rel: references
- concept: mod:parrot_formdesigner.renderers.base
  rel: references
---

# `parrot_formdesigner.renderers.adaptive_card`

Adaptive Card renderer for FormSchema.

Migrated and extended from parrot/integrations/msteams/dialogs/card_builder.py.
Produces valid Adaptive Card JSON (schema v1.5) from FormSchema + StyleSchema.

## Classes

- **`AdaptiveCardRenderer(AbstractFormRenderer)`** — Renders FormSchema as Adaptive Card JSON for MS Teams.

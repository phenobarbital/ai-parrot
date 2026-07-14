---
type: Wiki Summary
title: parrot.forms.renderers.adaptive_card
id: mod:parrot.forms.renderers.adaptive_card
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Adaptive Card renderer for FormSchema.
relates_to:
- concept: class:parrot.forms.renderers.adaptive_card.AdaptiveCardRenderer
  rel: defines
- concept: mod:parrot.forms.renderers.base
  rel: references
- concept: mod:parrot.forms.schema
  rel: references
- concept: mod:parrot.forms.style
  rel: references
- concept: mod:parrot.forms.types
  rel: references
---

# `parrot.forms.renderers.adaptive_card`

Adaptive Card renderer for FormSchema.

Migrated and extended from parrot/integrations/msteams/dialogs/card_builder.py.
Produces valid Adaptive Card JSON (schema v1.5) from FormSchema + StyleSchema.

## Classes

- **`AdaptiveCardRenderer(AbstractFormRenderer)`** — Renders FormSchema as Adaptive Card JSON for MS Teams.

---
type: Wiki Summary
title: parrot.integrations.msteams.dialogs.presets.conversational
id: mod:parrot.integrations.msteams.dialogs.presets.conversational
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Conversational Form Dialog - One prompt per field, text-based interaction.
relates_to:
- concept: class:parrot.integrations.msteams.dialogs.presets.conversational.ConversationalFormDialog
  rel: defines
- concept: mod:parrot.forms
  rel: references
- concept: mod:parrot.integrations.msteams.dialogs.presets.base
  rel: references
---

# `parrot.integrations.msteams.dialogs.presets.conversational`

Conversational Form Dialog - One prompt per field, text-based interaction.

Uses BotBuilder's native prompts instead of Adaptive Cards.
Useful for:
- More natural conversation flow
- Channels with limited Adaptive Card support
- Complex fields requiring contextual help
- Accessibility considerations

## Classes

- **`ConversationalFormDialog(BaseFormDialog)`** — Conversational form using native BotBuilder prompts.

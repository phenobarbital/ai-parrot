---
type: Wiki Entity
title: ConversationalFormDialog
id: class:parrot.integrations.msteams.dialogs.presets.conversational.ConversationalFormDialog
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Conversational form using native BotBuilder prompts.
relates_to:
- concept: class:parrot.integrations.msteams.dialogs.presets.base.BaseFormDialog
  rel: extends
---

# ConversationalFormDialog

Defined in [`parrot.integrations.msteams.dialogs.presets.conversational`](../summaries/mod:parrot.integrations.msteams.dialogs.presets.con-069250bf.md).

```python
class ConversationalFormDialog(BaseFormDialog)
```

Conversational form using native BotBuilder prompts.

Each field becomes a separate prompt in the waterfall.
Supports:
- TextPrompt for text fields
- NumberPrompt for numeric fields
- ChoicePrompt for single choice
- ConfirmPrompt for boolean/toggle
- DateTimePrompt for dates

Features:
- Field-level validation with retry
- Contextual help messages
- Skip optional fields
- Back navigation (restart)

Flow:
1. "What is your first name?"
2. User types: "John"
3. "What is your email?"
4. User types: "john@example.com"
5. ... continues for each field ...
6. "All done! Here's your summary..."

## Methods

- `async def intro_step(self, step_context: WaterfallStepContext) -> DialogTurnResult` — Introduction step with form title and instructions.
- `async def summary_step(self, step_context: WaterfallStepContext) -> DialogTurnResult` — Show summary and complete.

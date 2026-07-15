---
type: Wiki Entity
title: SimpleFormDialog
id: class:parrot.integrations.msteams.dialogs.presets.simple_form.SimpleFormDialog
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Single Adaptive Card containing all form fields.
relates_to:
- concept: class:parrot.integrations.msteams.dialogs.presets.base.BaseFormDialog
  rel: extends
---

# SimpleFormDialog

Defined in [`parrot.integrations.msteams.dialogs.presets.simple_form`](../summaries/mod:parrot.integrations.msteams.dialogs.presets.simple_form.md).

```python
class SimpleFormDialog(BaseFormDialog)
```

Single Adaptive Card containing all form fields.

Best for:
- Forms with 5 or fewer fields
- Quick data collection
- Simple workflows

Flow:
1. Show complete form
2. User fills and submits
3. Validate → show errors OR complete

## Methods

- `async def show_form_step(self, step_context: WaterfallStepContext) -> DialogTurnResult` — Show the complete form as a single Adaptive Card.
- `async def process_submission_step(self, step_context: WaterfallStepContext) -> DialogTurnResult` — Process the submitted form data.

---
type: Wiki Entity
title: WizardFormDialog
id: class:parrot.integrations.msteams.dialogs.presets.wizard.WizardFormDialog
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Multi-step wizard dialog with one section per step.
relates_to:
- concept: class:parrot.integrations.msteams.dialogs.presets.base.BaseFormDialog
  rel: extends
---

# WizardFormDialog

Defined in [`parrot.integrations.msteams.dialogs.presets.wizard`](../summaries/mod:parrot.integrations.msteams.dialogs.presets.wizard.md).

```python
class WizardFormDialog(BaseFormDialog)
```

Multi-step wizard dialog with one section per step.

Features:
- Progress indicator
- Back/Next navigation
- Per-section validation
- Skip optional sections

Flow:
1. Show Section 1
2. User fills → validates → Next
3. Show Section 2
4. ... repeat ...
5. Final section → Submit

## Methods

- `async def final_step(self, step_context: WaterfallStepContext) -> DialogTurnResult` — Final step: validate last section and complete.

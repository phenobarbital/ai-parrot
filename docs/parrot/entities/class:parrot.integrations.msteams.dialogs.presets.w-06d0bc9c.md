---
type: Wiki Entity
title: WizardWithSummaryDialog
id: class:parrot.integrations.msteams.dialogs.presets.wizard_summary.WizardWithSummaryDialog
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Multi-step wizard with a final summary/confirmation step.
relates_to:
- concept: class:parrot.integrations.msteams.dialogs.presets.wizard.WizardFormDialog
  rel: extends
---

# WizardWithSummaryDialog

Defined in [`parrot.integrations.msteams.dialogs.presets.wizard_summary`](../summaries/mod:parrot.integrations.msteams.dialogs.presets.wiz-c34fadf0.md).

```python
class WizardWithSummaryDialog(WizardFormDialog)
```

Multi-step wizard with a final summary/confirmation step.

Features:
- All wizard features
- Summary card before final submit
- Optional LLM-generated summary
- Edit option to go back

Flow:
1. Section 1 → Section 2 → ... → Section N
2. Summary/Confirmation card
3. User confirms → Complete OR User edits → Back to step 1

## Methods

- `async def summary_step(self, step_context: WaterfallStepContext) -> DialogTurnResult` — Show summary of all collected data.
- `async def confirmation_step(self, step_context: WaterfallStepContext) -> DialogTurnResult` — Process confirmation response.

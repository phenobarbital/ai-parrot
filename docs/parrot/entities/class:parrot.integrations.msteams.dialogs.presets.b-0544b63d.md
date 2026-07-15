---
type: Wiki Entity
title: BaseFormDialog
id: class:parrot.integrations.msteams.dialogs.presets.base.BaseFormDialog
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Base class for all form dialog presets.
---

# BaseFormDialog

Defined in [`parrot.integrations.msteams.dialogs.presets.base`](../summaries/mod:parrot.integrations.msteams.dialogs.presets.base.md).

```python
class BaseFormDialog(ComponentDialog)
```

Base class for all form dialog presets.

Provides:
- State management helpers (via step_context.values)
- Adaptive Card sending utilities (via _get_card_renderer())
- Validation integration (via _get_validator())

NOTE: This dialog stores ONLY the form_id (a string) to avoid jsonpickle
serialization issues. Complex objects are accessed via:
- form: looked up from registry via form_id
- renderer/validator: created fresh per-use
- agent: accessed from turn_state
- callbacks: handled by wrapper after dialog ends

## Methods

- `def form(self) -> FormSchema` — Get the form from the global registry.
- `def style(self) -> Optional[StyleSchema]` — Get the style from the global registry.
- `def get_form_data(self, step_context: WaterfallStepContext) -> Dict[str, Any]` — Get accumulated form data from step_context.values (persists across steps).
- `def set_form_data(self, step_context: WaterfallStepContext, data: Dict[str, Any])` — Store form data in step_context.values.
- `def get_current_section(self, step_context: WaterfallStepContext) -> int` — Get current section index from step values.
- `def set_current_section(self, step_context: WaterfallStepContext, index: int)` — Set current section index in step values.
- `def get_validation_errors(self, step_context: WaterfallStepContext) -> Optional[Dict[str, str]]` — Get validation errors from step values.
- `def set_validation_errors(self, step_context: WaterfallStepContext, errors: Optional[Dict[str, str]])` — Store validation errors in step values.
- `def merge_submitted_data(self, step_context: WaterfallStepContext, submitted: Dict[str, Any]) -> Dict[str, Any]` — Merge submitted values with existing form data.
- `async def send_card(self, step_context: WaterfallStepContext, card: Dict[str, Any])` — Send an Adaptive Card.
- `async def send_section_card(self, step_context: WaterfallStepContext, section_index: int, show_back: bool=False)` — Build and send card for a section.
- `def get_submitted_action(self, step_context: WaterfallStepContext) -> Optional[str]` — Get the action from submitted data.
- `async def handle_cancel(self, step_context: WaterfallStepContext) -> DialogTurnResult` — Handle cancel action.
- `async def handle_complete(self, step_context: WaterfallStepContext, form_data: Dict[str, Any]) -> DialogTurnResult` — Handle form completion.

---
type: Wiki Entity
title: FormDialogFactory
id: class:parrot.integrations.msteams.dialogs.factory.FormDialogFactory
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Factory to create WaterfallDialogs from FormSchemas.
---

# FormDialogFactory

Defined in [`parrot.integrations.msteams.dialogs.factory`](../summaries/mod:parrot.integrations.msteams.dialogs.factory.md).

```python
class FormDialogFactory
```

Factory to create WaterfallDialogs from FormSchemas.

Supports different layouts:
- SINGLE_COLUMN: Single Adaptive Card with all fields
- WIZARD: One section per step
- ACCORDION: Accordion-style (treated as SINGLE_COLUMN)
- CONVERSATIONAL: One prompt per field

NOTE: Dialogs no longer accept card_builder, validator, callbacks, or agent
to avoid serialization issues with jsonpickle. These are accessed via:
- renderer/validator: created fresh via _get_card_renderer()/_get_validator()
- agent: accessed via turn_state
- callbacks: handled by wrapper after dialog ends

## Methods

- `def create_dialog(self, form: FormSchema, style: Optional[StyleSchema]=None, on_complete: Callable[[Dict[str, Any]], Awaitable[Any]]=None, on_cancel: Optional[Callable[[], Awaitable[Any]]]=None) -> ComponentDialog` — Create appropriate dialog based on form layout.

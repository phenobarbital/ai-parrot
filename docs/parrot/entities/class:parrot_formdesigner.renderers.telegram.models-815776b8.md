---
type: Wiki Entity
title: FormFieldCallback
id: class:parrot_formdesigner.renderers.telegram.models.FormFieldCallback
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Compact callback data for inline form field selections.
relates_to:
- concept: class:parrot.integrations.telegram.callbacks.CallbackData
  rel: extends
---

# FormFieldCallback

Defined in [`parrot_formdesigner.renderers.telegram.models`](../summaries/mod:parrot_formdesigner.renderers.telegram.models.md).

```python
class FormFieldCallback(CallbackData)
```

Compact callback data for inline form field selections.

Encodes form hash, field index, and option index within the
64-byte Telegram callback_data limit.

Attributes:
    fh: Short hash of form_id (max 8 chars).
    fi: Field index in the flattened field list.
    oi: Selected option index (-1 for special actions like 'done').

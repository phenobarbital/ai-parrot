---
type: Wiki Entity
title: FormActionCallback
id: class:parrot_formdesigner.renderers.telegram.models.FormActionCallback
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Callback data for form-level actions (submit, cancel).
relates_to:
- concept: class:parrot.integrations.telegram.callbacks.CallbackData
  rel: extends
---

# FormActionCallback

Defined in [`parrot_formdesigner.renderers.telegram.models`](../summaries/mod:parrot_formdesigner.renderers.telegram.models.md).

```python
class FormActionCallback(CallbackData)
```

Callback data for form-level actions (submit, cancel).

Attributes:
    fh: Short hash of form_id (max 8 chars).
    act: Action identifier ('submit', 'cancel', 'done').

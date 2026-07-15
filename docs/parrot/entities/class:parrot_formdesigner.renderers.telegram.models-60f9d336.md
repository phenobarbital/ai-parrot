---
type: Wiki Entity
title: TelegramFormStep
id: class:parrot_formdesigner.renderers.telegram.models.TelegramFormStep
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A single step in an inline keyboard form conversation.
---

# TelegramFormStep

Defined in [`parrot_formdesigner.renderers.telegram.models`](../summaries/mod:parrot_formdesigner.renderers.telegram.models.md).

```python
class TelegramFormStep(BaseModel)
```

A single step in an inline keyboard form conversation.

Attributes:
    field_id: The field this step collects data for.
    message_text: Prompt text sent to the user.
    reply_markup: Serialized InlineKeyboardMarkup dict.
    field_type: The FieldType of the underlying form field.
    required: Whether this field is required.
    options: List of (value, label) pairs for select-type fields.

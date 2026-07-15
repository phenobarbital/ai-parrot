---
type: Wiki Entity
title: FormSchema
id: class:parrot.forms.schema.FormSchema
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: The canonical representation of a complete form.
---

# FormSchema

Defined in [`parrot.forms.schema`](../summaries/mod:parrot.forms.schema.md).

```python
class FormSchema(BaseModel)
```

The canonical representation of a complete form.

FormSchema is the central data model of the forms abstraction layer.
It is platform-agnostic and can be rendered to Adaptive Cards, HTML5,
JSON Schema, or any other format via the renderer system.

Attributes:
    form_id: Unique identifier for this form.
    version: Schema version string.
    title: Human-readable form title.
    description: Optional description of the form's purpose.
    sections: Ordered list of form sections.
    submit: Optional submission action configuration.
    cancel_allowed: Whether the user can cancel/dismiss the form.
    meta: Arbitrary metadata for renderer-specific extensions.

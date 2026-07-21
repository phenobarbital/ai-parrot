---
type: Wiki Entity
title: StyleSchema
id: class:parrot.forms.style.StyleSchema
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Presentation style configuration for a form.
---

# StyleSchema

Defined in [`parrot.forms.style`](../summaries/mod:parrot.forms.style.md).

```python
class StyleSchema(BaseModel)
```

Presentation style configuration for a form.

StyleSchema is kept separate from FormSchema to allow the same
form definition to be rendered differently in different contexts.

Attributes:
    layout: The overall layout mode.
    field_styles: Per-field style overrides keyed by field_id.
    show_section_numbers: Whether to prefix section titles with numbers.
    submit_label: Label for the submit button.
    cancel_label: Label for the cancel button.
    theme: Renderer-specific theme identifier.
    meta: Arbitrary metadata for renderer-specific extensions.

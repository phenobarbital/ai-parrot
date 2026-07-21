---
type: Wiki Entity
title: FormField
id: class:parrot.forms.schema.FormField
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single field within a form section.
---

# FormField

Defined in [`parrot.forms.schema`](../summaries/mod:parrot.forms.schema.md).

```python
class FormField(BaseModel)
```

A single field within a form section.

FormField is self-referential: GROUP fields can have children,
and ARRAY fields can have an item_template defining the repeated element.

Attributes:
    field_id: Unique identifier for this field within the form.
    field_type: The type of input control to render.
    label: Human-readable label shown to the user.
    description: Optional extended description or help text.
    placeholder: Optional placeholder text shown when the field is empty.
    required: Whether this field must be filled before submission.
    default: Default value for the field.
    read_only: Whether the field is displayed but cannot be edited.
    constraints: Validation constraints applied to this field.
    options: Static list of options for select/multi-select fields.
    options_source: Dynamic options source configuration.
    depends_on: Dependency rule controlling conditional visibility.
    children: Child fields for GROUP type fields.
    item_template: Template for items in ARRAY type fields.
    meta: Arbitrary metadata for renderer-specific extensions.

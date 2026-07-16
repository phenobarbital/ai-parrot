---
type: Wiki Entity
title: FieldOption
id: class:parrot.forms.options.FieldOption
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single option in a select or multi-select field.
---

# FieldOption

Defined in [`parrot.forms.options`](../summaries/mod:parrot.forms.options.md).

```python
class FieldOption(BaseModel)
```

A single option in a select or multi-select field.

Attributes:
    value: The machine-readable value submitted with the form.
    label: The human-readable label shown to the user.
    description: Optional extended description of the option.
    disabled: Whether this option is disabled and cannot be selected.
    icon: Optional icon identifier or URL to display alongside the option.

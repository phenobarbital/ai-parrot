---
type: Wiki Entity
title: FieldOption
id: class:parrot_formdesigner.core.options.FieldOption
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A single option in a select or multi-select field.
---

# FieldOption

Defined in [`parrot_formdesigner.core.options`](../summaries/mod:parrot_formdesigner.core.options.md).

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

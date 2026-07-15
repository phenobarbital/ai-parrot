---
type: Wiki Entity
title: FieldCondition
id: class:parrot_formdesigner.core.constraints.FieldCondition
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A single condition referencing another field's value.
---

# FieldCondition

Defined in [`parrot_formdesigner.core.constraints`](../summaries/mod:parrot_formdesigner.core.constraints.md).

```python
class FieldCondition(BaseModel)
```

A single condition referencing another field's value.

Attributes:
    field_id: The ID of the field to evaluate.
    operator: The comparison operator to apply.
    value: The value to compare against (not required for IS_EMPTY/IS_NOT_EMPTY).

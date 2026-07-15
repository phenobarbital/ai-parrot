---
type: Wiki Entity
title: ReusableFieldRef
id: class:parrot_formdesigner.services.question_bank.ReusableFieldRef
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A reference to a ``ReusableField`` with optional field-level overrides.
---

# ReusableFieldRef

Defined in [`parrot_formdesigner.services.question_bank`](../summaries/mod:parrot_formdesigner.services.question_bank.md).

```python
class ReusableFieldRef(BaseModel)
```

A reference to a ``ReusableField`` with optional field-level overrides.

When resolved via :meth:`QuestionBankService.resolve_ref`, the returned
``FormField`` is a deep copy of the bank definition with ``overrides``
applied on top.

Attributes:
    bank_field_id: The ``ReusableField.field_id`` to look up.
    overrides: Optional dict of ``FormField`` field-level attribute
        overrides (e.g. ``{"label": "New Label", "required": True}``).

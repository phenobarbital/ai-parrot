---
type: Wiki Entity
title: ReusableField
id: class:parrot_formdesigner.services.question_bank.ReusableField
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single entry in the tenant's QuestionBank.
---

# ReusableField

Defined in [`parrot_formdesigner.services.question_bank`](../summaries/mod:parrot_formdesigner.services.question_bank.md).

```python
class ReusableField(BaseModel)
```

A single entry in the tenant's QuestionBank.

Attributes:
    field_id: Unique identifier for this bank entry (UUID string).
    definition: The canonical ``FormField`` definition.
    tenant: Tenant slug that owns this entry.
    usage_forms: Number of forms that reference this entry.
    usage_responses: Cumulative response count across all referencing forms.
    created_at: UTC timestamp of creation.

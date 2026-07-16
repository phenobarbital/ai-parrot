---
type: Wiki Entity
title: ValidationResult
id: class:parrot_formdesigner.services.validators.ValidationResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Result of validating a form submission.
---

# ValidationResult

Defined in [`parrot_formdesigner.services.validators`](../summaries/mod:parrot_formdesigner.services.validators.md).

```python
class ValidationResult(BaseModel)
```

Result of validating a form submission.

Attributes:
    is_valid: Whether the entire submission passed validation.
    errors: Field-level error messages keyed by field_id.
    sanitized_data: Type-coerced and sanitized form data.

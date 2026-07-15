---
type: Wiki Entity
title: ValidationResult
id: class:parrot.forms.validators.ValidationResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Result of validating a form submission.
---

# ValidationResult

Defined in [`parrot.forms.validators`](../summaries/mod:parrot.forms.validators.md).

```python
class ValidationResult(BaseModel)
```

Result of validating a form submission.

Attributes:
    is_valid: Whether the entire submission passed validation.
    errors: Field-level error messages keyed by field_id.
    sanitized_data: Type-coerced and sanitized form data.

---
type: Wiki Entity
title: FormValidator
id: class:parrot_formdesigner.services.validators.FormValidator
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Platform-agnostic validator for FormSchema data.
---

# FormValidator

Defined in [`parrot_formdesigner.services.validators`](../summaries/mod:parrot_formdesigner.services.validators.md).

```python
class FormValidator
```

Platform-agnostic validator for FormSchema data.

Validates form submission data against FormSchema constraints,
including required checks, type coercion, regex patterns, numeric
bounds, cross-field rules, and circular dependency detection.

All validation methods are async to support ASYNC_REMOTE and UNIQUE
validation callbacks specified via FormField.meta.

Example:
    validator = FormValidator()
    result = await validator.validate(form_schema, submitted_data)
    if not result.is_valid:
        print(result.errors)

## Methods

- `async def validate(self, form: FormSchema, data: dict[str, Any], *, locale: str='en', auth_context: AuthContext | None=None) -> ValidationResult` — Validate all form submission data against the schema.
- `async def validate_field(self, field: FormField, value: Any, *, all_data: dict[str, Any] | None=None, locale: str='en', auth_context: AuthContext | None=None) -> list[str]` — Validate a single field value against its constraints.
- `def validate_rules(self, form: FormSchema) -> list[str]` — Validate rule integrity for all fields in the form.
- `def check_schema(self, form: FormSchema) -> list[str]` — Check a form schema for structural issues without submitted data.

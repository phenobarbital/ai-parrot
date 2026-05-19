---
id: F007
query: Q008
type: read
file: packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py
---

## Field-Level Validation (828 lines)

**FormValidator.validate_field()** (line 179): Validates a single field
value against its constraints. Returns `list[str]` of error messages.

Accepts: field, value, all_data, locale, auth_context.

**This enables per-field validation on partial saves.** When the frontend
sends a single answer, we can validate just that field and return
immediate feedback without requiring the full form.

**ValidationResult** (line 77): {is_valid, errors, sanitized_data}

**Coercion**: `_coerce_value()` handles all 52 field types.

For partial saves, we can optionally validate each field as it's saved
and return field-level errors immediately — useful for real-time
validation UX.

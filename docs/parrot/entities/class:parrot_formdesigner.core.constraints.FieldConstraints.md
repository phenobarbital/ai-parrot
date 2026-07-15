---
type: Wiki Entity
title: FieldConstraints
id: class:parrot_formdesigner.core.constraints.FieldConstraints
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Constraints applied to a form field for validation.
---

# FieldConstraints

Defined in [`parrot_formdesigner.core.constraints`](../summaries/mod:parrot_formdesigner.core.constraints.md).

```python
class FieldConstraints(BaseModel)
```

Constraints applied to a form field for validation.

Attributes:
    min_length: Minimum string length (>= 0).
    max_length: Maximum string length (>= 0).
    min_value: Minimum numeric value.
    max_value: Maximum numeric value.
    step: Numeric step increment.
    pattern: Regular expression pattern for validation. Validated at
        construction time to prevent ReDoS from malformed patterns.
    pattern_message: Human-readable message shown when pattern fails.
    min_items: Minimum number of items in array/multi-select fields (>= 0).
    max_items: Maximum number of items in array/multi-select fields (>= 0).
    allowed_mime_types: Allowed MIME types for file/image fields.
    max_file_size_bytes: Maximum file size in bytes for file/image fields (>= 0).

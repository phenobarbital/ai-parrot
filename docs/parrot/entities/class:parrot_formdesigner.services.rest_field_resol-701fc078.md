---
type: Wiki Entity
title: RestFieldResult
id: class:parrot_formdesigner.services.rest_field_resolver.RestFieldResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Output of ``RestFieldResolver.resolve()``.
---

# RestFieldResult

Defined in [`parrot_formdesigner.services.rest_field_resolver`](../summaries/mod:parrot_formdesigner.services.rest_field_resolver.md).

```python
class RestFieldResult(BaseModel)
```

Output of ``RestFieldResolver.resolve()``.

Never raises — all errors are captured here.

Warnings use the convention ``"<code>: <detail>"`` e.g.
``"jsonpath_miss: $.compliance_score"`` or
``"response_schema_mismatch: missing 'violations'"``.

Attributes:
    success: True when the resolver obtained a usable response.
    raw_value: Raw API / callback response before JSONPath extraction.
    answer: Value after JSONPath extraction (or ``raw_value`` if no path).
    blob_ref: Set by the upload handler after blob persistence.
    display: Rendered Jinja2 ``display_template`` string.
    status_code: HTTP status code (remote / internal modes only).
    warnings: Informational warning strings (NOT ``RenderWarning``).
    error: Human-readable error message on failure.

---
type: Wiki Entity
title: MetadataCallbackOutput
id: class:parrot_formdesigner.services.metadata_callbacks.MetadataCallbackOutput
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return value from a registered metadata-callback coroutine.
---

# MetadataCallbackOutput

Defined in [`parrot_formdesigner.services.metadata_callbacks`](../summaries/mod:parrot_formdesigner.services.metadata_callbacks.md).

```python
class MetadataCallbackOutput(BaseModel)
```

Return value from a registered metadata-callback coroutine.

A callback MAY return either a single value (stored under the
declaring field's ``key``) OR a fan-out dict of additional keys
merged into the submission. When ``values`` is set it takes
precedence over ``value``.

Attributes:
    success: Whether the callback completed successfully. ``False``
        triggers either the ``default`` substitution (when the
        field is not required) or a 422 (when it is).
    value: Single computed value, stored under the field's ``key``.
        Used only when ``values`` is ``None``.
    values: Optional fan-out dict merged flat into the submission.
        Every key must be a valid identifier — keys are checked at
        merge time by the enricher.
    error: Human-readable error message on failure (logged).

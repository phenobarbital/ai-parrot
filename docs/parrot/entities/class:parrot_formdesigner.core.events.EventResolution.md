---
type: Wiki Entity
title: EventResolution
id: class:parrot_formdesigner.core.events.EventResolution
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return value of a form lifecycle event handler.
---

# EventResolution

Defined in [`parrot_formdesigner.core.events`](../summaries/mod:parrot_formdesigner.core.events.md).

```python
class EventResolution(BaseModel)
```

Return value of a form lifecycle event handler.

All fields are optional. An empty ``EventResolution()`` is a valid
no-op: the dispatcher will leave all inputs unchanged.

Attributes:
    payload: When non-``None``, replaces the submission payload passed
        to the next processing step.
    schema_overrides: When non-``None``, shallow-merges into the
        serialised ``FormSchema`` dict (top-level keys only, per spec
        §7 shallow-merge decision for MVP).
    metadata: Added to ``FormEventContext.extra`` for downstream
        consumers (audit, tracing).
    user_message: Only meaningful for ``onError``; overrides the
        error message returned to the end-user.

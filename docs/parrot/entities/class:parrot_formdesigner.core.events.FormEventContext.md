---
type: Wiki Entity
title: FormEventContext
id: class:parrot_formdesigner.core.events.FormEventContext
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Payload passed to a form lifecycle event handler.
---

# FormEventContext

Defined in [`parrot_formdesigner.core.events`](../summaries/mod:parrot_formdesigner.core.events.md).

```python
class FormEventContext(BaseModel)
```

Payload passed to a form lifecycle event handler.

Attributes:
    event: The name of the lifecycle event being dispatched.
    form_id: Identifier of the form that owns the event.
    tenant: Tenant slug used to resolve the handler in the registry.
    auth_context: Resolved auth credentials.  Typed as ``Any`` to
        avoid a circular import through ``core/`` → ``services/``.
    payload: Submitted data (present only for submit events).
    schema_dump: Rendered schema dict (present for open/schema_loaded).
    error: The exception that triggered ``onError`` (if applicable).
    user_message: Mutable error message that ``onError`` handlers may
        replace for friendlier i18n output.
    extra: Free-form bag for correlation IDs, tracing data, etc.

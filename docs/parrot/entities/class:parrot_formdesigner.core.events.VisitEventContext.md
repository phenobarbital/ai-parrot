---
type: Wiki Entity
title: VisitEventContext
id: class:parrot_formdesigner.core.events.VisitEventContext
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Payload passed to a visit lifecycle event handler (FEAT-329).
---

# VisitEventContext

Defined in [`parrot_formdesigner.core.events`](../summaries/mod:parrot_formdesigner.core.events.md).

```python
class VisitEventContext(BaseModel)
```

Payload passed to a visit lifecycle event handler (FEAT-329).

Mirror of ``FormEventContext`` for the ``visit.*`` namespace: same
context → handler → resolution semantics, but scoped to a visit /
assignment rather than a form — no ``form_id`` / ``schema_dump``
in the path.

Attributes:
    event: The name of the visit lifecycle event being dispatched.
    tenant: Tenant slug used to resolve the handler in the registry.
    auth_context: Resolved auth credentials.  Typed as ``Any`` to
        avoid a circular import through ``core/`` → ``services/``.
    event_id: Identifier of the parent Event (FEAT-303), if any.
    shift_id: Identifier of the Shift the visit belongs to, if any.
    visit_id: Identifier of the Visit being processed, if any.
    staff_id: Identifier of the staff member performing the visit.
    payload: Event-specific data (artifact metadata, GPS fix, ...).
    extra: Free-form bag for correlation IDs, tracing data, etc.

---
type: Concept
title: dispatch_visit()
id: func:parrot_formdesigner.services.event_dispatcher.dispatch_visit
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Resolve and run the handler bound to a visit lifecycle ``event``.
---

# dispatch_visit

```python
async def dispatch_visit(event: VisitEventName, *, tenant: str | None, auth_context: Any, event_id: str | None=None, shift_id: str | None=None, visit_id: str | None=None, staff_id: str | None=None, payload: Mapping[str, Any] | None=None, extra: dict[str, Any] | None=None, handler_ref: str | None=None) -> EventResolution
```

Resolve and run the handler bound to a visit lifecycle ``event``.

Mirror of :func:`dispatch` for the ``visit.*`` namespace (FEAT-329).
Reuses the FEAT-188 tenant-scoped registry: handlers are registered
with ``@register_form_event("visit.onArrival")`` (optionally with
``tenant="<slug>"``) and the visit event name itself acts as the
``handler_ref``. No ``FormSchema`` / binding / ``schema_dump`` is
involved in the visit path.

Hook semantics (per FEAT-329 spec §2):

- **Pre-hooks** (``visit.onArrival``): ``FormEventAbort`` raised by
  the handler is re-raised intact (the caller converts it to an HTTP
  ``status_code`` + ``user_message``); other exceptions propagate
  unchanged, mirroring the ``before*`` form events.
- **Post-hooks** (all other visit events): fire-and-forget — any
  exception raised by the handler (including ``FormEventAbort``) is
  logged and swallowed so side-effects never break the visit flow.

Args:
    event: The visit lifecycle event name to dispatch
        (e.g. ``"visit.onArrival"``).
    tenant: Tenant slug used for registry lookup with global fallback.
    auth_context: Resolved authentication credentials (typed ``Any``
        to avoid a circular import; typically an ``AuthContext`` instance).
    event_id: Identifier of the parent Event (FEAT-303), if any.
    shift_id: Identifier of the Shift the visit belongs to, if any.
    visit_id: Identifier of the Visit being processed, if any.
    staff_id: Identifier of the staff member performing the visit.
    payload: Event-specific data (artifact metadata, GPS fix, ...).
    extra: Free-form bag for correlation IDs, tracing data, etc.
    handler_ref: Registry key to look up. Defaults to ``event``
        itself (the ``visit.*`` namespace disambiguates it from
        form-scoped ``'<form_id>.<event>'`` refs in the shared registry).

Returns:
    An ``EventResolution``. If no handler is registered for
    ``handler_ref`` (tenant-specific or global), returns an empty
    ``EventResolution()`` (no-op).

Raises:
    FormEventAbort: Re-raised intact when a **pre-hook** handler
        aborts (``visit.onArrival``). Never raised for post-hooks.
    Exception: Any other exception raised by a **pre-hook** handler
        propagates unchanged. Post-hook exceptions are logged and
        swallowed (fire-and-forget).

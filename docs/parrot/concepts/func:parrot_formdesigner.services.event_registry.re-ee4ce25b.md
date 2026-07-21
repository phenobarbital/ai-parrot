---
type: Concept
title: register_form_event()
id: func:parrot_formdesigner.services.event_registry.register_form_event
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Decorator that registers an async handler in the form event registry.
---

# register_form_event

```python
def register_form_event(handler_ref: str, *, tenant: str | None=None) -> Callable[[FormEventHandler], FormEventHandler]
```

Decorator that registers an async handler in the form event registry.

Tenant-scoped: pass ``tenant="<slug>"`` for a tenant-specific handler;
omit (or pass ``None``) to register a global fallback. Lookup falls
back from the tenant-specific entry to the global entry — see module
docstring for semantics.

The registered function signature should be::

    async def my_handler(ctx: FormEventContext) -> EventResolution | None:
        ...

Args:
    handler_ref: Logical handler reference (namespaced as
        ``'<form_id>.<event>'`` or deeper). Must match the
        ``FormEventBinding.handler_ref`` declared in ``FormSchema.events``.
    tenant: Tenant slug this registration applies to. ``None`` registers
        a global fallback visible to all tenants that lack a specific
        override for ``handler_ref``.

Returns:
    A decorator that registers the wrapped function and returns it unchanged.

Raises:
    ValueError: If ``tenant`` is the literal string ``"None"`` (collision
        with the global sentinel).
    ValueError: If ``(tenant, handler_ref)`` is already registered (no
        silent override allowed per spec §7).
    TypeError: If the decorated function is not an async coroutine function
        (per spec §7 async-only constraint).

Example::

    @register_form_event("survey_v1.onBeforeSubmit")
    async def normalize_email(ctx: FormEventContext) -> EventResolution | None:
        payload = dict(ctx.payload or {})
        payload["email"] = payload.get("email", "").strip().lower()
        return EventResolution(payload=payload)

    @register_form_event("survey_v1.onBeforeSubmit", tenant="acme")
    async def acme_normalize(ctx: FormEventContext) -> EventResolution | None:
        return None

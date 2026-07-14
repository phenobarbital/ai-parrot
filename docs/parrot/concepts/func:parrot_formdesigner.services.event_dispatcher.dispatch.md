---
type: Concept
title: dispatch()
id: func:parrot_formdesigner.services.event_dispatcher.dispatch
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Resolve and run the handler bound to ``event`` for ``form``.
---

# dispatch

```python
async def dispatch(event: FormEventName, *, form: FormSchema, request: web.Request, tenant: str | None, auth_context: Any, payload: Mapping[str, Any] | None=None, schema_dump: Mapping[str, Any] | None=None, error: BaseException | None=None) -> EventResolution
```

Resolve and run the handler bound to ``event`` for ``form``.

Args:
    event: The lifecycle event name to dispatch
        (e.g. ``"onBeforeSubmit"``).
    form: The ``FormSchema`` whose ``events`` config is inspected.
    request: The current aiohttp ``Request`` (passed to the context
        for handler access if needed; the dispatcher itself does not
        read it).
    tenant: Tenant slug used for registry lookup with global fallback.
    auth_context: Resolved authentication credentials (typed ``Any``
        to avoid a circular import; typically an ``AuthContext`` instance).
    payload: Submission data (present for submit events).
    schema_dump: Rendered schema dict (present for open / schema_loaded).
    error: The exception that triggered ``onError`` (if applicable).

Returns:
    An ``EventResolution``. If no binding is declared for ``event`` on
    ``form``, returns an empty ``EventResolution()`` (no-op).

Raises:
    FormEventAbort: Re-raised intact when the handler aborts a
        ``before*`` event.  The calling handler in ``FormAPIHandler``
        converts it to an HTTP response.
    RuntimeError: When the binding has ``required=True`` but no handler
        is registered for ``handler_ref``.
    Exception: Any other exception raised by the handler propagates
        unchanged. The caller decides whether to dispatch ``onError``
        and how to respond.

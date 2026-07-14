---
type: Wiki Entity
title: FormEventAbort
id: class:parrot_formdesigner.core.events.FormEventAbort
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Cancels a ``before*`` lifecycle event with a typed user-facing response.
---

# FormEventAbort

Defined in [`parrot_formdesigner.core.events`](../summaries/mod:parrot_formdesigner.core.events.md).

```python
class FormEventAbort(Exception)
```

Cancels a ``before*`` lifecycle event with a typed user-facing response.

Inspired by ``api/operations.py:150 OperationError``.  Raising this
inside a handler registered for ``onBeforeOpen`` or ``onBeforeSubmit``
causes the dispatcher to re-raise it immediately so that the calling
handler in ``FormAPIHandler`` can convert it to the correct HTTP error
response (``status_code`` + ``user_message``).

``onError`` is **not** triggered for ``FormEventAbort`` — an abort is a
controlled flow, not an unexpected failure (per spec §7).

Attributes:
    reason: Internal technical reason for the abort (logged, not exposed
        to end-users).
    user_message: Human-readable message safe to return in the HTTP body.
    status_code: HTTP status code for the response (default: 403).

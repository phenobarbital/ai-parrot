---
type: Concept
title: get_form_event()
id: func:parrot_formdesigner.services.event_registry.get_form_event
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Look up a registered event handler with tenant → global fallback.
---

# get_form_event

```python
def get_form_event(handler_ref: str, *, tenant: str | None=None) -> FormEventHandler
```

Look up a registered event handler with tenant → global fallback.

Resolution order:
1. ``(tenant, handler_ref)`` — tenant-specific override.
2. ``(None, handler_ref)`` — global fallback.
3. ``KeyError`` if neither exists.

Args:
    handler_ref: Logical handler reference (e.g. ``"survey_v1.onBeforeSubmit"``).
    tenant: Tenant slug for lookup. Pass ``None`` to look up only the
        global entry (skips the tenant-specific lookup).

Returns:
    The registered async callable.

Raises:
    KeyError: If no matching handler is found for ``handler_ref``.

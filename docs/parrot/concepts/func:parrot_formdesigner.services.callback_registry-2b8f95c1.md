---
type: Concept
title: get_form_callback()
id: func:parrot_formdesigner.services.callback_registry.get_form_callback
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Look up a registered callback with tenant → global fallback.
---

# get_form_callback

```python
def get_form_callback(name: str, *, tenant: str | None=None) -> RestCallback
```

Look up a registered callback with tenant → global fallback.

Resolution order:
1. ``(tenant, name)`` — tenant-specific override.
2. ``(None, name)`` — global fallback.
3. ``KeyError`` if neither exists.

Args:
    name: Logical callback name (e.g. ``"planogram_compliance"``).
    tenant: Tenant slug for lookup. Pass ``None`` to look up only the
        global entry (skips the tenant-specific lookup).

Returns:
    The registered callable.

Raises:
    KeyError: If no matching callback is found for ``name``.

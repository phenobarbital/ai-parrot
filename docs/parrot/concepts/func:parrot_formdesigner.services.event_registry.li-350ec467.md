---
type: Concept
title: list_form_events()
id: func:parrot_formdesigner.services.event_registry.list_form_events
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return all event handler keys visible to a tenant.
---

# list_form_events

```python
def list_form_events(tenant: str | None=None) -> list[tuple[str | None, str]]
```

Return all event handler keys visible to a tenant.

Returns the union of:
- Global entries (``tenant=None`` key).
- Tenant-specific entries for the given ``tenant`` (when not ``None``).

Useful for documentation generation and introspection.

Args:
    tenant: Tenant slug to include. When ``None``, only global entries
        are returned.

Returns:
    List of ``(tenant_or_None, handler_ref)`` keys.

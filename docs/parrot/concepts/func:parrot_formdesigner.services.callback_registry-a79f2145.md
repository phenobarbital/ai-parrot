---
type: Concept
title: list_form_callbacks()
id: func:parrot_formdesigner.services.callback_registry.list_form_callbacks
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return all callback keys visible to a tenant.
---

# list_form_callbacks

```python
def list_form_callbacks(tenant: str | None=None) -> list[tuple[str | None, str]]
```

Return all callback keys visible to a tenant.

Returns the union of:
- Global entries (``tenant=None`` key).
- Tenant-specific entries for the given ``tenant`` (when not ``None``).

Useful for documentation generation and introspection.

Args:
    tenant: Tenant slug to include. When ``None``, only global entries
        are returned.

Returns:
    List of ``(tenant_or_None, name)`` keys.

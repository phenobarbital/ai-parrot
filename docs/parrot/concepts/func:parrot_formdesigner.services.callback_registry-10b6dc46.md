---
type: Concept
title: register_form_callback()
id: func:parrot_formdesigner.services.callback_registry.register_form_callback
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Decorator that registers an async callback in the form callback registry.
---

# register_form_callback

```python
def register_form_callback(name: str, *, tenant: str | None=None) -> Callable[[RestCallback], RestCallback]
```

Decorator that registers an async callback in the form callback registry.

Tenant-scoped: pass ``tenant="<slug>"`` for a tenant-specific callback;
omit (or pass ``None``) to register a global fallback. Lookup falls
back from the tenant-specific entry to the global entry — see module
docstring for semantics.

The registered function signature should be::

    async def my_callback(
        payload: RestCallbackInput,
        auth_context: AuthContext,
    ) -> RestCallbackOutput: ...

Args:
    name: Logical name of the callback (e.g. ``"planogram_compliance"``).
    tenant: Tenant slug this registration applies to. ``None`` registers
        a global fallback visible to all tenants that lack a specific
        override for ``name``.

Returns:
    A decorator that registers the wrapped function and returns it unchanged.

Raises:
    ValueError: If ``tenant`` is the literal string ``"None"`` (collision
        with the global sentinel).
    ValueError: If ``(tenant, name)`` is already registered (no silent
        override).

Example::

    @register_form_callback("planogram_compliance")
    async def run_compliance(payload, auth_context):
        ...

    @register_form_callback("planogram_compliance", tenant="acme")
    async def run_acme_compliance(payload, auth_context):
        ...

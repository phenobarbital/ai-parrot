---
type: Wiki Summary
title: parrot_formdesigner.services.callback_registry
id: mod:parrot_formdesigner.services.callback_registry
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tenant-scoped form callback registry for FieldType.REST (mode=callback).
relates_to:
- concept: func:parrot_formdesigner.services.callback_registry.get_form_callback
  rel: defines
- concept: func:parrot_formdesigner.services.callback_registry.list_form_callbacks
  rel: defines
- concept: func:parrot_formdesigner.services.callback_registry.register_form_callback
  rel: defines
---

# `parrot_formdesigner.services.callback_registry`

Tenant-scoped form callback registry for FieldType.REST (mode=callback).

Provides a module-level ``_CALLBACK_REGISTRY`` mapping composite keys
``(tenant_slug_or_None, name)`` to registered async callback coroutines.

Semantics
---------
- ``None`` is the **global sentinel** — used for callbacks registered
  without a tenant. The literal string ``"None"`` is rejected at
  registration time to prevent collisions.
- Lookup order: ``(tenant, name)`` → ``(None, name)`` → ``KeyError``.
  A tenant-specific registration silently *shadows* (overrides) the
  global registration for that tenant; other tenants continue to see
  the global entry.
- Duplicate ``(tenant, name)`` registration raises ``ValueError``.
  Registrations cannot be silently overridden.

Authorization (who may invoke a callback) is NOT the responsibility of
this registry — ACLs live at the handler/resolver boundary.

Pattern
-------
This module mirrors the ``controls/registry.py`` shape (module-level dict
+ decorator) but uses a composite ``(tenant, name)`` key instead of a
plain string key. See spec §7 *Tenant-scoped callback registry* and
§8 Q3 refinement.

Note: ``RestCallback``, ``RestCallbackInput``, and ``RestCallbackOutput``
are defined in ``services/rest_field_resolver.py`` (TASK-1162). To avoid
a circular import, this module accepts and stores plain callables without
importing those types at module load time.

## Functions

- `def register_form_callback(name: str, *, tenant: str | None=None) -> Callable[[RestCallback], RestCallback]` — Decorator that registers an async callback in the form callback registry.
- `def get_form_callback(name: str, *, tenant: str | None=None) -> RestCallback` — Look up a registered callback with tenant → global fallback.
- `def list_form_callbacks(tenant: str | None=None) -> list[tuple[str | None, str]]` — Return all callback keys visible to a tenant.

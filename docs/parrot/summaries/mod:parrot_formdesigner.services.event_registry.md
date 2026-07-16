---
type: Wiki Summary
title: parrot_formdesigner.services.event_registry
id: mod:parrot_formdesigner.services.event_registry
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tenant-scoped form lifecycle event handler registry (FEAT-188).
relates_to:
- concept: func:parrot_formdesigner.services.event_registry.get_form_event
  rel: defines
- concept: func:parrot_formdesigner.services.event_registry.list_form_events
  rel: defines
- concept: func:parrot_formdesigner.services.event_registry.register_form_event
  rel: defines
- concept: mod:parrot_formdesigner.core.events
  rel: references
---

# `parrot_formdesigner.services.event_registry`

Tenant-scoped form lifecycle event handler registry (FEAT-188).

Provides a module-level ``_EVENT_REGISTRY`` mapping composite keys
``(tenant_slug_or_None, handler_ref)`` to registered async event handler
coroutines.

Semantics
---------
- ``None`` is the **global sentinel** — used for handlers registered
  without a tenant. The literal string ``"None"`` is rejected at
  registration time to prevent collisions.
- Lookup order: ``(tenant, handler_ref)`` → ``(None, handler_ref)`` →
  ``KeyError``.  A tenant-specific registration silently *shadows*
  (overrides) the global registration for that tenant; other tenants
  continue to see the global entry.
- Duplicate ``(tenant, handler_ref)`` registration raises ``ValueError``.
  Registrations cannot be silently overridden.
- Handlers **must** be async coroutine functions; synchronous functions
  are rejected at registration time with ``TypeError``.

This module mirrors the structure of ``services/callback_registry.py``
(same key-tuple shape, same fallback semantics, same duplicate-guard). The
key difference is the handler type: ``FormEventHandler`` returns
``EventResolution | None`` rather than arbitrary ``Any``.

Authorization (who may invoke a handler) is NOT the responsibility of this
registry — ACLs live at the handler/dispatcher boundary.

Pattern
-------
Mirror of ``callback_registry.py`` with the following renaming:
- ``RestCallback`` → ``FormEventHandler``
- ``_CALLBACK_REGISTRY`` → ``_EVENT_REGISTRY``
- ``register_form_callback`` → ``register_form_event``
- ``get_form_callback`` → ``get_form_event``
- ``list_form_callbacks`` → ``list_form_events``
- ``_clear_registry_for_tests`` → ``_clear_event_registry_for_tests``

Plus the async-only guard added inside the decorator.

## Functions

- `def register_form_event(handler_ref: str, *, tenant: str | None=None) -> Callable[[FormEventHandler], FormEventHandler]` — Decorator that registers an async handler in the form event registry.
- `def get_form_event(handler_ref: str, *, tenant: str | None=None) -> FormEventHandler` — Look up a registered event handler with tenant → global fallback.
- `def list_form_events(tenant: str | None=None) -> list[tuple[str | None, str]]` — Return all event handler keys visible to a tenant.

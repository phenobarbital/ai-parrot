"""Tenant-scoped form lifecycle event handler registry (FEAT-188).

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
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from parrot_formdesigner.core.events import EventResolution

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

# FormEventHandler signature: async (ctx: FormEventContext) -> EventResolution | None
FormEventHandler = Callable[..., Awaitable[EventResolution | None]]

# ---------------------------------------------------------------------------
# Module-level registry
# ---------------------------------------------------------------------------

# Key: (tenant_slug_or_None, handler_ref)
# Value: registered async event handler coroutine
_EVENT_REGISTRY: dict[tuple[str | None, str], FormEventHandler] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register_form_event(
    handler_ref: str,
    *,
    tenant: str | None = None,
) -> Callable[[FormEventHandler], FormEventHandler]:
    """Decorator that registers an async handler in the form event registry.

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
    """
    if tenant == "None":
        raise ValueError(
            "tenant slug 'None' (string) collides with the global sentinel; "
            "choose a different slug. Pass tenant=None (Python None) to register "
            "a global handler."
        )

    def decorator(fn: FormEventHandler) -> FormEventHandler:
        if not asyncio.iscoroutinefunction(fn):
            raise TypeError(
                f"Form event handler {fn!r} must be an async coroutine function. "
                "Synchronous handlers are not allowed (see spec §7 async-only constraint)."
            )
        key: tuple[str | None, str] = (tenant, handler_ref)
        if key in _EVENT_REGISTRY:
            raise ValueError(
                f"event handler {key!r} is already registered. "
                "Duplicate registrations are not allowed."
            )
        _EVENT_REGISTRY[key] = fn
        logger.debug(
            "registered form event handler %r (tenant=%r)", handler_ref, tenant
        )
        return fn

    return decorator


def get_form_event(
    handler_ref: str,
    *,
    tenant: str | None = None,
) -> FormEventHandler:
    """Look up a registered event handler with tenant → global fallback.

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
    """
    if tenant is not None:
        tenant_key: tuple[str | None, str] = (tenant, handler_ref)
        if tenant_key in _EVENT_REGISTRY:
            return _EVENT_REGISTRY[tenant_key]
    # Fall back to global
    return _EVENT_REGISTRY[(None, handler_ref)]


def list_form_events(
    tenant: str | None = None,
) -> list[tuple[str | None, str]]:
    """Return all event handler keys visible to a tenant.

    Returns the union of:
    - Global entries (``tenant=None`` key).
    - Tenant-specific entries for the given ``tenant`` (when not ``None``).

    Useful for documentation generation and introspection.

    Args:
        tenant: Tenant slug to include. When ``None``, only global entries
            are returned.

    Returns:
        List of ``(tenant_or_None, handler_ref)`` keys.
    """
    keys: list[tuple[str | None, str]] = []
    for key in _EVENT_REGISTRY:
        registered_tenant, _handler_ref = key
        if registered_tenant is None or registered_tenant == tenant:
            keys.append(key)
    return keys


def _clear_event_registry_for_tests() -> None:
    """Clear the event registry.

    **Test-only helper.** Do NOT call in production code. Use as a fixture
    teardown to ensure test isolation.
    """
    _EVENT_REGISTRY.clear()

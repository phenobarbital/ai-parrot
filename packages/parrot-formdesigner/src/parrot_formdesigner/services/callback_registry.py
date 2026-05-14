"""Tenant-scoped form callback registry for FieldType.REST (mode=callback).

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
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

# RestCallback signature: async (payload, auth_context) -> RestCallbackOutput
# Typed as Any here to avoid importing rest_field_resolver at module load time
# (which would create a circular dependency). The resolver validates at call time.
RestCallback = Callable[..., Awaitable[Any]]

# ---------------------------------------------------------------------------
# Module-level registry
# ---------------------------------------------------------------------------

# Key: (tenant_slug_or_None, name)
# Value: registered async callback coroutine
_CALLBACK_REGISTRY: dict[tuple[str | None, str], RestCallback] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register_form_callback(
    name: str,
    *,
    tenant: str | None = None,
) -> Callable[[RestCallback], RestCallback]:
    """Decorator that registers an async callback in the form callback registry.

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
    """
    if tenant == "None":
        raise ValueError(
            "tenant slug 'None' (string) collides with the global sentinel; "
            "choose a different slug. Pass tenant=None (Python None) to register "
            "a global callback."
        )

    def decorator(fn: RestCallback) -> RestCallback:
        key: tuple[str | None, str] = (tenant, name)
        if key in _CALLBACK_REGISTRY:
            raise ValueError(
                f"callback {key!r} is already registered. "
                "Duplicate registrations are not allowed."
            )
        _CALLBACK_REGISTRY[key] = fn
        logger.debug("registered form callback %r (tenant=%r)", name, tenant)
        return fn

    return decorator


def get_form_callback(
    name: str,
    *,
    tenant: str | None = None,
) -> RestCallback:
    """Look up a registered callback with tenant → global fallback.

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
    """
    if tenant is not None:
        tenant_key: tuple[str | None, str] = (tenant, name)
        if tenant_key in _CALLBACK_REGISTRY:
            return _CALLBACK_REGISTRY[tenant_key]
    # Fall back to global
    return _CALLBACK_REGISTRY[(None, name)]


def list_form_callbacks(
    tenant: str | None = None,
) -> list[tuple[str | None, str]]:
    """Return all callback keys visible to a tenant.

    Returns the union of:
    - Global entries (``tenant=None`` key).
    - Tenant-specific entries for the given ``tenant`` (when not ``None``).

    Useful for documentation generation and introspection.

    Args:
        tenant: Tenant slug to include. When ``None``, only global entries
            are returned.

    Returns:
        List of ``(tenant_or_None, name)`` keys.
    """
    keys: list[tuple[str | None, str]] = []
    for key in _CALLBACK_REGISTRY:
        registered_tenant, _name = key
        if registered_tenant is None or registered_tenant == tenant:
            keys.append(key)
    return keys


def _clear_registry_for_tests() -> None:
    """Clear the callback registry.

    **Test-only helper.** Do NOT call in production code. Use as a fixture
    teardown to ensure test isolation.
    """
    _CALLBACK_REGISTRY.clear()

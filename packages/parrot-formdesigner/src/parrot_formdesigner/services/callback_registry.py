"""Tenant-scoped callback registry for FieldType.REST callback mode.

Callbacks are keyed by ``(tenant_slug_or_None, name)``. The ``None`` tenant
is the global fallback; lookup checks the tenant-specific entry first, then
falls back to the global ``(None, name)`` entry.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

# Type alias — input/output models live in rest_field_resolver (TASK-1162).
# Accepting Any here avoids a circular import; the resolver enforces types.
RestCallback = Callable[..., Awaitable[Any]]

# Composite key: (tenant_slug | None, callback_name)
_CALLBACK_REGISTRY: dict[tuple[str | None, str], RestCallback] = {}


def register_form_callback(
    name: str,
    *,
    tenant: str | None = None,
) -> Callable[[RestCallback], RestCallback]:
    """Decorator that registers a coroutine as a named REST callback.

    Args:
        name: Callback name, unique within the tenant scope.
        tenant: Tenant slug that owns this override. ``None`` registers a
            global fallback available to all tenants.

    Returns:
        The decorator; returns the original function unchanged.

    Raises:
        ValueError: If ``tenant`` is the string ``"None"`` (collides with
            the global sentinel) or if the ``(tenant, name)`` key is already
            registered.
    """
    if tenant == "None":
        raise ValueError(
            "tenant slug 'None' (string) collides with the global "
            "sentinel; pick a different slug."
        )

    def decorator(fn: RestCallback) -> RestCallback:
        key: tuple[str | None, str] = (tenant, name)
        if key in _CALLBACK_REGISTRY:
            raise ValueError(
                f"callback {key!r} already registered; "
                "unregister it first or use a different name."
            )
        _CALLBACK_REGISTRY[key] = fn
        logger.debug("Registered callback %r for tenant=%r", name, tenant)
        return fn

    return decorator


def get_form_callback(name: str, *, tenant: str | None = None) -> RestCallback:
    """Retrieve a registered callback by name, with tenant fallback.

    Lookup order:
      1. ``(tenant, name)`` — tenant-specific override (if tenant given).
      2. ``(None, name)``   — global fallback.

    Args:
        name: Callback name.
        tenant: Tenant slug; if provided, the tenant-specific entry is
            checked before the global one.

    Returns:
        The registered coroutine.

    Raises:
        KeyError: If no entry is found for ``(tenant, name)`` or
            ``(None, name)``.
    """
    if tenant is not None and (tenant, name) in _CALLBACK_REGISTRY:
        return _CALLBACK_REGISTRY[(tenant, name)]
    return _CALLBACK_REGISTRY[(None, name)]


def list_form_callbacks(
    tenant: str | None = None,
) -> list[tuple[str | None, str]]:
    """Return all registered callback keys visible to the given tenant.

    Returns global entries (``(None, name)``) plus tenant-specific entries
    (``(tenant, name)``). When ``tenant`` is ``None``, returns only global
    entries.

    Args:
        tenant: Tenant slug to include in addition to globals.

    Returns:
        List of ``(tenant_or_None, name)`` tuples.
    """
    return [
        key
        for key in _CALLBACK_REGISTRY
        if key[0] is None or key[0] == tenant
    ]


def _clear_registry_for_tests() -> None:
    """Clear all registered callbacks. Test-only helper."""
    _CALLBACK_REGISTRY.clear()

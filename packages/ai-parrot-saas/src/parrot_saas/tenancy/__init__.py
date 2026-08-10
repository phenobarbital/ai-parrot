"""Tenant identity, storage and per-tenant runtime state.

The public surface is re-exported here; heavier members (repository, runtime
cache, middleware) are lazy so importing :mod:`parrot_saas.tenancy.context` in
a unit test does not pull in asyncdb or aiohttp.
"""
from typing import TYPE_CHECKING, Any

from .context import (
    TENANT_ID_PATTERN,
    InvalidTenantId,
    TenantContext,
    TenantMode,
    TenantStatus,
    validate_tenant_id,
)

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from .middleware import tenant_resolution_middleware
    from .registry import TenantAgentRegistry
    from .repository import TenantRepository
    from .runtime import TenantRuntime, TenantRuntimeCache

__all__ = (
    "TENANT_ID_PATTERN",
    "InvalidTenantId",
    "Tenant",
    "TenantAgentRegistry",
    "TenantContext",
    "TenantCreate",
    "TenantMode",
    "TenantRepository",
    "TenantRuntime",
    "TenantRuntimeCache",
    "TenantStatus",
    "TenantUpdate",
    "clone_tool_manager",
    "tenant_resolution_middleware",
    "validate_tenant_id",
)

_LAZY_EXPORTS = {
    "Tenant": ("parrot_saas.tenancy.models", "Tenant"),
    "TenantAgentRegistry": ("parrot_saas.tenancy.registry", "TenantAgentRegistry"),
    "TenantCreate": ("parrot_saas.tenancy.models", "TenantCreate"),
    "TenantRepository": ("parrot_saas.tenancy.repository", "TenantRepository"),
    "TenantRuntime": ("parrot_saas.tenancy.runtime", "TenantRuntime"),
    "TenantRuntimeCache": ("parrot_saas.tenancy.runtime", "TenantRuntimeCache"),
    "TenantUpdate": ("parrot_saas.tenancy.models", "TenantUpdate"),
    "clone_tool_manager": ("parrot_saas.tenancy.runtime", "clone_tool_manager"),
    "tenant_resolution_middleware": (
        "parrot_saas.tenancy.middleware",
        "tenant_resolution_middleware",
    ),
}


def __getattr__(name: str) -> Any:
    """Resolve lazily-exported names on first access (PEP 562)."""
    try:
        module_path, attr = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None
    from importlib import import_module

    return getattr(import_module(module_path), attr)


def __dir__() -> list[str]:
    """Expose lazy exports to ``dir()`` and tab-completion."""
    return sorted(__all__)

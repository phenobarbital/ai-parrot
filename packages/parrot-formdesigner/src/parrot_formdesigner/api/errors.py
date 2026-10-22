"""Compatibility re-exports for tenant errors now owned by ``core``."""

from ..core.tenant_errors import (  # noqa: F401
    TenantConflictError,
    TenantForbiddenError,
    TenantNotDeclaredError,
)

__all__ = [
    "TenantNotDeclaredError",
    "TenantForbiddenError",
    "TenantConflictError",
]

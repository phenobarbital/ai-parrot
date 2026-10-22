"""Compatibility re-exports for tenant helpers now owned by ``core``."""

from ..core.tenant import (  # noqa: F401
    _EXPECTED_HINT,
    _Handler,
    _authorize,
    _get_programs,
    _is_superuser,
    assert_body_tenant_matches,
    declared_tenant,
    enforce_membership_unless_public,
    logger,
    requires_tenant,
)
from ..core.tenant_errors import (  # noqa: F401
    TenantConflictError,
    TenantForbiddenError,
    TenantNotDeclaredError,
)

__all__ = [
    "requires_tenant",
    "declared_tenant",
    "enforce_membership_unless_public",
    "assert_body_tenant_matches",
    "TenantConflictError",
    "TenantForbiddenError",
    "TenantNotDeclaredError",
]

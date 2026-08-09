"""The tenant identity that every SaaS operation is scoped by.

:class:`TenantContext` is passed **explicitly** — as a constructor argument, a
factory closure, or a repository parameter. It is deliberately not propagated
through a :mod:`contextvars` variable, for two reasons specific to this system:

* ``AgentsFlow`` builds its nodes once and re-materializes them per
  ``run_flow()`` call, so the binding point is construction rather than
  execution; a context variable read at execution time is reading the wrong
  moment.
* The Community Manager flow also runs from places that have no request
  context at all — ``JobManager`` background workers, the webhook ingest
  queue, and ``FlowRecoveryService``'s shutdown hook. A context variable reads
  ``None`` there, silently, and a ``None`` tenant is a cross-tenant data leak
  rather than a crash.

This matches the explicit non-goal recorded in FEAT-183 ("No implicit tenant
propagation") for the form registry.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

#: Tenant slugs are used in Pulumi stack names, Docker object names, Postgres
#: values and URL path segments, so the character set is the intersection of
#: what all of those accept.
TENANT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,62}$")

_EMPTY_SETTINGS: Mapping[str, Any] = MappingProxyType({})


class InvalidTenantId(ValueError):
    """Raised when a tenant slug does not satisfy :data:`TENANT_ID_PATTERN`."""


class TenantMode(str, Enum):
    """How a tenant's workload is hosted.

    Attributes:
        SHARED: Runs inside the shared process. Isolation is the ``tenant_id``
            column plus repository-level enforcement.
        DEDICATED: Runs in its own provisioned stack with its own database.
            Isolation is the deployment boundary.
    """

    SHARED = "shared"
    DEDICATED = "dedicated"


class TenantStatus(str, Enum):
    """Lifecycle state gating whether a tenant may serve traffic."""

    ACTIVE = "active"
    PROVISIONING = "provisioning"
    SUSPENDED = "suspended"


def validate_tenant_id(tenant_id: str) -> str:
    """Validate and return a tenant slug.

    Args:
        tenant_id: Candidate slug.

    Returns:
        The slug unchanged, when valid.

    Raises:
        InvalidTenantId: If the slug is empty or does not match
            :data:`TENANT_ID_PATTERN`.
    """
    if not tenant_id or not TENANT_ID_PATTERN.match(tenant_id):
        raise InvalidTenantId(
            f"invalid tenant_id {tenant_id!r}: expected "
            f"{TENANT_ID_PATTERN.pattern} (lowercase, 2-63 chars, "
            "starting with a letter)"
        )
    return tenant_id


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Immutable identity and configuration of the tenant owning an operation.

    Attributes:
        tenant_id: Slug, unique across the deployment. Validated on creation.
        name: Human-readable business name.
        mode: Shared or dedicated hosting.
        timezone: IANA zone driving the navrules ``Environment`` temporal
            fields (``is_weekend``, ``day_period``, ...) used by coupon rules.
        locale: Default language for generated replies.
        status: Lifecycle state; only ``ACTIVE`` may serve runtime traffic.
        settings: Free-form per-tenant configuration (brand voice, model
            overrides, revise bounds). Read through :meth:`setting`.
    """

    tenant_id: str
    name: str
    mode: TenantMode = TenantMode.SHARED
    timezone: str = "UTC"
    locale: str = "en"
    status: TenantStatus = TenantStatus.ACTIVE
    settings: Mapping[str, Any] = field(default_factory=lambda: _EMPTY_SETTINGS)

    def __post_init__(self) -> None:
        """Validate the slug and freeze ``settings`` against later mutation."""
        validate_tenant_id(self.tenant_id)
        # `frozen=True` stops attribute reassignment but not mutation of a
        # referenced dict, and this object is shared by every node of a run.
        object.__setattr__(self, "settings", MappingProxyType(dict(self.settings)))

    @property
    def is_active(self) -> bool:
        """Whether the tenant may serve runtime traffic."""
        return self.status is TenantStatus.ACTIVE

    def setting(self, key: str, default: Any = None) -> Any:
        """Read a per-tenant setting.

        Args:
            key: Setting name.
            default: Value returned when the tenant has not set ``key``.

        Returns:
            The configured value, or ``default``.
        """
        return self.settings.get(key, default)


__all__ = (
    "InvalidTenantId",
    "TENANT_ID_PATTERN",
    "TenantContext",
    "TenantMode",
    "TenantStatus",
    "validate_tenant_id",
)

"""Persisted tenant records and the payloads that create or amend them.

:class:`~parrot_saas.tenancy.context.TenantContext` is what circulates through
the system at runtime — frozen, minimal, and safe to hold for the life of a
flow. :class:`Tenant` is the *stored* shape: the same identity plus its audit
timestamps. :meth:`Tenant.to_context` is the one-way bridge between them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .context import (
    TENANT_ID_PATTERN,
    TenantContext,
    TenantMode,
    TenantStatus,
)


class Tenant(BaseModel):
    """A tenant as stored in ``saas.tenants``.

    Attributes:
        tenant_id: Slug, unique across the deployment.
        name: Human-readable business name.
        mode: Shared or dedicated hosting.
        status: Lifecycle state; only ``active`` may serve runtime traffic.
        timezone: IANA zone driving the navrules temporal fields.
        locale: Default language for generated replies.
        settings: Free-form per-tenant configuration.
        created_at: Row creation time.
        updated_at: Last modification time.
    """

    model_config = ConfigDict(use_enum_values=True, validate_default=True)

    tenant_id: str
    name: str
    mode: TenantMode = TenantMode.SHARED
    status: TenantStatus = TenantStatus.ACTIVE
    timezone: str = "UTC"
    locale: str = "en"
    settings: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("tenant_id")
    @classmethod
    def _validate_slug(cls, value: str) -> str:
        """Enforce the slug pattern shared with :class:`TenantContext`."""
        if not TENANT_ID_PATTERN.match(value or ""):
            raise ValueError(
                f"invalid tenant_id {value!r}: expected "
                f"{TENANT_ID_PATTERN.pattern}"
            )
        return value

    def to_context(self) -> TenantContext:
        """Return the runtime view of this tenant.

        Returns:
            A frozen :class:`TenantContext` carrying identity and settings —
            deliberately without the audit timestamps, which no runtime code
            should branch on.
        """
        return TenantContext(
            tenant_id=self.tenant_id,
            name=self.name,
            mode=TenantMode(self.mode),
            timezone=self.timezone,
            locale=self.locale,
            status=TenantStatus(self.status),
            settings=self.settings,
        )

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Tenant":
        """Build a tenant from a database row.

        Args:
            row: A record from ``saas.tenants``. ``settings`` may arrive as a
                JSON string or as a mapping depending on driver codecs.

        Returns:
            The parsed tenant.
        """
        data = dict(row)
        settings = data.get("settings")
        if isinstance(settings, str):
            import json

            data["settings"] = json.loads(settings or "{}")
        elif settings is None:
            data["settings"] = {}
        return cls(**data)


class TenantCreate(BaseModel):
    """Payload accepted by the control plane to onboard a tenant."""

    model_config = ConfigDict(use_enum_values=True, validate_default=True)

    tenant_id: str
    name: str
    mode: TenantMode = TenantMode.SHARED
    timezone: str = "UTC"
    locale: str = "en"
    settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tenant_id")
    @classmethod
    def _validate_slug(cls, value: str) -> str:
        """Enforce the slug pattern."""
        if not TENANT_ID_PATTERN.match(value or ""):
            raise ValueError(
                f"invalid tenant_id {value!r}: expected "
                f"{TENANT_ID_PATTERN.pattern}"
            )
        return value


class TenantUpdate(BaseModel):
    """Partial amendment to a tenant.

    Every field is optional; ``None`` means "leave unchanged". ``tenant_id`` is
    absent on purpose — a tenant's slug appears in provisioned stack names,
    Docker objects and stored secrets' AAD, so renaming one is a migration
    rather than an edit.
    """

    model_config = ConfigDict(use_enum_values=True)

    name: Optional[str] = None
    mode: Optional[TenantMode] = None
    status: Optional[TenantStatus] = None
    timezone: Optional[str] = None
    locale: Optional[str] = None
    settings: Optional[dict[str, Any]] = None

    def changes(self) -> dict[str, Any]:
        """Return only the fields the caller actually set.

        Returns:
            Mapping of column name to new value; empty when nothing changed.
        """
        return self.model_dump(exclude_none=True)


__all__ = ("Tenant", "TenantCreate", "TenantUpdate")

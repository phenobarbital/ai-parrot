"""Persistence for tenant records.

The tenant table is the one place where cross-tenant access is normal rather
than suspicious: the control plane lists and creates tenants, and a tenant row
is *about* a tenant rather than *owned by* one. Those operations therefore use
the deliberately-named ``admin_*`` helpers, and everything else stays scoped.
"""
from __future__ import annotations

import json
from typing import Any, Optional, Sequence

from ..db.repository import BaseRepository
from .context import TenantStatus
from .models import Tenant, TenantCreate, TenantUpdate

#: Columns a caller may amend through :meth:`TenantRepository.update`.
#: An allow-list, not a filter on the payload: it is what stops a future field
#: on ``TenantUpdate`` from silently becoming SQL-injectable column names.
_UPDATABLE = frozenset(
    {"name", "mode", "status", "timezone", "locale", "settings"}
)


class TenantAlreadyExists(ValueError):
    """Raised when onboarding a tenant whose slug is already taken."""


class TenantRepository(BaseRepository):
    """CRUD over ``saas.tenants``."""

    @property
    def _table(self) -> str:
        """Schema-qualified tenant table."""
        return self.table("tenants")

    async def create(self, payload: TenantCreate) -> Tenant:
        """Onboard a new tenant.

        Args:
            payload: Validated creation payload.

        Returns:
            The stored tenant.

        Raises:
            TenantAlreadyExists: If the slug is taken. Detected with
                ``ON CONFLICT DO NOTHING`` plus an empty ``RETURNING`` rather
                than by catching a driver-specific integrity error.
        """
        row = await self.admin_fetch_one(
            f"INSERT INTO {self._table} "
            "(tenant_id, name, mode, status, timezone, locale, settings) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb) "
            "ON CONFLICT (tenant_id) DO NOTHING "
            "RETURNING *",
            payload.tenant_id,
            payload.name,
            str(payload.mode),
            TenantStatus.ACTIVE.value,
            payload.timezone,
            payload.locale,
            json.dumps(payload.settings or {}),
        )
        if row is None:
            raise TenantAlreadyExists(
                f"tenant {payload.tenant_id!r} already exists"
            )
        return Tenant.from_row(row)

    async def get(self, tenant_id: str) -> Optional[Tenant]:
        """Return one tenant.

        Args:
            tenant_id: Slug to look up.

        Returns:
            The tenant, or ``None`` when unknown.
        """
        row = await self.fetch_one(
            tenant_id,
            f"SELECT * FROM {self._table} WHERE tenant_id = $1",
        )
        return Tenant.from_row(row) if row is not None else None

    async def update(
        self, tenant_id: str, patch: TenantUpdate
    ) -> Optional[Tenant]:
        """Apply a partial amendment.

        Args:
            tenant_id: Tenant to amend.
            patch: Fields to change; unset fields are left alone.

        Returns:
            The updated tenant, or ``None`` when unknown. Returns the current
            tenant unchanged when ``patch`` is empty.
        """
        changes = {k: v for k, v in patch.changes().items() if k in _UPDATABLE}
        if not changes:
            return await self.get(tenant_id)

        assignments: list[str] = []
        params: list[Any] = []
        for position, (column, value) in enumerate(changes.items(), start=2):
            if column == "settings":
                assignments.append(f"settings = ${position}::jsonb")
                params.append(json.dumps(value or {}))
            else:
                assignments.append(f"{column} = ${position}")
                params.append(str(value) if column in {"mode", "status"} else value)
        assignments.append("updated_at = now()")

        row = await self.fetch_one(
            tenant_id,
            f"UPDATE {self._table} SET {', '.join(assignments)} "
            "WHERE tenant_id = $1 RETURNING *",
            *params,
        )
        return Tenant.from_row(row) if row is not None else None

    async def set_status(
        self, tenant_id: str, status: TenantStatus
    ) -> Optional[Tenant]:
        """Move a tenant through its lifecycle.

        Args:
            tenant_id: Tenant to change.
            status: New lifecycle state.

        Returns:
            The updated tenant, or ``None`` when unknown.
        """
        row = await self.fetch_one(
            tenant_id,
            f"UPDATE {self._table} SET status = $2, updated_at = now() "
            "WHERE tenant_id = $1 RETURNING *",
            status.value,
        )
        return Tenant.from_row(row) if row is not None else None

    async def delete(self, tenant_id: str) -> Optional[Tenant]:
        """Retire a tenant by suspending it.

        Deliberately a soft delete. A tenant's rows are referenced by issued
        coupons, published replies and provisioned infrastructure; removing the
        row would orphan all of it and destroy the audit trail for data the
        business may still be obliged to explain. Hard deletion belongs to a
        separate, explicit erasure path.

        Args:
            tenant_id: Tenant to retire.

        Returns:
            The suspended tenant, or ``None`` when unknown.
        """
        return await self.set_status(tenant_id, TenantStatus.SUSPENDED)

    async def list_tenants(
        self,
        *,
        status: Optional[TenantStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Tenant]:
        """List tenants across the deployment.

        Cross-tenant by definition — this is the control plane's own view, and
        it uses the ``admin_*`` helper so that intent is visible in the code.

        Args:
            status: Optional lifecycle filter.
            limit: Maximum rows.
            offset: Rows to skip.

        Returns:
            The matching tenants, ordered by slug.
        """
        if status is None:
            rows = await self.admin_fetch_all(
                f"SELECT * FROM {self._table} ORDER BY tenant_id "
                "LIMIT $1 OFFSET $2",
                limit,
                offset,
            )
        else:
            rows = await self.admin_fetch_all(
                f"SELECT * FROM {self._table} WHERE status = $1 "
                "ORDER BY tenant_id LIMIT $2 OFFSET $3",
                status.value,
                limit,
                offset,
            )
        return [Tenant.from_row(row) for row in rows]


__all__ = ("TenantAlreadyExists", "TenantRepository")

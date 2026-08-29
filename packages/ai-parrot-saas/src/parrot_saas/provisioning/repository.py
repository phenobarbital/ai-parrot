"""Persistence for the deployment serving each tenant."""
from __future__ import annotations

import json
from typing import Any, Optional, Sequence

from ..db.repository import BaseRepository
from .models import Deployment, DeploymentStatus

_COLUMNS = (
    "tenant_id, mode, status, stack, outputs, last_error, job_id, "
    "created_at, updated_at"
)


class DeploymentRepository(BaseRepository):
    """Reads and writes ``saas.deployments``."""

    async def get(self, tenant_id: str) -> Optional[Deployment]:
        """Return the tenant's deployment, or ``None``."""
        row = await self.fetch_one(
            tenant_id,
            f"SELECT {_COLUMNS} FROM {self.table('deployments')} "
            "WHERE tenant_id = $1",
        )
        return Deployment.from_row(row) if row else None

    async def upsert(
        self,
        tenant_id: str,
        *,
        mode: str,
        status: str,
        stack: str = "",
        job_id: str = "",
    ) -> Optional[Deployment]:
        """Create the deployment row, or move an existing one to ``status``.

        Args:
            tenant_id: Owning tenant.
            mode: What is being built.
            status: The state to move to.
            stack: Pulumi stack name, empty for shared.
            job_id: The background job taking it there.

        Returns:
            The stored deployment.
        """
        row = await self.fetch_one(
            tenant_id,
            f"INSERT INTO {self.table('deployments')} "
            "(tenant_id, mode, status, stack, job_id) "
            "VALUES ($1, $2, $3, $4, $5) "
            "ON CONFLICT (tenant_id) DO UPDATE SET "
            "  mode = EXCLUDED.mode, status = EXCLUDED.status, "
            # An empty stack must not erase the one already recorded: a
            # ``destroy`` names no stack, and losing it would leave the row
            # unable to say what was torn down.
            "  stack = COALESCE(NULLIF(EXCLUDED.stack, ''), "
            f"                  {self.table('deployments')}.stack), "
            "  job_id = EXCLUDED.job_id, updated_at = now() "
            f"RETURNING {_COLUMNS}",
            mode,
            status,
            stack,
            job_id,
        )
        return Deployment.from_row(row) if row else None

    async def record(
        self,
        tenant_id: str,
        *,
        status: str,
        outputs: Optional[dict] = None,
        last_error: str = "",
        stack: str = "",
    ) -> Optional[Deployment]:
        """Record the outcome of an operation.

        Args:
            tenant_id: Owning tenant.
            status: Terminal status for this operation.
            outputs: Non-secret stack outputs. ``None`` leaves them alone,
                which is what a failed apply wants — the previous outputs are
                still what is deployed.
            last_error: Why it failed, empty on success. Always written, so a
                success clears the previous failure rather than leaving a stale
                message beside a healthy stack.
            stack: Stack name, when the operation established one.

        Returns:
            The updated deployment, or ``None`` if there is no row.
        """
        row = await self.fetch_one(
            tenant_id,
            f"UPDATE {self.table('deployments')} SET "
            "  status = $2, "
            "  outputs = COALESCE($3::jsonb, outputs), "
            "  last_error = $4, "
            "  stack = COALESCE(NULLIF($5, ''), stack), "
            "  job_id = '', updated_at = now() "
            "WHERE tenant_id = $1 "
            f"RETURNING {_COLUMNS}",
            status,
            json.dumps(outputs, default=str) if outputs is not None else None,
            last_error[:2000],
            stack,
        )
        return Deployment.from_row(row) if row else None

    async def list_deployments(
        self, *, status: Optional[str] = None, limit: int = 100
    ) -> Sequence[Deployment]:
        """List deployments across every tenant.

        A control-plane read, so it goes through the administrative helper
        rather than the tenant-scoped one — the whole point is to span
        tenants, and that must be visible at the call site rather than hidden
        in a query with no tenant predicate.

        Args:
            status: Filter to one status.
            limit: Maximum rows.

        Returns:
            The deployments, most recently touched first.
        """
        rows = await self.admin_fetch_all(
            f"SELECT {_COLUMNS} FROM {self.table('deployments')} "
            "WHERE ($1::text IS NULL OR status = $1) "
            "ORDER BY updated_at DESC, tenant_id "
            "LIMIT $2",
            status,
            limit,
        )
        return [Deployment.from_row(row) for row in rows]

    async def claim(
        self, tenant_id: str, *, status: str, job_id: str, mode: str, stack: str = ""
    ) -> tuple[Optional[Deployment], Optional[Any]]:
        """Move a deployment into a transient state, if it is idle.

        This is the lock. Two ``pulumi up`` processes on one stack corrupt its
        state file, and the control plane is an HTTP API anyone can call twice,
        so the check has to be a conditional write rather than a read followed
        by a write.

        Args:
            tenant_id: Owning tenant.
            status: Transient status to move into.
            job_id: The job that will do the work.
            mode: What is being built.
            stack: Stack name, when known.

        Returns:
            ``(deployment, None)`` when the claim succeeded, or
            ``(None, current)`` with whatever is already in flight.
        """
        existing = await self.get(tenant_id)
        if existing is None:
            claimed = await self.upsert(
                tenant_id, mode=mode, status=status, stack=stack, job_id=job_id
            )
            return claimed, None
        if existing.busy:
            return None, existing

        row = await self.fetch_one(
            tenant_id,
            f"UPDATE {self.table('deployments')} SET "
            "  status = $2, job_id = $3, mode = $4, "
            "  stack = COALESCE(NULLIF($5, ''), stack), updated_at = now() "
            "WHERE tenant_id = $1 AND status = ANY($6::text[]) "
            f"RETURNING {_COLUMNS}",
            status,
            job_id,
            mode,
            stack,
            list(_IDLE),
        )
        if row is None:
            # Lost the race between the read and the write.
            return None, await self.get(tenant_id)
        return Deployment.from_row(row), None


_IDLE = (
    DeploymentStatus.PENDING.value,
    DeploymentStatus.READY.value,
    DeploymentStatus.FAILED.value,
    DeploymentStatus.DESTROYED.value,
)


__all__ = ("DeploymentRepository",)

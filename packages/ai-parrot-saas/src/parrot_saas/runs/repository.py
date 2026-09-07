"""Persistence for flow execution records.

Every statement is tenant-scoped through :class:`BaseRepository`, which binds
``tenant_id`` as ``$1`` and refuses to be used any other way. A run row is
written twice — once when the run starts and once when it ends — rather than
only at the end, so a run that dies with its worker is visible as ``running``
with no ``finished_at`` instead of never having existed.
"""
from __future__ import annotations

import json
import uuid as _uuid
from typing import Any, Optional, Sequence

from ..db.repository import BaseRepository
from .models import Run, RunStatus

_COLUMNS = (
    "run_id, tenant_id, flow, review_id, status, outcome, replied, "
    "coupon_code, failed_node, error, usage, nodes, duration_ms, "
    "started_at, finished_at"
)


def as_uuid(value: Any) -> Optional[_uuid.UUID]:
    """Coerce an identifier to a ``UUID``, or ``None`` when it is not one.

    asyncpg rejects a ``str`` bound to a ``uuid`` parameter outright, so the
    conversion has to happen in Python. Returning ``None`` for a malformed id
    turns "someone put a typo in a URL" into a clean miss rather than a 500.

    Args:
        value: A ``UUID``, a string, or anything else.

    Returns:
        The UUID, or ``None``.
    """
    if isinstance(value, _uuid.UUID):
        return value
    if not value:
        return None
    try:
        return _uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


class RunRepository(BaseRepository):
    """Reads and writes ``saas.runs``."""

    async def start(
        self,
        tenant_id: str,
        run_id: str,
        *,
        review_id: str = "",
        flow: str = "community_manager",
    ) -> Optional[Run]:
        """Record that a run has begun.

        Idempotent on ``run_id``: a retried job must not create a second row,
        and re-running an existing one moves it back to ``running`` with its
        previous outcome cleared rather than leaving a stale terminal state
        beside a live execution.

        Args:
            tenant_id: Owning tenant.
            run_id: Identifier minted at ingest.
            review_id: The review this run is about.
            flow: Which flow is running.

        Returns:
            The stored run, or ``None`` when ``run_id`` is not a UUID.
        """
        key = as_uuid(run_id)
        if key is None:
            return None
        row = await self.fetch_one(
            tenant_id,
            f"INSERT INTO {self.table('runs')} "
            "(run_id, tenant_id, flow, review_id, status) "
            "VALUES ($2, $1, $3, $4, 'running') "
            "ON CONFLICT (run_id) DO UPDATE SET "
            "  status = 'running', outcome = '', failed_node = '', "
            "  error = '', finished_at = NULL, started_at = now() "
            # The tenant guard belongs on the conflict branch too. Without it
            # a run id that already exists under another tenant would be
            # taken over by this write rather than refused.
            f"WHERE {self.table('runs')}.tenant_id = $1 "
            f"RETURNING {_COLUMNS}",
            key,
            flow,
            as_uuid(review_id),
        )
        return Run.from_row(row) if row else None

    async def finish(
        self,
        tenant_id: str,
        run_id: str,
        *,
        status: RunStatus,
        outcome: str = "",
        replied: bool = False,
        coupon_code: str = "",
        failed_node: str = "",
        error: str = "",
        usage: Optional[dict] = None,
        nodes: Optional[Sequence[dict]] = None,
        duration_ms: int = 0,
    ) -> Optional[Run]:
        """Record how a run ended.

        The ``tenant_id`` in the ``WHERE`` clause is not decoration: a run id
        is a UUID a caller could guess at, and without it this would be a
        cross-tenant write.

        Args:
            tenant_id: Owning tenant.
            run_id: The run.
            status: Terminal status.
            outcome: The flow's own label for what happened.
            replied: Whether a public reply went out.
            coupon_code: The coupon issued, if any.
            failed_node: Node that raised, for a failed run.
            error: That node's error.
            usage: Token usage per role.
            nodes: Per-node execution summary.
            duration_ms: Wall-clock duration.

        Returns:
            The updated run, or ``None`` when there is no such run.
        """
        key = as_uuid(run_id)
        if key is None:
            return None
        row = await self.fetch_one(
            tenant_id,
            f"UPDATE {self.table('runs')} SET "
            "  status = $3, outcome = $4, replied = $5, coupon_code = $6, "
            "  failed_node = $7, error = $8, usage = $9::jsonb, "
            "  nodes = $10::jsonb, duration_ms = $11, finished_at = now() "
            "WHERE tenant_id = $1 AND run_id = $2 "
            f"RETURNING {_COLUMNS}",
            key,
            getattr(status, "value", status),
            outcome,
            replied,
            coupon_code,
            failed_node,
            # An error message can be arbitrarily long and this column is read
            # in list views; the full text lives in the execution row.
            error[:2000],
            json.dumps(usage or {}, default=str),
            json.dumps(list(nodes or []), default=str),
            int(duration_ms),
        )
        return Run.from_row(row) if row else None

    async def get(self, tenant_id: str, run_id: str) -> Optional[Run]:
        """Return one run, or ``None``."""
        key = as_uuid(run_id)
        if key is None:
            return None
        row = await self.fetch_one(
            tenant_id,
            f"SELECT {_COLUMNS} FROM {self.table('runs')} "
            "WHERE tenant_id = $1 AND run_id = $2",
            key,
        )
        return Run.from_row(row) if row else None

    async def list_runs(
        self,
        tenant_id: str,
        *,
        status: Optional[str] = None,
        review_id: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Run]:
        """List a tenant's runs, newest first."""
        rows = await self.fetch_all(
            tenant_id,
            f"SELECT {_COLUMNS} FROM {self.table('runs')} "
            "WHERE tenant_id = $1 "
            "  AND ($2::text IS NULL OR status = $2) "
            "  AND ($3::uuid IS NULL OR review_id = $3) "
            "ORDER BY started_at DESC, run_id "
            "LIMIT $4 OFFSET $5",
            status,
            as_uuid(review_id),
            limit,
            offset,
        )
        return [Run.from_row(row) for row in rows]


__all__ = ("RunRepository", "as_uuid")

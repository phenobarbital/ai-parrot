"""Pending-upload registry (FEAT-731).

One row per blob returned by ``/file-upload`` that no stored submission references yet.
Cleared by ``FormSubmissionStorage.store()`` in the INSERT's transaction; swept by
``PendingUploadReaper`` (TTL by form: 48 h public / 7 days otherwise).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel

from ._identifiers import qualified_table, validate_identifier

DEFAULT_SCHEMA = "navigator"
DEFAULT_TABLE = "pending_uploads"  # FieldSync passes table_name="fs_pending_uploads"
DEFAULT_PUBLIC_FORM_TTL = timedelta(hours=48)
DEFAULT_TTL = timedelta(days=7)


class PendingUpload(BaseModel):
    """One pending (not yet submitted) uploaded blob."""

    blob_ref: str
    thumbnail_ref: str | None = None
    form_uid: uuid.UUID
    field_uid: uuid.UUID
    tenant: str
    public_form: bool  # form.is_public at upload time
    uploaded_at: datetime | None = None  # None on record -> DB default now()


class ReapResult(BaseModel):
    """Outcome of one ``reap_once`` run."""

    deleted: int = 0
    failed: int = 0
    still_referenced: int = 0


def iter_blob_refs(data: Any) -> set[str]:
    """Every ``str`` value under a ``blob_ref`` key, walking dicts/lists recursively.

    Covers ``FileEnvelope`` dicts, lists of envelopes, nested groups/arrays and
    the legacy ``{answer, blob_ref, display}`` multi-upload item. Non-string
    ``blob_ref`` values are ignored.

    Args:
        data: A submission ``data`` payload (any JSON-like structure).

    Returns:
        The set of blob refs found; empty when there are none.
    """
    found: set[str] = set()
    stack: list[Any] = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "blob_ref" and isinstance(value, str):
                    found.add(value)
                else:
                    stack.append(value)
        elif isinstance(node, (list, tuple)):
            stack.extend(node)
    return found


def _affected(status: Any) -> int:
    """Parse the row count from an asyncpg command status string (``"DELETE n"``)."""
    try:
        return int(str(status).rsplit(" ", 1)[-1])
    except (ValueError, IndexError):
        return 0


class PendingUploadStore:
    """CRUD over ``<tenant>.<table>`` (default ``pending_uploads``)."""

    def __init__(self, pool: Any, *, schema: str = DEFAULT_SCHEMA, table_name: str = DEFAULT_TABLE) -> None:
        validate_identifier(schema, kind="schema")
        validate_identifier(table_name, kind="table")
        self._pool = pool
        self._schema = schema
        self._table = table_name
        self.logger = logging.getLogger(__name__)

    def _qualified(self, tenant: str | None) -> str:
        schema = validate_identifier(tenant, kind="tenant") if tenant is not None else self._schema
        return qualified_table(schema, self._table)

    async def initialize(self, *, tenant: str | None = None) -> None:
        """CREATE TABLE / INDEX IF NOT EXISTS in <tenant or schema>."""
        qt = self._qualified(tenant)
        schema = validate_identifier(tenant, kind="tenant") if tenant is not None else self._schema
        idx_name = f"idx_{self._table}_uploaded_at"
        validate_identifier(idx_name, kind="index")
        sql = f"""
        CREATE TABLE IF NOT EXISTS {qt} (
            blob_ref       TEXT PRIMARY KEY,
            thumbnail_ref  TEXT,
            form_uid       UUID        NOT NULL,
            field_uid      UUID        NOT NULL,
            tenant         TEXT        NOT NULL,
            public_form    BOOLEAN     NOT NULL,
            uploaded_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS "{idx_name}" ON "{schema}"."{self._table}" (uploaded_at);
        """
        async with self._pool.acquire() as conn:
            await conn.execute(sql)
        self.logger.info("PendingUploadStore: %s ensured", qt)

    async def record(self, entry: PendingUpload, *, tenant: str) -> None:
        """INSERT … ON CONFLICT (blob_ref) DO UPDATE SET uploaded_at = now(), thumbnail_ref = EXCLUDED.thumbnail_ref."""
        qt = self._qualified(tenant)
        sql = f"""
        INSERT INTO {qt} (blob_ref, thumbnail_ref, form_uid, field_uid, tenant, public_form, uploaded_at)
        VALUES ($1, $2, $3, $4, $5, $6, COALESCE($7, now()))
        ON CONFLICT (blob_ref) DO UPDATE
            SET uploaded_at = now(), thumbnail_ref = EXCLUDED.thumbnail_ref
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                sql,
                entry.blob_ref,
                entry.thumbnail_ref,
                entry.form_uid,
                entry.field_uid,
                entry.tenant,
                entry.public_form,
                entry.uploaded_at,
            )

    async def clear(self, blob_refs: Iterable[str], *, tenant: str | None, conn: Any | None = None) -> int:
        """DELETE … WHERE blob_ref = ANY($1); uses ``conn`` when given (caller's transaction). No-op on empty."""
        refs = list(blob_refs)
        if not refs:
            return 0
        sql = f"DELETE FROM {self._qualified(tenant)} WHERE blob_ref = ANY($1::text[])"
        if conn is not None:
            return _affected(await conn.execute(sql, refs))
        async with self._pool.acquire() as pooled:
            return _affected(await pooled.execute(sql, refs))

    async def expired(
        self,
        *,
        tenant: str,
        public_form_ttl: timedelta,
        ttl: timedelta,
        limit: int,
        conn: Any | None = None,
    ) -> list[PendingUpload]:
        """Rows past their TTL, oldest first.

        ``(public_form AND uploaded_at < now()-public_form_ttl) OR
        (NOT public_form AND uploaded_at < now()-ttl)``. ``FOR UPDATE SKIP LOCKED``
        when ``conn`` is given (caller holds a transaction).
        """
        sql = f"""
        SELECT blob_ref, thumbnail_ref, form_uid, field_uid, tenant, public_form, uploaded_at
        FROM {self._qualified(tenant)}
        WHERE (public_form AND uploaded_at < now() - $1::interval)
           OR (NOT public_form AND uploaded_at < now() - $2::interval)
        ORDER BY uploaded_at
        LIMIT $3
        """
        if conn is not None:
            sql += " FOR UPDATE SKIP LOCKED"
            rows = await conn.fetch(sql, public_form_ttl, ttl, limit)
        else:
            async with self._pool.acquire() as pooled:
                rows = await pooled.fetch(sql, public_form_ttl, ttl, limit)
        return [PendingUpload(**dict(row)) for row in rows]

    async def delete_rows(self, blob_refs: Iterable[str], *, tenant: str) -> int:
        """Delete rows by blob_ref (pooled connection)."""
        return await self.clear(blob_refs, tenant=tenant)

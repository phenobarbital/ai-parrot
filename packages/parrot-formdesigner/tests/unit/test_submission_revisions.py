"""Tests for the FormSubmissionStorage revision-chain contract.

Covers the additive revision-chain columns (``root_submission_id``,
``revision``, ``context``), the ``store()`` INSERT threading them through,
and the ``get_submission`` / ``list_revisions`` read API. Backward
compatibility: legacy rows with NULL chain columns must still load, and
``store()`` must remain insert-only.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from parrot_formdesigner.services.submissions import (
    FormSubmission,
    FormSubmissionStorage,
)

from .test_storage_schema_tenant import _RecordingConn, _RecordingPool


# ---------------------------------------------------------------------------
# A pool whose connection returns pre-seeded rows for reads
# ---------------------------------------------------------------------------


class _RowsConn(_RecordingConn):
    """Recording connection that also returns seeded rows on reads."""

    def __init__(self, *, row=None, rows=None) -> None:
        super().__init__()
        self._row = row
        self._rows = rows or []

    async def fetchrow(self, sql: str, *args):
        self.fetched.append((sql, args))
        return self._row

    async def fetch(self, sql: str, *args):
        self.fetched.append((sql, args))
        return list(self._rows)


class _RowsPool(_RecordingPool):
    def __init__(self, *, row=None, rows=None) -> None:
        super().__init__()
        self.conn = _RowsConn(row=row, rows=rows)


def _db_row(
    submission_id: str,
    *,
    root_submission_id: str | None = None,
    revision: int | None = None,
    context: str | None = None,
    data: str = '{"q1": "yes"}',
) -> dict:
    """A dict shaped like an asyncpg Record for the SELECT column set.

    JSONB columns (``data``, ``context``) arrive as ``str`` and ``ip`` as
    an object stringified by the mapper — mirrors real asyncpg behavior.
    """
    return {
        "submission_id": submission_id,
        "form_id": "f-1",
        "form_version": "1.0",
        "data": data,
        "is_valid": True,
        "forwarded": False,
        "forward_status": None,
        "forward_error": None,
        "tenant": None,
        "created_at": datetime(2026, 7, 21, tzinfo=timezone.utc),
        "user_id": "u-1",
        "username": "alice",
        "org_id": 7,
        "submitted_at": datetime(2026, 7, 21, tzinfo=timezone.utc),
        "ip": "203.0.113.5",
        "user_agent": "ParrotTest/1.0",
        "locale": "en-US",
        "root_submission_id": root_submission_id,
        "revision": revision,
        "context": context,
    }


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class TestFormSubmissionRevisionFields:
    def test_defaults_none(self) -> None:
        sub = FormSubmission(
            form_id="f", form_version="1.0", data={}, is_valid=True
        )
        assert sub.root_submission_id is None
        assert sub.revision is None
        assert sub.context is None

    def test_roundtrip(self) -> None:
        sub = FormSubmission(
            form_id="f",
            form_version="1.0",
            data={},
            is_valid=True,
            root_submission_id="root-1",
            revision=2,
            context={"geofence_status": "outside", "post_visit": True},
        )
        restored = FormSubmission.model_validate(sub.model_dump())
        assert restored.root_submission_id == "root-1"
        assert restored.revision == 2
        assert restored.context == {
            "geofence_status": "outside",
            "post_visit": True,
        }


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------


class TestRevisionDDL:
    @pytest.mark.asyncio
    async def test_create_declares_revision_columns_and_index(self) -> None:
        pool = _RecordingPool()
        await FormSubmissionStorage(pool=pool).initialize()
        create_sql = pool.conn.executed[0][0]
        assert "root_submission_id VARCHAR(255)" in create_sql
        assert "revision INTEGER" in create_sql
        assert "context JSONB" in create_sql
        assert "idx_form_data_root_submission_id" in create_sql

    @pytest.mark.asyncio
    async def test_alter_adds_revision_columns_and_index(self) -> None:
        pool = _RecordingPool()
        await FormSubmissionStorage(pool=pool).initialize()
        alter_sql = pool.conn.executed[1][0]
        assert "ADD COLUMN IF NOT EXISTS root_submission_id" in alter_sql
        assert "ADD COLUMN IF NOT EXISTS revision" in alter_sql
        assert "ADD COLUMN IF NOT EXISTS context" in alter_sql
        assert "idx_form_data_root_submission_id" in alter_sql


# ---------------------------------------------------------------------------
# store() — insert-only, carries chain columns
# ---------------------------------------------------------------------------


class TestStoreRevisionColumns:
    @pytest.mark.asyncio
    async def test_store_carries_chain_values(self) -> None:
        pool = _RecordingPool()
        await FormSubmissionStorage(pool=pool).store(
            FormSubmission(
                form_id="f",
                form_version="1.0",
                data={},
                is_valid=True,
                submission_id="sub-1",
                root_submission_id="sub-1",
                revision=1,
                context={"geofence_status": "ok"},
            )
        )
        sql, args = pool.conn.executed[0]
        # args (1-indexed): ... 18 root_submission_id, 19 revision, 20 context
        assert args[17] == "sub-1"
        assert args[18] == 1
        assert json.loads(args[19]) == {"geofence_status": "ok"}
        assert sql.strip().upper().startswith("INSERT INTO")

    @pytest.mark.asyncio
    async def test_store_nulls_context_when_unset(self) -> None:
        pool = _RecordingPool()
        await FormSubmissionStorage(pool=pool).store(
            FormSubmission(
                form_id="f", form_version="1.0", data={}, is_valid=True
            )
        )
        _, args = pool.conn.executed[0]
        assert args[17] is None  # root_submission_id
        assert args[18] is None  # revision
        assert args[19] is None  # context

    @pytest.mark.asyncio
    async def test_store_never_updates_or_deletes(self) -> None:
        pool = _RecordingPool()
        storage = FormSubmissionStorage(pool=pool)
        await storage.store(
            FormSubmission(
                form_id="f", form_version="1.0", data={}, is_valid=True,
                submission_id="sub-1", root_submission_id="sub-1", revision=1,
            )
        )
        await storage.store(
            FormSubmission(
                form_id="f", form_version="1.0", data={}, is_valid=True,
                submission_id="sub-2", root_submission_id="sub-1", revision=2,
            )
        )
        for sql, _ in pool.conn.executed:
            upper = sql.strip().upper()
            assert "UPDATE" not in upper
            assert "DELETE" not in upper


# ---------------------------------------------------------------------------
# Read API
# ---------------------------------------------------------------------------


class TestReadAPI:
    @pytest.mark.asyncio
    async def test_get_submission_returns_none_when_absent(self) -> None:
        pool = _RowsPool(row=None)
        result = await FormSubmissionStorage(pool=pool).get_submission("nope")
        assert result is None
        sql, args = pool.conn.fetched[0]
        assert "WHERE submission_id = $1" in sql
        assert args == ("nope",)

    @pytest.mark.asyncio
    async def test_get_submission_maps_row(self) -> None:
        row = _db_row(
            "sub-2",
            root_submission_id="sub-1",
            revision=2,
            context='{"geofence_status": "outside", "post_visit": true}',
        )
        pool = _RowsPool(row=row)
        sub = await FormSubmissionStorage(pool=pool).get_submission("sub-2")
        assert sub is not None
        assert sub.submission_id == "sub-2"
        assert sub.root_submission_id == "sub-1"
        assert sub.revision == 2
        assert sub.data == {"q1": "yes"}  # JSONB str decoded
        assert sub.context == {"geofence_status": "outside", "post_visit": True}
        assert sub.ip == "203.0.113.5"  # INET stringified

    @pytest.mark.asyncio
    async def test_list_revisions_orders_by_revision_asc(self) -> None:
        rows = [
            _db_row("sub-1", root_submission_id="sub-1", revision=1),
            _db_row("sub-2", root_submission_id="sub-1", revision=2),
        ]
        pool = _RowsPool(rows=rows)
        chain = await FormSubmissionStorage(pool=pool).list_revisions("sub-1")
        assert [s.revision for s in chain] == [1, 2]
        sql, args = pool.conn.fetched[0]
        assert "WHERE root_submission_id = $1" in sql
        assert "ORDER BY revision ASC" in sql
        assert args == ("sub-1",)

    @pytest.mark.asyncio
    async def test_list_revisions_empty(self) -> None:
        pool = _RowsPool(rows=[])
        chain = await FormSubmissionStorage(pool=pool).list_revisions("nope")
        assert chain == []

    @pytest.mark.asyncio
    async def test_legacy_null_chain_row_loads(self) -> None:
        """A pre-migration row (NULL root/revision/context) still maps."""
        row = _db_row("legacy-1", root_submission_id=None, revision=None)
        pool = _RowsPool(row=row)
        sub = await FormSubmissionStorage(pool=pool).get_submission("legacy-1")
        assert sub is not None
        assert sub.root_submission_id is None
        assert sub.revision is None
        assert sub.context is None

    @pytest.mark.asyncio
    async def test_read_uses_tenant_override(self) -> None:
        pool = _RowsPool(row=None)
        await FormSubmissionStorage(pool=pool).get_submission(
            "x", tenant="epson"
        )
        sql, _ = pool.conn.fetched[0]
        assert '"epson"."form_data"' in sql

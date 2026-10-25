"""FEAT-731 — PendingUploadStore + iter_blob_refs (fake connection; real SQL in the PG tests)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest

from parrot_formdesigner.services.pending_uploads import (
    DEFAULT_PUBLIC_FORM_TTL,
    DEFAULT_TTL,
    PendingUpload,
    PendingUploadStore,
    iter_blob_refs,
)


class FakeConn:
    def __init__(self, rows: list[dict[str, Any]] | None = None, status: str = "DELETE 2") -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.rows = rows or []
        self.status = status

    async def execute(self, sql: str, *args: Any) -> str:
        self.calls.append((sql, args))
        return self.status

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        self.calls.append((sql, args))
        return self.rows


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn
        self.acquired = 0

    def acquire(self) -> "FakePool":
        self.acquired += 1
        return self

    async def __aenter__(self) -> FakeConn:
        return self.conn

    async def __aexit__(self, *exc: Any) -> None:
        return None


def _entry() -> PendingUpload:
    return PendingUpload(
        blob_ref="s3://b/k/1",
        thumbnail_ref="s3://b/k/t1",
        form_uid=uuid.uuid4(),
        field_uid=uuid.uuid4(),
        tenant="acme",
        public_form=True,
    )


def test_constants():
    assert DEFAULT_PUBLIC_FORM_TTL == timedelta(hours=48)
    assert DEFAULT_TTL == timedelta(days=7)


def test_iter_blob_refs_shapes():
    env = {"blob_ref": "a", "thumbnail_url": "x"}
    assert iter_blob_refs(env) == {"a"}
    assert iter_blob_refs({"f": [env, {"blob_ref": "b"}]}) == {"a", "b"}
    nested = {"grp": {"rows": [{"photo": {"blob_ref": "c"}}, {"photo": {"blob_ref": "d"}}]}}
    assert iter_blob_refs(nested) == {"c", "d"}
    legacy = {"f": [{"answer": "x", "blob_ref": "e", "display": "x.png"}]}
    assert iter_blob_refs(legacy) == {"e"}
    assert iter_blob_refs({"blob_ref": 5, "g": {"blob_ref": None}}) == set()
    assert iter_blob_refs({"a": 1, "b": ["x", 2]}) == set()
    assert iter_blob_refs(None) == set()


def test_store_rejects_bad_identifiers():
    with pytest.raises(ValueError):
        PendingUploadStore(FakePool(FakeConn()), schema="bad;drop")
    with pytest.raises(ValueError):
        PendingUploadStore(FakePool(FakeConn()), table_name="x y")
    store = PendingUploadStore(FakePool(FakeConn()))
    with pytest.raises(ValueError):
        store._qualified("a-b")


async def test_initialize_ddl():
    conn = FakeConn()
    store = PendingUploadStore(FakePool(conn), table_name="fs_pending_uploads")
    await store.initialize(tenant="acme")
    sql = conn.calls[0][0]
    assert 'CREATE TABLE IF NOT EXISTS "acme"."fs_pending_uploads"' in sql
    assert "blob_ref       TEXT PRIMARY KEY" in sql
    assert "public_form    BOOLEAN     NOT NULL" in sql
    assert '"idx_fs_pending_uploads_uploaded_at"' in sql


async def test_record_is_upsert():
    conn = FakeConn()
    store = PendingUploadStore(FakePool(conn))
    await store.record(_entry(), tenant="acme")
    sql, args = conn.calls[0]
    assert "ON CONFLICT (blob_ref) DO UPDATE" in sql
    assert "uploaded_at = now()" in sql
    assert '"acme"."pending_uploads"' in sql
    assert args[0] == "s3://b/k/1" and args[5] is True


async def test_clear_empty_is_noop():
    conn = FakeConn()
    pool = FakePool(conn)
    store = PendingUploadStore(pool)
    assert await store.clear([], tenant="acme") == 0
    assert conn.calls == [] and pool.acquired == 0


async def test_clear_uses_given_conn():
    conn, other = FakeConn(), FakeConn()
    pool = FakePool(other)
    store = PendingUploadStore(pool)
    assert await store.clear({"a", "b"}, tenant="acme", conn=conn) == 2
    assert len(conn.calls) == 1 and pool.acquired == 0 and other.calls == []
    assert "DELETE FROM" in conn.calls[0][0] and "ANY($1" in conn.calls[0][0]
    assert sorted(conn.calls[0][1][0]) == ["a", "b"]
    # without conn: uses the pool
    assert await store.delete_rows(["a"], tenant="acme") == 2
    assert pool.acquired == 1 and len(other.calls) == 1


async def test_expired_query_uses_both_ttls():
    row = {
        "blob_ref": "r",
        "thumbnail_ref": None,
        "form_uid": uuid.uuid4(),
        "field_uid": uuid.uuid4(),
        "tenant": "acme",
        "public_form": False,
        "uploaded_at": None,
    }
    conn = FakeConn(rows=[row])
    store = PendingUploadStore(FakePool(conn))
    out = await store.expired(
        tenant="acme",
        public_form_ttl=timedelta(hours=48),
        ttl=timedelta(days=7),
        limit=10,
        conn=conn,
    )
    sql, args = conn.calls[0]
    assert "public_form AND uploaded_at" in sql and "NOT public_form AND uploaded_at" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql and "ORDER BY uploaded_at" in sql
    assert args == (timedelta(hours=48), timedelta(days=7), 10)
    assert out[0].blob_ref == "r"
    # pooled variant: no row locking
    pconn = FakeConn()
    await PendingUploadStore(FakePool(pconn)).expired(
        tenant="acme",
        public_form_ttl=timedelta(hours=1),
        ttl=timedelta(hours=2),
        limit=1,
    )
    assert "SKIP LOCKED" not in pconn.calls[0][0]

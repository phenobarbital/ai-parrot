"""Unit tests for DatabaseToolkitBinder + FakeRawConnection (TASK-1419).

These tests use a lightweight stub toolkit to avoid importing the full
``parrot.bots`` stack (which has optional deps not available in the test venv).
The binder logic is fully exercised via the stub.
"""
import pytest
from contextlib import asynccontextmanager
from typing import Any

from parrot.eval import DatabaseToolkitBinder, DictStateBackend
from parrot.eval.sandbox.fakes import FakeRawConnection


class _StubToolkit:
    """Minimal stub that mimics DatabaseToolkit's injection points."""

    def __init__(self) -> None:
        self._connected: bool = False
        self._connection: Any = None
        self.primary_schema: str = "public"
        self._start_called: bool = False

    async def start(self) -> None:
        self._start_called = True

    @asynccontextmanager
    async def _acquire_asyncdb_connection(self):
        if self._connection is None:
            raise RuntimeError("Not connected")
        yield self._connection

    def _resolve_table(self, table: str) -> tuple:
        raise RuntimeError("Not connected — no metadata cache")


async def test_db_binder_sets_connected():
    """Binder marks toolkit._connected = True."""
    toolkit = _StubToolkit()
    assert toolkit._connected is False

    backend = DictStateBackend()
    binder = DatabaseToolkitBinder()
    binder.bind(toolkit, backend)

    assert toolkit._connected is True


async def test_db_binder_no_real_start():
    """start() is never called after binding."""
    toolkit = _StubToolkit()
    backend = DictStateBackend()
    binder = DatabaseToolkitBinder()
    binder.bind(toolkit, backend)

    # start() should NOT have been called
    assert toolkit._start_called is False


async def test_db_binder_acquire_connection_is_fake():
    """After binding, _acquire_asyncdb_connection yields a FakeRawConnection."""
    toolkit = _StubToolkit()
    backend = DictStateBackend()
    binder = DatabaseToolkitBinder()
    binder.bind(toolkit, backend)

    async with toolkit._acquire_asyncdb_connection() as conn:
        assert isinstance(conn, FakeRawConnection)


async def test_db_binder_resolve_table_returns_stub():
    """After binding, _resolve_table returns a (schema, table_name, meta) tuple."""
    from parrot.eval.sandbox.fakes import FakeTableMetadata

    toolkit = _StubToolkit()
    backend = DictStateBackend()
    binder = DatabaseToolkitBinder()
    binder.bind(toolkit, backend)

    schema, table_name, meta = toolkit._resolve_table("public.items")
    assert schema == "public"
    assert table_name == "items"
    assert isinstance(meta, FakeTableMetadata)
    assert meta.schema == "public"
    assert meta.tablename == "items"


async def test_fake_raw_connection_execute_doesnt_crash():
    """FakeRawConnection.execute for UPDATE doesn't raise."""
    backend = DictStateBackend()
    await backend.reset({"users": {"u1": {"name": "alice"}}})

    conn = FakeRawConnection(backend)
    await conn.execute(
        'UPDATE "public"."users" SET "name" = $1 WHERE "id" = $2',
        "bob",
        "u1",
    )
    # We only assert no exception is raised; the fake SQL parser is best-effort
    snap = await backend.snapshot()
    assert "users" in snap


async def test_fake_raw_connection_fetch_returns_list():
    """FakeRawConnection.fetch returns a list."""
    backend = DictStateBackend()
    await backend.reset({"users": {"u1": {"name": "alice"}}})

    conn = FakeRawConnection(backend)
    rows = await conn.fetch('SELECT * FROM "public"."users"')
    assert isinstance(rows, list)


async def test_fake_raw_connection_fetchrow_returns_dict_or_none():
    """FakeRawConnection.fetchrow returns a dict or None."""
    backend = DictStateBackend()
    await backend.reset({"users": {"u1": {"name": "alice"}}})

    conn = FakeRawConnection(backend)
    row = await conn.fetchrow('SELECT * FROM "public"."users" WHERE "id" = $1', "u1")
    assert row is None or isinstance(row, dict)


async def test_two_binders_independent_backends():
    """Two toolkits bound to different backends are independent."""
    tk1 = _StubToolkit()
    tk2 = _StubToolkit()
    b1 = DictStateBackend()
    b2 = DictStateBackend()
    binder = DatabaseToolkitBinder()
    binder.bind(tk1, b1)
    binder.bind(tk2, b2)

    await b1.reset({"t": {"e1": {"v": 1}}})
    await b2.reset({"t": {"e1": {"v": 2}}})

    async with tk1._acquire_asyncdb_connection() as c1:
        assert c1._backend is b1
    async with tk2._acquire_asyncdb_connection() as c2:
        assert c2._backend is b2

"""Unit tests for DatabaseToolkit._acquire_asyncdb_connection boundary unwrap.

TASK-926 — FEAT-118: verifies that _acquire_asyncdb_connection yields the raw
native connection (via wrapper.engine()) rather than the asyncdb wrapper
itself, and that the pool path still releases the wrapper (not the raw conn).
"""
from __future__ import annotations

import os
import sys

# Load worktree source (must precede any parrot imports)
# __file__ is tests/unit/bots/database/toolkits/ — go 3 levels up to tests/unit/
_UNIT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir)
)
sys.path.insert(0, _UNIT_DIR)
from conftest_db import setup_worktree_imports  # noqa: E402
setup_worktree_imports()

import pytest  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from parrot.bots.database.toolkits.base import DatabaseToolkit  # noqa: E402
from parrot.bots.database.models import QueryExecutionResponse  # noqa: E402


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class FakeRawConn:
    """Stub for raw asyncpg.Connection (or any dialect's native connection)."""

    async def fetch(self, sql: str, *args) -> list:
        """Fetch rows."""
        return []

    async def fetchrow(self, sql: str, *args):
        """Fetch a single row."""
        return None

    async def execute(self, sql: str, *args) -> str:
        """Execute a statement."""
        return "ok"


class FakeWrapper:
    """Stub for asyncdb pg driver wrapper."""

    def __init__(self) -> None:
        self._raw = FakeRawConn()

    def engine(self) -> FakeRawConn:
        """Return the underlying raw connection."""
        return self._raw

    @asynccontextmanager
    async def __aenter__(self):
        yield self

    async def __aexit__(self, *args):
        pass


class FakeSingleConnection:
    """Stub for the single-connection asyncdb AsyncDB object.

    Simulates: ``async with await self._connection.connection() as conn``
    where conn is an asyncdb wrapper.
    """

    def __init__(self) -> None:
        self._wrapper = FakeWrapper()

    async def connection(self) -> "FakeSingleConnection":
        """Return self as async context manager."""
        return self

    async def __aenter__(self) -> FakeWrapper:
        return self._wrapper

    async def __aexit__(self, *args) -> None:
        pass


class FakePool:
    """Stub for asyncdb pgPool."""

    def __init__(self) -> None:
        self._wrapper = FakeWrapper()
        self._released: object = None

    async def acquire(self) -> FakeWrapper:
        """Acquire a wrapper from the pool."""
        return self._wrapper

    async def release(self, conn: object) -> None:
        """Record what was passed to release."""
        self._released = conn


# ---------------------------------------------------------------------------
# Concrete toolkit subclass (minimal)
# ---------------------------------------------------------------------------

class _MinimalToolkit(DatabaseToolkit):
    """Concrete subclass for testing — no real DB interaction."""

    async def search_schema(self, search_term, schema_name=None, limit=10):
        """Search schema stub."""
        return []

    async def execute_query(self, query, limit=1000, timeout=30):
        """Execute query stub."""
        return QueryExecutionResponse(
            success=True, row_count=0, execution_time_ms=0.0, schema_used="public"
        )


# ---------------------------------------------------------------------------
# Tests — pool path
# ---------------------------------------------------------------------------

class TestAcquireAsyncdbConnectionPool:
    """Pool-path tests for _acquire_asyncdb_connection boundary unwrap."""

    @pytest.mark.asyncio
    async def test_acquire_asyncdb_yields_raw_asyncpg(self):
        """Pool path: yielded object is the raw conn from engine(), not the wrapper."""
        pool = FakePool()
        tk = _MinimalToolkit(dsn="postgresql://test", use_pool=True)
        tk._connection = pool  # inject fake pool

        async with tk._acquire_asyncdb_connection() as conn:
            assert conn is pool._wrapper._raw, (
                "Expected raw FakeRawConn from wrapper.engine(), got wrapper itself"
            )
            assert isinstance(conn, FakeRawConn)

    @pytest.mark.asyncio
    async def test_acquire_asyncdb_pool_releases_wrapper(self):
        """Pool path: pool.release() receives the wrapper, not the raw conn."""
        pool = FakePool()
        tk = _MinimalToolkit(dsn="postgresql://test", use_pool=True)
        tk._connection = pool

        async with tk._acquire_asyncdb_connection() as conn:
            raw_conn = conn  # the raw connection

        assert pool._released is pool._wrapper, (
            "pool.release() must receive the asyncdb wrapper, not the raw connection"
        )
        assert pool._released is not raw_conn, (
            "pool.release() must NOT receive the raw connection"
        )

    @pytest.mark.asyncio
    async def test_pool_release_called_on_exception(self):
        """Pool path: wrapper is released even when the body raises."""
        pool = FakePool()
        tk = _MinimalToolkit(dsn="postgresql://test", use_pool=True)
        tk._connection = pool

        with pytest.raises(RuntimeError, match="test error"):
            async with tk._acquire_asyncdb_connection():
                raise RuntimeError("test error")

        assert pool._released is pool._wrapper, (
            "Wrapper must be released even when the body raises"
        )


# ---------------------------------------------------------------------------
# Tests — single-connection path
# ---------------------------------------------------------------------------

class TestAcquireAsyncdbConnectionSingle:
    """Single-connection path tests for _acquire_asyncdb_connection."""

    @pytest.mark.asyncio
    async def test_single_conn_yields_raw(self):
        """Single path: yielded object is the raw conn from engine()."""
        fake_single = FakeSingleConnection()
        tk = _MinimalToolkit(dsn="postgresql://test", use_pool=False)
        tk._connection = fake_single

        async with tk._acquire_asyncdb_connection() as conn:
            assert conn is fake_single._wrapper._raw, (
                "Expected raw FakeRawConn from wrapper.engine()"
            )
            assert isinstance(conn, FakeRawConn)

    @pytest.mark.asyncio
    async def test_not_connected_raises(self):
        """RuntimeError raised when _connection is None."""
        tk = _MinimalToolkit(dsn="postgresql://test")
        tk._connection = None

        with pytest.raises(RuntimeError, match="Not connected"):
            async with tk._acquire_asyncdb_connection():
                pass  # should not reach here

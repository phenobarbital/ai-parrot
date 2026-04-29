"""Unit tests for PostgresToolkit.transaction() asyncpg-native rewrite.

TASK-929 — FEAT-118: verifies that transaction() yields a raw asyncpg
connection and that nested transaction() calls are supported (savepoints).
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
from unittest.mock import MagicMock  # noqa: E402

from parrot.bots.database.toolkits.postgres import PostgresToolkit  # noqa: E402


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class FakeTransaction:
    """Stub for asyncpg Transaction context manager."""

    def __init__(self) -> None:
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> "FakeTransaction":
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self.exited = True


class FakeRawConn:
    """Stub for raw asyncpg.Connection."""

    def __init__(self) -> None:
        self._tx = FakeTransaction()
        self.fetch_calls: list[tuple] = []
        self.execute_calls: list[tuple] = []

    def transaction(self) -> FakeTransaction:
        """Return asyncpg-style Transaction context manager."""
        return self._tx

    async def fetch(self, sql: str, *args) -> list:
        """Record fetch call."""
        self.fetch_calls.append((sql, args))
        return []

    async def fetchrow(self, sql: str, *args):
        """Return None (no row)."""
        return None

    async def execute(self, sql: str, *args) -> str:
        """Record execute call."""
        self.execute_calls.append((sql, args))
        return "ok"


class FakeWrapper:
    """Stub asyncdb wrapper that yields FakeRawConn via engine()."""

    def __init__(self) -> None:
        self._raw = FakeRawConn()

    def engine(self) -> FakeRawConn:
        """Return the raw connection."""
        return self._raw


class FakeSingleConnection:
    """Stub asyncdb single-connection driver."""

    def __init__(self) -> None:
        self._wrapper = FakeWrapper()

    async def connection(self) -> "FakeSingleConnection":
        """Return self as async context manager."""
        return self

    async def __aenter__(self) -> FakeWrapper:
        return self._wrapper

    async def __aexit__(self, *args) -> None:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_toolkit(read_only: bool = True) -> PostgresToolkit:
    """Build a PostgresToolkit injected with a fake connection."""
    tk = PostgresToolkit(
        dsn="postgresql://localhost/test",
        tables=["public.t"],
        read_only=read_only,
    )
    fake = FakeSingleConnection()
    tk._connection = fake
    return tk


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTransactionYieldsRaw:
    @pytest.mark.asyncio
    async def test_transaction_yields_raw_asyncpg(self):
        """transaction() yields raw FakeRawConn (has fetch/fetchrow/execute)."""
        tk = make_toolkit()

        async with tk.transaction() as tx:
            assert isinstance(tx, FakeRawConn), (
                f"Expected FakeRawConn, got {type(tx).__name__!r}"
            )
            assert hasattr(tx, "fetch")
            assert hasattr(tx, "fetchrow")
            assert hasattr(tx, "execute")

    @pytest.mark.asyncio
    async def test_transaction_enters_asyncpg_transaction(self):
        """transaction() opens an asyncpg transaction block."""
        tk = make_toolkit()
        fake_single = tk._connection

        async with tk.transaction() as tx:
            assert fake_single._wrapper._raw._tx.entered, (
                "asyncpg transaction() should have been entered"
            )

        assert fake_single._wrapper._raw._tx.exited, (
            "asyncpg transaction() should have been exited"
        )

    @pytest.mark.asyncio
    async def test_transaction_rollback_on_exception(self):
        """transaction() propagates exceptions (rolls back via asyncpg)."""
        tk = make_toolkit()

        with pytest.raises(ValueError, match="test rollback"):
            async with tk.transaction() as tx:
                raise ValueError("test rollback")

    @pytest.mark.asyncio
    async def test_no_in_transaction_flag(self):
        """PostgresToolkit no longer has a _in_transaction guard."""
        tk = make_toolkit()
        assert not hasattr(tk, "_in_transaction"), (
            "_in_transaction flag was removed in TASK-929"
        )

    @pytest.mark.asyncio
    async def test_transaction_conn_usable_inside(self):
        """Conn yielded by transaction() can call fetch/execute."""
        tk = make_toolkit()

        async with tk.transaction() as tx:
            await tx.fetch("SELECT $1", 42)
            await tx.execute("UPDATE t SET x=$1 WHERE id=$2", 1, 99)

        raw = tk._connection._wrapper._raw
        assert ("SELECT $1", (42,)) in raw.fetch_calls
        assert ("UPDATE t SET x=$1 WHERE id=$2", (1, 99)) in raw.execute_calls

    @pytest.mark.asyncio
    async def test_nested_transaction_no_runtime_error(self):
        """Nested transaction() calls do not raise RuntimeError.

        After TASK-929 the guard is removed; asyncpg handles nesting as
        savepoints natively. Here we simulate a nested call with fake stubs.
        """
        class _NestedTx:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass

        class _NestedRaw(FakeRawConn):
            def transaction(self):
                return _NestedTx()

        class _NestedWrapper(FakeWrapper):
            def __init__(self):
                self._raw = _NestedRaw()

        class _NestedSingle(FakeSingleConnection):
            def __init__(self):
                self._wrapper = _NestedWrapper()

        tk = make_toolkit()
        tk._connection = _NestedSingle()

        # Calling transaction() twice sequentially is fine (not blocked by guard)
        async with tk.transaction() as tx1:
            assert tx1 is tk._connection._wrapper._raw

        async with tk.transaction() as tx2:
            assert tx2 is tk._connection._wrapper._raw

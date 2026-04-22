"""Regression tests for FEAT-112 Modules 3 & 4 overrides:

- ``NavigatorToolkit._build_table_metadata`` — warms cache via raw
  asyncpg ``$1 / $2`` params.
- ``NavigatorToolkit.transaction()`` — runs on asyncpg native
  ``Connection.transaction()`` (async context manager with savepoints).

Spec: sdd/specs/navigator-toolkit-asyncdb-conn-unwrap.spec.md  (v0.4)
Task:  sdd/tasks/active/TASK-799-navigator-metadata-and-tx-tests.md
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager

# Load worktree source first (same pattern as the sibling tests).
sys.path.insert(0, os.path.dirname(__file__))
from conftest_db import setup_worktree_imports  # noqa: E402
setup_worktree_imports()

_WT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
_TOOLS_SRC = os.path.join(_WT_ROOT, "packages", "ai-parrot-tools", "src")
if _TOOLS_SRC not in sys.path:
    sys.path.insert(0, _TOOLS_SRC)

import pytest  # noqa: E402

from parrot.bots.database.models import TableMetadata  # noqa: E402
from parrot_tools.navigator.toolkit import NavigatorToolkit  # noqa: E402


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _RawAsyncpgStub:
    """Stand-in for asyncpg.Connection.

    ``fetch`` returns rows matched by SQL substring (so the stub
    serves all three introspection queries used by
    ``_build_table_metadata``: columns / primary keys / unique
    constraints).

    ``transaction()`` is an async context manager — matches asyncpg's
    native API.
    """

    def __init__(
        self,
        col_rows=None,
        pk_rows=None,
        uq_rows=None,
    ):
        self.col_rows = col_rows if col_rows is not None else [
            {
                "column_name": "program_id",
                "data_type": "integer",
                "is_nullable": "NO",
                "column_default": None,
                "ordinal_position": 1,
            },
            {
                "column_name": "program_slug",
                "data_type": "text",
                "is_nullable": "YES",
                "column_default": None,
                "ordinal_position": 2,
            },
        ]
        self.pk_rows = pk_rows if pk_rows is not None else [
            {"column_name": "program_id"},
        ]
        self.uq_rows = uq_rows if uq_rows is not None else [
            {
                "constraint_name": "programs_slug_key",
                "column_name": "program_slug",
                "ordinal_position": 1,
            },
        ]
        self.fetch_calls: list[tuple] = []
        self.transaction_enters = 0
        self.transaction_exits = 0

    async def fetch(self, sql: str, *args):
        self.fetch_calls.append((sql, args))
        if "information_schema.columns" in sql:
            return self.col_rows
        if "'PRIMARY KEY'" in sql:
            return self.pk_rows
        if "'UNIQUE'" in sql:
            return self.uq_rows
        return []

    def transaction(self):
        """asyncpg.Connection.transaction() → sync-returned async CM."""
        outer = self

        @asynccontextmanager
        async def _cm():
            outer.transaction_enters += 1
            try:
                yield outer
            finally:
                outer.transaction_exits += 1

        return _cm()


class _AsyncdbWrapperStub:
    """Stand-in for the asyncdb ``pg`` driver wrapper.

    ``engine()`` returns the raw stub.  Its own ``transaction`` /
    ``fetch`` methods match the **broken** asyncdb shapes and raise
    if called — proving the overrides never hit the wrapper path.
    """

    def __init__(self, raw: _RawAsyncpgStub):
        self._raw = raw

    def engine(self):
        return self._raw

    async def fetch(self, number=1):  # cursor-advance shape
        raise AssertionError("wrapper.fetch should not be called")

    async def transaction(self):  # async def coroutine, NOT a CM
        raise AssertionError("wrapper.transaction should not be called")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def raw():
    return _RawAsyncpgStub()


@pytest.fixture
def wrapped(raw):
    return _AsyncdbWrapperStub(raw)


@pytest.fixture
def toolkit(wrapped):
    """Minimal NavigatorToolkit instance with monkeypatched connection source.

    We bypass ``__init__`` (which requires a DSN + full config) by
    constructing via ``__new__`` and setting only the attributes the
    overrides under test actually read.
    """
    tk = NavigatorToolkit.__new__(NavigatorToolkit)
    tk._in_transaction = False

    # Route _acquire_asyncdb_connection to yield the wrapper stub.
    @asynccontextmanager
    async def _fake_acquire(self=None):
        yield wrapped

    tk._acquire_asyncdb_connection = _fake_acquire.__get__(tk, NavigatorToolkit)

    # Minimal logger — attribute is used inside _build_table_metadata.
    import logging
    tk.logger = logging.getLogger("test_navigator_metadata_tx")

    return tk


# ---------------------------------------------------------------------------
# _build_table_metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_table_metadata_populates_columns(toolkit, raw):
    result = await toolkit._build_table_metadata(
        "auth", "programs", "BASE TABLE", None
    )
    assert isinstance(result, TableMetadata)
    assert len(result.columns) == 2
    assert {c["name"] for c in result.columns} == {"program_id", "program_slug"}
    assert result.columns[0]["type"] == "integer"
    assert result.columns[0]["nullable"] is False
    assert result.columns[1]["nullable"] is True


@pytest.mark.asyncio
async def test_build_table_metadata_populates_primary_keys(toolkit):
    result = await toolkit._build_table_metadata(
        "auth", "programs", "BASE TABLE", None
    )
    assert result.primary_keys == ["program_id"]


@pytest.mark.asyncio
async def test_build_table_metadata_groups_unique_constraints(toolkit):
    result = await toolkit._build_table_metadata(
        "auth", "programs", "BASE TABLE", None
    )
    assert result.unique_constraints == [["program_slug"]]


@pytest.mark.asyncio
async def test_build_table_metadata_uses_dollar_placeholders(toolkit, raw):
    """All three introspection queries must pass schema+table as $1/$2."""
    await toolkit._build_table_metadata("auth", "programs", "BASE TABLE", None)
    assert len(raw.fetch_calls) == 3
    for sql, args in raw.fetch_calls:
        assert "$1" in sql and "$2" in sql
        assert args == ("auth", "programs")


@pytest.mark.asyncio
async def test_build_table_metadata_empty_columns_returns_none(wrapped):
    """If the table genuinely doesn't exist (no columns), return None."""
    raw_empty = _RawAsyncpgStub(col_rows=[])
    wrapper = _AsyncdbWrapperStub(raw_empty)
    tk = NavigatorToolkit.__new__(NavigatorToolkit)
    tk._in_transaction = False

    @asynccontextmanager
    async def _fake_acquire(self=None):
        yield wrapper

    tk._acquire_asyncdb_connection = _fake_acquire.__get__(tk, NavigatorToolkit)
    import logging
    tk.logger = logging.getLogger("test")

    result = await tk._build_table_metadata("auth", "missing", "BASE TABLE", None)
    assert result is None


@pytest.mark.asyncio
async def test_build_table_metadata_wrapper_fetch_never_called(toolkit, wrapped, raw):
    """Proves unwrap via engine() — wrapper.fetch would raise if hit."""
    # Just run it; _AsyncdbWrapperStub.fetch raises AssertionError
    # if invoked, so a successful run proves the raw path was used.
    await toolkit._build_table_metadata("auth", "programs", "BASE TABLE", None)
    assert len(raw.fetch_calls) == 3


# ---------------------------------------------------------------------------
# transaction()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transaction_yields_raw_asyncpg(toolkit, raw):
    async with toolkit.transaction() as tx:
        assert tx is raw
    assert raw.transaction_enters == 1
    assert raw.transaction_exits == 1


@pytest.mark.asyncio
async def test_transaction_sets_and_clears_in_transaction_flag(toolkit):
    assert toolkit._in_transaction is False
    async with toolkit.transaction():
        assert toolkit._in_transaction is True
    assert toolkit._in_transaction is False


@pytest.mark.asyncio
async def test_transaction_clears_flag_on_exception(toolkit, raw):
    with pytest.raises(ValueError, match="boom"):
        async with toolkit.transaction():
            assert toolkit._in_transaction is True
            raise ValueError("boom")
    assert toolkit._in_transaction is False
    # asyncpg transaction CM should still have exited cleanly.
    assert raw.transaction_exits == 1


@pytest.mark.asyncio
async def test_transaction_rejects_nested_calls(toolkit):
    async with toolkit.transaction():
        with pytest.raises(RuntimeError, match="[Nn]ested transactions"):
            async with toolkit.transaction():
                pytest.fail("inner transaction should not run")


@pytest.mark.asyncio
async def test_transaction_can_be_reentered_sequentially(toolkit, raw):
    """After clean exit, a new transaction() works."""
    async with toolkit.transaction():
        pass
    async with toolkit.transaction():
        pass
    assert raw.transaction_enters == 2
    assert raw.transaction_exits == 2

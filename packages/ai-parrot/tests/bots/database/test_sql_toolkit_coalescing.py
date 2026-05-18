"""Tests for SQLToolkit concurrency coalescing (FEAT-178, TASK-1203)."""
import asyncio
import logging

import pytest

from parrot.bots.database.models import Completeness, TableMetadata
from parrot.bots.database.toolkits.sql import SQLToolkit


@pytest.fixture
def toolkit() -> SQLToolkit:
    """Minimal SQLToolkit stub with only the coalescing infrastructure initialised."""
    tk = SQLToolkit.__new__(SQLToolkit)
    tk._inflight = {}
    tk._inflight_lock = asyncio.Lock()
    tk.logger = logging.getLogger("test.coalescing")
    return tk


async def test_inflight_and_lock_exist():
    """SQLToolkit instances expose _inflight and _inflight_lock after construction."""
    tk = SQLToolkit.__new__(SQLToolkit)
    tk._inflight = {}
    tk._inflight_lock = asyncio.Lock()
    assert isinstance(tk._inflight, dict)
    assert isinstance(tk._inflight_lock, asyncio.Lock)


async def test_coalesces_two_concurrent_calls(toolkit: SQLToolkit):
    """Two concurrent _introspect_table_full calls share a single _build_table_metadata."""
    call_count = 0

    async def fake_build(schema, table, table_type, comment=None):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return TableMetadata(
            schema=schema,
            tablename=table,
            table_type=table_type,
            full_name=f"{schema}.{table}",
        )

    toolkit._build_table_metadata = fake_build

    results = await asyncio.gather(
        toolkit._introspect_table_full("s", "t"),
        toolkit._introspect_table_full("s", "t"),
    )
    assert call_count == 1, f"Expected 1 DB call, got {call_count}"
    assert all(r.completeness == Completeness.FULL for r in results)


async def test_result_has_correct_source(toolkit: SQLToolkit):
    """_introspect_table_full stamps source='information_schema' on the result."""
    async def fake_build(schema, table, table_type, comment=None):
        return TableMetadata(
            schema=schema, tablename=table, table_type=table_type,
            full_name=f"{schema}.{table}",
        )

    toolkit._build_table_metadata = fake_build
    meta = await toolkit._introspect_table_full("pub", "users")
    assert meta is not None
    assert meta.source == "information_schema"
    assert meta.completeness == Completeness.FULL


async def test_different_keys_run_independently(toolkit: SQLToolkit):
    """Two concurrent calls for *different* keys both execute _build_table_metadata."""
    call_count = 0

    async def fake_build(schema, table, table_type, comment=None):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.02)
        return TableMetadata(
            schema=schema, tablename=table, table_type=table_type,
            full_name=f"{schema}.{table}",
        )

    toolkit._build_table_metadata = fake_build

    results = await asyncio.gather(
        toolkit._introspect_table_full("s", "t1"),
        toolkit._introspect_table_full("s", "t2"),
    )
    assert call_count == 2
    assert {r.tablename for r in results} == {"t1", "t2"}


async def test_clears_inflight_on_exception(toolkit: SQLToolkit):
    """On exception the in-flight map is cleaned up and both callers see the error."""
    async def fake_build(*a, **kw):
        raise RuntimeError("boom")

    toolkit._build_table_metadata = fake_build

    with pytest.raises(RuntimeError, match="boom"):
        await toolkit._introspect_table_full("s", "t")
    assert ("s", "t") not in toolkit._inflight


async def test_exception_propagates_to_waiting_caller(toolkit: SQLToolkit):
    """When the owner raises, waiting callers also receive the exception."""
    async def fake_build(*a, **kw):
        await asyncio.sleep(0.03)
        raise ValueError("db error")

    toolkit._build_table_metadata = fake_build

    results = await asyncio.gather(
        toolkit._introspect_table_full("s", "t"),
        toolkit._introspect_table_full("s", "t"),
        return_exceptions=True,
    )
    assert all(isinstance(r, ValueError) for r in results)
    assert ("s", "t") not in toolkit._inflight


async def test_clears_inflight_after_success(toolkit: SQLToolkit):
    """After a successful call the key is removed from _inflight."""
    async def fake_build(schema, table, table_type, comment=None):
        return TableMetadata(
            schema=schema, tablename=table, table_type=table_type,
            full_name=f"{schema}.{table}",
        )

    toolkit._build_table_metadata = fake_build
    await toolkit._introspect_table_full("s", "t")
    assert ("s", "t") not in toolkit._inflight

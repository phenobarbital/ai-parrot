"""FEAT-621 §2.5a — transaction primitives."""
import os
from contextlib import asynccontextmanager

import pytest

from parrot.handlers.studio.storage.models import StudioStorageError
from parrot.handlers.studio.storage.repositories import _exec, _fetch_all, studio_transaction


class _DriverDouble:
    """Stands in for the asyncdb pg driver (a third-party DB we cannot run here), not request/session plumbing."""

    def __init__(self, outcome=None):
        self.calls: list[str] = []
        self.outcome = outcome if outcome is not None else [None, "Postgres Error: check constraint violated"]

    async def transaction(self):
        self.calls.append("transaction")
        return self

    async def commit(self):
        self.calls.append("commit")

    async def rollback(self):
        self.calls.append("rollback")

    async def execute(self, sql, *args):
        return self.outcome

    async def fetch_all(self, sql, *args):
        return None


class _PoolDouble:
    def __init__(self, driver: _DriverDouble):
        self.driver = driver

    @asynccontextmanager
    async def acquire(self):
        yield self.driver


async def test_exec_raises_on_error_tuple() -> None:
    driver = _DriverDouble()
    with pytest.raises(StudioStorageError, match="check constraint"):
        async with studio_transaction(_PoolDouble(driver)) as conn:
            await _exec(conn, "UPDATE x SET y = $1", 1)
    assert driver.calls == ["transaction", "rollback"]


async def test_exec_returns_result_and_commits() -> None:
    driver = _DriverDouble(outcome=["INSERT 0 1", None])
    async with studio_transaction(_PoolDouble(driver)) as conn:
        assert await _exec(conn, "INSERT ...") == "INSERT 0 1"
        assert await _fetch_all(conn, "SELECT 1") == []
    assert driver.calls == ["transaction", "commit"]


async def test_cancellation_rolls_back() -> None:
    import asyncio

    driver = _DriverDouble(outcome=["ok", None])
    with pytest.raises(asyncio.CancelledError):
        async with studio_transaction(_PoolDouble(driver)):
            raise asyncio.CancelledError
    assert driver.calls == ["transaction", "rollback"]


async def test_studio_transaction_real_postgres() -> None:
    dsn = os.environ.get("TEST_STUDIO_PG_DSN")
    if not dsn:
        pytest.skip("TEST_STUDIO_PG_DSN not set; needs a real Postgres")
    from asyncdb import AsyncPool

    pool = AsyncPool("pg", dsn=dsn)
    await pool.connect()
    table = "navigator.studio_tx_probe"
    try:
        async with pool.acquire() as conn:
            await conn.execute("CREATE SCHEMA IF NOT EXISTS navigator")
            await conn.execute(f"DROP TABLE IF EXISTS {table}")
            await conn.execute(f"CREATE TABLE {table} (id integer PRIMARY KEY)")
        with pytest.raises(RuntimeError):
            async with studio_transaction(pool) as conn:
                await _exec(conn, f"INSERT INTO {table} VALUES (1)")
                raise RuntimeError("boom")
        async with studio_transaction(pool) as conn:
            assert await _fetch_all(conn, f"SELECT id FROM {table}") == []
            await _exec(conn, f"INSERT INTO {table} VALUES (2)")
        with pytest.raises(StudioStorageError):
            async with studio_transaction(pool) as conn:
                await _exec(conn, f"INSERT INTO {table} VALUES (3)")
                await _exec(conn, f"INSERT INTO {table} VALUES ('x')")   # error tuple → rollback of id 3
        async with studio_transaction(pool) as conn:
            rows = await _fetch_all(conn, f"SELECT id FROM {table} ORDER BY id")
        assert [r["id"] for r in rows] == [2]
    finally:
        async with pool.acquire() as conn:
            await conn.execute(f"DROP TABLE IF EXISTS {table}")
        await pool.close()

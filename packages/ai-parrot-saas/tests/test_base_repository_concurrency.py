"""The repository has to survive concurrent requests.

This is not a hypothetical. asyncpg guards each operation with ``_Atomic`` and
raises ``InterfaceError: cannot perform operation: another operation is in
progress`` the moment a second coroutine touches the same connection — so a
repository holding one shared connection serves one request and fails the rest.
Four concurrent reads on a shared connection produce one row and three errors.

Nothing else in the suite would notice, because tests are sequential. This
module is the one that would.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

import pytest
from asyncdb import AsyncDB

from parrot_saas.db.repository import BaseRepository
from parrot_saas.db.schema import ensure_schema

pytestmark = pytest.mark.integration

CONCURRENCY = 8


@pytest.fixture
async def repository(
    test_dsn: str, unique_schema: str
) -> AsyncIterator[BaseRepository]:
    """A repository on a throwaway schema holding one tenant."""
    conn = AsyncDB("pg", dsn=test_dsn)
    async with await conn.connection():
        await ensure_schema(conn, schema=unique_schema)
        await conn.execute(
            f"INSERT INTO {unique_schema}.tenants (tenant_id, name) "
            "VALUES ($1, $2)",
            "bar-pepe",
            "Bar Pepe",
        )

    repo = BaseRepository(test_dsn, schema=unique_schema)
    try:
        yield repo
    finally:
        await repo.aclose()
        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            await conn.execute(f"DROP SCHEMA IF EXISTS {unique_schema} CASCADE")


async def test_concurrent_reads_all_succeed(repository) -> None:
    """The failure a shared connection would produce, ruled out."""
    sql = (
        f"SELECT tenant_id, pg_sleep(0.05) FROM {repository.table('tenants')} "
        "WHERE tenant_id = $1"
    )

    results = await asyncio.gather(
        *(repository.fetch_one("bar-pepe", sql) for _ in range(CONCURRENCY)),
        return_exceptions=True,
    )

    errors = [r for r in results if isinstance(r, BaseException)]
    assert not errors, f"concurrent reads failed: {errors[:2]}"
    assert all(r["tenant_id"] == "bar-pepe" for r in results)


async def test_concurrent_writes_all_land(repository) -> None:
    """Writes contend for connections too, and all of them must apply."""
    await repository.execute(
        "bar-pepe",
        f"UPDATE {repository.table('tenants')} SET locale = 'en' "
        "WHERE tenant_id = $1",
    )

    sql = (
        f"UPDATE {repository.table('tenants')} SET locale = $2 "
        "WHERE tenant_id = $1"
    )

    results = await asyncio.gather(
        *(
            repository.execute("bar-pepe", sql, f"e{index}")
            for index in range(CONCURRENCY)
        ),
        return_exceptions=True,
    )

    assert not [r for r in results if isinstance(r, BaseException)]


async def test_the_pool_is_created_once_under_a_burst(repository) -> None:
    """A cold repository hit by many requests must build one pool, not eight."""
    pools = await asyncio.gather(
        *(repository.pool() for _ in range(CONCURRENCY))
    )

    assert len({id(p) for p in pools}) == 1


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


async def test_a_transaction_commits_on_a_clean_exit(repository) -> None:
    """The context manager is the whole point: no forgotten commit."""
    async with repository.transaction() as conn:
        await conn.execute(
            f"UPDATE {repository.table('tenants')} SET locale = 'fr' "
            "WHERE tenant_id = $1",
            "bar-pepe",
        )

    row = await repository.fetch_one(
        "bar-pepe",
        f"SELECT locale FROM {repository.table('tenants')} "
        "WHERE tenant_id = $1",
    )
    assert row["locale"] == "fr"


async def test_a_transaction_rolls_back_on_an_exception(repository) -> None:
    """A half-applied write must not survive, nor leak to the next borrower.

    The driver stores the in-flight transaction on the connection object, so a
    hand-rolled version that forgot to roll back would hand the next caller a
    connection still inside a doomed transaction.
    """
    with pytest.raises(RuntimeError, match="deliberate"):
        async with repository.transaction() as conn:
            await conn.execute(
                f"UPDATE {repository.table('tenants')} SET locale = 'de' "
                "WHERE tenant_id = $1",
                "bar-pepe",
            )
            raise RuntimeError("deliberate")

    row = await repository.fetch_one(
        "bar-pepe",
        f"SELECT locale FROM {repository.table('tenants')} "
        "WHERE tenant_id = $1",
    )
    assert row["locale"] != "de"


async def test_a_connection_is_usable_after_a_rolled_back_transaction(
    repository,
) -> None:
    """Proof the rollback really released the connection cleanly."""
    with pytest.raises(RuntimeError):
        async with repository.transaction() as conn:
            await conn.execute("SELECT 1")
            raise RuntimeError("deliberate")

    async with repository.acquire() as conn:
        assert await conn.fetch_one("SELECT 1 AS ok")


async def test_two_transactions_hold_different_connections(repository) -> None:
    """What makes ``SELECT ... FOR UPDATE`` actually serialise writers.

    On a shared connection the second holder would re-enter the same session
    and take the lock straight through, which is exactly how a budget check
    lets every caller past.
    """
    async with repository.transaction() as first:
        async with repository.transaction() as second:
            assert first is not second


async def test_the_tenant_guard_still_applies(repository) -> None:
    """The pool changed how a statement runs, not what is allowed to run."""
    from parrot_saas.db.repository import TenantScopeError

    with pytest.raises(TenantScopeError):
        await repository.fetch_all(
            "bar-pepe", f"SELECT * FROM {repository.table('tenants')}"
        )

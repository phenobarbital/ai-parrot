"""Focused unit and opt-in integration coverage for the Postgres manual catalog."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

from parrot.knowledge.manuals.catalog import AnswerRecord
from parrot.knowledge.manuals.catalog_postgres import PostgresManualCatalog
from parrot.knowledge.manuals.models import EquipmentRef, ManualCard

PG_DSN = os.environ.get("GRAPHINDEX_PG_DSN")
requires_pg = pytest.mark.skipif(not PG_DSN, reason="live Postgres suites require an explicit GRAPHINDEX_PG_DSN")


class FakeTransaction:
    """No-op transaction context used by the recording fake connection."""

    async def __aenter__(self) -> "FakeTransaction":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


class FakeConnection:
    """Records every SQL call and returns configured fake responses."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[Any, ...]]] = []

    async def execute(self, sql: str, *args: Any) -> str:
        self.calls.append(("execute", sql, args))
        return "OK"

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        self.calls.append(("fetch", sql, args))
        return []

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        self.calls.append(("fetchrow", sql, args))
        return None

    def transaction(self) -> FakeTransaction:
        return FakeTransaction()


class FakeAcquire:
    """Async connection context returned by ``FakePool.acquire``."""

    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> FakeConnection:
        return self.connection

    async def __aexit__(self, *args: Any) -> None:
        return None


class FakePool:
    """Minimal asyncpg-pool double that exposes a recording connection."""

    def __init__(self) -> None:
        self.connection = FakeConnection()

    def acquire(self) -> FakeAcquire:
        return FakeAcquire(self.connection)


def test_requires_dsn_or_pool() -> None:
    """A catalog never silently falls back to an ambient DSN."""
    with pytest.raises(ValueError):
        PostgresManualCatalog(tenant_id="t1")


def test_postgres_catalog_regconfig() -> None:
    """The validated regconfig is the only FTS configuration interpolation."""
    catalog = PostgresManualCatalog(pool=FakePool(), tenant_id="t1", search_regconfig="spanish")
    assert any("to_tsvector('spanish'" in statement for statement in catalog.ddl())
    with pytest.raises(ValueError):
        PostgresManualCatalog(pool=FakePool(), tenant_id="t1", search_regconfig="spanish'); drop")


@pytest.mark.asyncio
async def test_search_binds_query_parameter() -> None:
    """Search text is passed as an asyncpg parameter rather than interpolated SQL."""
    pool = FakePool()
    catalog = PostgresManualCatalog(pool=pool, tenant_id="t1", search_regconfig="spanish")
    query = "motor'); DROP TABLE manuals; --"
    assert await catalog.search(query) == []
    fetches = [call for call in pool.connection.calls if call[0] == "fetch"]
    assert fetches[-1][2] == (query, 8)
    assert query not in fetches[-1][1]
    assert "plainto_tsquery('spanish', $1)" in fetches[-1][1]


@pytest.mark.asyncio
async def test_record_answer_failure_raises() -> None:
    """Audit-write failures propagate and therefore block answer release."""
    pool = FakePool()
    catalog = PostgresManualCatalog(pool=pool, tenant_id="t1")

    async def fail_execute(sql: str, *args: Any) -> str:
        raise RuntimeError("audit unavailable")

    pool.connection.execute = fail_execute  # type: ignore[method-assign]
    record = AnswerRecord(
        answer_id="answer-1",
        asked_at=datetime(2026, 9, 25, tzinfo=timezone.utc),
        user="tech@example.test",
        question="How do I install it?",
        answer_kind="procedure",
    )
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await catalog.record_answer(record)


@requires_pg
@pytest.mark.asyncio
async def test_live_upsert_search_queue() -> None:
    """An explicitly configured Postgres accepts the primary catalog round-trip."""
    import asyncpg

    pool = await asyncpg.create_pool(dsn=PG_DSN, min_size=1, max_size=2)
    schema = f"manuals_it_{uuid.uuid4().hex[:8]}"
    catalog = PostgresManualCatalog(pool=pool, tenant_id="t1", schema=schema)
    card = ManualCard(
        manual_id="live-manual",
        revision="A",
        equipment=[EquipmentRef(equipment_id="live-equipment", model="Live Motor")],
    )
    try:
        await catalog.upsert(card)
        assert [hit.card.manual_id for hit in await catalog.search("motor")] == [card.manual_id]
        assert await catalog.verification_queue() == []
    finally:
        async with pool.acquire() as connection:
            await connection.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        await pool.close()

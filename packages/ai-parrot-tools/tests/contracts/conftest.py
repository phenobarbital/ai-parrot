"""Shared fixtures for the contracts answering-layer suites (TASK-3054).

The end-to-end slice runs on a **real Postgres catalog** when
``GRAPHINDEX_PG_DSN`` is set, and otherwise skips only the live tests.
Everything else in this package runs on the in-memory doubles defined in
``test_retrieval.py``.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from typing import Any, AsyncIterator, Optional

import pytest

FROZEN_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 9)

PG_DSN: Optional[str] = os.environ.get("GRAPHINDEX_PG_DSN")

requires_pg = pytest.mark.skipif(
    not PG_DSN, reason="live end-to-end tests require an explicit GRAPHINDEX_PG_DSN"
)


@pytest.fixture()
async def pg_pool() -> AsyncIterator[Any]:
    """A pool against the explicitly configured Postgres."""
    if not PG_DSN:  # pragma: no cover - skipped by the marker
        pytest.skip("no GRAPHINDEX_PG_DSN")
    import asyncpg

    pool = await asyncpg.create_pool(dsn=PG_DSN, min_size=1, max_size=6)
    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture()
async def live_catalog(pg_pool) -> AsyncIterator[Any]:
    """A real Postgres catalog on a temporary schema."""
    from parrot.knowledge.contracts.catalog_postgres import PostgresContractCatalog

    schema = f"contracts_e2e_{uuid.uuid4().hex[:8]}"
    catalog = PostgresContractCatalog(
        pool=pg_pool, tenant_id="troc", schema=schema, now=lambda: FROZEN_NOW
    )
    await catalog.setup()
    try:
        yield catalog
    finally:
        async with pg_pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")

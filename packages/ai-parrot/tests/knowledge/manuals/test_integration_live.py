"""Live FEAT-601 suites; explicit credentials only, otherwise skipped."""
from __future__ import annotations

import os
import uuid
from typing import Any, AsyncIterator

import pytest

from parrot.knowledge.manuals.catalog_postgres import PostgresManualCatalog

from parrot.knowledge.common.provenance import Evidence, Extracted
from parrot.knowledge.manuals.models import EquipmentRef, ManualCard, ManualVersion, Procedure

PG_DSN = os.environ.get("GRAPHINDEX_PG_DSN")
ARANGO_URL = os.environ.get("CONTRACTS_ARANGO_URL")
ARANGO_USER = os.environ.get("CONTRACTS_ARANGO_USER", "root")
ARANGO_PASSWORD = os.environ.get("CONTRACTS_ARANGO_PASSWORD", "")
requires_pg = pytest.mark.skipif(not PG_DSN, reason="live Postgres suites require an explicit GRAPHINDEX_PG_DSN")
requires_arango = pytest.mark.skipif(
    not ARANGO_URL, reason="live ArangoDB suites require an explicit CONTRACTS_ARANGO_URL"
)


@pytest.fixture()
async def pg_pool() -> AsyncIterator[Any]:
    """Create a short-lived pool only when the live DSN is configured."""
    if not PG_DSN:
        pytest.skip("no GRAPHINDEX_PG_DSN")
    import asyncpg

    pool = await asyncpg.create_pool(dsn=PG_DSN, min_size=1, max_size=4)
    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture()
async def temp_schema(pg_pool: Any) -> AsyncIterator[str]:
    """Return an isolated schema and remove it after the test."""
    schema = f"manuals_it_{uuid.uuid4().hex[:8]}"
    try:
        yield schema
    finally:
        async with pg_pool.acquire() as connection:
            await connection.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


def _card() -> ManualCard:
    """Build a minimal evidenced manual for live catalog persistence."""
    evidence = Evidence(node_id="title", quote="Assemble Model X", page=1)
    return ManualCard(
        manual_id="model-x-a",
        revision="A",
        equipment=[EquipmentRef(equipment_id="model-x", model="Model X")],
        procedures=[
            Procedure(
                procedure_id="assemble-x",
                slug="assemble-x",
                kind="assembly",
                title=Extracted(value="Assemble Model X", evidence=evidence),
                steps=[],
            )
        ],
        source_sha256="live-test-source",
    )


@requires_arango
@pytest.mark.asyncio
async def test_live_arango_publish() -> None:
    """The configured service is deliberately required for Arango acceptance."""
    pytest.skip("live Arango wiring is covered by the configured deployment suite")


@requires_pg
@pytest.mark.asyncio
async def test_live_postgres_catalog(pg_pool: Any, temp_schema: str) -> None:
    """Store a manual and recover it through full-text search and queue APIs."""
    catalog = PostgresManualCatalog(pool=pg_pool, tenant_id=f"t-{uuid.uuid4().hex[:6]}", schema=temp_schema)
    await catalog.setup()
    card = _card()
    await catalog.upsert(card, version=ManualVersion(n=1, revision="A", source_sha256=card.source_sha256))
    hits = await catalog.search("assembly")
    assert [hit.card.manual_id for hit in hits] == [card.manual_id]
    assert await catalog.verification_queue() == []

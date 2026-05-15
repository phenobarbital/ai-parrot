"""Fixtures for DatabaseAgent tests."""
from __future__ import annotations

import os
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.bots.database.cache import CachePartition
from parrot.bots.database.models import (
    Completeness,
    QueryExecutionResponse,
    QueryResponse,
    TableMetadata,
)
from parrot.bots.database.toolkits.base import DatabaseToolkit
from parrot.models import AIMessage


# ---------------------------------------------------------------------------
# Fake DatabaseToolkit (in-memory, no real DB connection)
# ---------------------------------------------------------------------------

class _FakePostgresToolkit(DatabaseToolkit):
    """Minimal concrete DatabaseToolkit for unit tests."""

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def search_schema(
        self,
        search_term: str,
        schema_name: Optional[str] = None,
        limit: int = 10,
    ) -> List[TableMetadata]:
        return []

    async def execute_query(
        self,
        query: str,
        limit: int = 1000,
        timeout: int = 30,
    ) -> QueryExecutionResponse:
        return QueryExecutionResponse(
            success=True,
            data=[],
            row_count=0,
            execution_time_ms=0.0,
            schema_used="public",
        )


@pytest.fixture
def fake_postgres_toolkit() -> _FakePostgresToolkit:
    """In-memory PostgresToolkit with no real DB connection."""
    return _FakePostgresToolkit(
        dsn="postgresql://test:test@localhost:5432/testdb",
        allowed_schemas=["public"],
        primary_schema="public",
        database_type="postgresql",
    )


# ---------------------------------------------------------------------------
# Mock LLM client
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Completeness / cache fixtures (FEAT-178 — TASK-1207)
# ---------------------------------------------------------------------------

@pytest.fixture
def stub_metadata() -> TableMetadata:
    """NAME_ONLY stub for pokemon.stores (no columns loaded)."""
    return TableMetadata(
        schema="pokemon",
        tablename="stores",
        table_type="BASE TABLE",
        full_name='"pokemon"."stores"',
        completeness=Completeness.NAME_ONLY,
        source="frontend",
    )


@pytest.fixture
def full_metadata() -> TableMetadata:
    """FULL metadata for pokemon.stores (columns + PK loaded)."""
    return TableMetadata(
        schema="pokemon",
        tablename="stores",
        table_type="BASE TABLE",
        full_name='"pokemon"."stores"',
        completeness=Completeness.FULL,
        source="pg_catalog",
        columns=[
            {"name": "store_id", "type": "integer", "nullable": False},
            {"name": "store_name", "type": "varchar", "nullable": True},
            {"name": "state_code", "type": "char(2)", "nullable": True},
        ],
        primary_keys=["store_id"],
    )


@pytest.fixture
def test_cache_partition() -> CachePartition:
    """In-memory CachePartition with no Redis or vector store."""
    return CachePartition(namespace="test_regression", redis_pool=None)


# ---------------------------------------------------------------------------
# Integration fixtures (require PARROT_TEST_PG_DSN env var — skip otherwise)
# ---------------------------------------------------------------------------

@pytest.fixture
async def pg_pool():
    """Live asyncpg connection pool. Skipped when PARROT_TEST_PG_DSN is unset."""
    dsn = os.environ.get("PARROT_TEST_PG_DSN")
    if not dsn:
        pytest.skip("Set PARROT_TEST_PG_DSN to run PG integration tests")
    try:
        import asyncpg  # type: ignore
    except ImportError:
        pytest.skip("asyncpg not installed — PG integration tests skipped")
    pool = await asyncpg.create_pool(dsn)
    yield pool
    await pool.close()


@pytest.fixture
async def pg_toolkit(pg_pool):
    """PostgresToolkit wired to the live pg_pool fixture (integration only)."""
    import asyncio
    import logging
    from parrot.bots.database.toolkits.postgres import PostgresToolkit

    tk = PostgresToolkit.__new__(PostgresToolkit)
    tk._inflight = {}
    tk._inflight_lock = asyncio.Lock()
    tk.logger = logging.getLogger("test.pg_toolkit")
    tk.cache_partition = None
    tk.allowed_schemas = ["pokemon", "networkninja"]
    tk._pool = pg_pool
    return tk


@pytest.fixture
async def seeded_pg(pg_pool):
    """Create pokemon + networkninja schemas with test tables; drop on teardown."""
    async with pg_pool.acquire() as conn:
        await conn.execute("CREATE SCHEMA IF NOT EXISTS pokemon")
        await conn.execute("CREATE SCHEMA IF NOT EXISTS networkninja")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pokemon.stores (
                store_id   SERIAL PRIMARY KEY,
                store_name VARCHAR(255),
                state_code CHAR(2)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS networkninja.organizations (
                org_id       SERIAL PRIMARY KEY,
                organization VARCHAR(255)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS networkninja.forms (
                form_id   SERIAL PRIMARY KEY,
                form_name VARCHAR(255),
                org_id    INT REFERENCES networkninja.organizations(org_id)
            )
            """
        )
    yield
    async with pg_pool.acquire() as conn:
        await conn.execute("DROP SCHEMA IF EXISTS pokemon CASCADE")
        await conn.execute("DROP SCHEMA IF EXISTS networkninja CASCADE")


@pytest.fixture
async def seeded_pg_with_fks(seeded_pg):
    """Alias for seeded_pg — FK relationships are set up in seeded_pg itself."""
    yield


# ---------------------------------------------------------------------------
# Mock LLM client
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm_client() -> MagicMock:
    """AbstractClient stub recording ask() payloads, returning a canned AIMessage."""
    client = MagicMock()
    default_qr = QueryResponse(explanation="ok", query=None, data=None)
    default_response = MagicMock(
        spec=AIMessage,
        is_structured=True,
        output=default_qr,
        response="ok",
        data=None,
        session_id=None,
    )
    client.ask = AsyncMock(return_value=default_response)
    return client

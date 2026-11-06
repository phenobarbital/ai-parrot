"""Shared fixtures for the vocabulary-store tests (FEAT-824)."""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio

from parrot.conf import default_dsn

FIXTURES = Path(__file__).parent / "fixtures"
PG_DSN = os.environ.get("ONTOLOGY_PG_DSN") or default_dsn


@pytest.fixture
def golden_v1() -> bytes:
    """legal_es v1: classes, SKOS concepts, a DAG with multiple inheritance."""
    return (FIXTURES / "legal_es.v1.ttl").read_bytes()


@pytest.fixture
def golden_v2() -> bytes:
    """Labels, attributes and relations changed; one deprecation with replacement."""
    return (FIXTURES / "legal_es.v2.ttl").read_bytes()


@pytest.fixture
def golden_v3() -> bytes:
    """A relation removed in v2 comes back."""
    return (FIXTURES / "legal_es.v3.ttl").read_bytes()


@pytest.fixture
def golden_base_iri() -> str:
    """Base IRI shared by the golden files."""
    return "https://ontology.parrot.dev/legal_es/"


@pytest_asyncio.fixture
async def pg_pool() -> AsyncIterator[asyncpg.Pool]:
    """asyncpg pool to the live test server; skips when no DSN is configured."""
    if not PG_DSN:
        pytest.skip("needs live Postgres (ONTOLOGY_PG_DSN or parrot.conf.default_dsn)")

    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=4)
    try:
        yield pool
    finally:
        await pool.close()


@pytest_asyncio.fixture
async def pg_schema_name(pg_pool: asyncpg.Pool) -> AsyncIterator[str]:
    """A unique schema name, dropped with CASCADE at teardown."""
    name = f"ontology_store_t_{uuid.uuid4().hex[:8]}"
    try:
        yield name
    finally:
        async with pg_pool.acquire() as conn:
            await conn.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')

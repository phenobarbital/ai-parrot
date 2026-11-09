"""Embedding binding works with and without the pgvector codec; ensure_schema is race-safe (FEAT-863)."""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import AsyncIterator, Sequence

import asyncpg
import pytest
import pytest_asyncio

from parrot.knowledge.ontology.vocabulary.pg_schema import ensure_schema, vector_literal
from parrot.knowledge.ontology.vocabulary.postgres_store import PostgresOntologyStore
from parrot.knowledge.ontology.vocabulary.publisher import PostgresOntologyPublisher

DIM = 3


async def _embed(texts: Sequence[str]) -> list[list[float]]:
    """Deterministic non-zero 3-d embeddings."""
    return [[1.0, float(len(text) % 7) + 1.0, 0.5] for text in texts]


@pytest_asyncio.fixture(params=["plain", "codec"])
async def any_pool(request: pytest.FixtureRequest, pg_pool: asyncpg.Pool) -> AsyncIterator[asyncpg.Pool]:
    """The codec-less fixture pool, or a sibling pool with the pgvector codec registered."""
    if request.param == "plain":
        yield pg_pool
        return
    from pgvector.asyncpg import register_vector

    async with pg_pool.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        params = conn._params  # noqa: SLF001 - reuse the fixture's connection target
        addr = conn._addr  # noqa: SLF001
    host, port = addr if isinstance(addr, tuple) else (addr, None)
    pool = await asyncpg.create_pool(
        host=host,
        port=port,
        user=params.user,
        password=params.password,
        database=params.database,
        min_size=1,
        max_size=2,
        init=register_vector,
    )
    try:
        yield pool
    finally:
        await pool.close()


def test_vector_literal() -> None:
    """The text form round-trips floats in pgvector syntax."""
    assert vector_literal([1, 2.5]) == "[1.0,2.5]"


@pytest.mark.asyncio
async def test_publish_and_search_with_embeddings(
    any_pool: asyncpg.Pool, pg_schema_name: str, golden_v1: bytes, golden_base_iri: str
) -> None:
    """Embeddings are written and searched on pools with and without the codec."""
    await ensure_schema(any_pool, schema=pg_schema_name, embedding_dim=DIM)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    publisher = PostgresOntologyPublisher(any_pool, schema=pg_schema_name, embed=_embed, executor=executor)
    try:
        await publisher.ensure_ontology("emb", base_iri=golden_base_iri)
        result = await publisher.publish("emb", golden_v1)
        assert result.version == 1
    finally:
        await publisher.close()
        executor.shutdown(wait=True)
    async with any_pool.acquire() as conn:
        count = await conn.fetchval(f"SELECT count(*) FROM {pg_schema_name}.concept WHERE embedding IS NOT NULL")
    assert count > 0
    store = PostgresOntologyStore(any_pool, schema=pg_schema_name)
    hits = await store.resolve("emb", "zzzz-no-lexical-match", embedding=[1.0, 2.0, 0.5])
    assert hits and any(hit.matched_by == "vector" for hit in hits)


@pytest.mark.asyncio
async def test_concurrent_ensure_schema(pg_pool: asyncpg.Pool, pg_schema_name: str) -> None:
    """Concurrent first-time ensure_schema calls on a fresh schema all succeed."""
    await asyncio.gather(*(ensure_schema(pg_pool, schema=pg_schema_name, embedding_dim=DIM) for _ in range(4)))

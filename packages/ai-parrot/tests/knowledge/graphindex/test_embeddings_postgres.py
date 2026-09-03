"""Live-DB-gated tests for in-schema embeddings + KNN (FEAT-520 TASK-2769)."""

from __future__ import annotations

import os
import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from parrot.conf import default_dsn
from parrot.knowledge.graphindex import pg_schema
from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence
from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode
from parrot.knowledge.wiki.postgres_store import PostgresWikiStore
from parrot.knowledge.wiki.store import WikiPageRecord

PG_DSN = os.environ.get("GRAPHINDEX_PG_DSN") or default_dsn
pytestmark = pytest.mark.skipif(not PG_DSN, reason="needs live Postgres")

DIM = pg_schema.GRAPHINDEX_EMBEDDING_DIM


def _make_ctx(tenant_id: str = "test_tenant") -> Any:
    ctx = MagicMock()
    ctx.tenant_id = tenant_id
    return ctx


def make_node(node_id: str, **kwargs: Any) -> UniversalNode:
    kwargs.setdefault("kind", NodeKind.DOCUMENT)
    kwargs.setdefault("source_uri", "test.txt")
    kwargs.setdefault("title", f"Node {node_id}")
    return UniversalNode(node_id=node_id, **kwargs)


def _vec(seed: float, dim: int = DIM) -> list[float]:
    """A deterministic, distinguishable unit-ish vector for KNN tests."""
    v = [seed] * dim
    v[0] += 1.0  # break perfect collinearity between different seeds
    return v


@pytest.fixture
def ctx():
    return _make_ctx()


@pytest.fixture
def tmp_schema() -> str:
    return f"graphindex_test_{uuid.uuid4().hex[:12]}"


@pytest.fixture
async def pg_persistence(tmp_schema):
    p = PostgresPersistence(PG_DSN, schema=tmp_schema)
    try:
        yield p
    finally:
        pool = await p._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {tmp_schema} CASCADE")
        await p.close()


@pytest.fixture
async def pg_wiki_store(pg_persistence, tmp_schema):
    store = PostgresWikiStore(PG_DSN, wiki_name="test-wiki", schema=tmp_schema)
    try:
        yield store
    finally:
        await store.close()


async def test_upsert_and_knn_roundtrip(pg_persistence, ctx):
    await pg_persistence.persist_graph(ctx, [make_node("a"), make_node("b"), make_node("c")], [])
    written = await pg_persistence.upsert_embeddings(
        ctx,
        [("a", _vec(0.1)), ("b", _vec(0.5)), ("c", _vec(0.9))],
    )
    assert written == 3

    pool = await pg_persistence._ensure_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT concept_id FROM {pg_persistence._schema}.embeddings
            ORDER BY embedding <=> $1 LIMIT 3
            """,
            _vec(0.1),
        )
    assert [r["concept_id"] for r in rows][0] == "a"  # nearest-first


async def test_knn_excludes_closed_versions(pg_persistence, ctx):
    await pg_persistence.persist_graph(ctx, [make_node("a", title="Node a", summary="v1")], [])
    await pg_persistence.upsert_embeddings(ctx, [("a", _vec(0.1))])

    # Close the current version and open a new one — the embedding row for
    # the OLD version_id must be excluded from a current-path KNN query.
    await pg_persistence.persist_graph(ctx, [make_node("a", title="Node a", summary="v2")], [])

    pool = await pg_persistence._ensure_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT emb.concept_id FROM {pg_persistence._schema}.embeddings emb
            JOIN {pg_persistence._schema}.node_versions nv ON nv.version_id = emb.version_id
            WHERE upper_inf(nv.validity)
            ORDER BY emb.embedding <=> $1
            """,
            _vec(0.1),
        )
    assert rows == []  # the embedded (closed) version is not the current one


async def test_wiki_search_vector_shape(pg_wiki_store):
    await pg_wiki_store.upsert_pages([WikiPageRecord(concept_id="p1", title="Page p1")])
    vec = _vec(0.3)
    await pg_wiki_store.upsert_embedding("p1", vec, model="test-model")

    results = await pg_wiki_store.search_vector(vec, limit=5)
    assert len(results) == 1
    stub = results[0]
    assert stub["concept_id"] == "p1"
    assert "score" in stub
    assert -1.0 <= stub["score"] <= 1.0 + 1e-6
    assert set(stub) >= {"concept_id", "node_id", "title", "category", "summary", "source_id", "token_count", "score"}


async def test_dimension_guard_persistence(pg_persistence, ctx):
    await pg_persistence.persist_graph(ctx, [make_node("a")], [])
    with pytest.raises(ValueError):
        await pg_persistence.upsert_embeddings(ctx, [("a", [0.1, 0.2, 0.3])])


async def test_dimension_guard_wiki(pg_wiki_store):
    await pg_wiki_store.upsert_pages([WikiPageRecord(concept_id="p1", title="P1")])
    with pytest.raises(ValueError):
        await pg_wiki_store.upsert_embedding("p1", [0.1, 0.2, 0.3])
    with pytest.raises(ValueError):
        await pg_wiki_store.search_vector([0.1, 0.2, 0.3])


async def test_ensure_ann_index_idempotent(pg_persistence):
    pool = await pg_persistence._ensure_pool()
    await pg_schema.ensure_ann_index(pool, schema=pg_persistence._schema, kind="hnsw")
    await pg_schema.ensure_ann_index(pool, schema=pg_persistence._schema, kind="hnsw")  # no-op second call

    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT to_regclass($1) IS NOT NULL",
            f"{pg_persistence._schema}.embeddings_hnsw_idx",
        )
    assert exists is True


async def test_ensure_ann_index_unknown_kind_raises(pg_persistence):
    pool = await pg_persistence._ensure_pool()
    with pytest.raises(ValueError):
        await pg_schema.ensure_ann_index(pool, schema=pg_persistence._schema, kind="bogus")


def test_no_sqlalchemy_imports():
    import parrot.knowledge.graphindex.persist_postgres as pmod
    import parrot.knowledge.graphindex.pg_schema as smod
    import parrot.knowledge.wiki.postgres_store as wmod

    for module in (pmod, smod, wmod):
        with open(module.__file__, "r", encoding="utf-8") as fh:
            assert "sqlalchemy" not in fh.read().lower()

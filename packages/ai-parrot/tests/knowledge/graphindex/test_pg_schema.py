"""Live-DB-gated tests for the GraphIndex Postgres schema/pool base (FEAT-520 TASK-2764)."""

from __future__ import annotations

import os
import uuid

import asyncpg
import pytest

from parrot.conf import default_dsn
from parrot.knowledge.graphindex import pg_schema

PG_DSN = os.environ.get("GRAPHINDEX_PG_DSN") or default_dsn
pytestmark = pytest.mark.skipif(not PG_DSN, reason="needs live Postgres")


@pytest.fixture
def tmp_schema() -> str:
    """A throwaway schema name, unique per test."""
    return f"graphindex_test_{uuid.uuid4().hex[:12]}"


@pytest.fixture
async def pg_pool(tmp_schema):
    """A pool pointed at a throwaway schema, dropped on teardown."""
    pool = await pg_schema.create_pg_pool(PG_DSN, schema=tmp_schema)
    try:
        yield pool
    finally:
        async with pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {tmp_schema} CASCADE")
        await pool.close()


async def test_migration_idempotent(pg_pool, tmp_schema):
    await pg_schema.ensure_schema(pg_pool, schema=tmp_schema)
    await pg_schema.ensure_schema(pg_pool, schema=tmp_schema)

    async with pg_pool.acquire() as conn:
        value = await conn.fetchval(
            f"SELECT value FROM {tmp_schema}.meta WHERE key = 'schema_version'"
        )
        tables = {
            row["table_name"]
            for row in await conn.fetch(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = $1",
                tmp_schema,
            )
        }

    assert value == pg_schema.PG_SCHEMA_VERSION
    assert {
        "nodes",
        "node_versions",
        "edges",
        "embeddings",
        "symbols",
        "files",
        "commits",
        "commit_items",
        "meta",
    } <= tables


async def test_exclusion_constraint_rejects_overlap(pg_pool, tmp_schema):
    await pg_schema.ensure_schema(pg_pool, schema=tmp_schema)

    async with pg_pool.acquire() as conn:
        await conn.execute(
            f"INSERT INTO {tmp_schema}.nodes (concept_id, category) VALUES ($1, $2)",
            "concept-1",
            "document",
        )
        await conn.execute(
            f"INSERT INTO {tmp_schema}.node_versions (concept_id, title) VALUES ($1, $2)",
            "concept-1",
            "v1",
        )
        with pytest.raises(asyncpg.exceptions.ExclusionViolationError):
            await conn.execute(
                f"INSERT INTO {tmp_schema}.node_versions (concept_id, title) VALUES ($1, $2)",
                "concept-1",
                "v2 overlapping",
            )


async def test_edge_confidence_check(pg_pool, tmp_schema):
    await pg_schema.ensure_schema(pg_pool, schema=tmp_schema)

    async with pg_pool.acquire() as conn:
        # provenance=inferred WITHOUT confidence -> CHECK violation.
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await conn.execute(
                f"""INSERT INTO {tmp_schema}.edges (src, dst, rel, provenance)
                    VALUES ($1, $2, $3, 'inferred')""",
                "a",
                "b",
                "relates_to",
            )
        # provenance=extracted WITH confidence -> CHECK violation.
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await conn.execute(
                f"""INSERT INTO {tmp_schema}.edges (src, dst, rel, provenance, confidence)
                    VALUES ($1, $2, $3, 'extracted', 0.9)""",
                "a",
                "b",
                "relates_to",
            )
        # Valid combination succeeds.
        await conn.execute(
            f"""INSERT INTO {tmp_schema}.edges (src, dst, rel, provenance, confidence)
                VALUES ($1, $2, $3, 'inferred', 0.9)""",
            "a",
            "b",
            "relates_to",
        )


async def test_vector_codec_roundtrip(pg_pool, tmp_schema):
    await pg_schema.ensure_schema(pg_pool, schema=tmp_schema)

    async with pg_pool.acquire() as conn:
        await conn.execute(
            f"INSERT INTO {tmp_schema}.nodes (concept_id, category) VALUES ($1, $2)",
            "concept-1",
            "document",
        )
        version_id = await conn.fetchval(
            f"""INSERT INTO {tmp_schema}.node_versions (concept_id, title)
                VALUES ($1, $2) RETURNING version_id""",
            "concept-1",
            "v1",
        )
        vec = [0.1] * pg_schema.GRAPHINDEX_EMBEDDING_DIM
        await conn.execute(
            f"""INSERT INTO {tmp_schema}.embeddings (concept_id, version_id, embedding)
                VALUES ($1, $2, $3)""",
            "concept-1",
            version_id,
            vec,
        )
        roundtripped = await conn.fetchval(
            f"SELECT embedding FROM {tmp_schema}.embeddings WHERE version_id = $1",
            version_id,
        )
    assert list(roundtripped) == pytest.approx(vec)


def test_resolve_regconfig_mapping():
    assert pg_schema.resolve_regconfig("legal:core") == "spanish"
    assert pg_schema.resolve_regconfig("sym:python") == "simple"
    assert pg_schema.resolve_regconfig("unmapped:namespace") == "simple"


def test_no_sqlalchemy_imports():
    module_path = pg_schema.__file__
    with open(module_path, "r", encoding="utf-8") as fh:
        content = fh.read()
    assert "sqlalchemy" not in content.lower()


def test_default_dsn_fallback(monkeypatch):
    """Unset GRAPHINDEX_PG_DSN resolves to parrot.conf.default_dsn."""
    import importlib

    from navconfig import config as navconfig_config

    monkeypatch.delenv("GRAPHINDEX_PG_DSN", raising=False)
    monkeypatch.setattr(navconfig_config, "get", lambda key, fallback=None: fallback)

    reloaded = importlib.reload(pg_schema)
    try:
        assert reloaded.GRAPHINDEX_PG_DSN == default_dsn
    finally:
        importlib.reload(pg_schema)

"""Live-DB-gated tests for PostgresPersistence parity surface (FEAT-520 TASK-2765)."""

from __future__ import annotations

import os
import uuid
from typing import Any
from unittest.mock import MagicMock

import asyncpg
import pytest

from parrot.conf import default_dsn
from parrot.knowledge.graphindex import pg_schema
from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence
from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    Provenance,
    UniversalEdge,
    UniversalNode,
)

PG_DSN = os.environ.get("GRAPHINDEX_PG_DSN") or default_dsn
pytestmark = pytest.mark.skipif(not PG_DSN, reason="needs live Postgres")


def _make_ctx(tenant_id: str = "test_tenant") -> Any:
    """Minimal TenantContext-like object (parity with test_persist_sqlite.py)."""
    ctx = MagicMock()
    ctx.tenant_id = tenant_id
    return ctx


def make_node(
    node_id: str,
    kind: NodeKind = NodeKind.DOCUMENT,
    source_uri: str = "test.txt",
    **kwargs: Any,
) -> UniversalNode:
    return UniversalNode(node_id=node_id, kind=kind, title=f"Node {node_id}", source_uri=source_uri, **kwargs)


def make_edge(
    source_id: str,
    target_id: str,
    kind: EdgeKind = EdgeKind.CONTAINS,
    **kwargs: Any,
) -> UniversalEdge:
    return UniversalEdge(source_id=source_id, target_id=target_id, kind=kind, **kwargs)


@pytest.fixture
def ctx():
    return _make_ctx()


@pytest.fixture
def tmp_schema() -> str:
    return f"graphindex_test_{uuid.uuid4().hex[:12]}"


@pytest.fixture
async def pg_persistence(tmp_schema):
    persistence = PostgresPersistence(PG_DSN, schema=tmp_schema)
    try:
        yield persistence
    finally:
        pool = await persistence._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {tmp_schema} CASCADE")
        await persistence.close()


# ---------------------------------------------------------------------------
# Roundtrip / parity
# ---------------------------------------------------------------------------


async def test_persist_load_roundtrip(pg_persistence, ctx):
    node = make_node("n1", NodeKind.DOCUMENT)
    edge_node = make_node("n2", NodeKind.SECTION)
    edge = make_edge("n1", "n2", EdgeKind.CONTAINS)

    result = await pg_persistence.persist_graph(ctx, [node, edge_node], [edge])
    assert result == {"nodes_persisted": 2, "edges_persisted": 1}

    nodes, edges = await pg_persistence.load_graph(ctx)
    assert {n.node_id for n in nodes} == {"n1", "n2"}
    assert len(edges) == 1
    assert edges[0].source_id == "n1"
    assert edges[0].target_id == "n2"
    assert edges[0].kind == EdgeKind.CONTAINS


async def test_append_only_correction(pg_persistence, ctx):
    node = make_node("n1")
    await pg_persistence.persist_graph(ctx, [node], [])

    changed = UniversalNode(node_id="n1", kind=NodeKind.DOCUMENT, title="Node n1", source_uri="test.txt", summary="changed")
    await pg_persistence.persist_graph(ctx, [changed], [])

    pool = await pg_persistence._ensure_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            f"SELECT COUNT(*) FROM {pg_persistence._schema}.node_versions WHERE concept_id = 'n1'"
        )
        open_count = await conn.fetchval(
            f"""SELECT COUNT(*) FROM {pg_persistence._schema}.node_versions
                WHERE concept_id = 'n1' AND upper_inf(validity)"""
        )
    assert count == 2
    assert open_count == 1


async def test_no_op_on_identical_content(pg_persistence, ctx):
    node = make_node("n1")
    await pg_persistence.persist_graph(ctx, [node], [])
    await pg_persistence.persist_graph(ctx, [node], [])

    pool = await pg_persistence._ensure_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            f"SELECT COUNT(*) FROM {pg_persistence._schema}.node_versions WHERE concept_id = 'n1'"
        )
    assert count == 1


async def test_replace_document_slice_atomic(pg_persistence, ctx):
    n1 = make_node("n1", source_uri="doc://a")
    n2 = make_node("n2", source_uri="doc://a")
    await pg_persistence.persist_graph(ctx, [n1, n2], [])

    n3 = make_node("n3", source_uri="doc://a")
    result = await pg_persistence.replace_document_slice(ctx, "doc://a", [n3], [])
    assert result["nodes_replaced"] == 2

    nodes, _ = await pg_persistence.load_graph(ctx)
    assert {n.node_id for n in nodes} == {"n3"}


async def test_is_stale(pg_persistence, ctx):
    assert await pg_persistence.is_stale(ctx, "file.py", 100.0, "sha1val") is True

    node = make_node("n1", source_uri="file.py", domain_tags={"mtime": 100.0, "sha1": "sha1val"})
    await pg_persistence.persist_graph(ctx, [node], [])

    assert await pg_persistence.is_stale(ctx, "file.py", 100.0, "sha1val") is False
    assert await pg_persistence.is_stale(ctx, "file.py", 200.0, "sha1val") is True
    assert await pg_persistence.is_stale(ctx, "file.py", 100.0, "other") is True


async def test_exclusion_violation_is_explicit(pg_persistence, ctx):
    pool = await pg_persistence._ensure_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            f"INSERT INTO {pg_persistence._schema}.nodes (concept_id, category) VALUES ($1, $2)",
            "n1",
            "document",
        )
        await conn.execute(
            f"INSERT INTO {pg_persistence._schema}.node_versions (concept_id, title) VALUES ($1, $2)",
            "n1",
            "v1",
        )
        with pytest.raises(asyncpg.exceptions.ExclusionViolationError):
            await conn.execute(
                f"INSERT INTO {pg_persistence._schema}.node_versions (concept_id, title) VALUES ($1, $2)",
                "n1",
                "v2 overlapping",
            )


async def test_evidence_ref_roundtrip(pg_persistence, ctx):
    n1 = make_node("n1")
    n2 = make_node("n2")
    edge = make_edge(
        "n1",
        "n2",
        EdgeKind.CONTAINS,
        domain_tags={"evidence_ref": {"body_ref": "doc.md", "byte_offset": 42}},
    )
    await pg_persistence.persist_graph(ctx, [n1, n2], [edge])

    _, edges = await pg_persistence.load_graph(ctx)
    assert len(edges) == 1
    assert edges[0].domain_tags["evidence_ref"] == {"body_ref": "doc.md", "byte_offset": 42}


async def test_fts_lang_per_namespace(pg_persistence, ctx):
    node = make_node("n1", source_uri="legal.txt", domain_tags={"namespace": "legal:core"})
    node.title = "Contrato de arrendamiento"
    await pg_persistence.persist_graph(ctx, [node], [])

    pool = await pg_persistence._ensure_pool()
    async with pool.acquire() as conn:
        lang = await conn.fetchval(f"SELECT lang FROM {pg_persistence._schema}.nodes WHERE concept_id = 'n1'")
        hit = await conn.fetchval(
            f"""SELECT fts @@ to_tsquery('spanish', 'arrendamiento')
                FROM {pg_persistence._schema}.node_versions WHERE concept_id = 'n1'"""
        )
    assert lang == "spanish"
    assert hit is True


def test_no_sqlalchemy_imports():
    import parrot.knowledge.graphindex.persist_postgres as module

    with open(module.__file__, "r", encoding="utf-8") as fh:
        content = fh.read()
    assert "sqlalchemy" not in content.lower()
    assert "parrot.stores.postgres" not in content

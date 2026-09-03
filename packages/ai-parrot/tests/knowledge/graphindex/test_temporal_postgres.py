"""Live-DB-gated tests for the temporal contract on PostgresPersistence (FEAT-520 TASK-2767)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from parrot.conf import default_dsn
from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence
from parrot.knowledge.graphindex.schema import EdgeKind, NodeKind, UniversalEdge, UniversalNode

PG_DSN = os.environ.get("GRAPHINDEX_PG_DSN") or default_dsn
pytestmark = pytest.mark.skipif(not PG_DSN, reason="needs live Postgres")


def _make_ctx(tenant_id: str = "test_tenant") -> Any:
    ctx = MagicMock()
    ctx.tenant_id = tenant_id
    return ctx


def make_node(node_id: str, **kwargs: Any) -> UniversalNode:
    kwargs.setdefault("kind", NodeKind.DOCUMENT)
    kwargs.setdefault("source_uri", "test.txt")
    kwargs.setdefault("title", f"Node {node_id}")
    return UniversalNode(node_id=node_id, **kwargs)


def make_edge(src: str, tgt: str, kind: EdgeKind = EdgeKind.CONTAINS) -> UniversalEdge:
    return UniversalEdge(source_id=src, target_id=tgt, kind=kind)


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


async def test_as_of_now_equals_load_graph(pg_persistence, ctx):
    await pg_persistence.persist_graph(ctx, [make_node("a"), make_node("b")], [make_edge("a", "b")])

    load_nodes, load_edges = await pg_persistence.load_graph(ctx)
    now = datetime.now(tz=timezone.utc) + timedelta(seconds=1)
    asof_nodes, asof_edges = await pg_persistence.as_of(ctx, now)

    assert {n.node_id for n in load_nodes} == {n.node_id for n in asof_nodes}
    assert [(e.source_id, e.target_id) for e in load_edges] == [(e.source_id, e.target_id) for e in asof_edges]


async def test_as_of_past_snapshot(pg_persistence, ctx):
    await pg_persistence.persist_graph(ctx, [make_node("a", title="Node a", summary="v1")], [])
    t_v1 = datetime.now(tz=timezone.utc)

    await pg_persistence.persist_graph(ctx, [make_node("a", title="Node a", summary="v2")], [])

    nodes_past, _ = await pg_persistence.as_of(ctx, t_v1)
    assert len(nodes_past) == 1
    assert nodes_past[0].summary == "v1"

    nodes_now, _ = await pg_persistence.as_of(ctx, datetime.now(tz=timezone.utc) + timedelta(seconds=1))
    assert nodes_now[0].summary == "v2"


async def test_history_ordering_and_ranges(pg_persistence, ctx):
    await pg_persistence.persist_graph(ctx, [make_node("a", summary="v1")], [])
    await pg_persistence.persist_graph(ctx, [make_node("a", summary="v2")], [])
    await pg_persistence.persist_graph(ctx, [make_node("a", summary="v3")], [])

    history = await pg_persistence.history(ctx, "a")
    assert [row.summary for row in history] == ["v1", "v2", "v3"]
    assert history[0].valid_to is not None
    assert history[1].valid_to is not None
    assert history[2].valid_to is None  # current, open range
    # contiguous: each closed row's valid_to equals the next row's valid_from
    assert history[0].valid_to == history[1].valid_from
    assert history[1].valid_to == history[2].valid_from


async def test_history_unknown_concept_empty(pg_persistence, ctx):
    assert await pg_persistence.history(ctx, "does-not-exist") == []


async def test_diff_structured_output(pg_persistence, ctx):
    await pg_persistence.persist_graph(ctx, [make_node("a"), make_node("b"), make_node("c")], [])
    t1 = datetime.now(tz=timezone.utc)

    await pg_persistence.persist_graph(ctx, [make_node("a", summary="changed")], [make_edge("a", "b")])
    t2 = datetime.now(tz=timezone.utc) + timedelta(seconds=1)

    diff = await pg_persistence.diff(ctx, "a", t1, t2)
    assert diff.concept_id == "a"
    assert len(diff.version_changes) == 2  # old closed + new opened
    assert any(e["dst"] == "b" for e in diff.edges_added)
    assert diff.edges_removed == []


async def test_naive_datetime_rejected(pg_persistence, ctx):
    with pytest.raises(ValueError):
        await pg_persistence.as_of(ctx, datetime.now())  # noqa: DTZ005 — intentionally naive
    with pytest.raises(ValueError):
        await pg_persistence.diff(ctx, "a", datetime.now(), datetime.now(tz=timezone.utc))


async def test_current_path_uses_partial_index(pg_persistence, ctx):
    """Spec D3: the current-time read path stays indexed, never a full scan.

    The planner may pick either ``nv_current`` (the plain partial index)
    or the EXCLUDE constraint's own GiST index on ``(concept_id,
    validity)`` — both satisfy ``concept_id = $1``. Either is a valid D3
    outcome: what the acceptance criterion actually guards against is a
    full ``Seq Scan`` across the whole (unbounded, historical)
    ``node_versions`` table on every current-time read.
    """
    await pg_persistence.persist_graph(ctx, [make_node("a")], [])
    pool = await pg_persistence._ensure_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SET LOCAL enable_seqscan = OFF")
            plan_rows = await conn.fetch(
                f"""EXPLAIN SELECT * FROM {pg_persistence._schema}.node_versions
                    WHERE concept_id = $1 AND upper_inf(validity)""",
                "a",
            )
    plan_text = "\n".join(row["QUERY PLAN"] for row in plan_rows)
    assert "Index Scan" in plan_text
    assert "Seq Scan" not in plan_text
    assert "nv_current" in plan_text or "excl" in plan_text

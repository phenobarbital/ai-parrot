"""Tests for the FEAT-520 temporal/hybrid tools on GraphIndexToolkit (TASK-2773).

Covers:
  - temporal/hybrid tools EXCLUDED from tool generation on a SQLite-backed
    toolkit (not merely error-returning)
  - present on a Postgres-backed toolkit (live-gated)
  - graph_hybrid_retrieve's tool schema exposes no weight/mode params
  - graph_diff / graph_as_of / graph_concept_history smoke over a live store
"""

from __future__ import annotations

import os
import uuid

import pytest

from parrot.conf import default_dsn
from parrot.knowledge.graphindex.factory import build_graph_memory_toolkit

PG_DSN = os.environ.get("GRAPHINDEX_PG_DSN") or default_dsn

_TEMPORAL_TOOL_NAMES = {"graph_as_of", "graph_concept_history", "graph_diff", "graph_hybrid_retrieve"}


@pytest.fixture
def db_dir(tmp_path):
    return tmp_path / "graph_memory"


@pytest.fixture
def tmp_schema() -> str:
    return f"graphindex_test_{uuid.uuid4().hex[:12]}"


async def test_temporal_tools_absent_on_sqlite(db_dir):
    tk = await build_graph_memory_toolkit(db_dir=db_dir, agent_id="ag")
    names = set(tk.list_tool_names())
    assert names.isdisjoint(_TEMPORAL_TOOL_NAMES)
    # graph_history (commit log) and revert_write remain available.
    assert "graph_history" in names
    assert "revert_write" in names


def test_hybrid_tool_schema_has_no_weights():
    # Schema inspection needs no live store — assert directly against the
    # class method signature, which is what args_schema is derived from
    # regardless of which backend excludes/includes the tool.
    import inspect

    from parrot_tools.graphindex.toolkit import GraphIndexToolkit

    sig = inspect.signature(GraphIndexToolkit.graph_hybrid_retrieve)
    params = set(sig.parameters) - {"self"}
    assert params == {"query", "seeds"}
    assert "weights" not in params
    assert "limit" not in params
    assert "reranker" not in params
    assert "mode" not in params


@pytest.mark.skipif(not PG_DSN, reason="needs live Postgres")
async def test_temporal_tools_present_on_postgres(tmp_schema):
    tk = await build_graph_memory_toolkit(
        tenant_id="test_tenant", agent_id="ag", backend="postgres", dsn=PG_DSN, schema=tmp_schema
    )
    try:
        names = set(tk.list_tool_names())
        assert _TEMPORAL_TOOL_NAMES <= names
    finally:
        pool = await tk.publisher.persistence._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {tmp_schema} CASCADE")
        await tk.publisher.persistence.close()


@pytest.mark.skipif(not PG_DSN, reason="needs live Postgres")
async def test_graph_diff_tool_smoke(tmp_schema):
    tk = await build_graph_memory_toolkit(
        tenant_id="test_tenant", agent_id="ag", backend="postgres", dsn=PG_DSN, schema=tmp_schema
    )
    try:
        r1 = await tk.create_concept("Widget", "v1 summary")
        concept_id = r1["node_id"]
        import datetime as _dt

        t1 = _dt.datetime.now(tz=_dt.timezone.utc).isoformat()
        await tk.attach_summary(concept_id, "v2 summary")
        t2 = (_dt.datetime.now(tz=_dt.timezone.utc) + _dt.timedelta(seconds=1)).isoformat()

        diff = await tk.graph_diff(concept_id, t1, t2)
        assert "error" not in diff
        assert diff["concept_id"] == concept_id
        assert diff["version_changes"]

        history = await tk.graph_concept_history(concept_id)
        assert "error" not in history
        assert len(history["versions"]) >= 2

        as_of = await tk.graph_as_of(t2)
        assert "error" not in as_of
        assert any(n["node_id"] == concept_id for n in as_of["nodes"])
    finally:
        pool = await tk.publisher.persistence._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {tmp_schema} CASCADE")
        await tk.publisher.persistence.close()


async def test_temporal_tool_returns_error_when_absent(db_dir):
    """Calling the underlying method directly (bypassing exclude_tools)
    still degrades gracefully — defensive, not just tool-registry gated."""
    tk = await build_graph_memory_toolkit(db_dir=db_dir, agent_id="ag")
    result = await tk.graph_as_of("2026-01-01T00:00:00+00:00")
    assert "error" in result

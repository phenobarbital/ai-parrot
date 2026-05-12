"""Unit tests for ConceptCatalogSyncWorker (TASK-1089).

All external I/O (asyncpg, ArangoDB, Redis) is mocked.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from parrot.knowledge.ontology.concept_catalog.worker import ConceptCatalogSyncWorker


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_pool(conn_mock: AsyncMock) -> MagicMock:
    pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield conn_mock

    pool.acquire = _acquire
    return pool


def _make_conn(fetch_return=None) -> AsyncMock:
    conn = AsyncMock()
    conn.fetch.return_value = fetch_return or []
    conn.execute.return_value = None

    # H1 fix: run_once now wraps the outbox drain in async with conn.transaction().
    # Set up transaction() as an asynccontextmanager so the mock works correctly.
    @asynccontextmanager
    async def _transaction():
        yield None

    conn.transaction = _transaction
    return conn


def _make_graph_store() -> MagicMock:
    gs = MagicMock()
    gs.upsert_nodes = AsyncMock(return_value=MagicMock())
    gs.create_edges = AsyncMock(return_value=0)
    gs.soft_delete_nodes = AsyncMock(return_value=None)
    return gs


def _make_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.publish = AsyncMock(return_value=1)
    return redis


def _outbox_row(
    operation: str = "invalidate_cache",
    attempts: int = 0,
    tenant_id: str = "tenant-a",
    payload: dict | None = None,
) -> dict:
    """Build a minimal outbox row dict.

    S2 fix: ontology_concept_outbox has NO tenant_id column. The worker reads
    tenant_id from payload.get("tenant_id"). We therefore put it in payload here
    so test rows match real DB rows.
    """
    # Merge tenant_id into payload so the worker's S2 fix reads it correctly.
    base_payload: dict = {"tenant_id": tenant_id}
    if payload:
        base_payload.update(payload)
    return {
        "id": 1,
        "operation": operation,
        "payload": base_payload,
        "attempts": attempts,
        "enqueued_at": None,
        "processed_at": None,
        "last_error": None,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestRunOnce:
    async def test_returns_zero_when_outbox_empty(self):
        conn = _make_conn(fetch_return=[])
        pool = _make_pool(conn)
        worker = ConceptCatalogSyncWorker(pool, _make_graph_store(), _make_redis())

        count = await worker.run_once(batch_size=10)
        assert count == 0

    async def test_drains_rows_and_returns_count(self):
        rows = [_outbox_row("invalidate_cache"), _outbox_row("invalidate_cache")]
        conn = _make_conn(fetch_return=rows)
        pool = _make_pool(conn)
        worker = ConceptCatalogSyncWorker(pool, _make_graph_store(), _make_redis())

        count = await worker.run_once(batch_size=10)
        assert count == 2

    async def test_marks_processed_at_after_success(self):
        rows = [_outbox_row("invalidate_cache")]
        conn = _make_conn(fetch_return=rows)
        pool = _make_pool(conn)
        worker = ConceptCatalogSyncWorker(pool, _make_graph_store(), _make_redis())

        await worker.run_once()
        # execute should be called at least once for SET processed_at
        assert conn.execute.call_count >= 1
        update_calls = [str(c) for c in conn.execute.call_args_list]
        assert any("processed_at" in s for s in update_calls)

    async def test_unknown_operation_skips_row(self):
        rows = [_outbox_row(operation="unknown_op")]
        conn = _make_conn(fetch_return=rows)
        pool = _make_pool(conn)
        worker = ConceptCatalogSyncWorker(pool, _make_graph_store(), _make_redis())

        # Should not raise
        count = await worker.run_once()
        assert count == 1
        # No processed_at update since row was skipped
        assert conn.execute.call_count == 0


class TestOpInvalidate:
    async def test_publishes_to_redis_channel(self):
        rows = [_outbox_row("invalidate_cache", tenant_id="tenant-x")]
        conn = _make_conn(fetch_return=rows)
        pool = _make_pool(conn)
        redis = _make_redis()
        worker = ConceptCatalogSyncWorker(pool, _make_graph_store(), redis)

        await worker.run_once()
        redis.publish.assert_called_once()
        channel, _ = redis.publish.call_args[0]
        assert channel == "ontology:invalidate:tenant-x"


class TestOpPublish:
    async def test_upserts_concept_node_with_pg_concept_id(self):
        concept_id = str(uuid4())
        payload = {
            "target_kind": "concept",
            "concept_id": concept_id,
            "slug": "sales",
            "label": "Sales",
        }
        rows = [_outbox_row("publish_to_graph", payload=payload)]
        conn = _make_conn(fetch_return=rows)
        pool = _make_pool(conn)
        gs = _make_graph_store()
        redis = _make_redis()
        worker = ConceptCatalogSyncWorker(pool, gs, redis)

        await worker.run_once()
        gs.upsert_nodes.assert_called_once()
        args = gs.upsert_nodes.call_args
        nodes = args[0][2]  # positional: ctx, collection, nodes
        assert nodes[0]["pg_concept_id"] == concept_id

    async def test_creates_isa_edge_for_edge_payload(self):
        edge_id = str(uuid4())
        payload = {
            "target_kind": "isa_edge",
            "isa_edge_id": edge_id,
            "child_id": str(uuid4()),
            "parent_ref": "Employee",
            "parent_tier": "framework",
        }
        rows = [_outbox_row("publish_to_graph", payload=payload)]
        conn = _make_conn(fetch_return=rows)
        pool = _make_pool(conn)
        gs = _make_graph_store()
        worker = ConceptCatalogSyncWorker(pool, gs, _make_redis())

        await worker.run_once()
        gs.create_edges.assert_called_once()
        edges = gs.create_edges.call_args[0][2]
        assert edges[0]["pg_isa_edge_id"] == edge_id

    async def test_publish_also_triggers_invalidation(self):
        payload = {
            "target_kind": "concept",
            "concept_id": str(uuid4()),
            "slug": "comp",
        }
        rows = [_outbox_row("publish_to_graph", payload=payload, tenant_id="t1")]
        conn = _make_conn(fetch_return=rows)
        pool = _make_pool(conn)
        redis = _make_redis()
        worker = ConceptCatalogSyncWorker(pool, _make_graph_store(), redis)

        await worker.run_once()
        redis.publish.assert_called_once()
        channel = redis.publish.call_args[0][0]
        assert "t1" in channel


class TestOpDeprecate:
    async def test_soft_deletes_concept_node(self):
        concept_id = str(uuid4())
        payload = {"target_kind": "concept", "concept_id": concept_id}
        rows = [_outbox_row("deprecate_in_graph", payload=payload)]
        conn = _make_conn(fetch_return=rows)
        pool = _make_pool(conn)
        gs = _make_graph_store()
        worker = ConceptCatalogSyncWorker(pool, gs, _make_redis())

        await worker.run_once()
        gs.soft_delete_nodes.assert_called_once()
        keys = gs.soft_delete_nodes.call_args[0][2]
        assert concept_id in keys

    async def test_soft_deletes_isa_edge(self):
        edge_id = str(uuid4())
        payload = {"target_kind": "isa_edge", "isa_edge_id": edge_id}
        rows = [_outbox_row("deprecate_in_graph", payload=payload)]
        conn = _make_conn(fetch_return=rows)
        pool = _make_pool(conn)
        gs = _make_graph_store()
        worker = ConceptCatalogSyncWorker(pool, gs, _make_redis())

        await worker.run_once()
        gs.soft_delete_nodes.assert_called_once()
        _, collection, keys = gs.soft_delete_nodes.call_args[0]
        assert collection == "concept_isa"
        assert edge_id in keys


class TestDLQ:
    async def test_increments_attempts_on_failure(self):
        # Make ArangoDB throw an error
        gs = _make_graph_store()
        gs.upsert_nodes.side_effect = RuntimeError("arango down")

        payload = {
            "target_kind": "concept",
            "concept_id": str(uuid4()),
            "slug": "x",
        }
        rows = [_outbox_row("publish_to_graph", payload=payload, attempts=0)]
        conn = _make_conn(fetch_return=rows)
        pool = _make_pool(conn)
        worker = ConceptCatalogSyncWorker(pool, gs, _make_redis())

        await worker.run_once()
        # execute called with attempts update
        update_calls = [str(c) for c in conn.execute.call_args_list]
        assert any("attempts" in s for s in update_calls)

    async def test_dlq_threshold_logs_error(self, caplog):
        import logging
        gs = _make_graph_store()
        gs.upsert_nodes.side_effect = RuntimeError("persistent error")

        payload = {
            "target_kind": "concept",
            "concept_id": str(uuid4()),
            "slug": "x",
        }
        # Row already at MAX_RETRIES - 1 attempts
        rows = [_outbox_row("publish_to_graph", payload=payload, attempts=4)]
        conn = _make_conn(fetch_return=rows)
        pool = _make_pool(conn)
        worker = ConceptCatalogSyncWorker(pool, gs, _make_redis())

        with caplog.at_level(logging.ERROR, logger="Parrot.Ontology.ConceptCatalog.Worker"):
            await worker.run_once()

        assert any("DLQ" in record.message for record in caplog.records)

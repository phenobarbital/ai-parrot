"""Unit tests for SchemaOverlaySyncWorker (TASK-1096)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from parrot.knowledge.ontology.schema_overlay.worker import SchemaOverlaySyncWorker


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
    return conn


def _make_redis() -> AsyncMock:
    r = AsyncMock()
    r.publish = AsyncMock(return_value=1)
    return r


def _outbox_row(operation: str = "invalidate_cache", attempts: int = 0) -> dict:
    return {
        "id": 1,
        "tenant_id": "tenant-x",
        "operation": operation,
        "payload": {},
        "attempts": attempts,
        "enqueued_at": None,
        "processed_at": None,
        "last_error": None,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestRunOnce:
    async def test_returns_zero_on_empty_outbox(self):
        conn = _make_conn()
        pool = _make_pool(conn)
        worker = SchemaOverlaySyncWorker(pool, _make_redis())
        assert await worker.run_once() == 0

    async def test_returns_count_of_rows(self):
        rows = [_outbox_row(), _outbox_row("deprecate_invalidate")]
        conn = _make_conn(fetch_return=rows)
        pool = _make_pool(conn)
        worker = SchemaOverlaySyncWorker(pool, _make_redis())
        assert await worker.run_once() == 2

    async def test_marks_processed_at(self):
        rows = [_outbox_row()]
        conn = _make_conn(fetch_return=rows)
        pool = _make_pool(conn)
        worker = SchemaOverlaySyncWorker(pool, _make_redis())
        await worker.run_once()
        update_calls = [str(c) for c in conn.execute.call_args_list]
        assert any("processed_at" in s for s in update_calls)

    async def test_unknown_operation_skipped(self):
        rows = [_outbox_row(operation="unknown_op")]
        conn = _make_conn(fetch_return=rows)
        pool = _make_pool(conn)
        worker = SchemaOverlaySyncWorker(pool, _make_redis())
        await worker.run_once()
        assert conn.execute.call_count == 0


class TestOpInvalidate:
    async def test_publishes_to_correct_channel_invalidate(self):
        rows = [_outbox_row("invalidate_cache")]
        conn = _make_conn(fetch_return=rows)
        pool = _make_pool(conn)
        redis = _make_redis()
        worker = SchemaOverlaySyncWorker(pool, redis)
        await worker.run_once()
        redis.publish.assert_called_once()
        channel = redis.publish.call_args[0][0]
        assert channel == "ontology:invalidate:tenant-x"

    async def test_publishes_to_correct_channel_deprecate(self):
        rows = [_outbox_row("deprecate_invalidate")]
        conn = _make_conn(fetch_return=rows)
        pool = _make_pool(conn)
        redis = _make_redis()
        worker = SchemaOverlaySyncWorker(pool, redis)
        await worker.run_once()
        redis.publish.assert_called_once()

    async def test_no_arango_calls_made(self):
        rows = [_outbox_row()]
        conn = _make_conn(fetch_return=rows)
        pool = _make_pool(conn)
        redis = _make_redis()
        worker = SchemaOverlaySyncWorker(pool, redis)
        # No graph_store attribute — verifying no ArangoDB calls are made
        assert not hasattr(worker, "_graph_store")
        await worker.run_once()


class TestDLQ:
    async def test_increments_attempts_on_failure(self):
        redis = _make_redis()
        redis.publish.side_effect = RuntimeError("redis down")

        rows = [_outbox_row(attempts=0)]
        conn = _make_conn(fetch_return=rows)
        pool = _make_pool(conn)
        worker = SchemaOverlaySyncWorker(pool, redis)
        await worker.run_once()
        update_calls = [str(c) for c in conn.execute.call_args_list]
        assert any("attempts" in s for s in update_calls)

    async def test_dlq_threshold_logs_error(self, caplog):
        import logging
        redis = _make_redis()
        redis.publish.side_effect = RuntimeError("persistent error")

        rows = [_outbox_row(attempts=4)]  # MAX_RETRIES - 1
        conn = _make_conn(fetch_return=rows)
        pool = _make_pool(conn)
        worker = SchemaOverlaySyncWorker(pool, redis)

        with caplog.at_level(logging.ERROR, logger="Parrot.Ontology.SchemaOverlay.Worker"):
            await worker.run_once()

        assert any("DLQ" in r.message for r in caplog.records)

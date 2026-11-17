"""Tests for ConceptCatalogSyncWorker vocabulary publication (TASK-5266)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, call

from parrot.knowledge.ontology.concept_catalog.worker import ConceptCatalogSyncWorker


def _make_pool(conn_mock: AsyncMock) -> MagicMock:
    """Create a pool mock which yields the supplied connection."""
    pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield conn_mock

    pool.acquire = _acquire
    return pool


def _make_conn(rows: list[dict]) -> AsyncMock:
    """Create a connection mock with a transaction context manager."""
    conn = AsyncMock()
    conn.fetch.return_value = rows
    conn.execute.return_value = None

    @asynccontextmanager
    async def _transaction():
        yield None

    conn.transaction = _transaction
    return conn


def _make_graph_store() -> MagicMock:
    """Create a graph store mock for the worker's operation handlers."""
    graph_store = MagicMock()
    graph_store.upsert_nodes = AsyncMock(return_value=MagicMock())
    return graph_store


def _outbox_row(tenant_id: str) -> dict:
    """Build a minimal outbox row that materialises a graph concept."""
    return {
        "id": tenant_id,
        "operation": "publish_to_graph",
        "payload": {
            "tenant_id": tenant_id,
            "target_kind": "concept",
            "concept_id": f"concept-{tenant_id}",
            "slug": f"concept-{tenant_id}",
        },
        "attempts": 0,
    }


async def test_worker_republishes_tenants():
    """Publish every distinct tenant once after the outbox batch commits."""
    rows = [_outbox_row("tenant-a"), _outbox_row("tenant-a"), _outbox_row("tenant-b")]
    publisher = MagicMock()
    publisher.publish_tenant = AsyncMock()
    worker = ConceptCatalogSyncWorker(
        _make_pool(_make_conn(rows)),
        _make_graph_store(),
        AsyncMock(),
        vocabulary_publisher=publisher,
    )

    assert await worker.run_once() == 3
    publisher.publish_tenant.assert_has_awaits([call("tenant-a"), call("tenant-b")])
    assert publisher.publish_tenant.await_count == 2


async def test_publisher_error_does_not_fail_run_once():
    """Keep the committed batch successful if vocabulary publication fails."""
    publisher = MagicMock()
    publisher.publish_tenant = AsyncMock(side_effect=RuntimeError("publisher unavailable"))
    worker = ConceptCatalogSyncWorker(
        _make_pool(_make_conn([_outbox_row("tenant-a")])),
        _make_graph_store(),
        AsyncMock(),
        vocabulary_publisher=publisher,
    )

    assert await worker.run_once() == 1
    publisher.publish_tenant.assert_awaited_once_with("tenant-a")


async def test_worker_without_publisher_unchanged():
    """Retain existing graph materialisation when no publisher is configured."""
    graph_store = _make_graph_store()
    worker = ConceptCatalogSyncWorker(
        _make_pool(_make_conn([_outbox_row("tenant-a")])),
        graph_store,
        AsyncMock(),
    )

    assert await worker.run_once() == 1
    graph_store.upsert_nodes.assert_awaited_once()

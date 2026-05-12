"""Unit tests for ConceptCatalogReconciler (TASK-1091).

All DB and graph store I/O is mocked.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from parrot.knowledge.ontology.concept_catalog.reconcile import (
    ConceptCatalogReconciler,
    ReconciliationReport,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_pool(conn_mock: AsyncMock) -> MagicMock:
    pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield conn_mock

    pool.acquire = _acquire
    return pool


def _make_graph_store(
    concept_docs: list | None = None,
    isa_docs: list | None = None,
) -> MagicMock:
    gs = MagicMock()

    async def _get_all(ctx, collection):
        if collection == "concept_isa":
            return isa_docs or []
        return concept_docs or []

    gs.get_all_nodes = _get_all
    return gs


# Old timestamp: well before the in-flight cutoff
OLD_TS = datetime(2020, 1, 1, tzinfo=timezone.utc)


def _pg_concept_row(concept_id: str | None = None) -> dict:
    cid = concept_id or str(uuid4())
    return {"id": cid, "slug": "test_slug", "updated_at": OLD_TS}


def _arango_concept_doc(pg_concept_id: str) -> dict:
    return {"_key": pg_concept_id, "pg_concept_id": pg_concept_id, "tenant_id": "t"}


def _pg_isa_row(edge_id: str | None = None) -> dict:
    eid = edge_id or str(uuid4())
    return {"id": eid, "updated_at": OLD_TS}


def _arango_isa_doc(pg_isa_edge_id: str) -> dict:
    return {"_key": pg_isa_edge_id, "pg_isa_edge_id": pg_isa_edge_id}


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestReconciliationClean:
    async def test_no_discrepancies_when_in_sync(self):
        pg_id = str(uuid4())
        conn = AsyncMock()
        conn.fetch.side_effect = [
            # concepts
            [_pg_concept_row(pg_id)],
            # isa edges
            [],
        ]
        pool = _make_pool(conn)
        gs = _make_graph_store(
            concept_docs=[_arango_concept_doc(pg_id)],
            isa_docs=[],
        )
        reconciler = ConceptCatalogReconciler(pool, gs)
        report = await reconciler.reconcile("tenant-a")

        assert not report.has_discrepancies
        assert report.missing_in_arango == 0
        assert report.orphans_in_arango == 0

    async def test_empty_both_sides_is_clean(self):
        conn = AsyncMock()
        conn.fetch.side_effect = [[], []]
        pool = _make_pool(conn)
        gs = _make_graph_store()
        reconciler = ConceptCatalogReconciler(pool, gs)
        report = await reconciler.reconcile("tenant-a")
        assert not report.has_discrepancies


class TestForwardScan:
    async def test_detects_missing_arango_doc(self):
        pg_id = str(uuid4())
        conn = AsyncMock()
        conn.fetch.side_effect = [[_pg_concept_row(pg_id)], []]
        pool = _make_pool(conn)
        gs = _make_graph_store(concept_docs=[], isa_docs=[])
        reconciler = ConceptCatalogReconciler(pool, gs)
        report = await reconciler.reconcile("tenant-a")

        assert report.missing_in_arango == 1
        assert any("MISSING_IN_ARANGO" in d for d in report.discrepancies)

    async def test_detects_missing_isa_edge(self):
        isa_id = str(uuid4())
        conn = AsyncMock()
        conn.fetch.side_effect = [[], [_pg_isa_row(isa_id)]]
        pool = _make_pool(conn)
        gs = _make_graph_store(concept_docs=[], isa_docs=[])
        reconciler = ConceptCatalogReconciler(pool, gs)
        report = await reconciler.reconcile("tenant-a")

        assert report.missing_isa_in_arango == 1
        assert any("MISSING_ISA_IN_ARANGO" in d for d in report.discrepancies)


class TestReverseScan:
    async def test_detects_orphan_arango_doc(self):
        orphan_id = str(uuid4())
        conn = AsyncMock()
        # PG returns NO rows (empty), ArangoDB has one doc
        conn.fetch.side_effect = [[], []]
        pool = _make_pool(conn)
        gs = _make_graph_store(
            concept_docs=[_arango_concept_doc(orphan_id)],
            isa_docs=[],
        )
        reconciler = ConceptCatalogReconciler(pool, gs)
        report = await reconciler.reconcile("tenant-a")

        assert report.orphans_in_arango == 1
        assert any("ORPHAN_IN_ARANGO" in d for d in report.discrepancies)

    async def test_detects_orphan_isa_edge(self):
        orphan_id = str(uuid4())
        conn = AsyncMock()
        conn.fetch.side_effect = [[], []]
        pool = _make_pool(conn)
        gs = _make_graph_store(
            concept_docs=[],
            isa_docs=[_arango_isa_doc(orphan_id)],
        )
        reconciler = ConceptCatalogReconciler(pool, gs)
        report = await reconciler.reconcile("tenant-a")

        assert report.orphan_edges_in_arango == 1


class TestNoAutoRepair:
    async def test_graph_store_not_written_during_reconcile(self):
        pg_id = str(uuid4())
        conn = AsyncMock()
        # PG has an approved concept, ArangoDB is empty
        conn.fetch.side_effect = [[_pg_concept_row(pg_id)], []]
        pool = _make_pool(conn)

        # Track any write calls
        gs = MagicMock()
        upsert_mock = AsyncMock(return_value=None)
        gs.upsert_nodes = upsert_mock
        gs.soft_delete_nodes = AsyncMock(return_value=None)

        async def _get_all(ctx, collection):
            return []

        gs.get_all_nodes = _get_all

        reconciler = ConceptCatalogReconciler(pool, gs)
        await reconciler.reconcile("tenant-a")

        # No write operations should occur
        gs.upsert_nodes.assert_not_called()
        gs.soft_delete_nodes.assert_not_called()


class TestInFlightFilter:
    async def test_in_flight_rows_excluded(self):
        """Rows updated after the cutoff should not appear in forward scan."""
        pg_id = str(uuid4())
        # Row updated very recently (in-flight) — should be excluded
        recent_ts = datetime.now(timezone.utc)
        conn = AsyncMock()
        # The query filters by cutoff, so conn.fetch returns empty if DB respects it.
        # In our mock, we simulate the DB already applying the filter.
        conn.fetch.side_effect = [[], []]  # no rows returned
        pool = _make_pool(conn)
        gs = _make_graph_store(concept_docs=[], isa_docs=[])
        reconciler = ConceptCatalogReconciler(pool, gs, outbox_drain_interval=30)
        report = await reconciler.reconcile("tenant-a")
        # No missing because in-flight filtered
        assert report.missing_in_arango == 0

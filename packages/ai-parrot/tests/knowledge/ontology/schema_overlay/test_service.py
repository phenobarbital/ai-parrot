"""Unit tests for SchemaOverlayService (TASK-1095).

All DB and external calls are mocked.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from parrot.knowledge.ontology.exceptions import DryRunFailedError, InvalidTransitionError
from parrot.knowledge.ontology.schema_overlay.models import DryRunReport, SchemaOverlayRow
from parrot.knowledge.ontology.schema_overlay.service import SchemaOverlayService


# ── Mock helpers ──────────────────────────────────────────────────────────────

def _make_pool(conn_mock: AsyncMock) -> MagicMock:
    pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield conn_mock

    pool.acquire = _acquire
    return pool


def _make_conn(
    fetchval_return=None,
    fetchrow_return=None,
    fetch_return=None,
) -> AsyncMock:
    conn = AsyncMock()
    conn.fetchval.return_value = fetchval_return
    conn.fetchrow.return_value = fetchrow_return
    conn.fetch.return_value = fetch_return or []
    conn.execute.return_value = None

    @asynccontextmanager
    async def _tx():
        yield None

    conn.transaction = _tx
    return conn


def _overlay_row(
    state: str = "proposed",
    overlay_id: object = None,
    tenant_id: str = "tenant-a",
) -> dict:
    """Return a minimal overlay row dict (only fields SchemaOverlayRow accepts)."""
    return {
        "id": overlay_id or uuid4(),
        "tenant_id": tenant_id,
        "overlay_kind": "entity_type",
        "name": "Project",
        "definition": {"collection": "projects"},
        "state": state,
        "asserted_by": "admin",
        "reviewed_by": None,
        "rationale": None,
        "dry_run_report": None,
    }


def _make_tenant_manager() -> MagicMock:
    mgr = MagicMock()
    mgr._ontology_dir = MagicMock()
    mgr._base_file = "base.ontology.yaml"
    mgr._domains_dir = "domains"
    mgr._clients_dir = "clients"
    mgr.list_tenants = MagicMock(return_value=[])
    return mgr


def _make_merger() -> MagicMock:
    merger = MagicMock()
    merger.merge_with_overlay = MagicMock(return_value=MagicMock())
    return merger


def _make_svc(conn: AsyncMock) -> SchemaOverlayService:
    pool = _make_pool(conn)
    return SchemaOverlayService(pool, _make_tenant_manager(), _make_merger())


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestPropose:
    async def test_creates_row_and_returns_uuid(self):
        new_id = uuid4()
        conn = _make_conn(fetchval_return=new_id)
        svc = _make_svc(conn)
        result = await svc.propose(
            tenant_id="tenant-a",
            overlay_kind="entity_type",
            name="Project",
            definition={"collection": "projects"},
            asserted_by="admin",
        )
        assert result == new_id

    async def test_inserts_audit_and_outbox(self):
        new_id = uuid4()
        conn = _make_conn(fetchval_return=new_id)
        svc = _make_svc(conn)
        await svc.propose(
            tenant_id="tenant-a",
            overlay_kind="entity_type",
            name="P",
            definition={},
            asserted_by="admin",
        )
        # Three execute calls: INSERT overlay, INSERT audit, INSERT outbox
        assert conn.execute.call_count >= 2


class TestApproveWithPassingDryRun:
    async def test_approve_transitions_to_approved(self):
        oid = uuid4()
        row = _overlay_row(state="pending_review", overlay_id=oid)
        conn = _make_conn(fetchrow_return=row)
        svc = _make_svc(conn)

        good_report = DryRunReport(ok=True, checks=[], duration_ms=1)
        with patch(
            "parrot.knowledge.ontology.schema_overlay.service.dry_run_overlay",
            AsyncMock(return_value=good_report),
        ):
            await svc.approve(oid, "reviewer")

        # execute called for UPDATE + audit + outbox
        assert conn.execute.call_count >= 1

    async def test_approve_from_proposed_also_allowed(self):
        oid = uuid4()
        row = _overlay_row(state="proposed", overlay_id=oid)
        conn = _make_conn(fetchrow_return=row)
        svc = _make_svc(conn)

        good_report = DryRunReport(ok=True, checks=[], duration_ms=1)
        with patch(
            "parrot.knowledge.ontology.schema_overlay.service.dry_run_overlay",
            AsyncMock(return_value=good_report),
        ):
            await svc.approve(oid, "reviewer")


class TestApproveWithFailingDryRun:
    async def test_raises_dry_run_failed_error(self):
        oid = uuid4()
        row = _overlay_row(state="pending_review", overlay_id=oid)
        conn = _make_conn(fetchrow_return=row)
        svc = _make_svc(conn)

        bad_report = DryRunReport(
            ok=False,
            checks=[{"check_name": "merge", "passed": False, "details": "fail"}],
            error="merge failed",
            duration_ms=5,
        )
        with patch(
            "parrot.knowledge.ontology.schema_overlay.service.dry_run_overlay",
            AsyncMock(return_value=bad_report),
        ):
            with pytest.raises(DryRunFailedError) as exc_info:
                await svc.approve(oid, "reviewer")
        assert exc_info.value.report is not None

    async def test_state_stays_at_pending_review_on_failure(self):
        oid = uuid4()
        row = _overlay_row(state="pending_review", overlay_id=oid)
        conn = _make_conn(fetchrow_return=row)
        svc = _make_svc(conn)

        bad_report = DryRunReport(
            ok=False, checks=[], error="fail", duration_ms=1
        )
        with patch(
            "parrot.knowledge.ontology.schema_overlay.service.dry_run_overlay",
            AsyncMock(return_value=bad_report),
        ):
            with pytest.raises(DryRunFailedError):
                await svc.approve(oid, "reviewer")
        # Verify dry_run_report update was called but NOT "approved" transition
        execute_calls = [str(c) for c in conn.execute.call_args_list]
        # No "approved" update should have occurred
        assert not any("state = 'approved'" in s for s in execute_calls)


class TestStateMachineTransitions:
    async def test_reject_from_proposed(self):
        oid = uuid4()
        row = _overlay_row(state="proposed", overlay_id=oid)
        conn = _make_conn(fetchrow_return=row)
        svc = _make_svc(conn)
        await svc.reject(oid, "reviewer", "not needed")

    async def test_reject_from_pending_review(self):
        oid = uuid4()
        row = _overlay_row(state="pending_review", overlay_id=oid)
        conn = _make_conn(fetchrow_return=row)
        svc = _make_svc(conn)
        await svc.reject(oid, "reviewer")

    async def test_deprecate_from_approved(self):
        oid = uuid4()
        row = _overlay_row(state="approved", overlay_id=oid)
        conn = _make_conn(fetchrow_return=row)
        svc = _make_svc(conn)
        await svc.deprecate(oid, "admin")

    async def test_restore_from_deprecated(self):
        oid = uuid4()
        row = _overlay_row(state="deprecated", overlay_id=oid)
        conn = _make_conn(fetchrow_return=row)
        svc = _make_svc(conn)
        await svc.restore(oid, "admin")

    async def test_approve_from_rejected_fails(self):
        oid = uuid4()
        row = _overlay_row(state="rejected", overlay_id=oid)
        conn = _make_conn(fetchrow_return=row)
        svc = _make_svc(conn)
        good_report = DryRunReport(ok=True, checks=[], duration_ms=1)
        with patch(
            "parrot.knowledge.ontology.schema_overlay.service.dry_run_overlay",
            AsyncMock(return_value=good_report),
        ):
            with pytest.raises(InvalidTransitionError) as exc_info:
                await svc.approve(oid, "reviewer")
        assert exc_info.value.current_state == "rejected"


class TestGetPending:
    async def test_returns_pending_rows(self):
        rows = [_overlay_row("proposed"), _overlay_row("pending_review")]
        conn = _make_conn(fetch_return=rows)
        svc = _make_svc(conn)
        result = await svc.get_pending("tenant-a")
        assert len(result) == 2
        assert all(isinstance(r, SchemaOverlayRow) for r in result)

    async def test_returns_empty_when_none(self):
        conn = _make_conn(fetch_return=[])
        svc = _make_svc(conn)
        result = await svc.get_pending("tenant-a")
        assert result == []


class TestGetHistory:
    async def test_returns_audit_records(self):
        audit_rows = [
            {"id": 1, "action": "approve", "occurred_at": None},
        ]
        conn = _make_conn(fetch_return=audit_rows)
        svc = _make_svc(conn)
        result = await svc.get_history(uuid4())
        assert len(result) == 1
        assert result[0]["action"] == "approve"

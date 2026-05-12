"""Unit tests for Schema Overlay HTTP routes (TASK-1097)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from parrot.knowledge.ontology.exceptions import DryRunFailedError, InvalidTransitionError
from parrot.knowledge.ontology.schema_overlay.http import register_routes
from parrot.knowledge.ontology.schema_overlay.models import DryRunReport, SchemaOverlayRow


# ── Helpers ──────────────────────────────────────────────────────────────────

def _overlay_row(overlay_id=None, state: str = "proposed") -> SchemaOverlayRow:
    return SchemaOverlayRow(
        id=overlay_id or uuid4(),
        tenant_id="tenant-a",
        overlay_kind="entity_type",
        name="Project",
        definition={"collection": "projects"},
        state=state,
        asserted_by="admin",
    )


def _make_service(**overrides) -> MagicMock:
    svc = MagicMock()
    svc.get_pending = AsyncMock(return_value=[_overlay_row()])
    svc.propose = AsyncMock(return_value=uuid4())
    svc.submit = AsyncMock(return_value=None)
    svc.approve = AsyncMock(return_value=None)
    svc.reject = AsyncMock(return_value=None)
    svc.deprecate = AsyncMock(return_value=None)
    svc.restore = AsyncMock(return_value=None)
    for k, v in overrides.items():
        setattr(svc, k, v)
    return svc


def _session(roles: list[str] | None = None) -> dict:
    return {
        "groups": roles or ["ontology_schema_admin"],
        "tenant_id": "tenant-a",
        "email": "admin@t.com",
    }


async def _make_client(svc: MagicMock, session: dict) -> TestClient:
    @web.middleware
    async def _inject(request, handler):
        request["session"] = session
        return await handler(request)

    app = web.Application(middlewares=[_inject])
    app["schema_overlay_service"] = svc
    register_routes(app)
    return TestClient(TestServer(app))


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestListOverlays:
    async def test_returns_200_for_admin(self):
        svc = _make_service()
        async with await _make_client(svc, _session()) as client:
            resp = await client.get("/api/ontology/schema")
            assert resp.status == 200
            data = await resp.json()
            assert "items" in data

    async def test_returns_403_without_role(self):
        svc = _make_service()
        async with await _make_client(svc, _session(["topic_curator"])) as client:
            resp = await client.get("/api/ontology/schema")
            assert resp.status == 403


class TestProposeOverlay:
    async def test_returns_201_on_propose(self):
        new_id = uuid4()
        svc = _make_service(propose=AsyncMock(return_value=new_id))
        async with await _make_client(svc, _session()) as client:
            resp = await client.post(
                "/api/ontology/schema",
                json={
                    "overlay_kind": "entity_type",
                    "name": "Project",
                    "definition": {"collection": "projects"},
                },
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["id"] == str(new_id)


class TestOverlayTransition:
    async def test_approve_calls_service(self):
        svc = _make_service()
        overlay_id = uuid4()
        async with await _make_client(svc, _session()) as client:
            resp = await client.post(
                f"/api/ontology/schema/{overlay_id}/transitions/approve"
            )
            assert resp.status == 200
            svc.approve.assert_called_once()

    async def test_dry_run_failure_returns_422(self):
        svc = _make_service(
            approve=AsyncMock(
                side_effect=DryRunFailedError(
                    "dry run failed",
                    report={"ok": False, "checks": [], "error": "fail", "duration_ms": 1},
                )
            )
        )
        overlay_id = uuid4()
        async with await _make_client(svc, _session()) as client:
            resp = await client.post(
                f"/api/ontology/schema/{overlay_id}/transitions/approve"
            )
            assert resp.status == 422
            data = await resp.json()
            assert data["error"] == "DryRunFailed"
            assert "dry_run_report" in data

    async def test_invalid_transition_returns_422(self):
        svc = _make_service(
            approve=AsyncMock(
                side_effect=InvalidTransitionError(
                    "bad state", current_state="rejected"
                )
            )
        )
        overlay_id = uuid4()
        async with await _make_client(svc, _session()) as client:
            resp = await client.post(
                f"/api/ontology/schema/{overlay_id}/transitions/approve"
            )
            assert resp.status == 422

    async def test_unknown_action_returns_400(self):
        svc = _make_service()
        overlay_id = uuid4()
        async with await _make_client(svc, _session()) as client:
            resp = await client.post(
                f"/api/ontology/schema/{overlay_id}/transitions/unknown_action"
            )
            assert resp.status == 400

    async def test_reject_calls_service(self):
        svc = _make_service()
        overlay_id = uuid4()
        async with await _make_client(svc, _session()) as client:
            resp = await client.post(
                f"/api/ontology/schema/{overlay_id}/transitions/reject"
            )
            assert resp.status == 200
            svc.reject.assert_called_once()

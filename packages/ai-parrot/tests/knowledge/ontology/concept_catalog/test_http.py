"""Unit tests for Concept Catalog HTTP routes (TASK-1092).

Tests use aiohttp test utilities with a mocked ConceptCatalogService.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from parrot.knowledge.ontology.concept_catalog.http import register_routes
from parrot.knowledge.ontology.concept_catalog.models import ConceptRow
from parrot.knowledge.ontology.exceptions import (
    CycleError,
    InvalidTransitionError,
    SynonymConflictError,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _concept_row(slug: str = "sales", concept_id=None) -> ConceptRow:
    return ConceptRow(
        id=concept_id or uuid4(),
        tenant_id="tenant-a",
        slug=slug,
        label=slug.title(),
        synonyms=[],
        state="approved",
        asserted_by="seed",
        effective_from=datetime.now(timezone.utc),
    )


def _make_service(**overrides) -> MagicMock:
    svc = MagicMock()
    svc.get_live_concepts = AsyncMock(return_value=[_concept_row()])
    svc.get_history = AsyncMock(return_value=[])
    svc.get_isa_subgraph = AsyncMock(return_value=[])
    svc.propose_concept = AsyncMock(return_value=uuid4())
    svc.approve = AsyncMock(return_value=None)
    svc.reject = AsyncMock(return_value=None)
    svc.deprecate = AsyncMock(return_value=None)
    svc.restore = AsyncMock(return_value=None)
    svc.submit_for_review = AsyncMock(return_value=None)
    svc.modify_metadata = AsyncMock(return_value=None)
    svc.propose_isa_edge = AsyncMock(return_value=uuid4())
    for k, v in overrides.items():
        setattr(svc, k, v)
    return svc


def _session(roles: list[str] | None = None, tenant: str = "tenant-a") -> dict:
    return {"groups": roles or ["topic_curator"], "tenant_id": tenant, "email": "user@t.com"}


async def _make_client(svc: MagicMock, session: dict) -> TestClient:
    """Build a test client with routes and a mocked service."""

    @web.middleware
    async def _inject_session(request, handler):
        request["session"] = session
        return await handler(request)

    app = web.Application(middlewares=[_inject_session])
    app["concept_catalog_service"] = svc
    register_routes(app)
    return TestClient(TestServer(app))


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestListConcepts:
    async def test_returns_200_for_curator(self):
        svc = _make_service()
        async with await _make_client(svc, _session(["topic_curator"])) as client:
            resp = await client.get("/api/ontology/concepts")
            assert resp.status == 200
            data = await resp.json()
            assert "items" in data

    async def test_returns_403_for_unauthenticated(self):
        svc = _make_service()
        async with await _make_client(svc, {}) as client:
            resp = await client.get("/api/ontology/concepts")
            assert resp.status in (401, 403)


class TestProposeConcept:
    async def test_curator_can_propose(self):
        new_id = uuid4()
        svc = _make_service(propose_concept=AsyncMock(return_value=new_id))
        async with await _make_client(svc, _session(["topic_curator"])) as client:
            resp = await client.post(
                "/api/ontology/concepts",
                json={"slug": "comp", "label": "Comp"},
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["id"] == str(new_id)

    async def test_synonym_conflict_returns_409(self):
        svc = _make_service(
            propose_concept=AsyncMock(
                side_effect=SynonymConflictError("conflict", synonym="comp")
            )
        )
        async with await _make_client(svc, _session(["topic_curator"])) as client:
            resp = await client.post(
                "/api/ontology/concepts",
                json={"slug": "x", "label": "X"},
            )
            assert resp.status == 409

    async def test_cycle_error_returns_422(self):
        svc = _make_service(
            propose_concept=AsyncMock(side_effect=CycleError("cycle detected"))
        )
        async with await _make_client(svc, _session(["topic_curator"])) as client:
            resp = await client.post(
                "/api/ontology/concepts",
                json={"slug": "x", "label": "X"},
            )
            assert resp.status == 422


class TestRoleEnforcement:
    async def test_curator_cannot_approve(self):
        svc = _make_service()
        concept_id = uuid4()
        async with await _make_client(svc, _session(["topic_curator"])) as client:
            resp = await client.post(
                f"/api/ontology/concepts/{concept_id}/transitions/approve"
            )
            assert resp.status == 403

    async def test_reviewer_can_approve(self):
        svc = _make_service()
        concept_id = uuid4()
        async with await _make_client(svc, _session(["topic_reviewer"])) as client:
            resp = await client.post(
                f"/api/ontology/concepts/{concept_id}/transitions/approve"
            )
            assert resp.status == 200

    async def test_curator_cannot_deprecate(self):
        svc = _make_service()
        concept_id = uuid4()
        async with await _make_client(svc, _session(["topic_curator"])) as client:
            resp = await client.post(
                f"/api/ontology/concepts/{concept_id}/transitions/deprecate"
            )
            assert resp.status == 403

    async def test_admin_can_deprecate(self):
        svc = _make_service()
        concept_id = uuid4()
        async with await _make_client(svc, _session(["topic_admin"])) as client:
            resp = await client.post(
                f"/api/ontology/concepts/{concept_id}/transitions/deprecate"
            )
            assert resp.status == 200

    async def test_admin_can_restore(self):
        svc = _make_service()
        concept_id = uuid4()
        async with await _make_client(svc, _session(["topic_admin"])) as client:
            resp = await client.post(
                f"/api/ontology/concepts/{concept_id}/transitions/restore"
            )
            assert resp.status == 200


class TestInvalidTransition:
    async def test_state_machine_error_returns_422(self):
        svc = _make_service(
            approve=AsyncMock(
                side_effect=InvalidTransitionError("bad transition", current_state="rejected")
            )
        )
        concept_id = uuid4()
        async with await _make_client(svc, _session(["topic_reviewer"])) as client:
            resp = await client.post(
                f"/api/ontology/concepts/{concept_id}/transitions/approve"
            )
            assert resp.status == 422


class TestIsaEdge:
    async def test_propose_isa_edge_returns_201(self):
        new_id = uuid4()
        svc = _make_service(propose_isa_edge=AsyncMock(return_value=new_id))
        async with await _make_client(svc, _session(["topic_curator"])) as client:
            resp = await client.post(
                "/api/ontology/concepts/isa",
                json={
                    "child_id": str(uuid4()),
                    "parent_tier": "framework",
                    "parent_ref": "Employee",
                },
            )
            assert resp.status == 201


class TestPagination:
    async def test_limit_and_offset_applied(self):
        concepts = [_concept_row(f"c{i}") for i in range(10)]
        svc = _make_service(get_live_concepts=AsyncMock(return_value=concepts))
        async with await _make_client(svc, _session()) as client:
            resp = await client.get("/api/ontology/concepts?limit=3&offset=2")
            assert resp.status == 200
            data = await resp.json()
            assert len(data["items"]) == 3
            assert data["total"] == 10

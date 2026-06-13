"""Unit tests for FEAT-302 API endpoints (TASK-018).

Tests the five new handler methods on FormAPIHandler:
  - get_org_graph          GET  /org/graph
  - create_project         POST /org/projects
  - map_project_workday    POST /org/cost-centers/{project_id}/workday-map
  - assign_user_role       POST /org/users/{user_id}/assign
  - sync_workday_identities POST /org/sync/workday

Also tests:
  - RBAC shadow-mode retrofit gate-keeping (rbac_enforcing=False vs True).
  - 501 when services are not configured.
  - 400 on missing required fields.

All tests use mocked requests — no live HTTP server required.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.services.org_graph import OrgGraph, OrgNode
from parrot_formdesigner.services.project_service import (
    DuplicateAccountingCodeError,
    Project,
    WorkdayCostCenterMapping,
)
from parrot_formdesigner.services.rbac import (
    PermissionRecord,
    RBACContext,
    RBACScope,
)
from parrot_formdesigner.services.workday_sync import WorkdayIdentitySyncAdapter
from parrot_formdesigner.services.registry import FormRegistry


# ---------------------------------------------------------------------------
# Request / handler helpers
# ---------------------------------------------------------------------------


def _make_request(
    *,
    method: str = "GET",
    body: dict | None = None,
    match_info: dict | None = None,
    session_programs: list[str] | None = None,
    tenant: str = "t1",
    user_id: str | None = None,
) -> MagicMock:
    """Build a mocked aiohttp web.Request for FEAT-302 tests."""
    from aiohttp import web

    req = MagicMock(spec=web.Request)
    req.method = method
    req.match_info = match_info or {}

    programs = session_programs if session_programs is not None else [tenant]
    session_obj = {"session": {"programs": programs}}
    req.session = session_obj
    req.__contains__ = lambda self, key: False

    # Mock request.user.organizations[0].org_id
    if user_id is not None:
        user = MagicMock()
        user.id = user_id
        user.organizations = []
        req.user = user
    else:
        user = MagicMock()
        user.id = "test-user"
        org = MagicMock()
        org.org_id = 7
        user.organizations = [org]
        req.user = user

    if body is not None:
        req.json = AsyncMock(return_value=body)
    else:
        req.json = AsyncMock(side_effect=ValueError("no body"))

    req.headers = {}
    return req


def _make_handler(
    *,
    org_graph_service=None,
    project_service=None,
    rbac_service=None,
    workday_adapter=None,
    rbac_enforcing: bool = False,
    tenant: str = "t1",
) -> FormAPIHandler:
    """Build a FormAPIHandler with FEAT-302 services mocked."""
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=None)
    registry.storage = None
    registry.default_tenant = tenant
    return FormAPIHandler(
        registry=registry,
        org_graph_service=org_graph_service,
        project_service=project_service,
        rbac_service=rbac_service,
        workday_adapter=workday_adapter,
        rbac_enforcing=rbac_enforcing,
    )


# ---------------------------------------------------------------------------
# Fake service helpers
# ---------------------------------------------------------------------------


def _make_org_graph(org_id: int = 7, tenant: str = "t1") -> OrgGraph:
    root = OrgNode(
        node_type="company",
        node_id=f"company:{tenant}",
        metadata={"tenant": tenant},
        children=[
            OrgNode(
                node_type="organization",
                node_id=str(org_id),
                parent_id=f"company:{tenant}",
                metadata={"name": "Test Org"},
            )
        ],
    )
    return OrgGraph(org_id=org_id, tenant=tenant, root=root)


def _make_project(
    project_id: int = 1,
    accounting_code: str = "ACC-001",
    client_id: int = 42,
    org_id: int = 7,
    tenant: str = "t1",
) -> Project:
    return Project(
        project_id=project_id,
        name="Test Project",
        accounting_code=accounting_code,
        client_id=client_id,
        org_id=org_id,
        tenant=tenant,
    )


def _make_mapping(project_id: int = 1, workday_code: str = "WD-001") -> WorkdayCostCenterMapping:
    return WorkdayCostCenterMapping(project_id=project_id, workday_code=workday_code)


def _make_permission_record(user_id: str = "u1", codename: str = "edit_form") -> PermissionRecord:
    return PermissionRecord(
        user_id=user_id,
        codename=codename,
        scope=RBACScope.OWN,
        program_id=7,
        policy_name=f"user__{user_id}__{codename}__own__prog7",
        tenant="t1",
    )


# ---------------------------------------------------------------------------
# get_org_graph
# ---------------------------------------------------------------------------


class TestGetOrgGraph:
    @pytest.mark.asyncio
    async def test_get_org_graph_200(self) -> None:
        graph = _make_org_graph()
        svc = MagicMock()
        svc.get_graph = AsyncMock(return_value=graph)
        handler = _make_handler(org_graph_service=svc)
        req = _make_request(method="GET")
        resp = await handler.get_org_graph(req)
        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["org_id"] == 7
        assert body["root"]["node_type"] == "company"

    @pytest.mark.asyncio
    async def test_get_org_graph_400_no_org_id(self) -> None:
        svc = MagicMock()
        handler = _make_handler(org_graph_service=svc)
        # No organizations
        req = _make_request(method="GET", user_id="anonymous")
        req.user.organizations = []
        resp = await handler.get_org_graph(req)
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_get_org_graph_501_not_configured(self) -> None:
        handler = _make_handler()  # no org_graph_service
        req = _make_request()
        resp = await handler.get_org_graph(req)
        assert resp.status == 501

    @pytest.mark.asyncio
    async def test_get_org_graph_404_not_found(self) -> None:
        svc = MagicMock()
        svc.get_graph = AsyncMock(side_effect=KeyError("Organization 99 not found"))
        handler = _make_handler(org_graph_service=svc)
        req = _make_request()
        resp = await handler.get_org_graph(req)
        assert resp.status == 404


# ---------------------------------------------------------------------------
# create_project
# ---------------------------------------------------------------------------


class TestCreateProject:
    @pytest.mark.asyncio
    async def test_create_project_201(self) -> None:
        project = _make_project()
        svc = MagicMock()
        svc.create_project = AsyncMock(return_value=project)
        handler = _make_handler(project_service=svc)
        req = _make_request(
            method="POST",
            body={"accounting_code": "ACC-001", "name": "Test", "client_id": 42, "org_id": 7},
        )
        resp = await handler.create_project(req)
        assert resp.status == 201
        body = json.loads(resp.body)
        assert body["accounting_code"] == "ACC-001"

    @pytest.mark.asyncio
    async def test_create_project_409_duplicate(self) -> None:
        svc = MagicMock()
        svc.create_project = AsyncMock(
            side_effect=DuplicateAccountingCodeError(42, "ACC-001")
        )
        handler = _make_handler(project_service=svc)
        req = _make_request(
            method="POST",
            body={"accounting_code": "ACC-001", "client_id": 42},
        )
        resp = await handler.create_project(req)
        assert resp.status == 409

    @pytest.mark.asyncio
    async def test_create_project_400_missing_accounting_code(self) -> None:
        svc = MagicMock()
        handler = _make_handler(project_service=svc)
        req = _make_request(method="POST", body={"client_id": 42})
        resp = await handler.create_project(req)
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_create_project_400_missing_client_id(self) -> None:
        svc = MagicMock()
        handler = _make_handler(project_service=svc)
        req = _make_request(method="POST", body={"accounting_code": "ACC"})
        resp = await handler.create_project(req)
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_create_project_501_not_configured(self) -> None:
        handler = _make_handler()
        req = _make_request(method="POST", body={"accounting_code": "A", "client_id": 1})
        resp = await handler.create_project(req)
        assert resp.status == 501


# ---------------------------------------------------------------------------
# map_project_workday
# ---------------------------------------------------------------------------


class TestMapProjectWorkday:
    @pytest.mark.asyncio
    async def test_map_workday_200(self) -> None:
        mapping = _make_mapping(project_id=5, workday_code="WD-999")
        svc = MagicMock()
        svc.map_to_workday = AsyncMock(return_value=mapping)
        handler = _make_handler(project_service=svc)
        req = _make_request(
            method="POST",
            match_info={"project_id": "5"},
            body={"workday_code": "WD-999"},
        )
        resp = await handler.map_project_workday(req)
        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["workday_code"] == "WD-999"

    @pytest.mark.asyncio
    async def test_map_workday_400_missing_workday_code(self) -> None:
        svc = MagicMock()
        handler = _make_handler(project_service=svc)
        req = _make_request(
            method="POST",
            match_info={"project_id": "5"},
            body={},
        )
        resp = await handler.map_project_workday(req)
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_map_workday_400_invalid_project_id(self) -> None:
        svc = MagicMock()
        handler = _make_handler(project_service=svc)
        req = _make_request(
            method="POST",
            match_info={"project_id": "notanint"},
            body={"workday_code": "WD-X"},
        )
        resp = await handler.map_project_workday(req)
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_map_workday_501_not_configured(self) -> None:
        handler = _make_handler()
        req = _make_request(
            method="POST",
            match_info={"project_id": "1"},
            body={"workday_code": "WD-001"},
        )
        resp = await handler.map_project_workday(req)
        assert resp.status == 501


# ---------------------------------------------------------------------------
# assign_user_role
# ---------------------------------------------------------------------------


class TestAssignUserRole:
    @pytest.mark.asyncio
    async def test_assign_role_200(self) -> None:
        from parrot_formdesigner.services.rbac import RBACContext
        record = _make_permission_record("user1", "edit_form")
        svc = MagicMock()
        svc.assign_role = AsyncMock(return_value=record)
        # H-1: caller must hold manage_roles — grant it via the resolve mock.
        svc.resolve = AsyncMock(return_value=RBACContext(
            user_id="caller", program_id=7,
            permissions=[_make_permission_record("caller", "manage_roles")],
        ))
        handler = _make_handler(rbac_service=svc)
        req = _make_request(
            method="POST",
            match_info={"user_id": "user1"},
            body={"codename": "edit_form", "scope": "own", "program_id": 7},
        )
        resp = await handler.assign_user_role(req)
        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["user_id"] == "user1"
        assert body["codename"] == "edit_form"

    @pytest.mark.asyncio
    async def test_assign_role_403_without_manage_roles(self) -> None:
        """H-1: caller lacking manage_roles is denied (privilege escalation guard)."""
        from parrot_formdesigner.services.rbac import RBACContext
        svc = MagicMock()
        svc.assign_role = AsyncMock(return_value=_make_permission_record("u1", "edit_form"))
        svc.resolve = AsyncMock(return_value=RBACContext(
            user_id="caller", program_id=7, permissions=[],
        ))
        handler = _make_handler(rbac_service=svc)
        req = _make_request(
            method="POST",
            match_info={"user_id": "u1"},
            body={"codename": "edit_form", "scope": "global", "program_id": 7},
        )
        resp = await handler.assign_user_role(req)
        assert resp.status == 403
        svc.assign_role.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_assign_role_400_missing_codename(self) -> None:
        svc = MagicMock()
        handler = _make_handler(rbac_service=svc)
        req = _make_request(
            method="POST",
            match_info={"user_id": "u1"},
            body={"scope": "own", "program_id": 7},
        )
        resp = await handler.assign_user_role(req)
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_assign_role_400_invalid_scope(self) -> None:
        svc = MagicMock()
        handler = _make_handler(rbac_service=svc)
        req = _make_request(
            method="POST",
            match_info={"user_id": "u1"},
            body={"codename": "edit_form", "scope": "invalid_scope", "program_id": 7},
        )
        resp = await handler.assign_user_role(req)
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_assign_role_501_not_configured(self) -> None:
        handler = _make_handler()
        req = _make_request(
            method="POST",
            match_info={"user_id": "u1"},
            body={"codename": "x", "scope": "own", "program_id": 1},
        )
        resp = await handler.assign_user_role(req)
        assert resp.status == 501


# ---------------------------------------------------------------------------
# sync_workday_identities
# ---------------------------------------------------------------------------


class TestSyncWorkdayIdentities:
    @pytest.mark.asyncio
    async def test_sync_workday_202(self) -> None:
        adapter = WorkdayIdentitySyncAdapter()
        handler = _make_handler(workday_adapter=adapter)
        req = _make_request(
            method="POST",
            body={"user_id": "u1", "action": "provision", "org_id": 7},
        )
        resp = await handler.sync_workday_identities(req)
        assert resp.status == 202
        body = json.loads(resp.body)
        assert body["status"] == "accepted"
        assert body["stub"] is True

    @pytest.mark.asyncio
    async def test_sync_workday_202_deprovision(self) -> None:
        adapter = WorkdayIdentitySyncAdapter()
        handler = _make_handler(workday_adapter=adapter)
        req = _make_request(
            method="POST",
            body={"user_id": "u2", "action": "deprovision", "org_id": 3},
        )
        resp = await handler.sync_workday_identities(req)
        assert resp.status == 202

    @pytest.mark.asyncio
    async def test_sync_workday_400_missing_user_id(self) -> None:
        adapter = WorkdayIdentitySyncAdapter()
        handler = _make_handler(workday_adapter=adapter)
        req = _make_request(
            method="POST",
            body={"action": "provision", "org_id": 7},
        )
        resp = await handler.sync_workday_identities(req)
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_sync_workday_400_invalid_action(self) -> None:
        adapter = WorkdayIdentitySyncAdapter()
        handler = _make_handler(workday_adapter=adapter)
        req = _make_request(
            method="POST",
            body={"user_id": "u1", "action": "teleport", "org_id": 7},
        )
        resp = await handler.sync_workday_identities(req)
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_sync_workday_501_not_configured(self) -> None:
        handler = _make_handler()
        req = _make_request(
            method="POST",
            body={"user_id": "u1", "action": "provision", "org_id": 1},
        )
        resp = await handler.sync_workday_identities(req)
        assert resp.status == 501


# ---------------------------------------------------------------------------
# RBAC shadow-mode gate-keeping
# ---------------------------------------------------------------------------


class TestRBACRetrofitGateKeeping:
    """Tests for the _rbac_shadow_gate helper."""

    @pytest.mark.asyncio
    async def test_shadow_mode_no_rbac_service_noop(self) -> None:
        """Without an RBACService, shadow gate does nothing (no error)."""
        handler = _make_handler(rbac_enforcing=False)
        req = _make_request()
        # Should not raise
        await handler._rbac_shadow_gate(req, "create_form")

    @pytest.mark.asyncio
    async def test_shadow_mode_allowed_no_block(self) -> None:
        """Shadow mode: allowed permission doesn't block even with enforcing=False."""
        svc = MagicMock()
        ctx = RBACContext(
            user_id="test-user",
            program_id=0,
            permissions=[
                PermissionRecord(
                    user_id="test-user",
                    codename="create_form",
                    scope=RBACScope.GLOBAL,
                    program_id=0,
                    policy_name="p1",
                    tenant="t1",
                )
            ],
        )
        svc.resolve = AsyncMock(return_value=ctx)
        handler = _make_handler(rbac_service=svc, rbac_enforcing=False)
        req = _make_request()
        await handler._rbac_shadow_gate(req, "create_form")  # no exception

    @pytest.mark.asyncio
    async def test_shadow_mode_denied_no_block_when_not_enforcing(self) -> None:
        """Shadow mode with rbac_enforcing=False: denied permission logs but never blocks."""
        svc = MagicMock()
        ctx = RBACContext(user_id="test-user", program_id=0, permissions=[])
        svc.resolve = AsyncMock(return_value=ctx)
        handler = _make_handler(rbac_service=svc, rbac_enforcing=False)
        req = _make_request()
        # Must NOT raise even though permission is denied
        await handler._rbac_shadow_gate(req, "delete_form")

    @pytest.mark.asyncio
    async def test_enforcing_mode_denied_raises_403(self) -> None:
        """When rbac_enforcing=True: denied permission raises HTTPForbidden."""
        from aiohttp import web

        svc = MagicMock()
        ctx = RBACContext(user_id="test-user", program_id=0, permissions=[])
        svc.resolve = AsyncMock(return_value=ctx)
        handler = _make_handler(rbac_service=svc, rbac_enforcing=True)
        req = _make_request()
        with pytest.raises(web.HTTPForbidden):
            await handler._rbac_shadow_gate(req, "delete_form")

    @pytest.mark.asyncio
    async def test_enforcing_mode_allowed_no_raise(self) -> None:
        """When rbac_enforcing=True and permission is granted: no exception."""
        svc = MagicMock()
        ctx = RBACContext(
            user_id="test-user",
            program_id=0,
            permissions=[
                PermissionRecord(
                    user_id="test-user",
                    codename="delete_form",
                    scope=RBACScope.GLOBAL,
                    program_id=0,
                    policy_name="p2",
                    tenant="t1",
                )
            ],
        )
        svc.resolve = AsyncMock(return_value=ctx)
        handler = _make_handler(rbac_service=svc, rbac_enforcing=True)
        req = _make_request()
        await handler._rbac_shadow_gate(req, "delete_form")  # no exception

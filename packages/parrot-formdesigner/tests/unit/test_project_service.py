"""Unit tests for TASK-015 — ProjectService (fake pool, no real DB).

Covers:
- create_project() happy path (returns Project with project_id).
- DuplicateAccountingCodeError on unique constraint violation.
- get_project() happy path + ProjectNotFoundError.
- list_projects() with no filter / client_id filter / org_id filter.
- map_to_workday() upsert round-trip.
- NEVER writes to networkninja.projects (verified by inspecting SQL constants).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_formdesigner.services.project_service import (
    DuplicateAccountingCodeError,
    Project,
    ProjectNotFoundError,
    ProjectService,
    WorkdayCostCenterMapping,
    _INSERT_PROJECT_SQL,
    _SELECT_PROJECT_SQL,
    _UPSERT_WORKDAY_MAPPING_SQL,
)


# ---------------------------------------------------------------------------
# Fake pool / connection helpers
# ---------------------------------------------------------------------------


def _row(data: dict) -> MagicMock:
    """Build a MagicMock that behaves like an asyncpg Record."""
    row = MagicMock()
    row.__getitem__ = lambda self, k: data[k]
    return row


def _make_conn(
    fetchrow_result: Any = None,
    fetch_result: list | None = None,
    fetchrow_side_effect: Any = None,
) -> MagicMock:
    conn = MagicMock()
    if fetchrow_side_effect is not None:
        conn.fetchrow = AsyncMock(side_effect=fetchrow_side_effect)
    else:
        conn.fetchrow = AsyncMock(return_value=fetchrow_result)
    conn.fetch = AsyncMock(return_value=fetch_result or [])
    return conn


def _make_pool(conn: MagicMock) -> MagicMock:
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=cm)
    return pool


def _project_row(
    project_id: int = 1,
    client_id: int = 42,
    name: str = "Test Project",
    accounting_code: str = "ACC001",
    org_id: int = 7,
    is_active: bool = True,
) -> MagicMock:
    return _row(
        {
            "project_id": project_id,
            "client_id": client_id,
            "name": name,
            "accounting_code": accounting_code,
            "org_id": org_id,
            "start_timestamp": None,
            "end_timestamp": None,
            "is_active": is_active,
        }
    )


# ---------------------------------------------------------------------------
# SQL safety: verify no writes to networkninja
# ---------------------------------------------------------------------------


class TestSQLSafety:
    """Ensure we never reference networkninja writes in our SQL constants."""

    def test_insert_sql_targets_fieldsync(self) -> None:
        assert "fieldsync.projects" in _INSERT_PROJECT_SQL
        assert "networkninja" not in _INSERT_PROJECT_SQL

    def test_select_sql_targets_fieldsync(self) -> None:
        assert "fieldsync.projects" in _SELECT_PROJECT_SQL
        assert "networkninja" not in _SELECT_PROJECT_SQL

    def test_workday_upsert_targets_fieldsync(self) -> None:
        assert "fieldsync.workday_cost_center_mappings" in _UPSERT_WORKDAY_MAPPING_SQL
        assert "networkninja" not in _UPSERT_WORKDAY_MAPPING_SQL


# ---------------------------------------------------------------------------
# create_project tests
# ---------------------------------------------------------------------------


class TestCreateProject:
    @pytest.mark.asyncio
    async def test_create_returns_project(self) -> None:
        row = _project_row()
        conn = _make_conn(fetchrow_result=row)
        svc = ProjectService(_make_pool(conn))
        proj = await svc.create_project(
            accounting_code="ACC001",
            name="Test Project",
            client_id=42,
            org_id=7,
            tenant="acme",
        )
        assert isinstance(proj, Project)
        assert proj.project_id == 1
        assert proj.accounting_code == "ACC001"
        assert proj.client_id == 42
        assert proj.tenant == "acme"

    @pytest.mark.asyncio
    async def test_create_passes_correct_params(self) -> None:
        row = _project_row()
        conn = _make_conn(fetchrow_result=row)
        pool = _make_pool(conn)
        svc = ProjectService(pool)
        await svc.create_project(
            accounting_code="ACC-X",
            name="Proj X",
            client_id=99,
            org_id=5,
            tenant="t1",
        )
        call_args = conn.fetchrow.call_args
        assert call_args[0][1] == 99   # client_id
        assert call_args[0][3] == "ACC-X"  # accounting_code (pos 3 in INSERT)

    @pytest.mark.asyncio
    async def test_create_duplicate_raises(self) -> None:
        class _UniqueViolation(Exception):
            pass

        err = _UniqueViolation("duplicate key value violates unique constraint uq_projects_client_accounting")
        conn = _make_conn(fetchrow_side_effect=err)
        svc = ProjectService(_make_pool(conn))
        with pytest.raises(DuplicateAccountingCodeError) as exc_info:
            await svc.create_project(
                accounting_code="ACC001",
                name="Dupe",
                client_id=42,
                org_id=7,
                tenant="t1",
            )
        assert exc_info.value.accounting_code == "ACC001"
        assert exc_info.value.client_id == 42

    @pytest.mark.asyncio
    async def test_create_other_error_propagates(self) -> None:
        conn = _make_conn(fetchrow_side_effect=RuntimeError("connection lost"))
        svc = ProjectService(_make_pool(conn))
        with pytest.raises(RuntimeError, match="connection lost"):
            await svc.create_project(
                accounting_code="ACC001",
                client_id=42,
                org_id=7,
                tenant="t1",
            )


# ---------------------------------------------------------------------------
# get_project tests
# ---------------------------------------------------------------------------


class TestGetProject:
    @pytest.mark.asyncio
    async def test_get_returns_project(self) -> None:
        row = _project_row(project_id=5, accounting_code="ACC-5")
        conn = _make_conn(fetchrow_result=row)
        svc = ProjectService(_make_pool(conn))
        proj = await svc.get_project(5, org_id=7)
        assert proj.project_id == 5
        assert proj.accounting_code == "ACC-5"

    @pytest.mark.asyncio
    async def test_get_not_found_raises(self) -> None:
        conn = _make_conn(fetchrow_result=None)
        svc = ProjectService(_make_pool(conn))
        with pytest.raises(ProjectNotFoundError) as exc_info:
            await svc.get_project(999, org_id=7)
        assert exc_info.value.project_id == 999

    @pytest.mark.asyncio
    async def test_get_passes_tenant_to_model(self) -> None:
        row = _project_row()
        conn = _make_conn(fetchrow_result=row)
        svc = ProjectService(_make_pool(conn))
        proj = await svc.get_project(1, org_id=7, tenant="mytenant")
        assert proj.tenant == "mytenant"


# ---------------------------------------------------------------------------
# list_projects tests
# ---------------------------------------------------------------------------


class TestListProjects:
    @pytest.mark.asyncio
    async def test_list_all_no_filter(self) -> None:
        rows = [_project_row(1), _project_row(2, accounting_code="ACC002")]
        conn = _make_conn(fetch_result=rows)
        svc = ProjectService(_make_pool(conn))
        projects = await svc.list_projects(org_id=7)
        assert len(projects) == 2

    @pytest.mark.asyncio
    async def test_list_by_client_id(self) -> None:
        rows = [_project_row(1, client_id=10)]
        conn = _make_conn(fetch_result=rows)
        svc = ProjectService(_make_pool(conn))
        projects = await svc.list_projects(org_id=7, client_id=10)
        assert len(projects) == 1
        assert projects[0].client_id == 10

    @pytest.mark.asyncio
    async def test_list_by_org_id(self) -> None:
        rows = [_project_row(1, org_id=99)]
        conn = _make_conn(fetch_result=rows)
        svc = ProjectService(_make_pool(conn))
        projects = await svc.list_projects(org_id=99)
        assert len(projects) == 1

    @pytest.mark.asyncio
    async def test_list_empty(self) -> None:
        conn = _make_conn(fetch_result=[])
        svc = ProjectService(_make_pool(conn))
        projects = await svc.list_projects(org_id=7, client_id=9999)
        assert projects == []


# ---------------------------------------------------------------------------
# map_to_workday tests
# ---------------------------------------------------------------------------


class TestMapToWorkday:
    def _mapping_row(
        self,
        project_id: int = 1,
        workday_code: str = "WD-001",
        direction: str = "internal_to_workday",
    ) -> MagicMock:
        return _row(
            {
                "project_id": project_id,
                "workday_code": workday_code,
                "direction": direction,
            }
        )

    @pytest.mark.asyncio
    async def test_map_returns_mapping(self) -> None:
        row = self._mapping_row(project_id=5, workday_code="WD-999")
        conn = _make_conn(fetchrow_result=row)
        svc = ProjectService(_make_pool(conn))
        mapping = await svc.map_to_workday(5, "WD-999", tenant="acme")
        assert isinstance(mapping, WorkdayCostCenterMapping)
        assert mapping.project_id == 5
        assert mapping.workday_code == "WD-999"
        assert mapping.direction == "internal_to_workday"

    @pytest.mark.asyncio
    async def test_map_upsert_called_with_correct_params(self) -> None:
        row = self._mapping_row()
        conn = _make_conn(fetchrow_result=row)
        pool = _make_pool(conn)
        svc = ProjectService(pool)
        await svc.map_to_workday(42, "WD-100", tenant="t1")
        conn.fetchrow.assert_called_once()
        call_sql = conn.fetchrow.call_args[0][0]
        assert "ON CONFLICT" in call_sql
        assert "DO UPDATE" in call_sql

    @pytest.mark.asyncio
    async def test_map_custom_direction(self) -> None:
        row = self._mapping_row(direction="bidirectional")
        conn = _make_conn(fetchrow_result=row)
        svc = ProjectService(_make_pool(conn))
        mapping = await svc.map_to_workday(
            1, "WD-200", tenant="t1", direction="bidirectional"
        )
        assert mapping.direction == "bidirectional"

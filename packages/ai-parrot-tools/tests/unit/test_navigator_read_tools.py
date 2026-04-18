"""Unit tests for migrated SELECT-heavy read tools — FEAT-107 TASK-755/756.

Verifies:
- list_programs routes through select_rows for superuser (no scope filter).
- list_modules sort_by_newest=True uses select_rows with column_casts.
- list_widget_categories uses select_rows with distinct=True.
- get_full_program_structure uses execute_sql directly (documented exception; raw SQL
  with (attributes->>'order')::numeric NULLS LAST cannot be expressed via select_rows).
- search uses execute_sql directly (documented exception; ILIKE + UNION queries cannot
  be expressed via select_rows).

Note: After TASK-756, _nav_run_query/_nav_run_one were removed from NavigatorToolkit.
      All legacy references in these tests now assert on execute_sql instead.
"""
from __future__ import annotations

import pytest

from parrot_tools.navigator.toolkit import NavigatorToolkit


_STUB_PROGRAM_ID = "00000000-0000-0000-0000-000000000001"
_STUB_DASHBOARD_ID = "00000000-0000-0000-0000-000000000002"


class TestListProgramsUsesSelectRows:
    """list_programs must route through select_rows when user is superuser."""

    @pytest.mark.asyncio
    async def test_list_programs_uses_select_rows(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """Superuser path: select_rows is called once for auth.programs."""
        tk = navigator_toolkit_factory()  # is_superuser=True by default
        tk.select_rows = mocker.AsyncMock(return_value=[
            {"program_id": 1, "program_name": "Prog A", "program_slug": "proga", "abbrv": "A", "is_active": True},
        ])

        result = await tk.list_programs(active_only=True, limit=10)

        assert result["status"] == "success"
        assert len(result["result"]) == 1

        # select_rows must have been called for auth.programs
        calls = tk.select_rows.call_args_list
        tables_called = [
            (c[0][0] if c[0] else c[1].get("table")) for c in calls
        ]
        assert "auth.programs" in tables_called, (
            f"Expected select_rows('auth.programs', ...) but got calls on: {tables_called}"
        )

    @pytest.mark.asyncio
    async def test_list_programs_passes_is_active_filter(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """active_only=True must pass where containing is_active=True."""
        tk = navigator_toolkit_factory()
        tk.select_rows = mocker.AsyncMock(return_value=[])

        await tk.list_programs(active_only=True)

        calls = [c for c in tk.select_rows.call_args_list
                 if (c[0][0] if c[0] else c[1].get("table")) == "auth.programs"]
        assert len(calls) >= 1
        args, kwargs = calls[0]
        where = kwargs.get("where") or (args[1] if len(args) > 1 else {})
        assert where is None or where.get("is_active") is True


class TestListModulesSortByNewestPreserved:
    """list_modules(sort_by_newest=True) must use select_rows with column_casts."""

    @pytest.mark.asyncio
    async def test_list_modules_sort_by_newest_preserved(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """sort_by_newest=True routes through select_rows (superuser path)."""
        tk = navigator_toolkit_factory()  # superuser
        tk.select_rows = mocker.AsyncMock(return_value=[
            {"module_id": 1, "module_name": "Module A", "inserted_at": "2024-01-01"},
        ])

        result = await tk.list_modules(sort_by_newest=True)

        assert result["status"] == "success"

        calls = [c for c in tk.select_rows.call_args_list
                 if (c[0][0] if c[0] else c[1].get("table")) == "navigator.modules"]
        assert len(calls) >= 1, "select_rows must be called for navigator.modules"

        args, kwargs = calls[0]
        order_by = kwargs.get("order_by")
        assert order_by is not None
        assert any("inserted_at" in str(o) for o in order_by), (
            f"order_by must reference inserted_at, got: {order_by}"
        )

    @pytest.mark.asyncio
    async def test_list_modules_column_casts_serializes_timestamps_as_text(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """sort_by_newest=True must pass column_casts for inserted_at/updated_at."""
        tk = navigator_toolkit_factory()
        tk.select_rows = mocker.AsyncMock(return_value=[])

        await tk.list_modules(sort_by_newest=True)

        calls = [c for c in tk.select_rows.call_args_list
                 if (c[0][0] if c[0] else c[1].get("table")) == "navigator.modules"]
        assert len(calls) >= 1

        args, kwargs = calls[0]
        column_casts = kwargs.get("column_casts")
        assert column_casts is not None, "column_casts must be passed for timestamp serialization"
        assert column_casts.get("inserted_at") == "text", (
            f"inserted_at must be cast to text, got: {column_casts}"
        )
        assert column_casts.get("updated_at") == "text", (
            f"updated_at must be cast to text, got: {column_casts}"
        )


class TestListWidgetCategoriesUsesSelectRowsDistinct:
    """list_widget_categories must use select_rows with distinct=True."""

    @pytest.mark.asyncio
    async def test_list_widget_categories_uses_select_rows_distinct(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """list_widget_categories routes through select_rows with distinct=True."""
        tk = navigator_toolkit_factory()
        tk.select_rows = mocker.AsyncMock(return_value=[
            {"category": "generic"},
            {"category": "walmart"},
        ])

        result = await tk.list_widget_categories()

        assert result["status"] == "success"

        calls = [c for c in tk.select_rows.call_args_list
                 if (c[0][0] if c[0] else c[1].get("table")) == "navigator.widget_types"]
        assert len(calls) >= 1, "select_rows must be called for navigator.widget_types"

        args, kwargs = calls[0]
        distinct = kwargs.get("distinct")
        assert distinct is True, f"distinct must be True, got: {distinct}"


class TestGetFullProgramStructureStillUsesExecuteQuery:
    """get_full_program_structure must still use execute_sql (documented exception).

    After TASK-756, _nav_run_query/_nav_run_one were removed; callers use execute_sql.
    """

    @pytest.mark.asyncio
    async def test_get_full_program_structure_still_uses_execute_query(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """get_full_program_structure uses multi-level nested fetch → uses execute_sql directly.

        The method uses (attributes->>'order')::numeric NULLS LAST and complex raw SQL
        that cannot be expressed via select_rows.  After TASK-756 it calls execute_sql
        directly (not _nav_run_query, which was deleted).
        """
        tk = navigator_toolkit_factory()
        # Provide side_effects for each execute_sql call the method makes:
        #   1. SELECT * FROM auth.programs WHERE program_id = $1  (single_row=True)
        #   2. SELECT module_id, ... FROM navigator.modules …      (single_row=False)
        #   3. SELECT dashboard_id, … FROM navigator.dashboards … (single_row=False)
        #   4. SELECT count(*) … FROM navigator.widgets …          (single_row=True)
        execute_sql_mock = mocker.AsyncMock(side_effect=[
            {"program_id": 1, "program_name": "Test", "program_slug": "test"},
            [],
            [],
            {"total": 5},
        ])
        tk.execute_sql = execute_sql_mock

        await tk.get_full_program_structure(entity_id=1)

        assert execute_sql_mock.call_count >= 1, (
            "get_full_program_structure must call execute_sql (raw SQL, not select_rows)"
        )


class TestSearchStillUsesExecuteQuery:
    """search must still use execute_sql (ILIKE + scope filters — documented exception).

    After TASK-756, _nav_run_query was deleted; callers use execute_sql directly.
    """

    @pytest.mark.asyncio
    async def test_search_still_uses_execute_query(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """search uses ILIKE patterns across multiple entity tables — uses execute_sql directly.

        ILIKE cross-table UNION queries cannot be expressed via select_rows.  After
        TASK-756 the method calls execute_sql (not _nav_run_query, which was deleted).
        """
        tk = navigator_toolkit_factory()
        execute_sql_mock = mocker.AsyncMock(return_value=[])
        tk.execute_sql = execute_sql_mock

        await tk.search(query="test")

        assert execute_sql_mock.call_count >= 1, (
            "search must call execute_sql (ILIKE + UNION, not expressible via select_rows)"
        )


class TestGetDashboardUsesSelectRows:
    """get_dashboard UUID path must route through select_rows."""

    @pytest.mark.asyncio
    async def test_get_dashboard_uses_select_rows_for_uuid_path(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        tk = navigator_toolkit_factory()
        tk.select_rows = mocker.AsyncMock(return_value=[
            {"dashboard_id": _STUB_DASHBOARD_ID, "name": "Test Dash", "program_id": 1},
        ])

        result = await tk.get_dashboard(entity_uuid=_STUB_DASHBOARD_ID)

        assert result["status"] == "success"

        calls = [c for c in tk.select_rows.call_args_list
                 if (c[0][0] if c[0] else c[1].get("table")) == "navigator.dashboards"]
        assert len(calls) >= 1, "select_rows must be called for navigator.dashboards"


class TestListClientsUsesSelectRows:
    """list_clients must route through select_rows."""

    @pytest.mark.asyncio
    async def test_list_clients_uses_select_rows(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        tk = navigator_toolkit_factory()
        tk.select_rows = mocker.AsyncMock(return_value=[
            {"client_id": 1, "client": "Client A", "client_slug": "ca", "is_active": True},
        ])

        result = await tk.list_clients()

        assert result["status"] == "success"

        calls = [c for c in tk.select_rows.call_args_list
                 if (c[0][0] if c[0] else c[1].get("table")) == "auth.clients"]
        assert len(calls) >= 1, "select_rows must be called for auth.clients"


class TestListGroupsUsesSelectRows:
    """list_groups must route through select_rows."""

    @pytest.mark.asyncio
    async def test_list_groups_uses_select_rows(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        tk = navigator_toolkit_factory()
        tk.select_rows = mocker.AsyncMock(return_value=[
            {"group_id": 1, "group_name": "Admins", "client_id": 1, "is_active": True},
        ])

        result = await tk.list_groups()

        assert result["status"] == "success"

        calls = [c for c in tk.select_rows.call_args_list
                 if (c[0][0] if c[0] else c[1].get("table")) == "auth.groups"]
        assert len(calls) >= 1, "select_rows must be called for auth.groups"

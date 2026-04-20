"""Unit tests for migrated create_dashboard — FEAT-107 TASK-751.

Verifies that create_dashboard uses insert_row (no raw SQL), passes plain
dicts for JSON columns, and preserves idempotency + return-shape contract.
"""
from __future__ import annotations

import pytest

from parrot_tools.navigator.toolkit import NavigatorToolkit


_STUB_DASHBOARD_ID = "00000000-0000-0000-0000-000000000010"


class TestCreateDashboardInsertRowPayloadShape:
    """insert_row must be called with a 20-column data dict and plain dicts for JSON."""

    @pytest.mark.asyncio
    async def test_create_dashboard_insert_row_payload_shape(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        tk = navigator_toolkit_factory()

        # No existing dashboard
        tk.select_rows = mocker.AsyncMock(return_value=[])
        captured_data = {}

        async def capture_insert(table, data, returning=None, conn=None):
            if table == "navigator.dashboards":
                captured_data.update(data)
            return {
                "dashboard_id": _STUB_DASHBOARD_ID,
                "name": "My Dashboard",
                "slug": None,
            }

        tk.insert_row = capture_insert

        result = await tk.create_dashboard(
            name="My Dashboard",
            module_id=1,
            program_id=1,
            confirm_execution=True,
        )

        assert result["status"] == "success"
        assert result["result"]["dashboard_id"] == str(_STUB_DASHBOARD_ID)

        # Verify 20-column data dict
        expected_keys = {
            "name", "description", "module_id", "program_id", "user_id",
            "dashboard_type", "position", "enabled", "shared", "published",
            "allow_filtering", "allow_widgets", "render_partials",
            "save_filtering", "is_system", "params", "attributes",
            "conditions", "slug", "cond_definition", "filtering_show",
        }
        assert expected_keys == set(captured_data.keys()), (
            f"Missing keys: {expected_keys - set(captured_data.keys())}\n"
            f"Extra keys: {set(captured_data.keys()) - expected_keys}"
        )

        # JSON columns must be plain dicts (not JSON strings)
        assert isinstance(captured_data["params"], dict)
        assert isinstance(captured_data["attributes"], dict)
        # conditions/cond_definition/filtering_show can be None or dict
        for jcol in ("conditions", "cond_definition", "filtering_show"):
            assert captured_data[jcol] is None or isinstance(captured_data[jcol], dict)

    @pytest.mark.asyncio
    async def test_create_dashboard_confirm_execution_false_returns_plan_dict(
        self, navigator_toolkit_factory
    ) -> None:
        """confirm_execution=False must return plan dict with zero CRUD writes."""
        tk = navigator_toolkit_factory()
        result = await tk.create_dashboard(
            name="Test Dashboard",
            module_id=1,
            program_id=1,
            confirm_execution=False,
        )
        assert result["status"] == "confirm_execution"
        for method in ("insert_row", "upsert_row", "update_row", "delete_row"):
            assert getattr(tk, method).call_count == 0


class TestCreateDashboardTransaction:
    """create_dashboard(confirm_execution=True) must open exactly one transaction."""

    @pytest.mark.asyncio
    async def test_create_dashboard_uses_transaction(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        tk = navigator_toolkit_factory()
        tk.select_rows = mocker.AsyncMock(return_value=[])
        tk.insert_row = mocker.AsyncMock(return_value={
            "dashboard_id": _STUB_DASHBOARD_ID,
            "name": "Test",
            "slug": None,
        })

        result = await tk.create_dashboard(
            name="Test",
            module_id=1,
            program_id=1,
            confirm_execution=True,
        )

        assert result["status"] == "success"
        assert tk.transaction.call_count == 1

    @pytest.mark.asyncio
    async def test_create_dashboard_idempotent_returns_existing(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """Second call with same name/module/program returns already_existed=True."""
        tk = navigator_toolkit_factory()
        tk.select_rows = mocker.AsyncMock(return_value=[{
            "dashboard_id": _STUB_DASHBOARD_ID,
            "name": "Existing",
            "slug": "existing_slug",
        }])

        result = await tk.create_dashboard(
            name="Existing",
            module_id=1,
            program_id=1,
            confirm_execution=True,
        )

        assert result["status"] == "success"
        assert result["result"]["already_existed"] is True
        assert result["result"]["dashboard_id"] == str(_STUB_DASHBOARD_ID)
        # No insert when already exists
        assert tk.insert_row.call_count == 0

    @pytest.mark.asyncio
    async def test_create_dashboard_no_jsonb_strings(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """No ::text::jsonb cast strings should appear in data passed to insert_row."""
        tk = navigator_toolkit_factory()
        tk.select_rows = mocker.AsyncMock(return_value=[])
        captured_data = {}

        async def capture_insert(table, data, returning=None, conn=None):
            captured_data.update(data)
            return {
                "dashboard_id": _STUB_DASHBOARD_ID,
                "name": "D",
                "slug": None,
            }

        tk.insert_row = capture_insert

        await tk.create_dashboard(
            name="D",
            module_id=1,
            program_id=1,
            params={"key": "value"},
            attributes={"icon": "test"},
            confirm_execution=True,
        )

        # Verify no JSON string encoding in the data dict
        for key, val in captured_data.items():
            assert not isinstance(val, str) or "::text::jsonb" not in val, (
                f"Column {key!r} contains a cast string: {val!r}"
            )
        # params and attributes must be dicts
        assert captured_data["params"] == {"key": "value"}
        assert captured_data["attributes"] == {"icon": "test"}

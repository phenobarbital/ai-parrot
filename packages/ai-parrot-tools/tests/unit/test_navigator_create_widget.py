"""Unit tests for migrated create_widget — FEAT-107 TASK-753.

Verifies that:
- insert_row is called once for navigator.widgets with plain dict values.
- update_row is called once for navigator.dashboards with merged widget_location.
- Both CRUD calls receive conn=tx.
- transaction() is entered exactly once.
- confirm_execution=False returns a plan dict with zero CRUD writes.
"""
from __future__ import annotations

import pytest

from parrot_tools.navigator.toolkit import NavigatorToolkit


_STUB_WIDGET_ID = "00000000-0000-0000-0000-000000000020"
_STUB_DASHBOARD_ID = "00000000-0000-0000-0000-000000000010"


class TestCreateWidgetUpdatesParentDashboardAttributes:
    """update_row on navigator.dashboards must be called with merged widget_location."""

    @pytest.mark.asyncio
    async def test_create_widget_updates_parent_dashboard_attributes(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """Verifies update_row("navigator.dashboards") is called with merged
        widget_location inside the same transaction as the widget insert."""
        tx_conn = mocker.AsyncMock()
        conn_values: list = []

        class _TrackingTx:
            async def __aenter__(self_inner):
                return tx_conn

            async def __aexit__(self_inner, *args):
                return False

        tk = navigator_toolkit_factory()
        tk.transaction = mocker.MagicMock(return_value=_TrackingTx())

        # select_rows: dashboard exists (for program_id deduction) + dashboard attributes read
        tk.select_rows = mocker.AsyncMock(side_effect=[
            [{"program_id": 1}],          # deduce program_id from dashboard
            [{"attributes": {"existing_key": "existing_val"}}],  # dashboard attrs for merge
        ])

        async def capture_insert(table, data, returning=None, conn=None):
            conn_values.append(("insert", table, conn))
            return {"widget_id": _STUB_WIDGET_ID, "widget_type": "api-echarts"}

        async def capture_update(table, data, where=None, returning=None, conn=None):
            conn_values.append(("update", table, conn))

        tk.insert_row = capture_insert
        tk.update_row = capture_update

        result = await tk.create_widget(
            dashboard_id=_STUB_DASHBOARD_ID,
            widget_name="Test Widget",
            title="Test Title",
            grid_position={"x": 0, "y": 0, "w": 6, "h": 4},
            confirm_execution=True,
        )

        assert result["status"] == "success"
        assert result["result"]["widget_id"] == str(_STUB_WIDGET_ID)

        # insert on navigator.widgets must have used conn=tx_conn
        insert_ops = [(op, tbl, conn) for op, tbl, conn in conn_values if op == "insert"]
        assert len(insert_ops) == 1
        assert insert_ops[0][1] == "navigator.widgets"
        assert insert_ops[0][2] is tx_conn

        # update on navigator.dashboards must have used conn=tx_conn
        update_ops = [(op, tbl, conn) for op, tbl, conn in conn_values if op == "update"]
        assert len(update_ops) == 1
        assert update_ops[0][1] == "navigator.dashboards"
        assert update_ops[0][2] is tx_conn

        # transaction was entered exactly once
        assert tk.transaction.call_count == 1

    @pytest.mark.asyncio
    async def test_create_widget_merges_widget_location_deep(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """widget_location in attributes must be deep-merged (not replaced)."""
        tx_conn = mocker.AsyncMock()
        captured_update_data: dict = {}

        class _TrackingTx:
            async def __aenter__(self_inner):
                return tx_conn

            async def __aexit__(self_inner, *args):
                return False

        tk = navigator_toolkit_factory()
        tk.transaction = mocker.MagicMock(return_value=_TrackingTx())

        tk.select_rows = mocker.AsyncMock(side_effect=[
            [{"program_id": 1}],  # program_id deduction
            [{"attributes": {
                "cols": "12",
                "widget_location": {"Existing Widget": {"x": 0, "y": 0, "w": 3, "h": 3}},
            }}],
        ])

        async def capture_insert(table, data, returning=None, conn=None):
            return {"widget_id": _STUB_WIDGET_ID, "widget_type": "api-echarts"}

        async def capture_update(table, data, where=None, returning=None, conn=None):
            captured_update_data.update(data)

        tk.insert_row = capture_insert
        tk.update_row = capture_update

        await tk.create_widget(
            dashboard_id=_STUB_DASHBOARD_ID,
            widget_name="New Widget",
            title="New Widget Title",
            grid_position={"x": 3, "y": 0, "w": 3, "h": 3},
            confirm_execution=True,
        )

        attrs = captured_update_data.get("attributes", {})
        wl = attrs.get("widget_location", {})

        # Both old and new widget_location entries must be present
        assert "Existing Widget" in wl, "Existing widget_location entry was lost"
        assert "New Widget Title" in wl, "New widget_location entry was not added"
        assert attrs.get("cols") == "12", "Other attributes must be preserved"

    @pytest.mark.asyncio
    async def test_create_widget_no_grid_position_skips_update_row(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """When grid_position is None, update_row must NOT be called."""
        tx_conn = mocker.AsyncMock()

        class _TrackingTx:
            async def __aenter__(self_inner):
                return tx_conn

            async def __aexit__(self_inner, *args):
                return False

        tk = navigator_toolkit_factory()
        tk.transaction = mocker.MagicMock(return_value=_TrackingTx())
        tk.select_rows = mocker.AsyncMock(return_value=[{"program_id": 1}])
        tk.insert_row = mocker.AsyncMock(
            return_value={"widget_id": _STUB_WIDGET_ID, "widget_type": "api-echarts"}
        )

        result = await tk.create_widget(
            dashboard_id=_STUB_DASHBOARD_ID,
            widget_name="Widget No Grid",
            title="No Grid",
            grid_position=None,
            confirm_execution=True,
        )

        assert result["status"] == "success"
        assert tk.update_row.call_count == 0


class TestCreateWidgetConfirmExecution:
    """confirm_execution=False must return plan dict with zero CRUD writes."""

    @pytest.mark.asyncio
    async def test_create_widget_confirm_execution_false_returns_plan_dict(
        self, navigator_toolkit_factory
    ) -> None:
        tk = navigator_toolkit_factory()
        result = await tk.create_widget(
            dashboard_id=_STUB_DASHBOARD_ID,
            widget_name="Draft Widget",
            title="Draft",
            confirm_execution=False,
        )
        assert result["status"] == "confirm_execution"
        for method in ("insert_row", "upsert_row", "update_row", "delete_row"):
            assert getattr(tk, method).call_count == 0, (
                f"{method} was called unexpectedly with confirm_execution=False"
            )


class TestCreateWidgetInsertRowPayload:
    """insert_row must receive plain Python values — no ::text::jsonb strings."""

    @pytest.mark.asyncio
    async def test_create_widget_no_cast_strings_in_data(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        tx_conn = mocker.AsyncMock()
        captured_data: dict = {}

        class _TrackingTx:
            async def __aenter__(self_inner):
                return tx_conn

            async def __aexit__(self_inner, *args):
                return False

        tk = navigator_toolkit_factory()
        tk.transaction = mocker.MagicMock(return_value=_TrackingTx())
        tk.select_rows = mocker.AsyncMock(return_value=[{"program_id": 1}])

        async def capture_insert(table, data, returning=None, conn=None):
            if table == "navigator.widgets":
                captured_data.update(data)
            return {"widget_id": _STUB_WIDGET_ID, "widget_type": "api-echarts"}

        tk.insert_row = capture_insert

        await tk.create_widget(
            dashboard_id=_STUB_DASHBOARD_ID,
            widget_name="Widget",
            title="Title",
            params={"key": "value"},
            attributes={"icon": "star"},
            conditions={"field": "val"},
            confirm_execution=True,
        )

        # Verify no cast strings in any column value
        for key, val in captured_data.items():
            assert not isinstance(val, str) or "::text::jsonb" not in val, (
                f"Column {key!r} contains a cast string: {val!r}"
            )
            assert not isinstance(val, str) or "::varchar" not in val, (
                f"Column {key!r} contains a ::varchar cast: {val!r}"
            )

        # JSON columns must be plain dicts
        assert isinstance(captured_data["params"], dict)
        assert isinstance(captured_data["attributes"], dict)

    @pytest.mark.asyncio
    async def test_create_widget_returning_widget_id_and_type(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """insert_row must be called with returning=["widget_id", "widget_type"]."""
        tx_conn = mocker.AsyncMock()
        returning_args: list = []

        class _TrackingTx:
            async def __aenter__(self_inner):
                return tx_conn

            async def __aexit__(self_inner, *args):
                return False

        tk = navigator_toolkit_factory()
        tk.transaction = mocker.MagicMock(return_value=_TrackingTx())
        tk.select_rows = mocker.AsyncMock(return_value=[{"program_id": 1}])

        async def capture_insert(table, data, returning=None, conn=None):
            returning_args.append(returning)
            return {"widget_id": _STUB_WIDGET_ID, "widget_type": "api-echarts"}

        tk.insert_row = capture_insert

        await tk.create_widget(
            dashboard_id=_STUB_DASHBOARD_ID,
            widget_name="Widget",
            confirm_execution=True,
        )

        assert len(returning_args) == 1
        assert "widget_id" in returning_args[0]
        assert "widget_type" in returning_args[0]

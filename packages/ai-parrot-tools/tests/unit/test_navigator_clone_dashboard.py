"""Unit tests for migrated clone_dashboard — FEAT-107 TASK-752.

Verifies atomicity: a failure on widget insert rolls back the entire
transaction (dashboard + preceding widgets).
"""
from __future__ import annotations

import pytest

from parrot_tools.navigator.toolkit import NavigatorToolkit


_STUB_SRC_ID = "00000000-0000-0000-0000-000000000001"
_STUB_NEW_ID = "00000000-0000-0000-0000-000000000002"

_SRC_DASH = {
    "description": "Source Desc",
    "module_id": 5,
    "program_id": 1,
    "enabled": True,
    "shared": False,
    "allow_filtering": True,
    "allow_widgets": True,
    "dashboard_type": "3",
    "position": 1,
    "params": {"closable": False},
    "attributes": {"cols": "12"},
    "conditions": None,
    "render_partials": False,
    "save_filtering": True,
}

_SRC_WIDGET_1 = {
    "widget_name": "Widget A",
    "title": "Widget A Title",
    "description": None,
    "url": None,
    "params": {},
    "embed": None,
    "attributes": {},
    "conditions": None,
    "cond_definition": None,
    "where_definition": None,
    "format_definition": None,
    "query_slug": None,
    "save_filtering": False,
    "master_filtering": True,
    "allow_filtering": True,
    "module_id": 5,
    "program_id": 1,
    "widgetcat_id": 3,
    "widget_type_id": "api-echarts",
    "active": True,
    "published": True,
    "template_id": None,
}

_SRC_WIDGET_2 = {**_SRC_WIDGET_1, "widget_name": "Widget B", "title": "Widget B Title"}


class TestCloneDashboardAtomicRollback:
    """A failure on the Nth widget insert must roll back ALL prior writes."""

    @pytest.mark.asyncio
    async def test_clone_dashboard_atomic_rollback(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """Simulated failure on 2nd widget insert causes rollback of dashboard + 1st widget."""
        # Track __aexit__ exc_type to verify rollback trigger
        exit_called_with_exc = []

        class _TrackingTx:
            async def __aenter__(self_inner):
                return mocker.AsyncMock()

            async def __aexit__(self_inner, exc_type, exc_val, exc_tb):
                exit_called_with_exc.append(exc_type)
                return False  # don't suppress

        tk = navigator_toolkit_factory()

        # select_rows: source access check, source dashboard, source widgets
        tk.select_rows = mocker.AsyncMock(side_effect=[
            [{"program_id": 1}],          # write access check
            [_SRC_DASH],                   # source dashboard fetch
            [_SRC_WIDGET_1, _SRC_WIDGET_2],  # source widgets
        ])

        # insert_row raises on 2nd widget (3rd call overall after dashboard)
        insert_calls = {"n": 0}
        original_insert = mocker.AsyncMock(
            return_value={"dashboard_id": _STUB_NEW_ID, "name": "Cloned"}
        )

        async def boom_insert(*args, **kwargs):
            insert_calls["n"] += 1
            if insert_calls["n"] == 2:  # 2nd call = 1st widget
                raise RuntimeError("simulated widget insert failure")
            return original_insert.return_value

        tk.insert_row = boom_insert
        tk.transaction = mocker.MagicMock(return_value=_TrackingTx())

        with pytest.raises(RuntimeError, match="simulated widget insert failure"):
            await tk.clone_dashboard(
                source_dashboard_id=_STUB_SRC_ID,
                new_name="Cloned",
                confirm_execution=True,
            )

        # Transaction __aexit__ must have been called with exc_type != None
        assert len(exit_called_with_exc) == 1
        assert exit_called_with_exc[0] is RuntimeError

    @pytest.mark.asyncio
    async def test_clone_dashboard_confirm_execution_false_returns_plan_dict(
        self, navigator_toolkit_factory
    ) -> None:
        """confirm_execution=False must return plan dict with zero CRUD writes."""
        tk = navigator_toolkit_factory()
        result = await tk.clone_dashboard(
            source_dashboard_id=_STUB_SRC_ID,
            new_name="Cloned",
            confirm_execution=False,
        )
        assert result["status"] == "confirm_execution"
        for method in ("insert_row", "upsert_row", "update_row", "delete_row"):
            assert getattr(tk, method).call_count == 0


class TestCloneDashboardSuccess:
    """clone_dashboard success path: widgets_cloned count and return shape."""

    @pytest.mark.asyncio
    async def test_clone_dashboard_success_widgets_cloned_count(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        tk = navigator_toolkit_factory()

        # select_rows: source access, source dashboard, widgets
        tk.select_rows = mocker.AsyncMock(side_effect=[
            [{"program_id": 1}],
            [_SRC_DASH],
            [_SRC_WIDGET_1, _SRC_WIDGET_2],
        ])

        insert_count = {"n": 0}

        async def track_insert(table, data, returning=None, conn=None):
            insert_count["n"] += 1
            if table == "navigator.dashboards":
                return {"dashboard_id": _STUB_NEW_ID, "name": "Cloned"}
            return {}

        tk.insert_row = track_insert

        result = await tk.clone_dashboard(
            source_dashboard_id=_STUB_SRC_ID,
            new_name="Cloned",
            confirm_execution=True,
        )

        assert result["status"] == "success"
        assert result["result"]["widgets_cloned"] == 2
        assert result["result"]["dashboard_id"] == str(_STUB_NEW_ID)
        # 1 dashboard + 2 widgets = 3 insert calls
        assert insert_count["n"] == 3

    @pytest.mark.asyncio
    async def test_clone_dashboard_uses_transaction(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        tk = navigator_toolkit_factory()

        tk.select_rows = mocker.AsyncMock(side_effect=[
            [{"program_id": 1}],
            [_SRC_DASH],
            [],
        ])
        tk.insert_row = mocker.AsyncMock(
            return_value={"dashboard_id": _STUB_NEW_ID, "name": "Cloned"}
        )

        result = await tk.clone_dashboard(
            source_dashboard_id=_STUB_SRC_ID,
            new_name="Cloned",
            confirm_execution=True,
        )

        assert result["status"] == "success"
        assert tk.transaction.call_count == 1

    @pytest.mark.asyncio
    async def test_clone_dashboard_widget_conn_tx_passed(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """Every insert_row inside the transaction must receive conn=tx."""
        tx_conn = mocker.AsyncMock()
        conn_values = []

        class _TrackingTx:
            async def __aenter__(self_inner):
                return tx_conn

            async def __aexit__(self_inner, *args):
                return False

        tk = navigator_toolkit_factory()
        tk.select_rows = mocker.AsyncMock(side_effect=[
            [{"program_id": 1}],
            [_SRC_DASH],
            [_SRC_WIDGET_1],
        ])
        tk.transaction = mocker.MagicMock(return_value=_TrackingTx())

        async def capture_insert(table, data, returning=None, conn=None):
            conn_values.append(conn)
            if table == "navigator.dashboards":
                return {"dashboard_id": _STUB_NEW_ID, "name": "Cloned"}
            return {}

        tk.insert_row = capture_insert

        await tk.clone_dashboard(
            source_dashboard_id=_STUB_SRC_ID,
            new_name="Cloned",
            confirm_execution=True,
        )

        # All insert calls must have received conn=tx_conn
        assert all(c is tx_conn for c in conn_values), (
            "Not all insert_row calls received conn=tx"
        )

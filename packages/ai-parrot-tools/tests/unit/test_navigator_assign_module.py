"""Unit tests for migrated assign_module_to_client + assign_module_to_group — FEAT-107 TASK-754.

Verifies UPSERT semantics: upsert_row is called with correct conflict_cols and
update_cols. Neither method opens a transaction.  confirm_execution=False guard
must prevent all writes.
"""
from __future__ import annotations

import pytest

from parrot_tools.navigator.toolkit import NavigatorToolkit


class TestAssignModuleToClientUpsertSemantics:
    """assign_module_to_client must call upsert_row with DO UPDATE conflict strategy."""

    @pytest.mark.asyncio
    async def test_assign_module_to_client_upsert_semantics(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """upsert_row called with conflict_cols and update_cols."""
        tk = navigator_toolkit_factory()
        tk.upsert_row = mocker.AsyncMock(return_value={"client_id": 5, "module_id": 10, "active": True})

        result = await tk.assign_module_to_client(
            client_id=5,
            program_id=1,
            module_id=10,
            active=True,
            confirm_execution=True,
        )

        assert result["status"] == "success"

        assert tk.upsert_row.call_count == 1
        args, kwargs = tk.upsert_row.call_args
        table = args[0] if args else kwargs.get("table")
        assert table == "navigator.client_modules"

        data = args[1] if len(args) > 1 else kwargs.get("data", {})
        assert data["client_id"] == 5
        assert data["program_id"] == 1
        assert data["module_id"] == 10
        assert data["active"] is True

        conflict_cols = kwargs.get("conflict_cols", args[2] if len(args) > 2 else None)
        assert set(conflict_cols) == {"client_id", "program_id", "module_id"}

        update_cols = kwargs.get("update_cols", args[3] if len(args) > 3 else None)
        assert update_cols == ["active"]

    @pytest.mark.asyncio
    async def test_assign_module_to_client_no_transaction(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """assign_module_to_client must NOT open a transaction."""
        tk = navigator_toolkit_factory()
        tk.upsert_row = mocker.AsyncMock(return_value={})

        await tk.assign_module_to_client(
            client_id=5,
            program_id=1,
            module_id=10,
            confirm_execution=True,
        )

        assert tk.transaction.call_count == 0

    @pytest.mark.asyncio
    async def test_assign_module_to_client_confirm_execution_false_returns_plan_dict(
        self, navigator_toolkit_factory
    ) -> None:
        """confirm_execution=False must return plan dict with zero CRUD writes."""
        tk = navigator_toolkit_factory()
        result = await tk.assign_module_to_client(
            client_id=5,
            program_id=1,
            module_id=10,
            confirm_execution=False,
        )
        assert result["status"] == "confirm_execution"
        for method in ("insert_row", "upsert_row", "update_row", "delete_row"):
            assert getattr(tk, method).call_count == 0, (
                f"{method} was called unexpectedly with confirm_execution=False"
            )


class TestAssignModuleToGroupUpsertSemantics:
    """assign_module_to_group must call upsert_row with 4-column conflict strategy."""

    @pytest.mark.asyncio
    async def test_assign_module_to_group_upsert_semantics(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """upsert_row called with 4-col conflict_cols and update_cols=["active"]."""
        tk = navigator_toolkit_factory()
        tk.upsert_row = mocker.AsyncMock(return_value={"group_id": 2, "module_id": 10, "active": True})

        result = await tk.assign_module_to_group(
            group_id=2,
            module_id=10,
            program_id=1,
            client_id=3,
            active=True,
            confirm_execution=True,
        )

        assert result["status"] == "success"

        assert tk.upsert_row.call_count == 1
        args, kwargs = tk.upsert_row.call_args
        table = args[0] if args else kwargs.get("table")
        assert table == "navigator.modules_groups"

        data = args[1] if len(args) > 1 else kwargs.get("data", {})
        assert data["group_id"] == 2
        assert data["module_id"] == 10
        assert data["program_id"] == 1
        assert data["client_id"] == 3
        assert data["active"] is True

        conflict_cols = kwargs.get("conflict_cols", args[2] if len(args) > 2 else None)
        assert set(conflict_cols) == {"group_id", "module_id", "client_id", "program_id"}

        update_cols = kwargs.get("update_cols", args[3] if len(args) > 3 else None)
        assert update_cols == ["active"]

    @pytest.mark.asyncio
    async def test_assign_module_to_group_no_transaction(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """assign_module_to_group must NOT open a transaction."""
        tk = navigator_toolkit_factory()
        tk.upsert_row = mocker.AsyncMock(return_value={})

        await tk.assign_module_to_group(
            group_id=2,
            module_id=10,
            program_id=1,
            client_id=3,
            confirm_execution=True,
        )

        assert tk.transaction.call_count == 0

    @pytest.mark.asyncio
    async def test_assign_module_to_group_confirm_execution_false_returns_plan_dict(
        self, navigator_toolkit_factory
    ) -> None:
        """confirm_execution=False must return plan dict with zero CRUD writes."""
        tk = navigator_toolkit_factory()
        result = await tk.assign_module_to_group(
            module_id=10,
            group_id=2,
            client_id=3,
            program_id=1,
            confirm_execution=False,
        )
        assert result["status"] == "confirm_execution"
        for method in ("insert_row", "upsert_row", "update_row", "delete_row"):
            assert getattr(tk, method).call_count == 0, (
                f"{method} was called unexpectedly with confirm_execution=False"
            )

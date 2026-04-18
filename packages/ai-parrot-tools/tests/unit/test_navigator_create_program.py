"""Unit tests for migrated create_program — FEAT-107 TASK-749.

Verifies that create_program uses CRUD primitives (insert_row, upsert_row,
execute_sql) instead of raw _nav_* helpers, and that the transaction boundary
is respected.
"""
from __future__ import annotations

import pytest

from parrot_tools.navigator.toolkit import NavigatorToolkit


_STUB_UUID = "00000000-0000-0000-0000-000000000001"


class TestCreateProgramUsesTransaction:
    """create_program(confirm_execution=True) must open exactly one transaction."""

    @pytest.mark.asyncio
    async def test_create_program_uses_transaction(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        tk = navigator_toolkit_factory()

        # select_rows returns [] so no existing program found
        tk.select_rows = mocker.AsyncMock(return_value=[])
        # insert_row returns the new program row
        tk.insert_row = mocker.AsyncMock(
            return_value={"program_id": 42, "program_slug": "new_prog"}
        )
        # execute_sql used for setval + program_clients + program_groups
        tk.execute_sql = mocker.AsyncMock(return_value={"status": "ok"})

        result = await tk.create_program(
            program_name="New Program",
            program_slug="new_prog",
            confirm_execution=True,
        )

        assert result["status"] == "success"
        assert result["result"]["program_id"] == 42
        # transaction() was entered exactly once
        assert tk.transaction.call_count == 1

    @pytest.mark.asyncio
    async def test_create_program_confirm_execution_false_no_writes(
        self, navigator_toolkit_factory
    ) -> None:
        """confirm_execution=False must return plan dict with zero CRUD writes."""
        tk = navigator_toolkit_factory()
        result = await tk.create_program(
            program_name="Test Program",
            program_slug="test_program",
            confirm_execution=False,
        )
        assert result["status"] == "confirm_execution"
        # No CRUD write methods called
        for method in ("insert_row", "upsert_row", "update_row", "delete_row"):
            assert getattr(tk, method).call_count == 0, (
                f"{method} was called unexpectedly with confirm_execution=False"
            )


class TestCreateProgramInsertRow:
    """insert_row must be called once for auth.programs with correct returning."""

    @pytest.mark.asyncio
    async def test_create_program_calls_insert_row_for_programs(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        tk = navigator_toolkit_factory()
        tk.select_rows = mocker.AsyncMock(return_value=[])
        tk.insert_row = mocker.AsyncMock(
            return_value={"program_id": 99, "program_slug": "slug99"}
        )
        tk.execute_sql = mocker.AsyncMock(return_value={"status": "ok"})

        await tk.create_program(
            program_name="Prog",
            program_slug="slug99",
            confirm_execution=True,
        )

        assert tk.insert_row.call_count == 1
        call_kwargs = tk.insert_row.call_args
        assert call_kwargs[0][0] == "auth.programs" or call_kwargs[1].get("table") == "auth.programs" or call_kwargs[0][0] == "auth.programs"
        # Check returning argument
        args, kwargs = call_kwargs
        returning = kwargs.get("returning") or (args[2] if len(args) > 2 else None)
        assert returning == ["program_id", "program_slug"]


class TestCreateProgramUpsertRowForModulesGroups:
    """upsert_row must be called for navigator.modules_groups with update_cols=["active"]."""

    @pytest.mark.asyncio
    async def test_create_program_calls_upsert_row_for_modules_groups(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        tk = navigator_toolkit_factory()
        # Simulate existing program so we cascade to existing modules
        tk.select_rows = mocker.AsyncMock(side_effect=[
            # First call: existing program lookup
            [{"program_id": 10, "program_slug": "exist_prog"}],
            # Second call: modules for existing program
            [{"module_id": 5}],
        ])
        tk.execute_sql = mocker.AsyncMock(return_value={"status": "ok"})
        tk.upsert_row = mocker.AsyncMock(return_value={"module_id": 5})

        await tk.create_program(
            program_name="Exist Program",
            program_slug="exist_prog",
            client_ids=[1],
            group_ids=[1],
            confirm_execution=True,
        )

        # upsert_row called for navigator.client_modules and navigator.modules_groups
        upsert_calls = tk.upsert_row.call_args_list
        tables_upserted = set()
        for call in upsert_calls:
            args, kwargs = call
            table = args[0] if args else kwargs.get("table")
            tables_upserted.add(table)
        assert "navigator.modules_groups" in tables_upserted
        assert "navigator.client_modules" in tables_upserted

        # Verify update_cols=["active"] for modules_groups
        for call in upsert_calls:
            args, kwargs = call
            table = args[0] if args else kwargs.get("table")
            update_cols = kwargs.get("update_cols") or (args[3] if len(args) > 3 else None)
            if table == "navigator.modules_groups":
                assert update_cols == ["active"]


class TestCreateProgramIdempotent:
    """Calling create_program twice with same slug returns already_existed=True."""

    @pytest.mark.asyncio
    async def test_create_program_idempotent_returns_existing_id(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        tk = navigator_toolkit_factory()
        # Existing program found
        tk.select_rows = mocker.AsyncMock(side_effect=[
            [{"program_id": 7, "program_slug": "existing"}],
            [],  # No modules
        ])
        tk.execute_sql = mocker.AsyncMock(return_value={"status": "ok"})
        tk.upsert_row = mocker.AsyncMock(return_value={})

        result = await tk.create_program(
            program_name="Existing Program",
            program_slug="existing",
            confirm_execution=True,
        )

        assert result["status"] == "success"
        assert result["result"]["program_id"] == 7
        assert result["result"]["already_existed"] is True
        # insert_row must NOT be called (program already exists)
        assert tk.insert_row.call_count == 0


class TestCreateProgramGprogramIdFallsBackToExecuteSql:
    """auth.program_groups INSERT with gprogram_id subquery must use execute_sql."""

    @pytest.mark.asyncio
    async def test_create_program_gprogram_id_falls_back_to_execute_sql(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        tk = navigator_toolkit_factory()
        tk.select_rows = mocker.AsyncMock(return_value=[])
        tk.insert_row = mocker.AsyncMock(
            return_value={"program_id": 20, "program_slug": "prog20"}
        )
        tk.execute_sql = mocker.AsyncMock(return_value={"status": "ok"})

        await tk.create_program(
            program_name="Prog20",
            program_slug="prog20",
            group_ids=[1],
            confirm_execution=True,
        )

        # At least one execute_sql call must target auth.program_groups
        sql_calls = tk.execute_sql.call_args_list
        pg_sql_calls = [
            c for c in sql_calls
            if "auth.program_groups" in (c[0][0] if c[0] else "")
        ]
        assert len(pg_sql_calls) >= 1, (
            "auth.program_groups INSERT must stay on execute_sql due to gprogram_id subquery"
        )

    @pytest.mark.asyncio
    async def test_create_program_no_nav_execute_calls(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """create_program must not call _nav_execute after migration."""
        tk = navigator_toolkit_factory()
        tk.select_rows = mocker.AsyncMock(return_value=[])
        tk.insert_row = mocker.AsyncMock(
            return_value={"program_id": 30, "program_slug": "prog30"}
        )
        tk.execute_sql = mocker.AsyncMock(return_value={"status": "ok"})
        nav_execute_mock = mocker.AsyncMock(return_value={"status": "ok"})
        tk._nav_execute = nav_execute_mock

        await tk.create_program(
            program_name="Prog30",
            program_slug="prog30",
            confirm_execution=True,
        )

        assert nav_execute_mock.call_count == 0, (
            "_nav_execute must not be called in migrated create_program"
        )

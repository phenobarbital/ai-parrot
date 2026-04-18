"""Unit tests for migrated create_module — FEAT-107 TASK-750.

Verifies that create_module uses CRUD primitives (insert_row, upsert_row,
execute_sql) and preserves the Home-module slug convention and
{program_slug}_{slug} prefix rule.
"""
from __future__ import annotations

import pytest

from parrot_tools.navigator.toolkit import NavigatorToolkit


class TestCreateModuleUsesTransaction:
    """create_module(confirm_execution=True) must open exactly one transaction."""

    @pytest.mark.asyncio
    async def test_create_module_uses_transaction(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        tk = navigator_toolkit_factory()

        # select_rows calls in order:
        # 1. program lookup (auth.programs WHERE program_id=1)
        # 2. _resolve_client_ids → auth.program_clients (returns [] → default_client_id)
        # 3. idempotency check (navigator.modules)
        tk.select_rows = mocker.AsyncMock(side_effect=[
            [{"program_slug": "test_prog"}],  # program lookup
            [],                               # auth.program_clients → falls back to default_client_id
            [],                               # idempotency check (no existing module)
        ])
        tk.insert_row = mocker.AsyncMock(
            return_value={"module_id": 10, "module_slug": "test_prog_home"}
        )
        tk.execute_sql = mocker.AsyncMock(return_value={"status": "ok"})
        tk.upsert_row = mocker.AsyncMock(return_value={})

        result = await tk.create_module(
            module_name="Home",
            module_slug="home",
            program_id=1,
            confirm_execution=True,
        )

        assert result["status"] == "success"
        assert result["result"]["module_id"] == 10
        assert tk.transaction.call_count == 1

    @pytest.mark.asyncio
    async def test_create_module_confirm_execution_false_no_writes(
        self, navigator_toolkit_factory
    ) -> None:
        """confirm_execution=False must return plan dict with zero CRUD writes."""
        tk = navigator_toolkit_factory()
        result = await tk.create_module(
            module_name="Test Module",
            module_slug="test_module",
            program_id=1,
            confirm_execution=False,
        )
        assert result["status"] == "confirm_execution"
        for method in ("insert_row", "upsert_row", "update_row", "delete_row"):
            assert getattr(tk, method).call_count == 0, (
                f"{method} was called unexpectedly with confirm_execution=False"
            )


class TestCreateModuleHomeSlugConvention:
    """Home-module slug convention must be preserved."""

    @pytest.mark.asyncio
    async def test_create_module_home_slug_convention_preserved(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """Home module: slug and classname should equal program_slug."""
        tk = navigator_toolkit_factory()

        tk.select_rows = mocker.AsyncMock(side_effect=[
            [{"program_slug": "myprogram"}],  # program lookup
            [],                               # auth.program_clients → default_client_id
            [],                               # idempotency check
        ])
        captured_data = {}

        async def capture_insert(table, data, returning=None, conn=None):
            if table == "navigator.modules":
                captured_data.update(data)
            return {"module_id": 5, "module_slug": data.get("module_slug", "myprogram")}

        tk.insert_row = capture_insert
        tk.execute_sql = mocker.AsyncMock(return_value={"status": "ok"})
        tk.upsert_row = mocker.AsyncMock(return_value={})

        result = await tk.create_module(
            module_name="Home",
            module_slug="home",
            program_id=1,
            confirm_execution=True,
        )

        assert result["status"] == "success"
        # Home module: slug must equal program_slug
        assert captured_data["module_slug"] == "myprogram"
        assert captured_data["module_name"] == "myprogram"
        assert captured_data["classname"] == "myprogram"


class TestCreateModulePrefixRule:
    """Non-home modules must get {program_slug}_{slug} prefix."""

    @pytest.mark.asyncio
    async def test_create_module_prefix_rule_preserved(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """Non-Home module: slug should be prefixed with program_slug."""
        tk = navigator_toolkit_factory()

        tk.select_rows = mocker.AsyncMock(side_effect=[
            [{"program_slug": "myprogram"}],  # program lookup
            [],                               # auth.program_clients → default_client_id
            [],                               # idempotency check
        ])
        captured_data = {}

        async def capture_insert(table, data, returning=None, conn=None):
            if table == "navigator.modules":
                captured_data.update(data)
            return {"module_id": 6, "module_slug": data.get("module_slug", "")}

        tk.insert_row = capture_insert
        tk.execute_sql = mocker.AsyncMock(return_value={"status": "ok"})
        tk.upsert_row = mocker.AsyncMock(return_value={})

        result = await tk.create_module(
            module_name="Reports",
            module_slug="reports",
            program_id=1,
            confirm_execution=True,
        )

        assert result["status"] == "success"
        # Non-home: slug must be prefixed with program_slug
        assert captured_data["module_slug"] == "myprogram_reports"
        # description defaults to module_name.title()
        assert captured_data["description"] == "Reports"

    @pytest.mark.asyncio
    async def test_create_module_prefix_not_duplicated(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """If slug already starts with program_slug_, do not add prefix again."""
        tk = navigator_toolkit_factory()

        tk.select_rows = mocker.AsyncMock(side_effect=[
            [{"program_slug": "myprogram"}],  # program lookup
            [],                               # auth.program_clients → default_client_id
            [],                               # idempotency check
        ])
        captured_data = {}

        async def capture_insert(table, data, returning=None, conn=None):
            if table == "navigator.modules":
                captured_data.update(data)
            return {"module_id": 7, "module_slug": data.get("module_slug", "")}

        tk.insert_row = capture_insert
        tk.execute_sql = mocker.AsyncMock(return_value={"status": "ok"})
        tk.upsert_row = mocker.AsyncMock(return_value={})

        result = await tk.create_module(
            module_name="Reports",
            module_slug="myprogram_reports",  # already prefixed
            program_id=1,
            confirm_execution=True,
        )

        assert result["status"] == "success"
        # Prefix must not be doubled
        assert captured_data["module_slug"] == "myprogram_reports"


class TestCreateModuleInsertRow:
    """insert_row must be called once for navigator.modules with correct returning."""

    @pytest.mark.asyncio
    async def test_create_module_calls_insert_row_for_modules(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        tk = navigator_toolkit_factory()
        tk.select_rows = mocker.AsyncMock(side_effect=[
            [{"program_slug": "prog"}],  # program lookup
            [],                          # auth.program_clients → default_client_id
            [],                          # idempotency check
        ])
        tk.insert_row = mocker.AsyncMock(
            return_value={"module_id": 20, "module_slug": "prog_test"}
        )
        tk.execute_sql = mocker.AsyncMock(return_value={"status": "ok"})
        tk.upsert_row = mocker.AsyncMock(return_value={})

        await tk.create_module(
            module_name="Test",
            module_slug="test",
            program_id=1,
            confirm_execution=True,
        )

        assert tk.insert_row.call_count == 1
        args, kwargs = tk.insert_row.call_args
        table = args[0] if args else kwargs.get("table")
        assert table == "navigator.modules"
        returning = kwargs.get("returning")
        assert returning == ["module_id", "module_slug"]

    @pytest.mark.asyncio
    async def test_create_module_no_nav_execute_calls(
        self, navigator_toolkit_factory, mocker
    ) -> None:
        """create_module must not call _nav_execute after migration."""
        tk = navigator_toolkit_factory()
        tk.select_rows = mocker.AsyncMock(side_effect=[
            [{"program_slug": "prog"}],  # program lookup
            [],                          # auth.program_clients → default_client_id
            [],                          # idempotency check
        ])
        tk.insert_row = mocker.AsyncMock(
            return_value={"module_id": 21, "module_slug": "prog_test2"}
        )
        tk.execute_sql = mocker.AsyncMock(return_value={"status": "ok"})
        tk.upsert_row = mocker.AsyncMock(return_value={})
        nav_execute_mock = mocker.AsyncMock(return_value={"status": "ok"})
        tk._nav_execute = nav_execute_mock

        await tk.create_module(
            module_name="Test2",
            module_slug="test2",
            program_id=1,
            confirm_execution=True,
        )

        assert nav_execute_mock.call_count == 0, (
            "_nav_execute must not be called in migrated create_module"
        )

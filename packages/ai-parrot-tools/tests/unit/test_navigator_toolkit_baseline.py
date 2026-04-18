"""Baseline regression tests for NavigatorToolkit — FEAT-107 TASK-748.

These tests form the *safety net* that every subsequent migration task
must keep green.

Snapshot strategy
-----------------
Tool names and first-line descriptions are pinned as constants in this
module (committed alongside the test).  Any migration that inadvertently
renames or rewrites a tool's docstring will fail here before it reaches
review.

confirm_execution=False guard
-----------------------------
Every write tool must return ``{"status": "confirm_execution", …}`` when
called without explicit user approval AND must make zero calls to the
underlying CRUD primitives (insert_row, upsert_row, update_row,
delete_row).
"""
from __future__ import annotations

import pytest

from parrot_tools.navigator.toolkit import NavigatorToolkit

# ---------------------------------------------------------------------------
# Snapshot constants — DO NOT edit without updating the migration
# ---------------------------------------------------------------------------

#: Exact sorted list of tool names exposed by NavigatorToolkit.
#: Pinned before any CRUD migration so changes surface immediately.
EXPECTED_TOOL_NAMES: list[str] = [
    "nav_assign_module_to_client",
    "nav_assign_module_to_group",
    "nav_clone_dashboard",
    "nav_create_dashboard",
    "nav_create_module",
    "nav_create_program",
    "nav_create_widget",
    "nav_find_widget_templates",
    "nav_get_dashboard",
    "nav_get_full_program_structure",
    "nav_get_module",
    "nav_get_program",
    "nav_get_widget",
    "nav_get_widget_schema",
    "nav_list_clients",
    "nav_list_dashboards",
    "nav_list_groups",
    "nav_list_modules",
    "nav_list_programs",
    "nav_list_widget_categories",
    "nav_list_widget_types",
    "nav_list_widgets",
    "nav_search",
    "nav_search_widget_docs",
    "nav_update_dashboard",
    "nav_update_module",
    "nav_update_program",
    "nav_update_widget",
]

#: First-line (LLM-visible) description for each tool.
#: Pinned so that wording changes surface before they reach agents.
EXPECTED_TOOL_DESCRIPTIONS: dict[str, str] = {
    "nav_assign_module_to_client": (
        "Activate a module for a specific client within a program."
    ),
    "nav_assign_module_to_group": (
        "Grant a group access to a module within a specific client context."
    ),
    "nav_clone_dashboard": (
        "Clone a dashboard and all its active widgets to a new dashboard."
    ),
    "nav_create_dashboard": (
        "Create a new Navigator dashboard inside a module."
    ),
    "nav_create_module": (
        "Create a Navigator module with optional menu hierarchy and permissions."
    ),
    "nav_create_program": (
        "Create a new Navigator program with client and group assignments."
    ),
    "nav_create_widget": (
        "Create a widget inside a dashboard."
    ),
    "nav_find_widget_templates": (
        "Find available widget templates for a given widget type."
    ),
    "nav_get_dashboard": (
        "Get a dashboard by UUID or Name. Requires access to the dashboard."
    ),
    "nav_get_full_program_structure": (
        "Get the complete structure of a program: modules, dashboards, and widget count."
    ),
    "nav_get_module": (
        "Get a module by ID or Slug. Requires access to the module."
    ),
    "nav_get_program": (
        "Get a program by ID or slug. Requires access to the program."
    ),
    "nav_get_widget": (
        "Get a widget by UUID or Name. Requires access to the widget."
    ),
    "nav_get_widget_schema": (
        "Get the full JSON configuration schema for a specific widget type."
    ),
    "nav_list_clients": (
        "List Navigator clients (tenants). Returns up to 500 by default."
    ),
    "nav_list_dashboards": (
        "List dashboards the current user has access to."
    ),
    "nav_list_groups": (
        "List auth groups, optionally filtered by client."
    ),
    "nav_list_modules": (
        "List Navigator modules the current user has access to."
    ),
    "nav_list_programs": (
        "List Navigator programs the current user has access to."
    ),
    "nav_list_widget_categories": (
        "List all widget categories (6 categories: generic, walmart, utility, mso, blank, loreal)."
    ),
    "nav_list_widget_types": (
        "List all available widget types in the platform (108 types)."
    ),
    "nav_list_widgets": (
        "List widgets the current user has access to."
    ),
    "nav_search": (
        "Search across Navigator entities by name, slug, or title."
    ),
    "nav_search_widget_docs": (
        "Search the Navigator widget documentation using PageIndex tree-search."
    ),
    "nav_update_dashboard": (
        "Update an existing Navigator dashboard. Requires write access."
    ),
    "nav_update_module": (
        "Update an existing Navigator module. Requires write access."
    ),
    "nav_update_program": (
        "Update an existing Navigator program. Only provided fields are changed."
    ),
    "nav_update_widget": (
        "Update an existing widget. Only provided fields are changed."
    ),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STUB_UUID = "00000000-0000-0000-0000-000000000001"
_STUB_UUID2 = "00000000-0000-0000-0000-000000000002"
_WRITE_CRUD = ("insert_row", "upsert_row", "update_row", "delete_row")


def _assert_no_writes(tk: NavigatorToolkit) -> None:
    """Assert none of the CRUD write methods were called."""
    for method in _WRITE_CRUD:
        mock = getattr(tk, method)
        assert mock.call_count == 0, (
            f"{method} was called {mock.call_count} time(s); "
            "confirm_execution=False must not trigger any write."
        )


# ---------------------------------------------------------------------------
# Tool contract snapshots
# ---------------------------------------------------------------------------


class TestGetToolsSnapshot:
    """Snapshot tests for the LLM-facing tool contract."""

    def test_get_tools_names_unchanged_post_migration(self) -> None:
        """Exactly 28 tools with the expected names must be exposed."""
        tk = NavigatorToolkit(dsn="postgres://stub", user_id=1)
        names = sorted(t.name for t in tk.get_tools())
        assert names == EXPECTED_TOOL_NAMES, (
            f"Tool names changed!\n"
            f"  Added:   {sorted(set(names) - set(EXPECTED_TOOL_NAMES))}\n"
            f"  Removed: {sorted(set(EXPECTED_TOOL_NAMES) - set(names))}"
        )

    def test_get_tools_count_is_28(self) -> None:
        """Exactly 28 tools must be registered."""
        tk = NavigatorToolkit(dsn="postgres://stub", user_id=1)
        assert len(tk.get_tools()) == 28

    def test_get_tools_descriptions_unchanged_post_migration(self) -> None:
        """First-line descriptions must not change during migration."""
        tk = NavigatorToolkit(dsn="postgres://stub", user_id=1)
        tools_by_name = {t.name: t for t in tk.get_tools()}
        for name, expected_desc in EXPECTED_TOOL_DESCRIPTIONS.items():
            actual = (tools_by_name[name].description or "").split("\n")[0].strip()
            assert actual == expected_desc, (
                f"Description for {name!r} changed:\n"
                f"  Expected: {expected_desc!r}\n"
                f"  Actual:   {actual!r}"
            )


# ---------------------------------------------------------------------------
# confirm_execution=False guard — CREATE tools
# ---------------------------------------------------------------------------


class TestConfirmExecutionFalseCreate:
    """Every create_* tool must return a plan dict and make zero CRUD writes."""

    @pytest.mark.asyncio
    async def test_create_program_confirm_execution_false_returns_plan_dict(
        self, navigator_toolkit_factory
    ) -> None:
        tk = navigator_toolkit_factory()
        result = await tk.create_program(
            program_name="Test Program",
            program_slug="test_program",
            confirm_execution=False,
        )
        assert result["status"] == "confirm_execution"
        _assert_no_writes(tk)

    @pytest.mark.asyncio
    async def test_create_module_confirm_execution_false_returns_plan_dict(
        self, navigator_toolkit_factory
    ) -> None:
        tk = navigator_toolkit_factory()
        result = await tk.create_module(
            module_name="Test Module",
            module_slug="test_module",
            program_id=1,
            confirm_execution=False,
        )
        assert result["status"] == "confirm_execution"
        _assert_no_writes(tk)

    @pytest.mark.asyncio
    async def test_create_dashboard_confirm_execution_false_returns_plan_dict(
        self, navigator_toolkit_factory
    ) -> None:
        tk = navigator_toolkit_factory()
        result = await tk.create_dashboard(
            name="Test Dashboard",
            module_id=1,
            program_id=1,
            confirm_execution=False,
        )
        assert result["status"] == "confirm_execution"
        _assert_no_writes(tk)

    @pytest.mark.asyncio
    async def test_create_widget_confirm_execution_false_returns_plan_dict(
        self, navigator_toolkit_factory
    ) -> None:
        tk = navigator_toolkit_factory()
        result = await tk.create_widget(
            program_id=1,
            dashboard_id=_STUB_UUID,
            widget_name="test_widget",
            confirm_execution=False,
        )
        assert result["status"] == "confirm_execution"
        _assert_no_writes(tk)


# ---------------------------------------------------------------------------
# confirm_execution=False guard — CLONE
# ---------------------------------------------------------------------------


class TestConfirmExecutionFalseClone:
    @pytest.mark.asyncio
    async def test_clone_dashboard_confirm_execution_false_returns_plan_dict(
        self, navigator_toolkit_factory
    ) -> None:
        tk = navigator_toolkit_factory()
        result = await tk.clone_dashboard(
            source_dashboard_id=_STUB_UUID,
            new_name="Cloned Dashboard",
            confirm_execution=False,
        )
        assert result["status"] == "confirm_execution"
        _assert_no_writes(tk)


# ---------------------------------------------------------------------------
# confirm_execution=False guard — UPDATE tools
# ---------------------------------------------------------------------------


class TestConfirmExecutionFalseUpdate:
    """Every update_* tool must return a plan dict and make zero CRUD writes."""

    @pytest.mark.asyncio
    async def test_update_program_confirm_execution_false_returns_plan_dict(
        self, navigator_toolkit_factory
    ) -> None:
        """update_program delegates to _nav_build_update(confirm_execution=False)."""
        tk = navigator_toolkit_factory()
        result = await tk.update_program(program_id=1, program_name="New Name")
        assert result["status"] == "confirm_execution"
        _assert_no_writes(tk)

    @pytest.mark.asyncio
    async def test_update_module_confirm_execution_false_returns_plan_dict(
        self, navigator_toolkit_factory
    ) -> None:
        """update_module delegates to _nav_build_update(confirm_execution=False)."""
        tk = navigator_toolkit_factory()
        result = await tk.update_module(module_id=1, module_name="New Name")
        assert result["status"] == "confirm_execution"
        _assert_no_writes(tk)

    @pytest.mark.asyncio
    async def test_update_dashboard_confirm_execution_false_returns_plan_dict(
        self, navigator_toolkit_factory
    ) -> None:
        tk = navigator_toolkit_factory()
        result = await tk.update_dashboard(
            dashboard_id=_STUB_UUID,
            name="New Name",
            confirm_execution=False,
        )
        assert result["status"] == "confirm_execution"
        _assert_no_writes(tk)

    @pytest.mark.asyncio
    async def test_update_widget_confirm_execution_false_returns_plan_dict(
        self, navigator_toolkit_factory
    ) -> None:
        tk = navigator_toolkit_factory()
        result = await tk.update_widget(
            widget_id=_STUB_UUID,
            title="New Title",
            confirm_execution=False,
        )
        assert result["status"] == "confirm_execution"
        _assert_no_writes(tk)


# ---------------------------------------------------------------------------
# confirm_execution=False guard — ASSIGN tools
# ---------------------------------------------------------------------------


class TestConfirmExecutionFalseAssign:
    """assign_module_to_* tools must return a plan dict and make zero CRUD writes."""

    @pytest.mark.asyncio
    async def test_assign_module_to_client_confirm_execution_false_returns_plan_dict(
        self, navigator_toolkit_factory
    ) -> None:
        tk = navigator_toolkit_factory()
        result = await tk.assign_module_to_client(
            module_id=1,
            client_id=1,
            program_id=1,
            confirm_execution=False,
        )
        assert result["status"] == "confirm_execution"
        _assert_no_writes(tk)

    @pytest.mark.asyncio
    async def test_assign_module_to_group_confirm_execution_false_returns_plan_dict(
        self, navigator_toolkit_factory
    ) -> None:
        tk = navigator_toolkit_factory()
        result = await tk.assign_module_to_group(
            module_id=1,
            group_id=1,
            client_id=1,
            program_id=1,
            confirm_execution=False,
        )
        assert result["status"] == "confirm_execution"
        _assert_no_writes(tk)

"""Regression tests for NavigatorToolkit refactor (TASK-744 / FEAT-106).

Verifies:
- NavigatorToolkit inherits PostgresToolkit
- Constructor accepts dsn=, rejects connection_params=
- Legacy DB helpers (_query, _query_one, _exec, _get_db, _connection, _build_update) removed
- tool_prefix = 'nav'
- All expected nav_* tool names are exposed

Uses conftest_db.py to load the worktree's source.
"""
from __future__ import annotations

import os
import sys

# Load worktree source first
sys.path.insert(0, os.path.dirname(__file__))
from conftest_db import setup_worktree_imports  # noqa: E402
setup_worktree_imports()

# Also insert ai-parrot-tools worktree source
_WT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
_TOOLS_SRC = os.path.join(_WT_ROOT, "packages", "ai-parrot-tools", "src")
if _TOOLS_SRC not in sys.path:
    sys.path.insert(0, _TOOLS_SRC)

import pytest  # noqa: E402

from parrot.bots.database.toolkits.postgres import PostgresToolkit  # noqa: E402
from parrot_tools.navigator.toolkit import NavigatorToolkit  # noqa: E402


# ---------------------------------------------------------------------------
# Inheritance + constructor
# ---------------------------------------------------------------------------

class TestNavigatorToolkitRefactor:
    def test_inherits_postgres_toolkit(self):
        """NavigatorToolkit must subclass PostgresToolkit after TASK-744."""
        assert issubclass(NavigatorToolkit, PostgresToolkit)

    def test_init_accepts_dsn_only(self):
        """Constructor with dsn= must succeed."""
        tk = NavigatorToolkit(dsn="postgres://user:pw@localhost:5432/db")
        assert tk is not None

    def test_init_rejects_connection_params(self):
        """Passing connection_params= must raise TypeError with migration msg."""
        with pytest.raises(TypeError, match="connection_params"):
            NavigatorToolkit(connection_params={"host": "localhost"})

    def test_read_only_is_false(self):
        """NavigatorToolkit must always be read_only=False."""
        tk = NavigatorToolkit(dsn="postgres://u:p@h/d")
        assert tk.read_only is False

    def test_tool_prefix_nav(self):
        """tool_prefix must be 'nav'."""
        tk = NavigatorToolkit(dsn="postgres://u:p@h/d")
        assert tk.tool_prefix == "nav"

    # -----------------------------------------------------------------------
    # Legacy helpers removed
    # -----------------------------------------------------------------------

    def test_no_legacy_helpers(self):
        """All removed helper methods must be absent from the instance.

        Note: _connection is a *state attribute* set by DatabaseToolkit.__init__
        (the asyncdb connection object). It should NOT be checked here —
        only the old _connection() context-manager *method* from NavigatorToolkit
        was removed, and that was not a bound method (it shadowed the attribute).
        """
        tk = NavigatorToolkit(dsn="postgres://u:p@h/d")
        for attr in ("_query", "_query_one", "_exec", "_get_db", "_build_update"):
            assert not hasattr(tk, attr), f"{attr!r} should have been removed"
        # _connection as a callable method (the old CM) must not exist
        assert not callable(getattr(tk, "_connection", None)), \
            "_connection should not be a callable method"

    def test_no_connection_params_attribute(self):
        """connection_params attribute must not exist."""
        tk = NavigatorToolkit(dsn="postgres://u:p@h/d")
        assert not hasattr(tk, "connection_params")

    def test_no_db_attribute(self):
        """_db and _db_lock attributes must not exist."""
        tk = NavigatorToolkit(dsn="postgres://u:p@h/d")
        assert not hasattr(tk, "_db")
        assert not hasattr(tk, "_db_lock")

    def test_no_asyncpool_import(self):
        """asyncdb.AsyncPool must not be imported in toolkit module."""
        import parrot_tools.navigator.toolkit as mod
        assert not hasattr(mod, "AsyncPool"), "AsyncPool import should have been removed"

    # -----------------------------------------------------------------------
    # Tool names
    # -----------------------------------------------------------------------

    def test_tool_names_frozen(self):
        """All expected nav_* tool names must be present."""
        tk = NavigatorToolkit(dsn="postgres://u:p@h/d")
        names = {t.name for t in tk.get_tools()}
        expected = {
            "nav_create_program", "nav_update_program", "nav_get_program",
            "nav_list_programs", "nav_create_module", "nav_update_module",
            "nav_get_module", "nav_list_modules", "nav_create_dashboard",
            "nav_update_dashboard", "nav_get_dashboard", "nav_list_dashboards",
            "nav_clone_dashboard", "nav_create_widget", "nav_update_widget",
            "nav_get_widget", "nav_list_widgets", "nav_assign_module_to_client",
            "nav_assign_module_to_group", "nav_list_widget_types",
            "nav_list_widget_categories", "nav_list_clients", "nav_list_groups",
            "nav_get_widget_schema", "nav_find_widget_templates",
            "nav_search_widget_docs", "nav_get_full_program_structure",
            "nav_search",
        }
        missing = expected - names
        assert not missing, f"Missing tools: {sorted(missing)}"

    def test_no_db_prefix_tools(self):
        """No tool should have the db_ prefix (inherited write tools excluded)."""
        tk = NavigatorToolkit(dsn="postgres://u:p@h/d")
        names = {t.name for t in tk.get_tools()}
        # CRUD tools from parent should be accessible but NOT appearing as db_ prefix
        # because tool_prefix is overridden to "nav"
        # db_insert_row / db_select_rows etc should NOT appear
        db_prefixed = [n for n in names if n.startswith("db_")]
        assert len(db_prefixed) == 0, f"Unexpected db_-prefixed tools: {db_prefixed}"

    # -----------------------------------------------------------------------
    # Navigator-specific state preserved
    # -----------------------------------------------------------------------

    def test_navigator_state_preserved(self):
        """Navigator-specific attributes must be set on init."""
        tk = NavigatorToolkit(
            dsn="postgres://u:p@h/d",
            default_client_id=5,
            user_id=42,
        )
        assert tk.default_client_id == 5
        assert tk.user_id == 42
        assert tk._is_superuser is None
        assert tk._is_builder is False

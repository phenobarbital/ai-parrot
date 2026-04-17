"""Tests for DatabaseQueryToolkit AbstractToolkit contract.

Verifies inheritance, tool count, tool naming, and exclude_tools behaviour.

Part of FEAT-105 — databasetoolkit-clash / TASK-738.
"""
import pytest

from parrot.tools.databasequery import DatabaseQueryToolkit
from parrot.tools.toolkit import AbstractToolkit


class TestAbstractToolkitContract:
    """DatabaseQueryToolkit must satisfy the full AbstractToolkit contract."""

    def test_inherits_abstract_toolkit(self):
        """isinstance check confirms AbstractToolkit inheritance."""
        assert isinstance(DatabaseQueryToolkit(), AbstractToolkit)

    def test_tool_count_is_four(self):
        """get_tools() returns exactly 4 AbstractTool instances."""
        tk = DatabaseQueryToolkit()
        tools = tk.get_tools()
        assert len(tools) == 4, f"Expected 4 tools, got {len(tools)}: {[t.name for t in tools]}"

    def test_tool_names_prefixed_with_dq(self):
        """Tool names are prefixed with 'dq_' (Q2 decision)."""
        tk = DatabaseQueryToolkit()
        names = {t.name for t in tk.get_tools()}
        expected = {
            "dq_get_database_metadata",
            "dq_validate_database_query",
            "dq_execute_database_query",
            "dq_fetch_database_row",
        }
        assert names == expected, f"Unexpected tool names: {names}"

    def test_tool_prefix_attribute(self):
        """tool_prefix class attribute is 'dq'."""
        assert DatabaseQueryToolkit.tool_prefix == "dq"

    def test_exclude_tools_hides_get_source(self):
        """get_source does NOT appear in get_tools() output."""
        tk = DatabaseQueryToolkit()
        names = {t.name for t in tk.get_tools()}
        assert "get_source" not in names
        assert "dq_get_source" not in names

    def test_exclude_tools_hides_cleanup(self):
        """cleanup does NOT appear in get_tools() output."""
        tk = DatabaseQueryToolkit()
        names = {t.name for t in tk.get_tools()}
        assert "cleanup" not in names
        assert "dq_cleanup" not in names

    def test_no_abstract_tool_subclasses_remain(self):
        """toolkit.py no longer contains the old AbstractTool subclasses."""
        import parrot.tools.databasequery.toolkit as m
        removed_classes = [
            "GetDatabaseMetadataTool",
            "ValidateDatabaseQueryTool",
            "ExecuteDatabaseQueryTool",
            "FetchDatabaseRowTool",
            "DatabaseBaseArgs",
            "GetMetadataArgs",
            "ValidateQueryArgs",
            "ExecuteQueryArgs",
            "FetchRowArgs",
        ]
        for cls_name in removed_classes:
            assert not hasattr(m, cls_name), (
                f"Old class {cls_name!r} should have been removed from toolkit.py"
            )

    def test_each_tool_has_docstring_description(self):
        """Every auto-generated tool has a non-empty description (from method docstring)."""
        tk = DatabaseQueryToolkit()
        for tool in tk.get_tools():
            schema = tool.get_schema()
            desc = schema.get("description", "")
            assert desc, f"Tool {tool.name!r} has empty description"

    def test_each_tool_has_driver_parameter(self):
        """Every tool has a 'driver' parameter in its schema."""
        tk = DatabaseQueryToolkit()
        for tool in tk.get_tools():
            schema = tool.get_schema()
            props = schema.get("parameters", {}).get("properties", {})
            assert "driver" in props, f"Tool {tool.name!r} missing 'driver' parameter"

    def test_get_tools_is_idempotent(self):
        """Calling get_tools() multiple times returns the same set."""
        tk = DatabaseQueryToolkit()
        names1 = {t.name for t in tk.get_tools()}
        names2 = {t.name for t in tk.get_tools()}
        assert names1 == names2

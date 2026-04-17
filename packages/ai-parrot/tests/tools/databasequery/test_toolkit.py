"""Tests for DatabaseQueryToolkit (FEAT-105 refactor).

Updated from FEAT-062 DatabaseToolkit tests to reflect the new AbstractToolkit
inheritance and dq_ tool prefix.

Part of FEAT-105 — databasetoolkit-clash / TASK-738.
"""
import pytest
from parrot.tools.databasequery import DatabaseQueryToolkit
from parrot.tools.toolkit import AbstractToolkit


class TestDatabaseQueryToolkit:
    """Tests for DatabaseQueryToolkit class (AbstractToolkit-based)."""

    def test_inherits_abstract_toolkit(self):
        """DatabaseQueryToolkit inherits from AbstractToolkit."""
        assert isinstance(DatabaseQueryToolkit(), AbstractToolkit)

    def test_get_tools_count(self):
        """get_tools() returns exactly 4 tools."""
        tk = DatabaseQueryToolkit()
        tools = tk.get_tools()
        assert len(tools) == 4

    def test_tool_names_prefixed_with_dq(self):
        """Tool names have dq_ prefix (Q2 decision)."""
        tk = DatabaseQueryToolkit()
        names = {t.name for t in tk.get_tools()}
        assert names == {
            "dq_get_database_metadata",
            "dq_validate_database_query",
            "dq_execute_database_query",
            "dq_fetch_database_row",
        }

    def test_get_source_caches(self):
        """Same driver returns the same cached instance."""
        tk = DatabaseQueryToolkit()
        src1 = tk.get_source("pg")
        src2 = tk.get_source("pg")
        assert src1 is src2

    def test_get_source_alias_resolves(self):
        """Alias and canonical name return the same cached instance."""
        tk = DatabaseQueryToolkit()
        src1 = tk.get_source("postgresql")
        src2 = tk.get_source("pg")
        assert src1 is src2

    def test_get_source_different_drivers(self):
        """Different drivers return different instances."""
        tk = DatabaseQueryToolkit()
        pg = tk.get_source("pg")
        mysql = tk.get_source("mysql")
        assert pg is not mysql

    def test_tool_schemas_valid(self):
        """Each tool's get_schema() produces valid JSON schema with name and description."""
        tk = DatabaseQueryToolkit()
        for tool in tk.get_tools():
            schema = tool.get_schema()
            assert "name" in schema, f"Tool {tool.name} schema missing 'name'"
            assert "description" in schema, f"Tool {tool.name} schema missing 'description'"
            assert schema["name"] == tool.name

    def test_tool_schemas_have_driver_parameter(self):
        """Each tool's schema has a 'driver' parameter."""
        tk = DatabaseQueryToolkit()
        for tool in tk.get_tools():
            schema = tool.get_schema()
            params = schema.get("parameters", {})
            props = params.get("properties", {})
            assert "driver" in props, f"Tool {tool.name} missing 'driver' parameter"

    def test_excluded_methods_not_in_tools(self):
        """get_source and cleanup do not appear in get_tools() output."""
        tk = DatabaseQueryToolkit()
        names = {t.name for t in tk.get_tools()}
        assert "get_source" not in names
        assert "dq_get_source" not in names
        assert "cleanup" not in names
        assert "dq_cleanup" not in names

    @pytest.mark.asyncio
    async def test_cleanup_clears_cache(self):
        """cleanup() clears the source cache."""
        tk = DatabaseQueryToolkit()
        _ = tk.get_source("pg")
        assert len(tk._source_cache) > 0
        await tk.cleanup()
        assert len(tk._source_cache) == 0

    def test_get_source_unknown_raises(self):
        """get_source with unknown driver raises an error."""
        tk = DatabaseQueryToolkit()
        with pytest.raises((ValueError, Exception)):
            tk.get_source("unknown_database_xyz")

    def test_all_sources_instantiate(self):
        """All 13 canonical drivers can be accessed via get_source()."""
        tk = DatabaseQueryToolkit()
        drivers = [
            "pg", "mysql", "sqlite", "bigquery", "oracle",
            "clickhouse", "duckdb", "mssql", "mongo", "documentdb",
            "atlas", "influx", "elastic",
        ]
        for driver in drivers:
            src = tk.get_source(driver)
            assert src is not None, f"Failed to get source for '{driver}'"
            assert src.driver == driver, f"Expected driver='{driver}', got '{src.driver}'"

"""Tests for DatabaseToolkit, tools, and argument schemas.

Part of FEAT-062 — DatabaseToolkit / TASK-436.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../packages/ai-parrot/src"))

import pytest
from parrot.tools.database import DatabaseToolkit
from parrot.tools.database.toolkit import (
    DatabaseBaseArgs,
    ExecuteQueryArgs,
    FetchRowArgs,
    GetMetadataArgs,
    ValidateQueryArgs,
)


class TestDatabaseToolkit:
    """Tests for DatabaseToolkit class."""

    def test_get_tools_count(self):
        """get_tools() returns exactly 4 tools."""
        tk = DatabaseToolkit()
        tools = tk.get_tools()
        assert len(tools) == 4

    def test_tool_names(self):
        """Tool names match expected set."""
        tk = DatabaseToolkit()
        names = {t.name for t in tk.get_tools()}
        assert names == {
            "get_database_metadata",
            "validate_database_query",
            "execute_database_query",
            "fetch_database_row",
        }

    def test_get_tool_by_name(self):
        """get_tool_by_name returns correct tool."""
        tk = DatabaseToolkit()
        tool = tk.get_tool_by_name("validate_database_query")
        assert tool is not None
        assert tool.name == "validate_database_query"

    def test_get_tool_by_name_not_found(self):
        """get_tool_by_name returns None for nonexistent tool."""
        tk = DatabaseToolkit()
        assert tk.get_tool_by_name("nonexistent") is None

    def test_get_source_caches(self):
        """Same driver returns the same cached instance."""
        tk = DatabaseToolkit()
        src1 = tk.get_source("pg")
        src2 = tk.get_source("pg")
        assert src1 is src2

    def test_get_source_alias_resolves(self):
        """Alias and canonical name return the same cached instance."""
        tk = DatabaseToolkit()
        src1 = tk.get_source("postgresql")
        src2 = tk.get_source("pg")
        assert src1 is src2

    def test_get_source_different_drivers(self):
        """Different drivers return different instances."""
        tk = DatabaseToolkit()
        pg = tk.get_source("pg")
        mysql = tk.get_source("mysql")
        assert pg is not mysql

    def test_tool_schemas_valid(self):
        """Each tool's get_schema() produces valid JSON schema with name and description."""
        tk = DatabaseToolkit()
        for tool in tk.get_tools():
            schema = tool.get_schema()
            assert "name" in schema, f"Tool {tool.name} schema missing 'name'"
            assert "description" in schema, f"Tool {tool.name} schema missing 'description'"
            assert schema["name"] == tool.name

    def test_tool_schemas_have_parameters(self):
        """Each tool's schema has parameters with driver field."""
        tk = DatabaseToolkit()
        for tool in tk.get_tools():
            schema = tool.get_schema()
            params = schema.get("parameters", {})
            props = params.get("properties", {})
            assert "driver" in props, f"Tool {tool.name} missing 'driver' parameter"

    @pytest.mark.asyncio
    async def test_cleanup(self):
        """cleanup() clears the source cache."""
        tk = DatabaseToolkit()
        _ = tk.get_source("pg")
        assert len(tk._source_cache) > 0
        await tk.cleanup()
        assert len(tk._source_cache) == 0

    def test_get_source_unknown_raises(self):
        """get_source with unknown driver raises ValueError."""
        tk = DatabaseToolkit()
        with pytest.raises(ValueError):
            tk.get_source("unknown_database_xyz")

    def test_all_sources_instantiate(self):
        """All 13 canonical drivers can be accessed via get_source()."""
        tk = DatabaseToolkit()
        drivers = [
            "pg", "mysql", "sqlite", "bigquery", "oracle",
            "clickhouse", "duckdb", "mssql", "mongo", "documentdb",
            "atlas", "influx", "elastic",
        ]
        for driver in drivers:
            src = tk.get_source(driver)
            assert src is not None, f"Failed to get source for '{driver}'"
            assert src.driver == driver, f"Expected driver='{driver}', got '{src.driver}'"


class TestArgSchemas:
    """Tests for tool argument schemas."""

    def test_database_base_args(self):
        """DatabaseBaseArgs requires driver, credentials defaults to None."""
        args = DatabaseBaseArgs(driver="pg")
        assert args.driver == "pg"
        assert args.credentials is None

    def test_database_base_args_with_credentials(self):
        """DatabaseBaseArgs accepts credentials dict."""
        args = DatabaseBaseArgs(driver="pg", credentials={"dsn": "postgres://localhost/db"})
        assert args.credentials == {"dsn": "postgres://localhost/db"}

    def test_get_metadata_args_no_tables(self):
        """GetMetadataArgs tables defaults to None."""
        args = GetMetadataArgs(driver="pg")
        assert args.tables is None

    def test_get_metadata_args_with_tables(self):
        """GetMetadataArgs accepts table list."""
        args = GetMetadataArgs(driver="pg", tables=["users", "orders"])
        assert args.tables == ["users", "orders"]

    def test_validate_query_args(self):
        """ValidateQueryArgs requires query."""
        args = ValidateQueryArgs(driver="pg", query="SELECT 1")
        assert args.query == "SELECT 1"

    def test_execute_query_args_no_params(self):
        """ExecuteQueryArgs params defaults to None."""
        args = ExecuteQueryArgs(driver="pg", query="SELECT 1")
        assert args.params is None

    def test_execute_query_args_with_params(self):
        """ExecuteQueryArgs accepts params dict."""
        args = ExecuteQueryArgs(driver="pg", query="SELECT 1", params={"id": 1})
        assert args.params == {"id": 1}

    def test_fetch_row_args(self):
        """FetchRowArgs requires query."""
        args = FetchRowArgs(driver="pg", query="SELECT 1")
        assert args.query == "SELECT 1"

    def test_fetch_row_args_with_params(self):
        """FetchRowArgs accepts params."""
        args = FetchRowArgs(driver="mongo", query='{"_id": "abc"}', params=None)
        assert args.params is None


class TestCodeReviewFixes:
    """Tests for code-review-driven improvements to DatabaseToolkit."""

    def test_logger_uses_module_name(self):
        """Toolkit logger uses __name__, not a hardcoded string."""
        import parrot.tools.database.toolkit as toolkit_module
        tk = DatabaseToolkit()
        assert tk.logger.name == toolkit_module.__name__

    @pytest.mark.asyncio
    async def test_cleanup_calls_source_close(self):
        """cleanup() calls close() on all cached sources."""
        from unittest.mock import AsyncMock, patch

        tk = DatabaseToolkit()
        src = tk.get_source("pg")

        with patch.object(src, "close", new_callable=AsyncMock) as mock_close:
            await tk.cleanup()

        mock_close.assert_awaited_once()

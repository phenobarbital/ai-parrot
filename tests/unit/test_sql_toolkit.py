"""Unit tests for SQLToolkit."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(__file__))
from conftest_db import setup_worktree_imports  # noqa: E402
setup_worktree_imports()

import pytest  # noqa: E402
from parrot.bots.database.toolkits.sql import SQLToolkit  # noqa: E402
from parrot.bots.database.models import QueryExecutionResponse  # noqa: E402


class TestSQLToolkit:
    def test_tool_methods_exposed(self):
        tk = SQLToolkit(dsn="postgresql://test", backend="asyncdb")
        tool_names = [t.name for t in tk.get_tools()]
        assert "search_schema" in tool_names
        assert "generate_query" in tool_names
        assert "execute_query" in tool_names
        assert "explain_query" in tool_names
        assert "validate_query" in tool_names

    def test_dialect_hooks_not_exposed(self):
        tk = SQLToolkit(dsn="postgresql://test", backend="asyncdb")
        tool_names = [t.name for t in tk.get_tools()]
        # Private methods starting with _ are auto-excluded
        assert "_get_explain_prefix" not in tool_names
        assert "_build_dsn" not in tool_names
        assert "_execute_asyncdb" not in tool_names

    def test_default_explain_prefix(self):
        tk = SQLToolkit(dsn="postgresql://test", backend="asyncdb")
        assert "EXPLAIN" in tk._get_explain_prefix()

    def test_backend_selection(self):
        tk1 = SQLToolkit(dsn="postgresql://test", backend="asyncdb")
        tk2 = SQLToolkit(dsn="postgresql://test", backend="sqlalchemy")
        assert tk1.backend == "asyncdb"
        assert tk2.backend == "sqlalchemy"

    def test_information_schema_query(self):
        tk = SQLToolkit(dsn="postgresql://test")
        sql, params = tk._get_information_schema_query("orders", ["public"])
        assert "information_schema" in sql.lower()
        assert params["term"] == "%orders%"

    def test_columns_query(self):
        tk = SQLToolkit(dsn="postgresql://test")
        sql, params = tk._get_columns_query("public", "orders")
        assert "information_schema.columns" in sql.lower()
        assert params["schema"] == "public"
        assert params["table"] == "orders"

    def test_primary_keys_query(self):
        tk = SQLToolkit(dsn="postgresql://test")
        sql, params = tk._get_primary_keys_query("public", "orders")
        assert "PRIMARY KEY" in sql
        assert params["table"] == "orders"

    def test_sample_data_query(self):
        tk = SQLToolkit(dsn="postgresql://test")
        sql = tk._get_sample_data_query("public", "orders", limit=5)
        assert '"public"."orders"' in sql
        assert "LIMIT 5" in sql


class TestSQLToolkitExecution:
    @pytest.mark.asyncio
    async def test_execute_not_connected(self):
        tk = SQLToolkit(dsn="postgresql://test", backend="asyncdb")
        result = await tk.execute_query("SELECT 1")
        assert not result.success
        assert "Not connected" in result.error_message

    @pytest.mark.asyncio
    async def test_validate_query_basic(self):
        tk = SQLToolkit(dsn="postgresql://test", backend="asyncdb")
        result = await tk.validate_query('SELECT * FROM "public"."orders"')
        assert "referenced_tables" in result
        assert "public.orders" in result["referenced_tables"]

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
        # tool_prefix="db" so all tools get db_ prefix
        tk = SQLToolkit(dsn="postgresql://test")
        tool_names = [t.name for t in tk.get_tools()]
        assert any("search_schema" in n for n in tool_names)
        assert any("generate_query" in n for n in tool_names)
        assert any("execute_query" in n for n in tool_names)
        assert any("explain_query" in n for n in tool_names)
        assert any("validate_query" in n for n in tool_names)

    def test_dialect_hooks_not_exposed(self):
        tk = SQLToolkit(dsn="postgresql://test")
        tool_names = [t.name for t in tk.get_tools()]
        # Private methods starting with _ are auto-excluded
        assert "_get_explain_prefix" not in tool_names
        assert "_build_dsn" not in tool_names
        assert "_execute_asyncdb" not in tool_names

    def test_default_explain_prefix(self):
        tk = SQLToolkit(dsn="postgresql://test")
        assert "EXPLAIN" in tk._get_explain_prefix()

    def test_backend_kwarg_removed(self):
        """backend= kwarg no longer accepted (hard removed in FEAT-118)."""
        with pytest.raises(TypeError):
            SQLToolkit(dsn="postgresql://test", backend="sqlalchemy")

    def test_information_schema_query_dollar_placeholders(self):
        """_get_information_schema_query emits $N placeholders, returns tuple params."""
        tk = SQLToolkit(dsn="postgresql://test")
        sql, params = tk._get_information_schema_query("orders", ["public"])
        assert "information_schema" in sql.lower()
        assert "$1" in sql
        assert ":schemas" not in sql
        assert ":term" not in sql
        assert isinstance(params, tuple)
        assert params[0] == ["public"]
        assert "%orders%" in params[1]

    def test_columns_query_dollar_placeholders(self):
        """_get_columns_query emits $N placeholders, returns tuple params."""
        tk = SQLToolkit(dsn="postgresql://test")
        sql, params = tk._get_columns_query("public", "orders")
        assert "information_schema.columns" in sql.lower()
        assert "$1" in sql and "$2" in sql
        assert ":schema" not in sql
        assert ":table" not in sql
        assert params == ("public", "orders")

    def test_primary_keys_query_dollar_placeholders(self):
        """_get_primary_keys_query emits $N placeholders, returns tuple params."""
        tk = SQLToolkit(dsn="postgresql://test")
        sql, params = tk._get_primary_keys_query("public", "orders")
        assert "PRIMARY KEY" in sql
        assert "$1" in sql and "$2" in sql
        assert ":schema" not in sql
        assert params == ("public", "orders")

    def test_unique_constraints_query_dollar_placeholders(self):
        """_get_unique_constraints_query emits $N placeholders, returns tuple params."""
        tk = SQLToolkit(dsn="postgresql://test")
        sql, params = tk._get_unique_constraints_query("public", "orders")
        assert "UNIQUE" in sql
        assert "$1" in sql and "$2" in sql
        assert params == ("public", "orders")

    def test_sample_data_query(self):
        tk = SQLToolkit(dsn="postgresql://test")
        sql = tk._get_sample_data_query("public", "orders", limit=5)
        assert '"public"."orders"' in sql
        assert "LIMIT 5" in sql


class TestSQLToolkitExecution:
    @pytest.mark.asyncio
    async def test_execute_not_connected(self):
        tk = SQLToolkit(dsn="postgresql://test")
        result = await tk.execute_query("SELECT 1")
        assert not result.success
        assert "Not connected" in result.error_message

    @pytest.mark.asyncio
    async def test_validate_query_basic(self):
        tk = SQLToolkit(dsn="postgresql://test")
        result = await tk.validate_query('SELECT * FROM "public"."orders"')
        assert "referenced_tables" in result
        assert "public.orders" in result["referenced_tables"]

    @pytest.mark.asyncio
    async def test_execute_asyncdb_forwards_tuple_params(self):
        """_execute_asyncdb passes params tuple to conn.fetch(*params)."""
        from unittest.mock import AsyncMock, MagicMock
        from contextlib import asynccontextmanager

        tk = SQLToolkit(dsn="postgresql://test")

        # Stub a raw connection that records fetch calls
        fake_conn = MagicMock()
        fetch_calls = []

        async def fake_fetch(sql, *args):
            fetch_calls.append((sql, args))
            return []

        fake_conn.fetch = fake_fetch

        # Patch _acquire_asyncdb_connection to yield the fake conn
        @asynccontextmanager
        async def fake_acquire():
            yield fake_conn

        tk._connection = MagicMock()  # non-None to pass guard
        tk._acquire_asyncdb_connection = fake_acquire

        data, err = await tk._execute_asyncdb("SELECT $1", params=(42,))

        assert err is None
        assert len(fetch_calls) == 1
        assert fetch_calls[0] == ("SELECT $1", (42,))

    @pytest.mark.asyncio
    async def test_execute_asyncdb_no_params(self):
        """_execute_asyncdb calls conn.fetch(sql) when params is empty."""
        from unittest.mock import MagicMock
        from contextlib import asynccontextmanager

        tk = SQLToolkit(dsn="postgresql://test")

        fake_conn = MagicMock()
        fetch_calls = []

        async def fake_fetch(sql, *args):
            fetch_calls.append((sql, args))
            return []

        fake_conn.fetch = fake_fetch

        @asynccontextmanager
        async def fake_acquire():
            yield fake_conn

        tk._connection = MagicMock()
        tk._acquire_asyncdb_connection = fake_acquire

        data, err = await tk._execute_asyncdb("SELECT 1")

        assert err is None
        assert fetch_calls[0] == ("SELECT 1", ())

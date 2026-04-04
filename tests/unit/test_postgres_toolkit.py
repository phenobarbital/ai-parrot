"""Unit tests for PostgresToolkit."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(__file__))
from conftest_db import setup_worktree_imports  # noqa: E402
setup_worktree_imports()

import pytest  # noqa: E402
from parrot.bots.database.toolkits.postgres import PostgresToolkit  # noqa: E402


class TestPostgresToolkit:
    def test_explain_prefix(self):
        tk = PostgresToolkit(dsn="postgresql://test")
        assert tk._get_explain_prefix() == "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)"

    def test_information_schema_query(self):
        tk = PostgresToolkit(dsn="postgresql://test")
        sql, params = tk._get_information_schema_query("orders", ["public"])
        assert "pg_class" in sql.lower()
        assert "pg_namespace" in sql.lower()
        assert "obj_description" in sql.lower()

    def test_columns_query_has_col_description(self):
        tk = PostgresToolkit(dsn="postgresql://test")
        sql, params = tk._get_columns_query("public", "orders")
        assert "col_description" in sql.lower()

    def test_asyncdb_driver(self):
        tk = PostgresToolkit(dsn="postgresql://test")
        assert tk._get_asyncdb_driver() == "pg"

    def test_sqlalchemy_dsn(self):
        tk = PostgresToolkit(dsn="postgresql://u:p@host/db", backend="sqlalchemy")
        assert tk._build_sqlalchemy_dsn(tk.dsn) == "postgresql+asyncpg://u:p@host/db"

    def test_postgres_dsn(self):
        tk = PostgresToolkit(dsn="postgres://u:p@host/db", backend="sqlalchemy")
        assert tk._build_sqlalchemy_dsn(tk.dsn) == "postgresql+asyncpg://u:p@host/db"

    def test_tool_methods_inherited(self):
        tk = PostgresToolkit(dsn="postgresql://test")
        tool_names = [t.name for t in tk.get_tools()]
        assert "search_schema" in tool_names
        assert "execute_query" in tool_names
        assert "generate_query" in tool_names
        assert "explain_query" in tool_names
        assert "validate_query" in tool_names

    def test_database_type(self):
        tk = PostgresToolkit(dsn="postgresql://test")
        assert tk.database_type == "postgresql"

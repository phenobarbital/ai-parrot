"""Unit tests for DatabaseToolkit base class."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(__file__))
from conftest_db import setup_worktree_imports  # noqa: E402
setup_worktree_imports()

import pytest  # noqa: E402
from parrot.bots.database.toolkits.base import DatabaseToolkit, DatabaseToolkitConfig  # noqa: E402
from parrot.bots.database.models import TableMetadata, QueryExecutionResponse  # noqa: E402


class MockToolkit(DatabaseToolkit):
    """Concrete subclass for testing."""
    async def search_schema(self, search_term, schema_name=None, limit=10):
        """Search database schema for tables matching the term."""
        return []

    async def execute_query(self, query, limit=1000, timeout=30):
        """Execute a database query."""
        return QueryExecutionResponse(
            success=True, row_count=0, execution_time_ms=0.0, schema_used="public",
        )

    async def do_something(self, param: str) -> str:
        """A custom tool method exposed to LLM."""
        return f"done: {param}"


class TestDatabaseToolkitBase:
    def test_tool_generation(self):
        # tool_prefix="db" so all tools are prefixed: db_search_schema etc.
        tk = MockToolkit(dsn="postgresql://test")
        tool_names = [t.name for t in tk.get_tools()]
        assert any("search_schema" in n for n in tool_names)
        assert any("execute_query" in n for n in tool_names)
        assert any("do_something" in n for n in tool_names)

    def test_exclude_tools(self):
        tk = MockToolkit(dsn="postgresql://test")
        tool_names = [t.name for t in tk.get_tools()]
        for name in ("start", "stop", "cleanup", "get_table_metadata", "health_check"):
            assert name not in tool_names
            assert f"db_{name}" not in tool_names

    def test_default_config(self):
        tk = MockToolkit(dsn="postgresql://test")
        assert tk.database_type == "postgresql"
        assert tk.allowed_schemas == ["public"]
        assert tk.primary_schema == "public"
        assert not tk._connected

    def test_asyncdb_driver_mapping(self):
        assert MockToolkit(dsn="x", database_type="postgresql")._get_asyncdb_driver() == "pg"
        assert MockToolkit(dsn="x", database_type="bigquery")._get_asyncdb_driver() == "bigquery"

    def test_backend_kwarg_removed(self):
        """backend= kwarg no longer accepted (hard removed in FEAT-118)."""
        with pytest.raises(TypeError):
            MockToolkit(dsn="postgresql://localhost/test", backend="sqlalchemy")

    def test_config_model(self):
        config = DatabaseToolkitConfig(dsn="postgresql://test", allowed_schemas=["public", "sales"])
        assert config.dsn == "postgresql://test"
        assert "sales" in config.allowed_schemas

    def test_config_model_no_backend_field(self):
        """DatabaseToolkitConfig no longer has a backend field."""
        config = DatabaseToolkitConfig(dsn="postgresql://test")
        assert not hasattr(config, "backend")

    def test_no_sqlalchemy_imports_at_module_level(self):
        """sqlalchemy must not be imported at module level in toolkit modules."""
        import importlib
        import inspect
        for mod_name in [
            "parrot.bots.database.toolkits.base",
            "parrot.bots.database.toolkits.sql",
            "parrot.bots.database.toolkits.postgres",
        ]:
            mod = sys.modules.get(mod_name)
            if mod is None:
                continue
            source = inspect.getsource(mod)
            # Only check top-level imports (before any 'def ' or 'class ')
            top_level = source.split("def ")[0].split("class ")[0]
            assert "from sqlalchemy" not in top_level, (
                f"sqlalchemy found at module level in {mod_name}"
            )
            assert "import sqlalchemy" not in top_level, (
                f"sqlalchemy found at module level in {mod_name}"
            )


class TestDatabaseToolkitLifecycle:
    @pytest.mark.asyncio
    async def test_stop_when_not_connected(self):
        tk = MockToolkit(dsn="postgresql://test")
        await tk.stop()
        assert not tk._connected

    @pytest.mark.asyncio
    async def test_get_table_metadata_no_cache(self):
        tk = MockToolkit(dsn="postgresql://test", cache_partition=None)
        assert await tk.get_table_metadata("public", "orders") is None

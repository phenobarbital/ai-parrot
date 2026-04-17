"""Unit tests for PostgresToolkit — dialect hooks + CRUD tools (TASK-743 / FEAT-106).

Uses conftest_db.py to load the worktree's source so changes under
packages/ai-parrot/src/ are visible rather than the installed package.
"""
from __future__ import annotations

import os
import sys

# Load worktree source first (must precede any parrot imports)
sys.path.insert(0, os.path.dirname(__file__))
from conftest_db import setup_worktree_imports  # noqa: E402
setup_worktree_imports()

import pytest  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from pydantic import ValidationError  # noqa: E402
from parrot.bots.database.toolkits.postgres import PostgresToolkit  # noqa: E402
from parrot.bots.database.models import TableMetadata  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_toolkit(read_only: bool = True, tables=None) -> PostgresToolkit:
    """Construct a PostgresToolkit without triggering real DB connections."""
    return PostgresToolkit(
        dsn="postgres://localhost/test",
        tables=tables or ["test.t"],
        read_only=read_only,
    )


@pytest.fixture
def fake_meta() -> TableMetadata:
    """TableMetadata stub with integer, varchar, and jsonb columns."""
    return TableMetadata(
        schema="test",
        tablename="t",
        table_type="BASE TABLE",
        full_name='"test"."t"',
        columns=[
            {"name": "id",   "type": "integer", "nullable": False, "default": None},
            {"name": "name", "type": "varchar", "nullable": False, "default": None},
            {"name": "data", "type": "jsonb",   "nullable": True,  "default": "'{}'"},
        ],
        primary_keys=["id"],
    )


# ---------------------------------------------------------------------------
# Dialect hooks (pre-existing tests preserved)
# ---------------------------------------------------------------------------

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
        assert "db_search_schema" in tool_names or "search_schema" in tool_names
        assert any("execute_query" in n for n in tool_names)

    def test_database_type(self):
        tk = PostgresToolkit(dsn="postgresql://test")
        assert tk.database_type == "postgresql"


# ---------------------------------------------------------------------------
# read_only gating (TASK-743)
# ---------------------------------------------------------------------------

class TestReadOnlyGating:
    def test_read_only_hides_write_tools(self):
        tk = make_toolkit(read_only=True)
        names = {t.name for t in tk.get_tools()}
        assert "db_select_rows" in names
        for write_tool in ("db_insert_row", "db_upsert_row", "db_update_row", "db_delete_row"):
            assert write_tool not in names, f"{write_tool!r} should be hidden in read_only mode"

    def test_read_only_false_exposes_write_tools(self):
        tk = make_toolkit(read_only=False)
        names = {t.name for t in tk.get_tools()}
        for tool_name in (
            "db_insert_row", "db_upsert_row", "db_update_row",
            "db_delete_row", "db_select_rows",
        ):
            assert tool_name in names, f"{tool_name!r} should be exposed when read_only=False"

    def test_select_rows_always_exposed(self):
        """select_rows must be visible in both read-only and read-write modes."""
        names_ro = {t.name for t in make_toolkit(read_only=True).get_tools()}
        names_rw = {t.name for t in make_toolkit(read_only=False).get_tools()}
        assert "db_select_rows" in names_ro
        assert "db_select_rows" in names_rw

    def test_prepared_cache_initialized(self):
        """Instance cache attrs must exist on construction."""
        tk = make_toolkit()
        assert hasattr(tk, "_prepared_cache") and isinstance(tk._prepared_cache, dict)
        assert hasattr(tk, "_json_cols_cache") and isinstance(tk._json_cols_cache, dict)
        assert hasattr(tk, "_in_transaction") and tk._in_transaction is False


# ---------------------------------------------------------------------------
# Whitelist rejection
# ---------------------------------------------------------------------------

class TestWhitelistRejection:
    @pytest.mark.asyncio
    async def test_insert_row_whitelist_rejects_unknown_table(self):
        tk = make_toolkit(read_only=False, tables=["test.t"])
        with pytest.raises(ValueError, match="public.foo"):
            await tk.insert_row("public.foo", {"id": 1})

    @pytest.mark.asyncio
    async def test_select_rows_whitelist_rejects_unknown_table(self):
        tk = make_toolkit(read_only=True, tables=["test.t"])
        with pytest.raises(ValueError, match="not in the allowed"):
            await tk.select_rows("other.schema")

    @pytest.mark.asyncio
    async def test_whitelist_match_schema_dot_table(self, fake_meta):
        """Whitelisted table should not raise ValueError during resolution."""
        tk = make_toolkit(read_only=False, tables=["test.t"])
        with patch.object(tk, "_resolve_table", return_value=("test", "t", fake_meta)):
            mock_model_cls = MagicMock()
            mock_model_instance = MagicMock()
            mock_model_instance.model_dump.return_value = {}
            mock_model_cls.return_value = mock_model_instance
            with patch.object(tk, "_get_or_build_pydantic_model", return_value=mock_model_cls):
                with patch.object(tk, "_get_or_build_template", return_value=("SELECT 1", [])):
                    with patch.object(tk, "_json_cols_for", return_value=frozenset()):
                        with patch.object(tk, "_execute_crud", new=AsyncMock(return_value={"status": "ok"})):
                            result = await tk.insert_row("test.t", {})
                            assert result == {"status": "ok"}


# ---------------------------------------------------------------------------
# Input validation (pydantic)
# ---------------------------------------------------------------------------

class TestInputValidation:
    @pytest.mark.asyncio
    async def test_insert_row_rejects_unknown_field(self, fake_meta):
        """extra='forbid' should cause ValidationError for unknown keys."""
        tk = make_toolkit(read_only=False)
        with patch.object(tk, "_resolve_table", return_value=("test", "t", fake_meta)):
            with pytest.raises(ValidationError):
                await tk.insert_row("test.t", {"nope_field": 1, "another_unknown": "x"})

    @pytest.mark.asyncio
    async def test_update_row_rejects_unknown_field_in_where(self, fake_meta):
        tk = make_toolkit(read_only=False)
        with patch.object(tk, "_resolve_table", return_value=("test", "t", fake_meta)):
            with pytest.raises(ValidationError):
                await tk.update_row("test.t", data={"name": "x"}, where={"ghost_col": 99})


# ---------------------------------------------------------------------------
# Template caching
# ---------------------------------------------------------------------------

class TestTemplateCaching:
    @pytest.mark.asyncio
    async def test_prepared_cache_populated_after_insert(self, fake_meta):
        """_prepared_cache must have at least one entry after insert_row."""
        tk = make_toolkit(read_only=False)

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"id": 1, "name": "Alice"})

        @asynccontextmanager
        async def fake_acquire():
            yield mock_conn

        with patch.object(tk, "_resolve_table", return_value=("test", "t", fake_meta)):
            with patch.object(tk, "_acquire_asyncdb_connection", side_effect=fake_acquire):
                assert len(tk._prepared_cache) == 0
                await tk.insert_row("test.t", {"name": "Alice"}, returning=["id", "name"])
                assert len(tk._prepared_cache) >= 1


# ---------------------------------------------------------------------------
# upsert_row
# ---------------------------------------------------------------------------

class TestUpsertRow:
    @pytest.mark.asyncio
    async def test_upsert_defaults_conflict_cols_to_pk(self, fake_meta):
        """When conflict_cols=None, meta.primary_keys should be used."""
        tk = make_toolkit(read_only=False)

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"id": 1})

        @asynccontextmanager
        async def fake_acquire():
            yield mock_conn

        with patch.object(tk, "_resolve_table", return_value=("test", "t", fake_meta)):
            with patch.object(tk, "_acquire_asyncdb_connection", side_effect=fake_acquire):
                from parrot.bots.database.toolkits import _crud as crud_module
                with patch.object(crud_module, "_build_upsert_sql", wraps=crud_module._build_upsert_sql) as spy:
                    await tk.upsert_row("test.t", {"id": 1, "name": "X"}, returning=["id"])
                    assert spy.called
                    _, kw = spy.call_args
                    conflict = kw.get("conflict_cols")
                    assert conflict is not None
                    assert "id" in conflict

    @pytest.mark.asyncio
    async def test_upsert_no_pk_raises_value_error(self):
        """If table has no PKs and conflict_cols=None, raise ValueError."""
        meta_no_pk = TableMetadata(
            schema="test", tablename="t", table_type="BASE TABLE",
            full_name='"test"."t"',
            columns=[{"name": "name", "type": "varchar", "nullable": False, "default": None}],
            primary_keys=[],
        )
        tk = make_toolkit(read_only=False)
        with patch.object(tk, "_resolve_table", return_value=("test", "t", meta_no_pk)):
            with pytest.raises(ValueError, match="no conflict_cols"):
                await tk.upsert_row("test.t", {"name": "X"}, conflict_cols=None)


# ---------------------------------------------------------------------------
# update_row / delete_row: PK-in-WHERE enforcement
# ---------------------------------------------------------------------------

class TestPkInWhereEnforcement:
    @pytest.mark.asyncio
    async def test_update_row_passes_require_pk_to_validator(self, fake_meta):
        """update_row must pass require_pk_in_where=True to QueryValidator."""
        tk = make_toolkit(read_only=False)

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"id": 1, "name": "new"})

        @asynccontextmanager
        async def fake_acquire():
            yield mock_conn

        with patch.object(tk, "_resolve_table", return_value=("test", "t", fake_meta)):
            with patch.object(tk, "_acquire_asyncdb_connection", side_effect=fake_acquire):
                from parrot.security import QueryValidator
                with patch.object(QueryValidator, "validate_sql_ast", return_value={"is_safe": True}) as mock_val:
                    await tk.update_row(
                        "test.t",
                        data={"name": "new"},
                        where={"id": 1},
                        returning=["id", "name"],
                    )
                    assert mock_val.called
                    _, kw = mock_val.call_args
                    assert kw.get("require_pk_in_where") is True
                    assert "id" in (kw.get("primary_keys") or [])

    @pytest.mark.asyncio
    async def test_delete_row_rejected_when_validator_fails(self, fake_meta):
        """delete_row should raise RuntimeError if QueryValidator returns is_safe=False."""
        tk = make_toolkit(read_only=False)
        with patch.object(tk, "_resolve_table", return_value=("test", "t", fake_meta)):
            from parrot.security import QueryValidator
            with patch.object(
                QueryValidator, "validate_sql_ast",
                return_value={"is_safe": False, "message": "No PK in WHERE"},
            ):
                with pytest.raises(RuntimeError, match="No PK in WHERE"):
                    await tk.delete_row("test.t", where={"name": "Alice"})


# ---------------------------------------------------------------------------
# transaction()
# ---------------------------------------------------------------------------

class TestTransaction:
    @pytest.mark.asyncio
    async def test_transaction_nested_raises(self):
        """Nested transaction() must raise RuntimeError."""
        tk = make_toolkit(read_only=False)

        mock_conn = AsyncMock()
        mock_tx_cm = MagicMock()
        mock_tx_cm.__aenter__ = AsyncMock(return_value=None)
        mock_tx_cm.__aexit__ = AsyncMock(return_value=False)
        mock_conn.transaction = MagicMock(return_value=mock_tx_cm)

        @asynccontextmanager
        async def fake_acquire():
            yield mock_conn

        with patch.object(tk, "_acquire_asyncdb_connection", side_effect=fake_acquire):
            with pytest.raises(RuntimeError, match="Nested"):
                async with tk.transaction():
                    async with tk.transaction():
                        pass

    @pytest.mark.asyncio
    async def test_transaction_flag_reset_after_success(self):
        """_in_transaction must be False after a successful transaction."""
        tk = make_toolkit(read_only=False)

        mock_conn = AsyncMock()
        mock_tx_cm = MagicMock()
        mock_tx_cm.__aenter__ = AsyncMock(return_value=None)
        mock_tx_cm.__aexit__ = AsyncMock(return_value=False)
        mock_conn.transaction = MagicMock(return_value=mock_tx_cm)

        @asynccontextmanager
        async def fake_acquire():
            yield mock_conn

        with patch.object(tk, "_acquire_asyncdb_connection", side_effect=fake_acquire):
            assert tk._in_transaction is False
            async with tk.transaction() as tx:
                assert tk._in_transaction is True
                assert tx is mock_conn
            assert tk._in_transaction is False

    @pytest.mark.asyncio
    async def test_transaction_flag_reset_after_exception(self):
        """_in_transaction must be False even when the block raises."""
        tk = make_toolkit(read_only=False)

        mock_conn = AsyncMock()
        mock_tx_cm = MagicMock()
        mock_tx_cm.__aenter__ = AsyncMock(return_value=None)
        mock_tx_cm.__aexit__ = AsyncMock(return_value=False)
        mock_conn.transaction = MagicMock(return_value=mock_tx_cm)

        @asynccontextmanager
        async def fake_acquire():
            yield mock_conn

        with patch.object(tk, "_acquire_asyncdb_connection", side_effect=fake_acquire):
            with pytest.raises(ValueError):
                async with tk.transaction():
                    raise ValueError("rollback me")
            assert tk._in_transaction is False


# ---------------------------------------------------------------------------
# reload_metadata()
# ---------------------------------------------------------------------------

class TestReloadMetadata:
    @pytest.mark.asyncio
    async def test_reload_clears_prepared_cache(self, fake_meta):
        """reload_metadata should remove matching entries from _prepared_cache."""
        tk = make_toolkit(read_only=False)
        tk._prepared_cache["insert|test|t|cols=('name',)|ret=()"] = "INSERT INTO ..."
        tk._prepared_cache["select|other|t2|cols=()|where=()"] = "SELECT ..."
        tk._json_cols_cache["test.t"] = frozenset({"data"})
        tk.cache_partition = None

        from parrot.bots.database.toolkits import _crud as crud_module
        crud_module._build_pydantic_model.cache_clear()

        await tk.reload_metadata("test", "t")

        remaining = list(tk._prepared_cache.keys())
        assert all("|test|t|" not in k for k in remaining)
        assert "select|other|t2|cols=()|where=()" in tk._prepared_cache
        assert "test.t" not in tk._json_cols_cache

    @pytest.mark.asyncio
    async def test_reload_calls_pydantic_cache_clear(self):
        tk = make_toolkit(read_only=False)
        tk.cache_partition = None

        from parrot.bots.database.toolkits import _crud as crud_module
        with patch.object(crud_module._build_pydantic_model, "cache_clear") as mock_clear:
            await tk.reload_metadata("test", "t")
            mock_clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_reload_purges_schema_cache(self, fake_meta):
        """reload_metadata should remove the table entry from schema_cache."""
        tk = make_toolkit(read_only=False)

        schema_meta_stub = MagicMock()
        schema_meta_stub.tables = {"t": fake_meta, "other_table": MagicMock()}
        cache_stub = MagicMock()
        cache_stub.schema_cache = {"test": schema_meta_stub}
        cache_stub.hot_cache = {"test.t": fake_meta}
        tk.cache_partition = cache_stub

        await tk.reload_metadata("test", "t")

        assert "t" not in schema_meta_stub.tables
        assert "other_table" in schema_meta_stub.tables
        assert "test.t" not in cache_stub.hot_cache

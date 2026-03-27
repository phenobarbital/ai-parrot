"""Tests for DatabaseToolkit result models and AbstractDatabaseSource.

Part of FEAT-062 — DatabaseToolkit / TASK-436.
"""
import sys
import os

# Ensure the local package takes precedence
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../packages/ai-parrot/src"))

import pytest
from parrot.tools.database.base import (
    AbstractDatabaseSource,
    ColumnMeta,
    MetadataResult,
    QueryResult,
    RowResult,
    TableMeta,
    ValidationResult,
)


class TestValidationResult:
    """Tests for ValidationResult model."""

    def test_validation_result_valid(self):
        """Valid result with dialect serializes correctly."""
        r = ValidationResult(valid=True, dialect="postgres")
        assert r.valid is True
        assert r.error is None
        assert r.dialect == "postgres"

    def test_validation_result_invalid(self):
        """Invalid result with error message."""
        r = ValidationResult(valid=False, error="parse error", dialect="postgres")
        assert r.valid is False
        assert "parse" in r.error
        assert r.dialect == "postgres"

    def test_validation_result_minimal(self):
        """Only valid field is required."""
        r = ValidationResult(valid=True)
        assert r.valid is True
        assert r.error is None
        assert r.dialect is None

    def test_validation_result_serializes(self):
        """model_dump() produces expected structure."""
        r = ValidationResult(valid=False, error="bad query", dialect="mysql")
        d = r.model_dump()
        assert d["valid"] is False
        assert d["error"] == "bad query"
        assert d["dialect"] == "mysql"


class TestColumnMeta:
    """Tests for ColumnMeta model."""

    def test_column_meta_defaults(self):
        """Default nullable=True, primary_key=False, default=None."""
        c = ColumnMeta(name="id", data_type="integer")
        assert c.nullable is True
        assert c.primary_key is False
        assert c.default is None

    def test_column_meta_primary_key(self):
        """Can set primary_key=True."""
        c = ColumnMeta(name="id", data_type="int", primary_key=True)
        assert c.primary_key is True

    def test_column_meta_not_nullable(self):
        """Can set nullable=False."""
        c = ColumnMeta(name="name", data_type="varchar", nullable=False)
        assert c.nullable is False

    def test_column_meta_with_default(self):
        """Can set a default value."""
        c = ColumnMeta(name="created_at", data_type="timestamp", default="NOW()")
        assert c.default == "NOW()"


class TestTableMeta:
    """Tests for TableMeta model."""

    def test_table_meta_minimal(self):
        """Only name is required."""
        t = TableMeta(name="users")
        assert t.name == "users"
        assert t.schema_name is None
        assert t.columns == []
        assert t.row_count is None

    def test_table_meta_with_columns(self):
        """TableMeta with nested ColumnMeta list."""
        t = TableMeta(
            name="users",
            schema_name="public",
            columns=[ColumnMeta(name="id", data_type="int", primary_key=True)],
        )
        assert len(t.columns) == 1
        assert t.columns[0].primary_key is True
        assert t.schema_name == "public"

    def test_table_meta_with_row_count(self):
        """row_count field works."""
        t = TableMeta(name="orders", row_count=1000)
        assert t.row_count == 1000


class TestMetadataResult:
    """Tests for MetadataResult model."""

    def test_metadata_result_fields(self):
        """MetadataResult has correct fields."""
        r = MetadataResult(
            driver="pg",
            tables=[TableMeta(name="users")],
        )
        assert r.driver == "pg"
        assert len(r.tables) == 1
        assert r.raw == {}

    def test_metadata_result_with_raw(self):
        """raw field accepts arbitrary dict."""
        r = MetadataResult(driver="mongo", tables=[], raw={"version": "7.0"})
        assert r.raw["version"] == "7.0"


class TestQueryResult:
    """Tests for QueryResult model."""

    def test_query_result_fields(self):
        """QueryResult has correct field types."""
        r = QueryResult(
            driver="pg",
            rows=[{"id": 1}],
            row_count=1,
            columns=["id"],
            execution_time_ms=12.5,
        )
        assert r.row_count == 1
        assert r.driver == "pg"
        assert r.rows[0]["id"] == 1
        assert r.columns == ["id"]
        assert r.execution_time_ms == 12.5

    def test_query_result_empty(self):
        """Empty result set is valid."""
        r = QueryResult(
            driver="mysql",
            rows=[],
            row_count=0,
            columns=[],
            execution_time_ms=0.5,
        )
        assert r.row_count == 0
        assert r.rows == []


class TestRowResult:
    """Tests for RowResult model."""

    def test_row_result_not_found(self):
        """RowResult with found=False and row=None."""
        r = RowResult(driver="pg", row=None, found=False, execution_time_ms=1.0)
        assert r.found is False
        assert r.row is None

    def test_row_result_found(self):
        """RowResult with found=True and row data."""
        r = RowResult(
            driver="sqlite",
            row={"id": 42, "name": "Alice"},
            found=True,
            execution_time_ms=0.5,
        )
        assert r.found is True
        assert r.row["name"] == "Alice"


class TestAbstractDatabaseSource:
    """Tests for AbstractDatabaseSource ABC."""

    def test_cannot_instantiate(self):
        """AbstractDatabaseSource cannot be instantiated directly (ABC)."""
        with pytest.raises(TypeError):
            AbstractDatabaseSource()

    def test_concrete_subclass_can_be_instantiated(self):
        """Concrete implementation can be instantiated."""

        class ConcreteSource(AbstractDatabaseSource):
            driver = "test"
            sqlglot_dialect = "sqlite"

            async def get_default_credentials(self):
                return {}

            async def get_metadata(self, credentials, tables=None):
                return MetadataResult(driver=self.driver, tables=[])

            async def query(self, credentials, sql, params=None):
                return QueryResult(driver=self.driver, rows=[], row_count=0, columns=[], execution_time_ms=0.0)

            async def query_row(self, credentials, sql, params=None):
                return RowResult(driver=self.driver, row=None, found=False, execution_time_ms=0.0)

        src = ConcreteSource()
        assert src.driver == "test"

    @pytest.mark.asyncio
    async def test_resolve_credentials_explicit(self):
        """resolve_credentials returns explicit creds when provided."""

        class SimpleSource(AbstractDatabaseSource):
            driver = "test"
            sqlglot_dialect = None

            async def get_default_credentials(self):
                return {"host": "default-host"}

            async def get_metadata(self, creds, tables=None):
                pass

            async def query(self, creds, sql, params=None):
                pass

            async def query_row(self, creds, sql, params=None):
                pass

        src = SimpleSource()
        explicit = {"host": "explicit-host", "port": 5432}
        resolved = await src.resolve_credentials(explicit)
        assert resolved == explicit

    @pytest.mark.asyncio
    async def test_resolve_credentials_default(self):
        """resolve_credentials returns defaults when None provided."""

        class SimpleSource(AbstractDatabaseSource):
            driver = "test"
            sqlglot_dialect = None

            async def get_default_credentials(self):
                return {"host": "default-host"}

            async def get_metadata(self, creds, tables=None):
                pass

            async def query(self, creds, sql, params=None):
                pass

            async def query_row(self, creds, sql, params=None):
                pass

        src = SimpleSource()
        resolved = await src.resolve_credentials(None)
        assert resolved == {"host": "default-host"}

    @pytest.mark.asyncio
    async def test_validate_query_with_dialect(self):
        """validate_query uses sqlglot when dialect is set."""

        class SqlSource(AbstractDatabaseSource):
            driver = "test"
            sqlglot_dialect = "sqlite"

            async def get_default_credentials(self):
                return {}

            async def get_metadata(self, creds, tables=None):
                pass

            async def query(self, creds, sql, params=None):
                pass

            async def query_row(self, creds, sql, params=None):
                pass

        src = SqlSource()
        result = await src.validate_query("SELECT 1")
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_query_no_dialect_raises(self):
        """validate_query raises NotImplementedError when dialect is None."""

        class NonSqlSource(AbstractDatabaseSource):
            driver = "test"
            sqlglot_dialect = None

            async def get_default_credentials(self):
                return {}

            async def get_metadata(self, creds, tables=None):
                pass

            async def query(self, creds, sql, params=None):
                pass

            async def query_row(self, creds, sql, params=None):
                pass

        src = NonSqlSource()
        with pytest.raises(NotImplementedError):
            await src.validate_query("SELECT 1")


# ---------------------------------------------------------------------------
# Tests for new foundation helpers (added by code review fixes)
# ---------------------------------------------------------------------------

from parrot.tools.database.base import _validate_sql_identifier, _make_cred_key


class TestValidateSqlIdentifier:
    """Tests for the SQL injection guard helper."""

    def test_simple_name_passes(self):
        assert _validate_sql_identifier("users") == "users"

    def test_schema_qualified_passes(self):
        assert _validate_sql_identifier("public.orders") == "public.orders"

    def test_dollar_sign_passes(self):
        assert _validate_sql_identifier("$temp") == "$temp"

    def test_hash_passes(self):
        assert _validate_sql_identifier("#temp") == "#temp"

    def test_single_quote_rejected(self):
        with pytest.raises(ValueError, match="injection"):
            _validate_sql_identifier("users'; DROP TABLE users; --")

    def test_semicolon_rejected(self):
        with pytest.raises(ValueError):
            _validate_sql_identifier("users; --")

    def test_dash_rejected(self):
        with pytest.raises(ValueError):
            _validate_sql_identifier("my-table")

    def test_space_rejected(self):
        with pytest.raises(ValueError):
            _validate_sql_identifier("my table")

    def test_empty_string_rejected(self):
        with pytest.raises(ValueError):
            _validate_sql_identifier("")


class TestMakeCredKey:
    """Tests for the credential cache key helper."""

    def test_dsn_only(self):
        key = _make_cred_key("postgres://localhost/db", None)
        assert "postgres://localhost/db" in key

    def test_none_none(self):
        key = _make_cred_key(None, None)
        assert key  # not empty

    def test_same_params_same_key(self):
        k1 = _make_cred_key(None, {"host": "localhost", "port": 5432})
        k2 = _make_cred_key(None, {"port": 5432, "host": "localhost"})
        assert k1 == k2  # sort_keys ensures determinism

    def test_different_params_different_key(self):
        k1 = _make_cred_key(None, {"host": "host1"})
        k2 = _make_cred_key(None, {"host": "host2"})
        assert k1 != k2


class TestGetDbAndClose:
    """Tests for AbstractDatabaseSource._get_db() and close()."""

    def _make_source(self) -> AbstractDatabaseSource:
        class SimpleSource(AbstractDatabaseSource):
            driver = "test"
            sqlglot_dialect = "sqlite"

            async def get_default_credentials(self):
                return {}

            async def get_metadata(self, creds, tables=None):
                return MetadataResult(driver=self.driver, tables=[])

            async def query(self, creds, sql, params=None):
                return QueryResult(driver=self.driver, rows=[], row_count=0, columns=[], execution_time_ms=0.0)

            async def query_row(self, creds, sql, params=None):
                return RowResult(driver=self.driver, row=None, found=False, execution_time_ms=0.0)

        return SimpleSource()

    @pytest.mark.asyncio
    async def test_get_db_caches_instance(self):
        """Same credentials return the same AsyncDB instance."""
        from unittest.mock import MagicMock, patch

        src = self._make_source()
        mock_db = MagicMock()

        with patch("asyncdb.AsyncDB", return_value=mock_db) as MockAsyncDB:
            db1 = src._get_db("sqlite", None, {"database": ":memory:"})
            db2 = src._get_db("sqlite", None, {"database": ":memory:"})

        assert db1 is db2
        assert MockAsyncDB.call_count == 1  # Only instantiated once

    @pytest.mark.asyncio
    async def test_different_credentials_different_instances(self):
        """Different credentials return different AsyncDB instances."""
        from unittest.mock import MagicMock, patch

        src = self._make_source()

        with patch("asyncdb.AsyncDB", side_effect=[MagicMock(), MagicMock()]):
            db1 = src._get_db("sqlite", "sqlite:///db1.sqlite", None)
            db2 = src._get_db("sqlite", "sqlite:///db2.sqlite", None)

        assert db1 is not db2

    @pytest.mark.asyncio
    async def test_close_clears_pool(self):
        """close() clears the _db_pool and calls close() on each AsyncDB."""
        from unittest.mock import AsyncMock, MagicMock, patch

        src = self._make_source()
        mock_db = MagicMock()
        mock_db.close = AsyncMock()

        with patch("asyncdb.AsyncDB", return_value=mock_db):
            src._get_db("sqlite", None, None)

        assert len(src._db_pool) == 1
        await src.close()
        assert len(src._db_pool) == 0
        mock_db.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_on_fresh_instance_is_noop(self):
        """close() on a source that never opened a DB is safe."""
        src = self._make_source()
        await src.close()  # should not raise

"""Tests for DatabaseQueryToolkit DDL/DML guard (QueryValidator safety layer).

Verifies that CREATE, DROP, INSERT, UPDATE, DELETE, TRUNCATE, GRANT, EXEC etc.
are rejected BEFORE the underlying source is contacted.

Part of FEAT-105 — databasetoolkit-clash / TASK-738.
"""
import pytest
from unittest.mock import AsyncMock, patch

from parrot.tools.databasequery import DatabaseQueryToolkit, ValidationResult


DDL_QUERIES = [
    "DROP TABLE users",
    "CREATE TABLE t (id int)",
    "TRUNCATE TABLE users",
    "INSERT INTO users VALUES (1)",
    "UPDATE users SET x = 1",
    "DELETE FROM users",
    "GRANT ALL ON users TO x",
    "EXEC sp_foo",
]


@pytest.fixture
def toolkit():
    """Fresh DatabaseQueryToolkit instance (no DB connection needed)."""
    return DatabaseQueryToolkit()


class TestDDLGuard:
    """DDL/DML safety checks across SQL, Flux, and JSON dialects."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_query", DDL_QUERIES)
    async def test_validate_rejects_ddl(self, toolkit, bad_query):
        """validate_database_query returns valid=False for every DDL/DML query."""
        result = await toolkit.validate_database_query(driver="pg", query=bad_query)
        assert result["valid"] is False, (
            f"Expected valid=False for query {bad_query!r}, got {result}"
        )
        assert result.get("error"), "Expected non-empty error message"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_query", DDL_QUERIES)
    async def test_execute_rejects_ddl_before_source(self, toolkit, bad_query):
        """execute_database_query returns valid=False without calling source.query."""
        with patch.object(toolkit, "get_source") as mock_get_source:
            mock_source = AsyncMock()
            mock_get_source.return_value = mock_source
            result = await toolkit.execute_database_query(driver="pg", query=bad_query)
        assert result["valid"] is False
        mock_source.query.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_query", DDL_QUERIES)
    async def test_fetch_row_rejects_ddl_before_source(self, toolkit, bad_query):
        """fetch_database_row returns valid=False without calling source.query_row."""
        with patch.object(toolkit, "get_source") as mock_get_source:
            mock_source = AsyncMock()
            mock_get_source.return_value = mock_source
            result = await toolkit.fetch_database_row(driver="pg", query=bad_query)
        assert result["valid"] is False
        mock_source.query_row.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_passes_select(self, toolkit):
        """SELECT statements pass the safety check."""
        with patch.object(toolkit, "get_source") as mock_get_source:
            mock_source = AsyncMock()
            mock_source.validate_query = AsyncMock(
                return_value=ValidationResult(valid=True, dialect="postgresql")
            )
            mock_get_source.return_value = mock_source
            result = await toolkit.validate_database_query(
                driver="pg", query="SELECT 1"
            )
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_validate_passes_select_with_clause(self, toolkit):
        """WITH (CTE) SELECT statements pass the safety check."""
        with patch.object(toolkit, "get_source") as mock_get_source:
            mock_source = AsyncMock()
            mock_source.validate_query = AsyncMock(
                return_value=ValidationResult(valid=True, dialect="postgresql")
            )
            mock_get_source.return_value = mock_source
            result = await toolkit.validate_database_query(
                driver="pg", query="WITH cte AS (SELECT 1) SELECT * FROM cte"
            )
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_flux_query_allowed(self, toolkit):
        """Valid Flux query (from() source) passes."""
        with patch.object(toolkit, "get_source") as mock_get_source:
            mock_source = AsyncMock()
            mock_source.validate_query = AsyncMock(
                return_value=ValidationResult(valid=True, dialect="flux")
            )
            mock_get_source.return_value = mock_source
            result = await toolkit.validate_database_query(
                driver="influx",
                query='from(bucket: "my-bucket") |> range(start: -1h)',
            )
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_flux_drop_rejected(self, toolkit):
        """Flux drop() function is rejected by the safety check."""
        result = await toolkit.validate_database_query(
            driver="influx",
            query='drop(bucket: "my-bucket")',
        )
        assert result["valid"] is False

    @pytest.mark.asyncio
    async def test_mongo_find_allowed(self, toolkit):
        """MQL find queries are allowed (QueryValidator returns is_safe=True for MQL)."""
        with patch.object(toolkit, "get_source") as mock_get_source:
            mock_source = AsyncMock()
            mock_source.validate_query = AsyncMock(
                return_value=ValidationResult(valid=True, dialect="mql")
            )
            mock_get_source.return_value = mock_source
            result = await toolkit.validate_database_query(
                driver="mongo",
                query='{"status": "active"}',
            )
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_result_has_dialect_field(self, toolkit):
        """DDL rejection result includes the dialect field."""
        result = await toolkit.validate_database_query(
            driver="pg", query="DROP TABLE users"
        )
        assert "dialect" in result
        assert result["dialect"] == "sql"


class TestDriverLanguageMapping:
    """Tests for _DRIVER_TO_QUERY_LANGUAGE mapping."""

    def test_driver_to_query_language_sql_family(self):
        """SQL-family drivers resolve to QueryLanguage.SQL."""
        from parrot.security import QueryLanguage
        from parrot.tools.databasequery.toolkit import (
            _DRIVER_TO_QUERY_LANGUAGE,
            _resolve_query_language,
        )
        sql_drivers = ["pg", "mysql", "bigquery", "sqlite", "oracle",
                       "mssql", "clickhouse", "duckdb"]
        for driver in sql_drivers:
            lang = _resolve_query_language(driver)
            assert lang == QueryLanguage.SQL, f"Expected SQL for '{driver}', got {lang}"

    def test_driver_to_query_language_influx(self):
        """Influx driver resolves to QueryLanguage.FLUX."""
        from parrot.security import QueryLanguage
        from parrot.tools.databasequery.toolkit import _resolve_query_language
        assert _resolve_query_language("influx") == QueryLanguage.FLUX

    def test_driver_to_query_language_mongo_family(self):
        """Mongo-family drivers resolve to QueryLanguage.MQL."""
        from parrot.security import QueryLanguage
        from parrot.tools.databasequery.toolkit import _resolve_query_language
        for driver in ["mongo", "atlas", "documentdb"]:
            lang = _resolve_query_language(driver)
            assert lang == QueryLanguage.MQL, f"Expected MQL for '{driver}'"

    def test_driver_to_query_language_elastic(self):
        """Elastic driver resolves to QueryLanguage.JSON."""
        from parrot.security import QueryLanguage
        from parrot.tools.databasequery.toolkit import _resolve_query_language
        assert _resolve_query_language("elastic") == QueryLanguage.JSON

    def test_alias_resolves_via_normalize(self):
        """Driver alias ('postgres') is normalized before mapping lookup."""
        from parrot.security import QueryLanguage
        from parrot.tools.databasequery.toolkit import _resolve_query_language
        assert _resolve_query_language("postgres") == QueryLanguage.SQL

    def test_unsupported_driver_raises(self):
        """Unknown driver raises ValueError."""
        from parrot.tools.databasequery.toolkit import _resolve_query_language
        with pytest.raises(ValueError, match="Unsupported driver"):
            _resolve_query_language("unknown_driver_xyz")

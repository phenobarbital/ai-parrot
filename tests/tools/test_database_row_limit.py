"""Unit tests for add_row_limit() and AbstractDatabaseSource.test_connection().

Part of FEAT-136 — database-toolkit-parity, TASK-931.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from parrot.tools.databasequery.base import (
    AbstractDatabaseSource,
    QueryResult,
    add_row_limit,
)


# ---------------------------------------------------------------------------
# Tests for add_row_limit()
# ---------------------------------------------------------------------------


class TestAddRowLimit:
    """Tests for the add_row_limit() free function."""

    # -- SQL dialect ----------------------------------------------------------

    def test_sql_adds_limit(self) -> None:
        result = add_row_limit("SELECT * FROM users", 100, "pg")
        assert result == "SELECT * FROM users LIMIT 100"

    def test_sql_no_double_limit(self) -> None:
        result = add_row_limit("SELECT * FROM users LIMIT 50", 100, "pg")
        assert "LIMIT 50" in result
        assert result.count("LIMIT") == 1

    def test_sql_no_double_limit_uppercase(self) -> None:
        result = add_row_limit("SELECT * FROM t LIMIT 10", 500, "mysql")
        assert result.count("LIMIT") == 1

    def test_sql_zero_max_rows_no_change(self) -> None:
        q = "SELECT 1"
        assert add_row_limit(q, 0, "pg") == q

    def test_sql_negative_max_rows_no_change(self) -> None:
        q = "SELECT 1"
        assert add_row_limit(q, -1, "pg") == q

    def test_sql_strips_trailing_semicolon(self) -> None:
        result = add_row_limit("SELECT * FROM t;", 10, "pg")
        assert "LIMIT 10" in result

    def test_sql_strips_trailing_comment(self) -> None:
        result = add_row_limit("SELECT * FROM t -- comment", 5, "pg")
        assert "LIMIT 5" in result

    def test_mysql_alias(self) -> None:
        result = add_row_limit("SELECT 1", 5, "mariadb")
        assert "LIMIT 5" in result

    def test_postgresql_alias(self) -> None:
        result = add_row_limit("SELECT 1", 3, "postgresql")
        assert "LIMIT 3" in result

    def test_sqlite_driver(self) -> None:
        result = add_row_limit("SELECT * FROM t", 20, "sqlite")
        assert "LIMIT 20" in result

    def test_oracle_driver_unchanged(self) -> None:
        # Oracle does not support bare LIMIT — query must be returned unchanged.
        # Use FETCH FIRST N ROWS ONLY (Oracle 12c+) or WHERE ROWNUM <= N directly.
        query = "SELECT * FROM t"
        result = add_row_limit(query, 15, "oracle")
        assert result == query
        assert "LIMIT" not in result

    def test_mssql_driver_unchanged(self) -> None:
        # T-SQL (MSSQL) does not support bare LIMIT — query must be returned unchanged.
        # Use SELECT TOP N or FETCH FIRST N ROWS ONLY directly in the query.
        query = "SELECT * FROM t"
        result = add_row_limit(query, 7, "mssql")
        assert result == query
        assert "LIMIT" not in result

    def test_sqlserver_alias_unchanged(self) -> None:
        # 'sqlserver' is an alias for mssql — same no-limit behaviour.
        query = "SELECT * FROM t"
        result = add_row_limit(query, 10, "sqlserver")
        assert result == query
        assert "LIMIT" not in result

    def test_clickhouse_driver(self) -> None:
        result = add_row_limit("SELECT * FROM t", 50, "clickhouse")
        assert "LIMIT 50" in result

    def test_duckdb_driver(self) -> None:
        result = add_row_limit("SELECT * FROM t", 25, "duckdb")
        assert "LIMIT 25" in result

    def test_bigquery_driver(self) -> None:
        result = add_row_limit("SELECT * FROM t", 100, "bigquery")
        assert "LIMIT 100" in result

    # -- Flux dialect ---------------------------------------------------------

    def test_flux_adds_limit(self) -> None:
        q = 'from(bucket:"test") |> range(start: -1h)'
        result = add_row_limit(q, 10, "influx")
        assert "|> limit(n: 10)" in result

    def test_flux_no_double_limit(self) -> None:
        q = 'from(bucket:"b") |> range(start: -1h) |> limit(n: 5)'
        result = add_row_limit(q, 100, "influx")
        assert result.count("|> limit(") == 1

    def test_influxdb_alias(self) -> None:
        q = 'from(bucket:"b") |> range(start: -1h)'
        result = add_row_limit(q, 3, "influxdb")
        assert "|> limit(n: 3)" in result

    def test_flux_zero_max_rows_no_change(self) -> None:
        q = 'from(bucket:"b")'
        assert add_row_limit(q, 0, "influx") == q

    # -- JSON/Elasticsearch dialect -------------------------------------------

    def test_elastic_adds_size(self) -> None:
        q = json.dumps({"query": {"match_all": {}}})
        result = add_row_limit(q, 50, "elastic")
        parsed = json.loads(result)
        assert parsed["size"] == 50

    def test_elastic_no_override_smaller_size(self) -> None:
        # When existing size < max_rows, keep the existing smaller size
        # (the query already has a tighter constraint than max_rows)
        q = json.dumps({"query": {"match_all": {}}, "size": 10})
        result = add_row_limit(q, 50, "elastic")
        parsed = json.loads(result)
        # size=10 already <= max_rows=50, so keep 10 (already constrained)
        assert parsed["size"] == 10

    def test_elastic_no_override_equal_size(self) -> None:
        q = json.dumps({"size": 50})
        result = add_row_limit(q, 50, "elastic")
        parsed = json.loads(result)
        assert parsed["size"] == 50

    def test_elastic_invalid_json_passthrough(self) -> None:
        q = "not json"
        result = add_row_limit(q, 10, "elastic")
        assert result == q

    def test_elasticsearch_alias(self) -> None:
        q = json.dumps({"query": {}})
        result = add_row_limit(q, 5, "elasticsearch")
        parsed = json.loads(result)
        assert parsed["size"] == 5

    def test_opensearch_alias(self) -> None:
        q = json.dumps({"query": {}})
        result = add_row_limit(q, 8, "opensearch")
        parsed = json.loads(result)
        assert parsed["size"] == 8

    # -- MQL passthrough ------------------------------------------------------

    def test_mql_passthrough(self) -> None:
        q = '{"status": "active"}'
        result = add_row_limit(q, 10, "mongo")
        assert result == q

    def test_atlas_passthrough(self) -> None:
        q = '{"x": 1}'
        result = add_row_limit(q, 20, "atlas")
        assert result == q

    def test_documentdb_passthrough(self) -> None:
        q = '{"y": 2}'
        result = add_row_limit(q, 5, "documentdb")
        assert result == q

    def test_mongodb_alias_passthrough(self) -> None:
        q = '{"z": 3}'
        result = add_row_limit(q, 10, "mongodb")
        assert result == q

    # -- Unknown driver -------------------------------------------------------

    def test_unknown_driver_passthrough(self) -> None:
        q = "some query"
        result = add_row_limit(q, 10, "unknowndb")
        assert result == q


# ---------------------------------------------------------------------------
# Tests for AbstractDatabaseSource.test_connection()
# ---------------------------------------------------------------------------


class _ConcreteSource(AbstractDatabaseSource):
    """Minimal concrete implementation for testing AbstractDatabaseSource."""

    driver = "pg"
    sqlglot_dialect = "postgres"

    async def get_default_credentials(self) -> dict:
        return {}

    async def get_metadata(self, credentials, tables=None):
        raise NotImplementedError

    async def query(self, credentials, sql, params=None) -> QueryResult:
        return QueryResult(
            driver=self.driver,
            rows=[{"col": 1}],
            row_count=1,
            columns=["col"],
            execution_time_ms=1.0,
        )

    async def query_row(self, credentials, sql, params=None):
        raise NotImplementedError


class TestAbstractSourceTestConnection:
    """Tests for the default test_connection() on AbstractDatabaseSource."""

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self) -> None:
        source = _ConcreteSource()
        result = await source.test_connection({})
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_query_exception(self) -> None:
        source = _ConcreteSource()

        async def _bad_query(credentials, sql, params=None):
            raise ConnectionError("cannot connect")

        with patch.object(source, "query", new=_bad_query):
            result = await source.test_connection({"host": "badhost"})
        assert result is False

    @pytest.mark.asyncio
    async def test_never_raises(self) -> None:
        """test_connection must never propagate exceptions."""
        source = _ConcreteSource()

        async def _raises(*args, **kwargs):
            raise RuntimeError("unexpected error")

        with patch.object(source, "query", new=_raises):
            result = await source.test_connection({})
        assert isinstance(result, bool)
        assert result is False

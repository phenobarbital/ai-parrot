"""Tests for all database source implementations.

Validates driver attributes, sqlglot dialects, and custom query validation
for all 13 database sources without requiring live database connections.

Part of FEAT-062 — DatabaseToolkit / TASK-436.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../packages/ai-parrot/src"))

import pytest

from parrot.tools.database.sources.postgres import PostgresSource
from parrot.tools.database.sources.mysql import MySQLSource
from parrot.tools.database.sources.sqlite import SQLiteSource
from parrot.tools.database.sources.bigquery import BigQuerySource
from parrot.tools.database.sources.oracle import OracleSource
from parrot.tools.database.sources.clickhouse import ClickHouseSource
from parrot.tools.database.sources.duckdb import DuckDBSource
from parrot.tools.database.sources.mssql import MSSQLSource
from parrot.tools.database.sources.mongodb import MongoSource
from parrot.tools.database.sources.documentdb import DocumentDBSource
from parrot.tools.database.sources.atlas import AtlasSource
from parrot.tools.database.sources.influx import InfluxSource
from parrot.tools.database.sources.elastic import ElasticSource


# ---------------------------------------------------------------------------
# SQL Sources — Core
# ---------------------------------------------------------------------------


class TestPostgresSource:
    """Tests for PostgresSource."""

    def test_driver_and_dialect(self):
        assert PostgresSource().driver == "pg"
        assert PostgresSource().sqlglot_dialect == "postgres"

    @pytest.mark.asyncio
    async def test_validate_valid_sql(self):
        result = await PostgresSource().validate_query("SELECT 1")
        assert result.valid is True
        assert result.dialect == "postgres"

    @pytest.mark.asyncio
    async def test_validate_invalid_sql(self):
        result = await PostgresSource().validate_query("SELEC FROM")
        assert result.valid is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_validate_complex_sql(self):
        sql = "SELECT u.id, u.name, COUNT(o.id) FROM users u LEFT JOIN orders o ON u.id = o.user_id GROUP BY u.id"
        result = await PostgresSource().validate_query(sql)
        assert result.valid is True


class TestMySQLSource:
    """Tests for MySQLSource."""

    def test_driver_and_dialect(self):
        assert MySQLSource().driver == "mysql"
        assert MySQLSource().sqlglot_dialect == "mysql"

    @pytest.mark.asyncio
    async def test_validate_valid_sql(self):
        result = await MySQLSource().validate_query("SELECT 1")
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_invalid_sql(self):
        result = await MySQLSource().validate_query("SELEC FROM")
        assert result.valid is False


class TestSQLiteSource:
    """Tests for SQLiteSource."""

    def test_driver_and_dialect(self):
        assert SQLiteSource().driver == "sqlite"
        assert SQLiteSource().sqlglot_dialect == "sqlite"

    @pytest.mark.asyncio
    async def test_validate_valid_sql(self):
        result = await SQLiteSource().validate_query("SELECT * FROM users WHERE id = 1")
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_invalid_sql(self):
        result = await SQLiteSource().validate_query("SELEC FROM")
        assert result.valid is False


# ---------------------------------------------------------------------------
# SQL Sources — Extended
# ---------------------------------------------------------------------------


class TestBigQuerySource:
    """Tests for BigQuerySource."""

    def test_driver_and_dialect(self):
        assert BigQuerySource().driver == "bigquery"
        assert BigQuerySource().sqlglot_dialect == "bigquery"

    @pytest.mark.asyncio
    async def test_validate_valid_sql(self):
        result = await BigQuerySource().validate_query(
            "SELECT * FROM `project.dataset.table`"
        )
        assert result.valid is True


class TestOracleSource:
    """Tests for OracleSource."""

    def test_driver_and_dialect(self):
        assert OracleSource().driver == "oracle"
        assert OracleSource().sqlglot_dialect == "oracle"

    @pytest.mark.asyncio
    async def test_validate_valid_sql(self):
        result = await OracleSource().validate_query("SELECT 1 FROM DUAL")
        assert result.valid is True


class TestClickHouseSource:
    """Tests for ClickHouseSource."""

    def test_driver_and_dialect(self):
        assert ClickHouseSource().driver == "clickhouse"
        assert ClickHouseSource().sqlglot_dialect == "clickhouse"

    @pytest.mark.asyncio
    async def test_validate_valid_sql(self):
        result = await ClickHouseSource().validate_query(
            "SELECT * FROM system.tables LIMIT 10"
        )
        assert result.valid is True


class TestDuckDBSource:
    """Tests for DuckDBSource."""

    def test_driver_and_dialect(self):
        assert DuckDBSource().driver == "duckdb"
        assert DuckDBSource().sqlglot_dialect == "duckdb"

    @pytest.mark.asyncio
    async def test_validate_valid_sql(self):
        result = await DuckDBSource().validate_query(
            "SELECT * FROM read_parquet('data.parquet')"
        )
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_invalid_sql(self):
        result = await DuckDBSource().validate_query("SELEC FROM")
        assert result.valid is False


# ---------------------------------------------------------------------------
# MSSQL with Stored Procedure Support
# ---------------------------------------------------------------------------


class TestMSSQLSource:
    """Tests for MSSQLSource with stored procedure support."""

    def test_driver_and_dialect(self):
        assert MSSQLSource().driver == "mssql"
        assert MSSQLSource().sqlglot_dialect == "tsql"

    @pytest.mark.asyncio
    async def test_validate_select(self):
        """Standard SELECT validates via tsql dialect."""
        result = await MSSQLSource().validate_query("SELECT TOP 10 * FROM users")
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_exec(self):
        """EXEC statement is valid."""
        result = await MSSQLSource().validate_query("EXEC sp_who")
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_execute_with_params(self):
        """EXECUTE with parameters is valid."""
        result = await MSSQLSource().validate_query(
            "EXECUTE dbo.GetUsers @age = 25, @status = 'active'"
        )
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_invalid_sql(self):
        """Invalid SQL returns valid=False."""
        result = await MSSQLSource().validate_query("SELEC FROM")
        assert result.valid is False

    @pytest.mark.asyncio
    async def test_exec_case_insensitive(self):
        """exec (lowercase) is also accepted."""
        result = await MSSQLSource().validate_query("exec sp_helpdb")
        assert result.valid is True


# ---------------------------------------------------------------------------
# MongoDB Sources
# ---------------------------------------------------------------------------


class TestMongoSource:
    """Tests for MongoSource (base MongoDB source)."""

    def test_driver_and_dialect(self):
        assert MongoSource().driver == "mongo"
        assert MongoSource().sqlglot_dialect is None

    @pytest.mark.asyncio
    async def test_validate_filter(self):
        """JSON filter document validates as valid."""
        result = await MongoSource().validate_query('{"status": "active"}')
        assert result.valid is True
        assert result.dialect == "json"

    @pytest.mark.asyncio
    async def test_validate_pipeline(self):
        """Aggregation pipeline validates as valid."""
        result = await MongoSource().validate_query(
            '[{"$match": {"age": {"$gt": 25}}}]'
        )
        assert result.valid is True
        assert result.dialect == "json-pipeline"

    @pytest.mark.asyncio
    async def test_validate_invalid_json(self):
        """Non-JSON returns valid=False."""
        result = await MongoSource().validate_query("not json at all")
        assert result.valid is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_validate_non_object(self):
        """JSON scalar (non-object) returns valid=False."""
        result = await MongoSource().validate_query('"just a string"')
        assert result.valid is False

    @pytest.mark.asyncio
    async def test_validate_non_dict_pipeline(self):
        """Pipeline with non-dict elements returns valid=False."""
        result = await MongoSource().validate_query("[1, 2, 3]")
        assert result.valid is False


class TestDocumentDBSource:
    """Tests for DocumentDBSource (extends MongoSource)."""

    def test_extends_mongo(self):
        """DocumentDBSource is a subclass of MongoSource."""
        assert issubclass(DocumentDBSource, MongoSource)

    def test_driver(self):
        assert DocumentDBSource().driver == "documentdb"

    def test_dbtype(self):
        assert DocumentDBSource.dbtype == "documentdb"

    @pytest.mark.asyncio
    async def test_validate_inherits_json(self):
        """Inherits JSON validation from MongoSource."""
        result = await DocumentDBSource().validate_query('{"status": "active"}')
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_ssl_defaults(self):
        """Default credentials include ssl=True."""
        src = DocumentDBSource()
        # Mock the interface to avoid config dependency
        from unittest.mock import patch
        with patch("parrot.interfaces.database.get_default_credentials", return_value=None):
            creds = await src.get_default_credentials()
        assert creds.get("ssl") is True


class TestAtlasSource:
    """Tests for AtlasSource (extends MongoSource)."""

    def test_extends_mongo(self):
        """AtlasSource is a subclass of MongoSource."""
        assert issubclass(AtlasSource, MongoSource)

    def test_driver(self):
        assert AtlasSource().driver == "atlas"

    def test_dbtype(self):
        assert AtlasSource.dbtype == "atlas"

    @pytest.mark.asyncio
    async def test_validate_inherits_json(self):
        """Inherits JSON validation from MongoSource."""
        result = await AtlasSource().validate_query('{"status": "active"}')
        assert result.valid is True


# ---------------------------------------------------------------------------
# InfluxDB Source
# ---------------------------------------------------------------------------


class TestInfluxSource:
    """Tests for InfluxSource (Flux query language)."""

    def test_driver_and_dialect(self):
        assert InfluxSource().driver == "influx"
        assert InfluxSource().sqlglot_dialect is None

    @pytest.mark.asyncio
    async def test_validate_valid_flux(self):
        """Valid Flux query with from(bucket:...) passes."""
        result = await InfluxSource().validate_query(
            'from(bucket: "my-bucket") |> range(start: -1h) '
            '|> filter(fn: (r) => r._measurement == "cpu")'
        )
        assert result.valid is True
        assert result.dialect == "flux"

    @pytest.mark.asyncio
    async def test_validate_invalid_flux(self):
        """SQL-like query fails Flux validation."""
        result = await InfluxSource().validate_query("SELECT * FROM cpu")
        assert result.valid is False

    @pytest.mark.asyncio
    async def test_validate_empty(self):
        """Empty string fails."""
        result = await InfluxSource().validate_query("")
        assert result.valid is False

    @pytest.mark.asyncio
    async def test_validate_from_variations(self):
        """from(bucket: with spaces and different formatting passes."""
        result = await InfluxSource().validate_query("from( bucket : \"test\") |> range(start: -5m)")
        assert result.valid is True


# ---------------------------------------------------------------------------
# Elasticsearch Source
# ---------------------------------------------------------------------------


class TestElasticSource:
    """Tests for ElasticSource (JSON DSL)."""

    def test_driver_and_dialect(self):
        assert ElasticSource().driver == "elastic"
        assert ElasticSource().sqlglot_dialect is None

    @pytest.mark.asyncio
    async def test_validate_valid_query(self):
        """JSON DSL with 'query' key validates."""
        result = await ElasticSource().validate_query('{"query": {"match_all": {}}}')
        assert result.valid is True
        assert result.dialect == "json-dsl"

    @pytest.mark.asyncio
    async def test_validate_valid_aggs(self):
        """JSON DSL with 'aggs' key validates."""
        result = await ElasticSource().validate_query(
            '{"aggs": {"avg_price": {"avg": {"field": "price"}}}}'
        )
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_valid_size(self):
        """JSON DSL with 'size' key validates."""
        result = await ElasticSource().validate_query('{"size": 10}')
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_invalid_json(self):
        """Non-JSON returns valid=False."""
        result = await ElasticSource().validate_query("not json")
        assert result.valid is False

    @pytest.mark.asyncio
    async def test_validate_no_valid_keys(self):
        """JSON object without valid ES keys returns valid=False."""
        result = await ElasticSource().validate_query('{"invalid_key": 123}')
        assert result.valid is False

    @pytest.mark.asyncio
    async def test_validate_non_object_json(self):
        """Non-object JSON (list) returns valid=False."""
        result = await ElasticSource().validate_query('[{"query": {}}]')
        assert result.valid is False

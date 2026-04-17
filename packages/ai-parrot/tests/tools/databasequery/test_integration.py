"""Integration tests for DatabaseQueryToolkit with mocked sources.

Tests the three-step agentic flow: metadata → validate → execute.
Rewritten for FEAT-105: uses the async method API instead of the old
AbstractTool._execute interface (which is no longer present in the
AbstractToolkit-based design).

No real database connections are required.

Part of FEAT-105 — databasetoolkit-clash / TASK-738.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.tools.databasequery import DatabaseQueryToolkit
from parrot.tools.databasequery.base import (
    ColumnMeta,
    MetadataResult,
    QueryResult,
    RowResult,
    TableMeta,
    ValidationResult,
)


@pytest.fixture
def toolkit():
    """Fresh DatabaseQueryToolkit instance."""
    return DatabaseQueryToolkit()


@pytest.fixture
def mock_pg_metadata():
    """Canned MetadataResult for PostgreSQL."""
    return MetadataResult(
        driver="pg",
        tables=[
            TableMeta(
                name="users",
                schema_name="public",
                columns=[
                    ColumnMeta(name="id", data_type="integer", primary_key=True, nullable=False),
                    ColumnMeta(name="name", data_type="varchar"),
                    ColumnMeta(name="email", data_type="varchar"),
                ],
            )
        ],
    )


@pytest.fixture
def mock_pg_query_result():
    """Canned QueryResult for PostgreSQL."""
    return QueryResult(
        driver="pg",
        rows=[{"id": 1, "name": "Alice", "email": "alice@example.com"}],
        row_count=1,
        columns=["id", "name", "email"],
        execution_time_ms=5.2,
    )


@pytest.fixture
def mock_pg_row_result():
    """Canned RowResult for PostgreSQL."""
    return RowResult(
        driver="pg",
        row={"id": 1, "name": "Alice", "email": "alice@example.com"},
        found=True,
        execution_time_ms=2.1,
    )


class TestThreeStepFlow:
    """Integration tests for the metadata → validate → execute flow."""

    @pytest.mark.asyncio
    async def test_validate_valid_sql(self, toolkit):
        """Step 2: validate_database_query with valid SQL returns valid=True."""
        with patch.object(toolkit, "get_source") as mock_get_source:
            mock_source = AsyncMock()
            mock_source.validate_query = AsyncMock(
                return_value=ValidationResult(valid=True, dialect="postgres")
            )
            mock_get_source.return_value = mock_source
            result = await toolkit.validate_database_query(
                driver="pg", query="SELECT id, name FROM users WHERE id = 1"
            )
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_validate_invalid_sql_ddl(self, toolkit):
        """Step 2: validate_database_query with DDL returns valid=False (DDL guard)."""
        result = await toolkit.validate_database_query(
            driver="pg", query="DROP TABLE users"
        )
        assert result["valid"] is False
        assert result.get("error") is not None

    @pytest.mark.asyncio
    async def test_validate_invalid_syntax(self, toolkit):
        """Step 2: validate_database_query with bad syntax returns valid=False."""
        with patch.object(toolkit, "get_source") as mock_get_source:
            mock_source = AsyncMock()
            mock_source.validate_query = AsyncMock(
                return_value=ValidationResult(valid=False, error="Parse error", dialect="postgres")
            )
            mock_get_source.return_value = mock_source
            result = await toolkit.validate_database_query(
                driver="pg", query="SELECT WHERE"
            )
        assert result["valid"] is False
        assert result["error"] is not None

    @pytest.mark.asyncio
    async def test_metadata_delegates_to_source(self, toolkit, mock_pg_metadata):
        """Step 1: get_database_metadata calls source.get_metadata."""
        with patch.object(toolkit, "get_source") as mock_get_source:
            mock_source = AsyncMock()
            mock_source.get_metadata = AsyncMock(return_value=mock_pg_metadata)
            mock_source.resolve_credentials = AsyncMock(return_value={"dsn": "postgresql://localhost/db"})
            mock_get_source.return_value = mock_source
            result = await toolkit.get_database_metadata(
                driver="pg",
                credentials={"dsn": "postgresql://localhost/db"},
            )

        assert result["driver"] == "pg"
        assert len(result["tables"]) == 1
        assert result["tables"][0]["name"] == "users"
        mock_source.get_metadata.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_delegates_to_source(self, toolkit, mock_pg_query_result):
        """Step 3: execute_database_query calls source.query."""
        with patch.object(toolkit, "get_source") as mock_get_source:
            mock_source = AsyncMock()
            mock_source.query = AsyncMock(return_value=mock_pg_query_result)
            mock_source.resolve_credentials = AsyncMock(return_value={})
            mock_get_source.return_value = mock_source
            result = await toolkit.execute_database_query(
                driver="pg",
                query="SELECT * FROM users",
            )

        assert result["row_count"] == 1
        assert result["rows"][0]["name"] == "Alice"
        mock_source.query.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetch_row_delegates_to_source(self, toolkit, mock_pg_row_result):
        """Step 3b: fetch_database_row calls source.query_row."""
        with patch.object(toolkit, "get_source") as mock_get_source:
            mock_source = AsyncMock()
            mock_source.query_row = AsyncMock(return_value=mock_pg_row_result)
            mock_source.resolve_credentials = AsyncMock(return_value={})
            mock_get_source.return_value = mock_source
            result = await toolkit.fetch_database_row(
                driver="pg",
                query="SELECT * FROM users WHERE id = 1",
            )

        assert result["found"] is True
        assert result["row"]["name"] == "Alice"
        mock_source.query_row.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetch_row_not_found(self, toolkit):
        """fetch_database_row with no rows returns found=False."""
        not_found = RowResult(driver="pg", row=None, found=False, execution_time_ms=1.0)
        with patch.object(toolkit, "get_source") as mock_get_source:
            mock_source = AsyncMock()
            mock_source.query_row = AsyncMock(return_value=not_found)
            mock_source.resolve_credentials = AsyncMock(return_value={})
            mock_get_source.return_value = mock_source
            result = await toolkit.fetch_database_row(
                driver="pg",
                query="SELECT * FROM users WHERE id = 999",
            )

        assert result["found"] is False
        assert result["row"] is None

    @pytest.mark.asyncio
    async def test_mongo_validate_passes(self, toolkit):
        """MongoDB validate_database_query passes for valid MQL filter."""
        with patch.object(toolkit, "get_source") as mock_get_source:
            mock_source = AsyncMock()
            mock_source.validate_query = AsyncMock(
                return_value=ValidationResult(valid=True, dialect="mql")
            )
            mock_get_source.return_value = mock_source
            result = await toolkit.validate_database_query(
                driver="mongo",
                query='{"status": "active", "age": {"$gt": 18}}',
            )
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_influx_validate_passes(self, toolkit):
        """InfluxDB validate_database_query passes for valid Flux query."""
        with patch.object(toolkit, "get_source") as mock_get_source:
            mock_source = AsyncMock()
            mock_source.validate_query = AsyncMock(
                return_value=ValidationResult(valid=True, dialect="flux")
            )
            mock_get_source.return_value = mock_source
            result = await toolkit.validate_database_query(
                driver="influx",
                query='from(bucket: "metrics") |> range(start: -1h)',
            )
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_elastic_validate_passes(self, toolkit):
        """Elasticsearch validate_database_query passes for valid JSON DSL."""
        with patch.object(toolkit, "get_source") as mock_get_source:
            mock_source = AsyncMock()
            mock_source.validate_query = AsyncMock(
                return_value=ValidationResult(valid=True, dialect="json")
            )
            mock_get_source.return_value = mock_source
            result = await toolkit.validate_database_query(
                driver="elastic",
                query='{"query": {"term": {"status": "published"}}}',
            )
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_alias_works(self, toolkit):
        """Driver aliases ('postgresql') resolve correctly."""
        with patch.object(toolkit, "get_source") as mock_get_source:
            mock_source = AsyncMock()
            mock_source.validate_query = AsyncMock(
                return_value=ValidationResult(valid=True, dialect="postgres")
            )
            mock_get_source.return_value = mock_source
            result = await toolkit.validate_database_query(
                driver="postgresql",
                query="SELECT 1",
            )
        assert result["valid"] is True

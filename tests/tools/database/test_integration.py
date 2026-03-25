"""Integration tests for DatabaseToolkit with mocked asyncdb connections.

Tests the three-step agentic flow: metadata → validate → execute.
No real database connections are required.

Part of FEAT-062 — DatabaseToolkit / TASK-436.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../packages/ai-parrot/src"))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.tools.database import DatabaseToolkit
from parrot.tools.database.base import (
    ColumnMeta,
    MetadataResult,
    QueryResult,
    RowResult,
    TableMeta,
)
from parrot.tools.database.sources.postgres import PostgresSource


@pytest.fixture
def toolkit():
    """Fresh DatabaseToolkit instance."""
    return DatabaseToolkit()


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
        tool = toolkit.get_tool_by_name("validate_database_query")
        assert tool is not None

        result = await tool._execute(driver="pg", query="SELECT id, name FROM users WHERE id = 1")
        assert result.success is True
        assert result.result["valid"] is True
        assert result.result["dialect"] == "postgres"

    @pytest.mark.asyncio
    async def test_validate_invalid_sql(self, toolkit):
        """Step 2: validate_database_query with invalid SQL returns valid=False."""
        tool = toolkit.get_tool_by_name("validate_database_query")

        result = await tool._execute(driver="pg", query="SELECT WHERE")
        assert result.success is True
        assert result.result["valid"] is False
        assert result.result["error"] is not None

    @pytest.mark.asyncio
    async def test_metadata_tool_delegates_to_source(self, toolkit, mock_pg_metadata):
        """Step 1: get_database_metadata calls source.get_metadata."""
        tool = toolkit.get_tool_by_name("get_database_metadata")
        src = toolkit.get_source("pg")

        with patch.object(src, "get_metadata", AsyncMock(return_value=mock_pg_metadata)):
            with patch.object(src, "resolve_credentials", AsyncMock(return_value={"dsn": "postgresql://localhost/db"})):
                result = await tool._execute(
                    driver="pg",
                    credentials={"dsn": "postgresql://localhost/db"},
                )

        assert result.success is True
        assert result.result["driver"] == "pg"
        assert len(result.result["tables"]) == 1
        assert result.result["tables"][0]["name"] == "users"

    @pytest.mark.asyncio
    async def test_execute_tool_delegates_to_source(self, toolkit, mock_pg_query_result):
        """Step 3: execute_database_query calls source.query."""
        tool = toolkit.get_tool_by_name("execute_database_query")
        src = toolkit.get_source("pg")

        with patch.object(src, "query", AsyncMock(return_value=mock_pg_query_result)):
            with patch.object(src, "resolve_credentials", AsyncMock(return_value={})):
                result = await tool._execute(
                    driver="pg",
                    query="SELECT * FROM users",
                )

        assert result.success is True
        assert result.result["row_count"] == 1
        assert result.result["rows"][0]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_fetch_row_tool_delegates_to_source(self, toolkit, mock_pg_row_result):
        """Step 3b: fetch_database_row calls source.query_row."""
        tool = toolkit.get_tool_by_name("fetch_database_row")
        src = toolkit.get_source("pg")

        with patch.object(src, "query_row", AsyncMock(return_value=mock_pg_row_result)):
            with patch.object(src, "resolve_credentials", AsyncMock(return_value={})):
                result = await tool._execute(
                    driver="pg",
                    query="SELECT * FROM users WHERE id = 1",
                )

        assert result.success is True
        assert result.result["found"] is True
        assert result.result["row"]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_fetch_row_not_found(self, toolkit):
        """fetch_database_row with no rows returns found=False."""
        tool = toolkit.get_tool_by_name("fetch_database_row")
        src = toolkit.get_source("pg")
        not_found = RowResult(driver="pg", row=None, found=False, execution_time_ms=1.0)

        with patch.object(src, "query_row", AsyncMock(return_value=not_found)):
            with patch.object(src, "resolve_credentials", AsyncMock(return_value={})):
                result = await tool._execute(
                    driver="pg",
                    query="SELECT * FROM users WHERE id = 999",
                )

        assert result.success is True
        assert result.result["found"] is False
        assert result.result["row"] is None

    @pytest.mark.asyncio
    async def test_tool_handles_source_error(self, toolkit):
        """Tool returns success=False with error when source raises."""
        tool = toolkit.get_tool_by_name("execute_database_query")
        src = toolkit.get_source("pg")

        with patch.object(src, "query", AsyncMock(side_effect=ConnectionError("DB unavailable"))):
            with patch.object(src, "resolve_credentials", AsyncMock(return_value={})):
                result = await tool._execute(
                    driver="pg",
                    query="SELECT 1",
                )

        assert result.success is False
        assert "DB unavailable" in (result.error or "")

    @pytest.mark.asyncio
    async def test_mongo_validate_in_flow(self, toolkit):
        """MongoDB validate_query works with JSON filter."""
        tool = toolkit.get_tool_by_name("validate_database_query")
        result = await tool._execute(
            driver="mongo",
            query='{"status": "active", "age": {"$gt": 18}}',
        )
        assert result.success is True
        assert result.result["valid"] is True
        assert result.result["dialect"] == "json"

    @pytest.mark.asyncio
    async def test_influx_validate_in_flow(self, toolkit):
        """InfluxDB validate_query works with Flux query."""
        tool = toolkit.get_tool_by_name("validate_database_query")
        result = await tool._execute(
            driver="influx",
            query='from(bucket: "metrics") |> range(start: -1h)',
        )
        assert result.success is True
        assert result.result["valid"] is True
        assert result.result["dialect"] == "flux"

    @pytest.mark.asyncio
    async def test_elastic_validate_in_flow(self, toolkit):
        """Elasticsearch validate_query works with JSON DSL."""
        tool = toolkit.get_tool_by_name("validate_database_query")
        result = await tool._execute(
            driver="elastic",
            query='{"query": {"term": {"status": "published"}}}',
        )
        assert result.success is True
        assert result.result["valid"] is True
        assert result.result["dialect"] == "json-dsl"

    @pytest.mark.asyncio
    async def test_alias_works_in_tools(self, toolkit):
        """Tools resolve driver aliases correctly."""
        tool = toolkit.get_tool_by_name("validate_database_query")

        # 'postgresql' should resolve to 'pg'
        result = await tool._execute(
            driver="postgresql",
            query="SELECT 1",
        )
        assert result.success is True
        assert result.result["valid"] is True

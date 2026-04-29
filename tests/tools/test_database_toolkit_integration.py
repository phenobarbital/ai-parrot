"""Integration tests for DatabaseQueryToolkit (FEAT-136 TASK-936).

Tests the full toolkit lifecycle with mocked database sources:
- metadata discovery → query → save roundtrip
- test_connection error path
- validate_query DDL blocking
- get_table_metadata single-table delegation
- max_rows injection
- Backward compat: DatabaseQueryTool instantiation
- Export verification

Part of FEAT-136 — database-toolkit-parity, TASK-936.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.tools.databasequery.base import (
    ColumnMeta,
    MetadataResult,
    QueryResult,
    RowResult,
    TableMeta,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def toolkit(tmp_path: Path):
    from parrot.tools.databasequery import DatabaseQueryToolkit
    return DatabaseQueryToolkit(output_dir=str(tmp_path))


@pytest.fixture
def toolkit_no_output():
    from parrot.tools.databasequery import DatabaseQueryToolkit
    return DatabaseQueryToolkit()


def _make_mock_source(
    meta: MetadataResult = None,
    query_result: QueryResult = None,
    row_result: RowResult = None,
    test_conn: bool = True,
    validate_result: ValidationResult = None,
):
    """Build a mock source with sensible defaults."""
    mock = MagicMock()
    mock.resolve_credentials = AsyncMock(return_value={"host": "localhost"})
    mock.get_metadata = AsyncMock(return_value=meta or MetadataResult(
        driver="pg",
        tables=[TableMeta(name="users", columns=[
            ColumnMeta(name="id", data_type="integer"),
            ColumnMeta(name="name", data_type="varchar"),
        ])]
    ))
    mock.query = AsyncMock(return_value=query_result or QueryResult(
        driver="pg",
        rows=[{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}],
        row_count=2,
        columns=["id", "name"],
        execution_time_ms=5.0,
    ))
    mock.query_row = AsyncMock(return_value=row_result or RowResult(
        driver="pg",
        row={"id": 1, "name": "alice"},
        found=True,
        execution_time_ms=2.0,
    ))
    mock.test_connection = AsyncMock(return_value=test_conn)
    mock.validate_query = AsyncMock(return_value=validate_result or ValidationResult(
        valid=True, dialect="sql"
    ))
    return mock


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


class TestExports:
    """Verify all public exports are accessible."""

    def test_add_row_limit_exported(self) -> None:
        from parrot.tools.databasequery import add_row_limit
        assert callable(add_row_limit)

    def test_add_row_limit_works(self) -> None:
        from parrot.tools.databasequery import add_row_limit
        result = add_row_limit("SELECT * FROM t", 100, "pg")
        assert "LIMIT" in result.upper()

    def test_database_query_toolkit_importable(self) -> None:
        from parrot.tools.databasequery import DatabaseQueryToolkit
        tk = DatabaseQueryToolkit()
        assert tk is not None

    def test_database_query_tool_importable(self) -> None:
        from parrot.tools.databasequery import DatabaseQueryTool
        tool = DatabaseQueryTool()
        assert tool.name == "database_query"

    def test_abstract_database_source_importable(self) -> None:
        from parrot.tools.databasequery import AbstractDatabaseSource
        assert AbstractDatabaseSource is not None

    def test_result_types_importable(self) -> None:
        from parrot.tools.databasequery import (
            MetadataResult, QueryResult, RowResult, ValidationResult
        )
        assert MetadataResult and QueryResult and RowResult and ValidationResult


# ---------------------------------------------------------------------------
# Tool names
# ---------------------------------------------------------------------------


class TestToolkitIntegration:
    """Integration tests for the full toolkit lifecycle."""

    def test_tool_names(self, toolkit) -> None:
        names = [t.name for t in toolkit.get_tools()]
        assert "dq_validate_query" in names
        assert "dq_get_table_metadata" in names
        assert "dq_test_connection" in names
        assert "dq_save_result" in names
        assert "dq_execute_database_query" in names
        assert "dq_fetch_database_row" in names
        assert "dq_get_database_metadata" in names
        # Old name must not exist
        assert "dq_validate_database_query" not in names

    def test_tool_names_no_output(self, toolkit_no_output) -> None:
        names = [t.name for t in toolkit_no_output.get_tools()]
        # save_result excluded when output_dir is not set
        assert "dq_save_result" not in names

    # ---- validate_query ----

    @pytest.mark.asyncio
    async def test_validate_query_blocks_drop(self, toolkit) -> None:
        result = await toolkit.validate_query(driver="pg", query="DROP TABLE users")
        assert isinstance(result, ValidationResult)
        assert result.valid is False

    @pytest.mark.asyncio
    async def test_validate_query_blocks_insert(self, toolkit) -> None:
        result = await toolkit.validate_query(driver="pg", query="INSERT INTO t VALUES (1)")
        assert result.valid is False

    @pytest.mark.asyncio
    async def test_validate_query_passes_select(self, toolkit) -> None:
        mock_source = _make_mock_source(validate_result=ValidationResult(valid=True, dialect="sql"))
        with patch.object(toolkit, "get_source", return_value=mock_source):
            result = await toolkit.validate_query(driver="pg", query="SELECT * FROM users")
        assert isinstance(result, ValidationResult)
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_query_no_credentials_param(self, toolkit) -> None:
        """validate_query must not accept credentials."""
        import inspect
        sig = inspect.signature(toolkit.validate_query)
        assert "credentials" not in sig.parameters

    # ---- get_table_metadata ----

    @pytest.mark.asyncio
    async def test_get_table_metadata_delegates_correctly(self, toolkit) -> None:
        meta = MetadataResult(driver="pg", tables=[
            TableMeta(name="orders", columns=[ColumnMeta(name="id", data_type="int")])
        ])
        mock_source = _make_mock_source(meta=meta)
        with patch.object(toolkit, "get_source", return_value=mock_source):
            result = await toolkit.get_table_metadata("pg", "orders")

        mock_source.get_metadata.assert_awaited_once_with(
            {"host": "localhost"}, tables=["orders"]
        )
        assert isinstance(result, MetadataResult)
        assert result.tables[0].name == "orders"

    # ---- test_connection ----

    @pytest.mark.asyncio
    async def test_test_connection_success(self, toolkit) -> None:
        mock_source = _make_mock_source(test_conn=True)
        with patch.object(toolkit, "get_source", return_value=mock_source):
            result = await toolkit.test_connection("pg")
        assert result == {"status": "success"}

    @pytest.mark.asyncio
    async def test_test_connection_failure_returns_error(self, toolkit) -> None:
        mock_source = _make_mock_source(test_conn=False)
        with patch.object(toolkit, "get_source", return_value=mock_source):
            result = await toolkit.test_connection("pg")
        assert result["status"] == "error"
        assert "message" in result

    @pytest.mark.asyncio
    async def test_test_connection_exception_returns_error(self, toolkit) -> None:
        with patch.object(toolkit, "get_source", side_effect=Exception("network unreachable")):
            result = await toolkit.test_connection("pg")
        assert result["status"] == "error"
        assert "network unreachable" in result["message"]

    # ---- execute_database_query with max_rows ----

    @pytest.mark.asyncio
    async def test_execute_injects_limit(self, toolkit) -> None:
        mock_source = _make_mock_source()
        with patch.object(toolkit, "get_source", return_value=mock_source):
            await toolkit.execute_database_query("pg", "SELECT * FROM users", max_rows=50)
        called_query = mock_source.query.call_args[0][1]
        assert "50" in called_query

    @pytest.mark.asyncio
    async def test_execute_blocks_ddl_returns_validation_result(self, toolkit) -> None:
        result = await toolkit.execute_database_query("pg", "TRUNCATE TABLE t")
        assert isinstance(result, ValidationResult)
        assert result.valid is False

    @pytest.mark.asyncio
    async def test_execute_returns_query_result(self, toolkit) -> None:
        mock_source = _make_mock_source()
        with patch.object(toolkit, "get_source", return_value=mock_source):
            result = await toolkit.execute_database_query(
                "pg", "SELECT id, name FROM users"
            )
        assert isinstance(result, QueryResult)
        assert result.row_count == 2

    # ---- save_result roundtrip ----

    @pytest.mark.asyncio
    async def test_save_result_csv_roundtrip(self, toolkit, tmp_path: Path) -> None:
        rows = [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]
        output = await toolkit.save_result(
            {"rows": rows, "columns": ["id", "name"]},
            filename="roundtrip",
            file_format="csv",
        )
        assert "file_path" in output
        assert output["file_format"] == "csv"
        assert output["row_count"] == 2
        assert os.path.exists(output["file_path"])

    @pytest.mark.asyncio
    async def test_save_result_json_roundtrip(self, toolkit) -> None:
        rows = [{"a": 1}, {"a": 2}]
        output = await toolkit.save_result(
            {"rows": rows},
            filename="roundtrip_json",
            file_format="json",
        )
        assert output["file_path"].endswith(".json")
        assert os.path.exists(output["file_path"])

    @pytest.mark.asyncio
    async def test_save_result_no_output_dir(self, toolkit_no_output) -> None:
        output = await toolkit_no_output.save_result({"rows": [{"a": 1}]})
        assert "error" in output
        assert "output_dir" in output["error"]

    # ---- full lifecycle: metadata → query → save ----

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, toolkit, tmp_path: Path) -> None:
        """metadata discovery → execute query → save to file."""
        mock_source = _make_mock_source()

        with patch.object(toolkit, "get_source", return_value=mock_source):
            # Step 1: discover metadata
            meta = await toolkit.get_database_metadata("pg")
            assert isinstance(meta, MetadataResult)
            assert len(meta.tables) > 0

            # Step 2: execute query
            query_result = await toolkit.execute_database_query(
                "pg", "SELECT id, name FROM users", max_rows=100
            )
            assert isinstance(query_result, QueryResult)
            assert query_result.row_count > 0

        # Step 3: save result to file
        save_output = await toolkit.save_result(
            {"rows": query_result.rows, "columns": query_result.columns},
            filename="lifecycle_test",
            file_format="csv",
        )
        assert "file_path" in save_output
        assert os.path.exists(save_output["file_path"])

    # ---- _post_execute serialization ----

    @pytest.mark.asyncio
    async def test_post_execute_serializes_query_result(self, toolkit) -> None:
        qr = QueryResult(
            driver="pg", rows=[{"id": 1}], row_count=1,
            columns=["id"], execution_time_ms=1.0
        )
        result = await toolkit._post_execute("execute_database_query", qr)
        assert isinstance(result, dict)
        assert result["driver"] == "pg"

    @pytest.mark.asyncio
    async def test_post_execute_passes_through_plain_dict(self, toolkit) -> None:
        d = {"status": "success"}
        result = await toolkit._post_execute("test_connection", d)
        assert result is d


# ---------------------------------------------------------------------------
# Backward compatibility: DatabaseQueryTool
# ---------------------------------------------------------------------------


class TestDatabaseQueryToolBackwardCompat:
    """DatabaseQueryTool should still work after TASK-935 cleanup."""

    def test_can_instantiate(self) -> None:
        from parrot.tools.databasequery import DatabaseQueryTool
        tool = DatabaseQueryTool()
        assert tool.name == "database_query"

    def test_has_execute_method(self) -> None:
        from parrot.tools.databasequery import DatabaseQueryTool
        tool = DatabaseQueryTool()
        assert hasattr(tool, "_execute")
        assert callable(tool._execute)

    def test_validate_safety_blocks_ddl(self) -> None:
        from parrot.tools.databasequery import DatabaseQueryTool
        tool = DatabaseQueryTool()
        result = tool._validate_query_safety("DROP TABLE t", "pg")
        assert result["is_safe"] is False

    def test_validate_safety_passes_select(self) -> None:
        from parrot.tools.databasequery import DatabaseQueryTool
        tool = DatabaseQueryTool()
        result = tool._validate_query_safety("SELECT 1", "pg")
        assert result["is_safe"] is True

    def test_get_default_credentials_returns_tuple(self) -> None:
        from parrot.tools.databasequery import DatabaseQueryTool
        tool = DatabaseQueryTool()
        with patch("parrot.interfaces.database.get_default_credentials", return_value={"host": "localhost"}):
            creds, dsn = tool._get_default_credentials("pg")
        assert isinstance(creds, dict)
        assert dsn is None or isinstance(dsn, str)

    def test_no_driver_info_class(self) -> None:
        import parrot.tools.databasequery.tool as mod
        assert not hasattr(mod, "DriverInfo")

    def test_no_local_query_validator(self) -> None:
        import parrot.tools.databasequery.tool as mod
        # QueryValidator attribute must come from parrot.security
        if hasattr(mod, "QueryValidator"):
            from parrot.security import QueryValidator
            assert mod.QueryValidator is QueryValidator

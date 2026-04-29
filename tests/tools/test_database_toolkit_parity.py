"""Unit tests for DatabaseQueryToolkit refactor (FEAT-136 TASK-934).

Tests:
- validate_database_query renamed → validate_query (no credentials param)
- _post_execute serializes BaseModel results
- get_table_metadata tool
- test_connection tool
- save_result tool (CSV, JSON, Excel, error when no output_dir)
- execute_database_query with max_rows
- fetch_database_row with max_rows

Part of FEAT-136 — database-toolkit-parity, TASK-934.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from parrot.tools.databasequery.base import (
    MetadataResult,
    QueryResult,
    RowResult,
    TableMeta,
    ValidationResult,
)
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def toolkit(tmp_path: Path) -> DatabaseQueryToolkit:
    """Toolkit with output_dir configured."""
    return DatabaseQueryToolkit(output_dir=str(tmp_path))


@pytest.fixture
def toolkit_no_output() -> DatabaseQueryToolkit:
    """Toolkit without output_dir."""
    return DatabaseQueryToolkit()


# ---------------------------------------------------------------------------
# Rename: validate_database_query → validate_query
# ---------------------------------------------------------------------------


class TestValidateQueryRenamed:
    """validate_database_query must not exist; validate_query must exist."""

    def test_validate_query_tool_exists(self, toolkit: DatabaseQueryToolkit) -> None:
        tool_names = [t.name for t in toolkit.get_tools()]
        assert "dq_validate_query" in tool_names

    def test_validate_database_query_does_not_exist(self, toolkit: DatabaseQueryToolkit) -> None:
        tool_names = [t.name for t in toolkit.get_tools()]
        assert "dq_validate_database_query" not in tool_names

    def test_validate_query_has_no_credentials_param(self, toolkit: DatabaseQueryToolkit) -> None:
        import inspect
        sig = inspect.signature(toolkit.validate_query)
        assert "credentials" not in sig.parameters

    @pytest.mark.asyncio
    async def test_validate_query_blocks_ddl(self, toolkit: DatabaseQueryToolkit) -> None:
        result = await toolkit.validate_query("pg", "DROP TABLE users")
        assert isinstance(result, ValidationResult)
        assert result.valid is False

    @pytest.mark.asyncio
    async def test_validate_query_safe_query(self, toolkit: DatabaseQueryToolkit) -> None:
        """A safe SELECT delegates to source.validate_query()."""
        mock_source = MagicMock()
        mock_source.validate_query = AsyncMock(
            return_value=ValidationResult(valid=True, dialect="sql")
        )
        with patch.object(toolkit, "get_source", return_value=mock_source):
            result = await toolkit.validate_query("pg", "SELECT 1")
        assert isinstance(result, ValidationResult)
        assert result.valid is True


# ---------------------------------------------------------------------------
# _post_execute
# ---------------------------------------------------------------------------


class TestPostExecute:
    """_post_execute must serialize BaseModel results to dicts."""

    @pytest.mark.asyncio
    async def test_serializes_basemodel(self, toolkit: DatabaseQueryToolkit) -> None:
        class Dummy(BaseModel):
            x: int = 1
            y: str = "hello"

        result = await toolkit._post_execute("test", Dummy())
        assert result == {"x": 1, "y": "hello"}

    @pytest.mark.asyncio
    async def test_passes_through_dict(self, toolkit: DatabaseQueryToolkit) -> None:
        result = await toolkit._post_execute("test", {"a": 1})
        assert result == {"a": 1}

    @pytest.mark.asyncio
    async def test_passes_through_string(self, toolkit: DatabaseQueryToolkit) -> None:
        result = await toolkit._post_execute("test", "hello")
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_passes_through_none(self, toolkit: DatabaseQueryToolkit) -> None:
        result = await toolkit._post_execute("test", None)
        assert result is None

    @pytest.mark.asyncio
    async def test_serializes_query_result(self, toolkit: DatabaseQueryToolkit) -> None:
        qr = QueryResult(driver="pg", rows=[{"id": 1}], row_count=1, columns=["id"], execution_time_ms=0.0)
        result = await toolkit._post_execute("test", qr)
        assert isinstance(result, dict)
        assert result["driver"] == "pg"
        assert result["rows"] == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_serializes_validation_result(self, toolkit: DatabaseQueryToolkit) -> None:
        vr = ValidationResult(valid=True, dialect="sql")
        result = await toolkit._post_execute("test", vr)
        assert isinstance(result, dict)
        assert result["valid"] is True


# ---------------------------------------------------------------------------
# get_table_metadata
# ---------------------------------------------------------------------------


class TestGetTableMetadata:
    """get_table_metadata delegates to source.get_metadata(creds, tables=[table])."""

    def test_tool_exists(self, toolkit: DatabaseQueryToolkit) -> None:
        tool_names = [t.name for t in toolkit.get_tools()]
        assert "dq_get_table_metadata" in tool_names

    @pytest.mark.asyncio
    async def test_delegates_to_source(self, toolkit: DatabaseQueryToolkit) -> None:
        meta = MetadataResult(driver="pg", tables=[TableMeta(name="users", columns=[])])
        mock_source = MagicMock()
        mock_source.resolve_credentials = AsyncMock(return_value={"host": "localhost"})
        mock_source.get_metadata = AsyncMock(return_value=meta)

        with patch.object(toolkit, "get_source", return_value=mock_source):
            result = await toolkit.get_table_metadata("pg", "users")

        mock_source.get_metadata.assert_awaited_once_with(
            {"host": "localhost"}, tables=["users"]
        )
        assert isinstance(result, MetadataResult)
        assert result.tables[0].name == "users"

    @pytest.mark.asyncio
    async def test_accepts_credentials(self, toolkit: DatabaseQueryToolkit) -> None:
        meta = MetadataResult(driver="pg", tables=[])
        mock_source = MagicMock()
        mock_source.resolve_credentials = AsyncMock(return_value={"host": "db.host"})
        mock_source.get_metadata = AsyncMock(return_value=meta)

        creds = {"host": "db.host", "port": "5432"}
        with patch.object(toolkit, "get_source", return_value=mock_source):
            result = await toolkit.get_table_metadata("pg", "orders", credentials=creds)

        mock_source.resolve_credentials.assert_awaited_once_with(creds)
        assert isinstance(result, MetadataResult)


# ---------------------------------------------------------------------------
# test_connection tool
# ---------------------------------------------------------------------------


class TestTestConnectionTool:
    """test_connection returns {"status": "success"} or {"status": "error", ...}."""

    def test_tool_exists(self, toolkit: DatabaseQueryToolkit) -> None:
        tool_names = [t.name for t in toolkit.get_tools()]
        assert "dq_test_connection" in tool_names

    @pytest.mark.asyncio
    async def test_returns_success(self, toolkit: DatabaseQueryToolkit) -> None:
        mock_source = MagicMock()
        mock_source.resolve_credentials = AsyncMock(return_value={})
        mock_source.test_connection = AsyncMock(return_value=True)

        with patch.object(toolkit, "get_source", return_value=mock_source):
            result = await toolkit.test_connection("pg")

        assert result == {"status": "success"}

    @pytest.mark.asyncio
    async def test_returns_error_when_false(self, toolkit: DatabaseQueryToolkit) -> None:
        mock_source = MagicMock()
        mock_source.resolve_credentials = AsyncMock(return_value={})
        mock_source.test_connection = AsyncMock(return_value=False)

        with patch.object(toolkit, "get_source", return_value=mock_source):
            result = await toolkit.test_connection("pg")

        assert result["status"] == "error"
        assert "message" in result

    @pytest.mark.asyncio
    async def test_returns_error_on_exception(self, toolkit: DatabaseQueryToolkit) -> None:
        mock_source = MagicMock()
        mock_source.resolve_credentials = AsyncMock(side_effect=Exception("network error"))

        with patch.object(toolkit, "get_source", return_value=mock_source):
            result = await toolkit.test_connection("pg")

        assert result["status"] == "error"
        assert "network error" in result["message"]

    @pytest.mark.asyncio
    async def test_never_raises(self, toolkit: DatabaseQueryToolkit) -> None:
        with patch.object(toolkit, "get_source", side_effect=ValueError("bad driver")):
            result = await toolkit.test_connection("bogus_driver")
        assert isinstance(result, dict)
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# save_result tool
# ---------------------------------------------------------------------------


class TestSaveResult:
    """save_result writes files and returns metadata dict."""

    def test_tool_exists_when_output_dir(self, toolkit: DatabaseQueryToolkit) -> None:
        tool_names = [t.name for t in toolkit.get_tools()]
        assert "dq_save_result" in tool_names

    def test_tool_excluded_when_no_output_dir(self, toolkit_no_output: DatabaseQueryToolkit) -> None:
        tool_names = [t.name for t in toolkit_no_output.get_tools()]
        assert "dq_save_result" not in tool_names

    @pytest.mark.asyncio
    async def test_csv_export(self, toolkit: DatabaseQueryToolkit, tmp_path: Path) -> None:
        result = {"rows": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]}
        output = await toolkit.save_result(result, filename="test_out", file_format="csv")
        assert "file_path" in output
        assert output["file_path"].endswith(".csv")
        assert output["row_count"] == 2
        assert output["file_format"] == "csv"
        assert Path(output["file_path"]).exists()

    @pytest.mark.asyncio
    async def test_json_export(self, toolkit: DatabaseQueryToolkit) -> None:
        result = {"rows": [{"id": 1}]}
        output = await toolkit.save_result(result, filename="test_json", file_format="json")
        assert output["file_path"].endswith(".json")
        assert output["row_count"] == 1

    @pytest.mark.asyncio
    async def test_no_output_dir_returns_error(self, toolkit_no_output: DatabaseQueryToolkit) -> None:
        output = await toolkit_no_output.save_result({"rows": []})
        assert "error" in output
        assert "output_dir" in output["error"]

    @pytest.mark.asyncio
    async def test_empty_rows(self, toolkit: DatabaseQueryToolkit) -> None:
        output = await toolkit.save_result({"rows": []}, filename="empty")
        assert "file_path" in output
        assert output["row_count"] == 0

    @pytest.mark.asyncio
    async def test_unsupported_format(self, toolkit: DatabaseQueryToolkit) -> None:
        output = await toolkit.save_result({"rows": [{"a": 1}]}, file_format="parquet")
        assert "error" in output

    @pytest.mark.asyncio
    async def test_auto_filename_generated(self, toolkit: DatabaseQueryToolkit) -> None:
        output = await toolkit.save_result({"rows": [{"x": 1}]})
        assert "file_path" in output
        assert Path(output["file_path"]).exists()

    @pytest.mark.asyncio
    async def test_excel_export(self, toolkit: DatabaseQueryToolkit) -> None:
        openpyxl = pytest.importorskip("openpyxl", reason="openpyxl not installed")  # noqa: F841
        result = {"rows": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]}
        output = await toolkit.save_result(result, filename="test_excel", file_format="excel")
        assert "file_path" in output
        assert output["file_path"].endswith(".xlsx")
        assert output["row_count"] == 2
        assert output["file_format"] == "excel"
        assert Path(output["file_path"]).exists()


# ---------------------------------------------------------------------------
# execute_database_query with max_rows
# ---------------------------------------------------------------------------


class TestExecuteWithMaxRows:
    """execute_database_query must inject row limits."""

    @pytest.mark.asyncio
    async def test_default_max_rows_applied(self, toolkit: DatabaseQueryToolkit) -> None:
        qr = QueryResult(driver="pg", rows=[{"id": 1}], row_count=1, columns=["id"], execution_time_ms=0.0)
        mock_source = MagicMock()
        mock_source.resolve_credentials = AsyncMock(return_value={})
        mock_source.query = AsyncMock(return_value=qr)

        with patch.object(toolkit, "get_source", return_value=mock_source):
            await toolkit.execute_database_query("pg", "SELECT * FROM users")

        # The query passed to source.query should contain LIMIT
        called_query = mock_source.query.call_args[0][1]
        assert "LIMIT" in called_query.upper()

    @pytest.mark.asyncio
    async def test_custom_max_rows(self, toolkit: DatabaseQueryToolkit) -> None:
        qr = QueryResult(driver="pg", rows=[], row_count=0, columns=[], execution_time_ms=0.0)
        mock_source = MagicMock()
        mock_source.resolve_credentials = AsyncMock(return_value={})
        mock_source.query = AsyncMock(return_value=qr)

        with patch.object(toolkit, "get_source", return_value=mock_source):
            await toolkit.execute_database_query("pg", "SELECT 1", max_rows=50)

        called_query = mock_source.query.call_args[0][1]
        assert "50" in called_query

    @pytest.mark.asyncio
    async def test_zero_max_rows_disables_limit(self, toolkit: DatabaseQueryToolkit) -> None:
        qr = QueryResult(driver="pg", rows=[], row_count=0, columns=[], execution_time_ms=0.0)
        mock_source = MagicMock()
        mock_source.resolve_credentials = AsyncMock(return_value={})
        mock_source.query = AsyncMock(return_value=qr)

        with patch.object(toolkit, "get_source", return_value=mock_source):
            await toolkit.execute_database_query("pg", "SELECT 1", max_rows=0)

        called_query = mock_source.query.call_args[0][1]
        assert "LIMIT" not in called_query.upper()

    @pytest.mark.asyncio
    async def test_blocks_ddl(self, toolkit: DatabaseQueryToolkit) -> None:
        result = await toolkit.execute_database_query("pg", "DROP TABLE x")
        assert isinstance(result, ValidationResult)
        assert result.valid is False

    @pytest.mark.asyncio
    async def test_returns_query_result_model(self, toolkit: DatabaseQueryToolkit) -> None:
        qr = QueryResult(driver="pg", rows=[{"id": 1}], row_count=1, columns=["id"], execution_time_ms=0.0)
        mock_source = MagicMock()
        mock_source.resolve_credentials = AsyncMock(return_value={})
        mock_source.query = AsyncMock(return_value=qr)

        with patch.object(toolkit, "get_source", return_value=mock_source):
            result = await toolkit.execute_database_query("pg", "SELECT id FROM t")

        assert isinstance(result, QueryResult)


# ---------------------------------------------------------------------------
# fetch_database_row with max_rows
# ---------------------------------------------------------------------------


class TestFetchRowWithMaxRows:
    """fetch_database_row must inject row limits."""

    @pytest.mark.asyncio
    async def test_default_max_rows_is_1(self, toolkit: DatabaseQueryToolkit) -> None:
        rr = RowResult(driver="pg", row={"id": 1}, found=True, execution_time_ms=0.0)
        mock_source = MagicMock()
        mock_source.resolve_credentials = AsyncMock(return_value={})
        mock_source.query_row = AsyncMock(return_value=rr)

        with patch.object(toolkit, "get_source", return_value=mock_source):
            await toolkit.fetch_database_row("pg", "SELECT * FROM users WHERE id=1")

        called_query = mock_source.query_row.call_args[0][1]
        assert "LIMIT" in called_query.upper()
        assert "1" in called_query

    @pytest.mark.asyncio
    async def test_blocks_ddl(self, toolkit: DatabaseQueryToolkit) -> None:
        result = await toolkit.fetch_database_row("pg", "DELETE FROM t")
        assert isinstance(result, ValidationResult)
        assert result.valid is False

    @pytest.mark.asyncio
    async def test_returns_row_result_model(self, toolkit: DatabaseQueryToolkit) -> None:
        rr = RowResult(driver="pg", row={"id": 5}, found=True, execution_time_ms=0.0)
        mock_source = MagicMock()
        mock_source.resolve_credentials = AsyncMock(return_value={})
        mock_source.query_row = AsyncMock(return_value=rr)

        with patch.object(toolkit, "get_source", return_value=mock_source):
            result = await toolkit.fetch_database_row("pg", "SELECT * FROM t LIMIT 1")

        assert isinstance(result, RowResult)
        assert result.found is True


# ---------------------------------------------------------------------------
# output_dir / static_dir init
# ---------------------------------------------------------------------------


class TestToolkitInit:
    """Test __init__ kwarg handling for output_dir and static_dir."""

    def test_output_dir_stored(self, tmp_path: Path) -> None:
        tk = DatabaseQueryToolkit(output_dir=str(tmp_path))
        assert tk._output_dir == tmp_path

    def test_no_output_dir(self) -> None:
        tk = DatabaseQueryToolkit()
        assert tk._output_dir is None

    def test_static_dir_stored(self, tmp_path: Path) -> None:
        tk = DatabaseQueryToolkit(output_dir=str(tmp_path), static_dir="/var/www/static")
        assert tk._static_dir == "/var/www/static"

    def test_save_result_excluded_without_output_dir(self) -> None:
        tk = DatabaseQueryToolkit()
        assert "save_result" in tk.exclude_tools

    def test_save_result_not_excluded_with_output_dir(self, tmp_path: Path) -> None:
        tk = DatabaseQueryToolkit(output_dir=str(tmp_path))
        assert "save_result" not in tk.exclude_tools

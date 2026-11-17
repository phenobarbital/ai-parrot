"""Tests for terminal fetch_dataset failures."""

import sys
from types import ModuleType
from unittest.mock import AsyncMock

import pytest

_utils_types_original = sys.modules.get("parrot.utils.types")
_toml_parser_original = sys.modules.get("parrot.utils.parsers.toml")
_stubbed_extensions = False

try:
    import parrot.utils.types  # noqa: F401 -- prefer the compiled extension when available.
except ModuleNotFoundError:
    _stubbed_extensions = True
    utils_types = ModuleType("parrot.utils.types")
    utils_types.SafeDict = dict
    sys.modules["parrot.utils.types"] = utils_types

    toml_parser = ModuleType("parrot.utils.parsers.toml")
    toml_parser.TOMLParser = object
    sys.modules["parrot.utils.parsers.toml"] = toml_parser

from parrot.tools.dataset_manager.tool import DatasetManager, _classify_fetch_failure  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def restore_extension_stubs() -> object:
    """Restore process-wide extension-module registrations after these tests."""
    yield
    if _stubbed_extensions:
        for module_name, original in (
            ("parrot.utils.types", _utils_types_original),
            ("parrot.utils.parsers.toml", _toml_parser_original),
        ):
            if original is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original


MISSING = (
    "TableSource query failed on 'troc.financial_projection_detail': Sentence Error: "
    'relation "troc.financial_projection_detail" does not exist'
)
TABLE = "troc.financial_projection_detail"


class TestClassifier:
    def test_own_table_missing_is_terminal(self):
        assert _classify_fetch_failure(RuntimeError(MISSING), TABLE) == "missing_table"

    def test_other_table_missing_is_correctable(self):
        assert _classify_fetch_failure(RuntimeError(MISSING), "troc.sales") is None

    def test_column_error_is_correctable(self):
        assert _classify_fetch_failure(RuntimeError('column "x" does not exist'), "troc.sales") is None

    def test_permission_denied(self):
        assert _classify_fetch_failure(RuntimeError("permission denied for table sales"), "troc.sales") == "permission_denied"

    def test_connection(self):
        assert _classify_fetch_failure(ConnectionRefusedError("connection refused"), "troc.sales") == "connection"

    def test_no_table_skips_missing(self):
        assert _classify_fetch_failure(RuntimeError(MISSING), None) is None


@pytest.fixture
async def manager() -> DatasetManager:
    """Manager with one TableSource entry and a mocked materialize()."""
    dm = DatasetManager()
    await dm.add_table_source("fpd", TABLE, "pg", strict_schema=False, dsn="postgres://x/y")
    dm.materialize = AsyncMock()
    return dm


SQL = f"SELECT 1 FROM {TABLE}"


class TestFetchDatasetFailures:
    async def test_missing_table_terminal_and_cached(self, manager):
        manager.materialize.side_effect = RuntimeError(MISSING)
        res = await manager.fetch_dataset("fpd", sql=SQL)
        assert res["status"] == "error" and res["success"] is False
        assert res["retryable"] is False and res["error_kind"] == "missing_table"
        assert "Do NOT retry" in res["error"] and "hint" not in res
        calls = manager.materialize.await_count
        again = await manager.fetch_dataset("fpd", sql=SQL, force_refresh=True)
        assert again["error_kind"] == "missing_table"
        assert manager.materialize.await_count == calls

    async def test_list_and_activate(self, manager):
        manager.materialize.side_effect = RuntimeError(MISSING)
        await manager.fetch_dataset("fpd", sql=SQL)
        info = manager._datasets["fpd"].to_info()
        assert info.available is False and info.unavailable_reason
        manager.activate("fpd")
        assert manager._datasets["fpd"].to_info().available is True
        calls = manager.materialize.await_count
        await manager.fetch_dataset("fpd", sql=SQL)
        assert manager.materialize.await_count == calls + 1

    async def test_other_table_is_correctable(self, manager):
        manager.materialize.side_effect = RuntimeError('relation "troc.other" does not exist')
        res = await manager.fetch_dataset("fpd", sql=SQL)
        assert res["status"] == "error" and res["hint"] in res["error"]
        assert manager._datasets["fpd"].unavailable_reason is None

    async def test_column_error_is_correctable(self, manager):
        manager.materialize.side_effect = RuntimeError('column "zz" does not exist')
        res = await manager.fetch_dataset("fpd", sql=SQL)
        assert res["status"] == "error" and "hint" in res
        assert manager._datasets["fpd"].unavailable_reason is None

    async def test_connection_not_marked(self, manager):
        manager.materialize.side_effect = ConnectionRefusedError("connection refused")
        res = await manager.fetch_dataset("fpd", sql=SQL)
        assert res["error_kind"] == "connection" and "Do NOT retry" in res["error"]
        assert manager._datasets["fpd"].unavailable_reason is None

    async def test_tool_result_is_error(self, manager):
        manager.materialize.side_effect = RuntimeError(MISSING)
        tool = next(t for t in manager.get_tools() if t.name == "dataset_fetch_dataset")
        result = await tool.execute(name="fpd", sql=SQL)
        assert result.status == "error"

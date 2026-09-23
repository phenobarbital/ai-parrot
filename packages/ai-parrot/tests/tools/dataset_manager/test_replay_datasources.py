"""Tests for replaying Agent Studio datasource descriptors."""

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

from parrot.tools.dataset_manager.tool import DatasetManager
from parrot.tools.dataset_manager.config import FileDatasource


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


@pytest.fixture
def dm(monkeypatch: pytest.MonkeyPatch) -> DatasetManager:
    """Provide a manager whose registration methods are isolated mocks."""
    manager = DatasetManager()
    for method in (
        "add_dataset",
        "load_file",
        "add_table_source",
        "add_airtable_source",
        "add_smartsheet_source",
        "add_iceberg_source",
        "add_mongo_source",
        "add_deltatable_source",
        "create_deltatable_from_parquet",
    ):
        monkeypatch.setattr(manager, method, AsyncMock(return_value="ok"))
    return manager


@pytest.mark.asyncio
async def test_parquet_goes_to_delta(dm: DatasetManager) -> None:
    """Parquet descriptors create an overwrite-mode Delta table."""
    await dm.replay_datasources([{"kind": "file", "name": "p", "path": "/d/a.parquet"}])

    dm.create_deltatable_from_parquet.assert_awaited_once()
    assert dm.create_deltatable_from_parquet.await_args.args[2] == "/d/a.delta"
    assert dm.create_deltatable_from_parquet.await_args.kwargs["mode"] == "overwrite"


@pytest.mark.asyncio
async def test_model_descriptor_is_replayed_without_revalidation(dm: DatasetManager) -> None:
    """A concrete datasource model is accepted alongside dictionary descriptors."""
    descriptor = FileDatasource(kind="file", name="csv", path="/d/a.csv")

    await dm.replay_datasources([descriptor])

    dm.load_file.assert_awaited_once_with("csv", "/d/a.csv", metadata=None)


@pytest.mark.asyncio
async def test_table_kwargs(dm: DatasetManager) -> None:
    """Table descriptors retain their connection and restriction settings."""
    await dm.replay_datasources(
        [
            {
                "kind": "table",
                "name": "t",
                "table": "s.t",
                "driver": "pg",
                "dsn": "x",
                "strict_schema": False,
                "permanent_filter": {"tenant": "a"},
                "allowed_columns": ["id"],
            }
        ]
    )

    kwargs = dm.add_table_source.await_args.kwargs
    assert kwargs["dsn"] == "x"
    assert kwargs["strict_schema"] is False
    assert kwargs["permanent_filter"] == {"tenant": "a"}
    assert kwargs["allowed_columns"] == ["id"]
    assert dm.add_table_source.await_args.args[:3] == ("t", "s.t", "pg")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("descriptor", "method", "expected_args", "expected_kwargs"),
    [
        (
            {"kind": "query_slug", "name": "query", "slug": "orders", "is_active": False},
            "add_dataset",
            ("query",),
            {"query_slug": "orders", "is_active": False},
        ),
        (
            {"kind": "sql", "name": "sql", "sql": "select 1", "driver": "pg", "dsn": "dsn"},
            "add_dataset",
            ("sql",),
            # add_dataset()'s "exactly one of query_slug/query/table/dataframe" selector is
            # `query=`, not `sql=` (`sql=` is only a `table`-mode refinement there) — see
            # replay_datasources()'s "sql" branch (fixed post-review, commit 841da0c44).
            {"query": "select 1", "driver": "pg", "dsn": "dsn"},
        ),
        (
            {"kind": "file", "name": "csv", "path": "/d/a.csv", "metadata": {"source": "test"}},
            "load_file",
            ("csv", "/d/a.csv"),
            {"metadata": {"source": "test"}},
        ),
        (
            {"kind": "airtable", "name": "air", "base_id": "base", "table": "records", "api_key": "key"},
            "add_airtable_source",
            ("air", "base", "records"),
            {"api_key": "key"},
        ),
        (
            {"kind": "smartsheet", "name": "sheet", "sheet_id": "1", "access_token": "token"},
            "add_smartsheet_source",
            ("sheet", "1"),
            {"access_token": "token"},
        ),
        (
            {
                "kind": "iceberg",
                "name": "ice",
                "table_id": "catalog.table",
                "catalog_params": {"uri": "uri"},
                "factory": "polars",
            },
            "add_iceberg_source",
            ("ice", "catalog.table", {"uri": "uri"}),
            {"factory": "polars"},
        ),
        (
            {"kind": "mongo", "name": "mongo", "collection": "orders", "database": "sales"},
            "add_mongo_source",
            ("mongo", "orders", "sales"),
            {"required_filter": True},
        ),
        (
            {"kind": "deltatable", "name": "delta", "path": "/d/table", "table_name": "TABLE"},
            "add_deltatable_source",
            ("delta", "/d/table"),
            {"table_name": "TABLE", "mode": "error"},
        ),
    ],
)
async def test_replay_dispatches_each_datasource_kind(
    dm: DatasetManager,
    descriptor: dict[str, object],
    method: str,
    expected_args: tuple[object, ...],
    expected_kwargs: dict[str, object],
) -> None:
    """Every descriptor kind is replayed through its established registration method."""
    await dm.replay_datasources([descriptor])

    call = getattr(dm, method).await_args
    assert call.args == expected_args
    for key, value in expected_kwargs.items():
        assert call.kwargs[key] == value


@pytest.mark.asyncio
async def test_failure_continues_without_logging_secret(dm: DatasetManager, caplog: pytest.LogCaptureFixture) -> None:
    """A failed descriptor does not prevent subsequent registrations or expose secrets."""
    dm.add_dataset.side_effect = RuntimeError("postgres://secret")

    names = await dm.replay_datasources(
        [
            {"kind": "query_slug", "name": "a", "slug": "s"},
            {"kind": "smartsheet", "name": "b", "sheet_id": "1"},
        ]
    )

    assert names == ["b"]
    assert "postgres://secret" not in caplog.text


def test_config_schema_and_replay_exclusion() -> None:
    """Dataset configuration comes from its model and replay is not LLM-callable."""
    assert DatasetManager.config_schema("dataset_manager")["source"] == "model"
    assert not any("replay_datasources" in tool.name for tool in DatasetManager().get_tools_sync())

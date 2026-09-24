"""Focused tests for the schema-plane service."""

from pathlib import Path

import pytest

from parrot.bots.database.models import Completeness, TableMetadata
from parrot.knowledge.wiki.schema.models import SchemaPlaneConfig, SchemaSourceConfig
from parrot.knowledge.wiki.schema.service import SchemaPlaneService


class FakeToolkit:
    """Minimal live-producer toolkit that records describe calls."""

    def __init__(self, metadata: TableMetadata) -> None:
        self.metadata = metadata
        self.calls = 0

    async def describe_table(self, schema: str, table: str) -> TableMetadata:
        self.calls += 1
        return self.metadata


@pytest.fixture
def sales_metadata() -> TableMetadata:
    """Return a deterministic complete sales-table record."""
    return TableMetadata(
        schema="epson", tablename="sales", table_type="BASE TABLE", full_name="epson.sales",
        columns=[{"name": "id", "type": "INT", "nullable": False}], primary_keys=["id"],
        completeness=Completeness.FULL, source="information_schema",
    )


@pytest.fixture
def schema_service(tmp_path: Path) -> SchemaPlaneService:
    """Return an isolated writable schema plane."""
    config = SchemaPlaneConfig(sources={"bigquery": SchemaSourceConfig(
        alias="bigquery", dialect="bigquery", dsn_env="TEST_DSN", allowed_schemas=["epson"], tables=["epson.sales"]
    )})
    return SchemaPlaneService.from_dir(tmp_path / "schema", config=config, read_only=False)


async def test_sync_then_unchanged_and_lookup(schema_service: SchemaPlaneService, sales_metadata: TableMetadata) -> None:
    """Sync reports creation then unchanged content and normalizes lookup refs."""
    toolkit = FakeToolkit(sales_metadata)
    first = await schema_service.sync("bigquery", dsn_resolver=lambda _: "dsn", toolkit=toolkit)
    second = await schema_service.sync("bigquery", dsn_resolver=lambda _: "dsn", toolkit=toolkit, changed_only=True)
    assert first.created == ["table:bigquery/epson.sales"]
    assert second.unchanged == ["table:bigquery/epson.sales"]
    assert await schema_service.lookup("bigquery:epson.sales") == await schema_service.lookup("table:bigquery/epson.sales")


async def test_read_only_service_refuses_put(tmp_path: Path, sales_metadata: TableMetadata) -> None:
    """A rootless read-only service refuses cache write-through."""
    writable = SchemaPlaneService.from_dir(tmp_path / "schema", read_only=False)
    await writable.put_table("bigquery", "bigquery", sales_metadata)
    readonly = SchemaPlaneService.from_dir(tmp_path / "schema")
    with pytest.raises(PermissionError):
        await readonly.put_table("bigquery", "bigquery", sales_metadata)

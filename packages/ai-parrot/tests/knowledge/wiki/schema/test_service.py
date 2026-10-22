"""Focused tests for the schema-plane service."""

from pathlib import Path

import pytest

from parrot.bots.database.models import Completeness, TableMetadata
from parrot.knowledge.wiki.mcp_server import create_wiki_mcp_server
from parrot.knowledge.wiki.project import WikiProjectConfig, save_project_config
from parrot.knowledge.wiki.schema.models import SchemaPlaneConfig, SchemaSourceConfig
from parrot.knowledge.wiki.schema.service import SchemaPlaneService
from parrot.knowledge.wiki.store import create_wiki_store


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
        schema="epson",
        tablename="sales",
        table_type="BASE TABLE",
        full_name="epson.sales",
        columns=[{"name": "id", "type": "INT", "nullable": False}],
        primary_keys=["id"],
        completeness=Completeness.FULL,
        source="information_schema",
    )


@pytest.fixture
def schema_service(tmp_path: Path) -> SchemaPlaneService:
    """Return an isolated writable schema plane."""
    config = SchemaPlaneConfig(
        sources={
            "bigquery": SchemaSourceConfig(
                alias="bigquery",
                dialect="bigquery",
                dsn_env="TEST_DSN",
                allowed_schemas=["epson"],
                tables=["epson.sales"],
            )
        }
    )
    return SchemaPlaneService.from_dir(tmp_path / "schema", config=config, read_only=False)


async def test_sync_then_unchanged_and_lookup(
    schema_service: SchemaPlaneService, sales_metadata: TableMetadata
) -> None:
    """Sync reports creation then unchanged content and normalizes lookup refs."""
    toolkit = FakeToolkit(sales_metadata)
    first = await schema_service.sync("bigquery", dsn_resolver=lambda _: "dsn", toolkit=toolkit)
    second = await schema_service.sync("bigquery", dsn_resolver=lambda _: "dsn", toolkit=toolkit, changed_only=True)
    assert first.created == ["table:bigquery/epson.sales"]
    assert second.unchanged == ["table:bigquery/epson.sales"]
    # `age_days` is computed live from `datetime.now()` on every lookup() call, so two
    # calls microseconds apart will almost never produce bit-identical floats — compare
    # everything else for exact equality and only assert `age_days` is close.
    by_normalized_ref = await schema_service.lookup("bigquery:epson.sales")
    by_explicit_id = await schema_service.lookup("table:bigquery/epson.sales")
    assert by_normalized_ref.model_dump(exclude={"age_days"}) == by_explicit_id.model_dump(exclude={"age_days"})
    assert by_normalized_ref.age_days == pytest.approx(by_explicit_id.age_days, abs=1.0)


async def test_read_only_service_refuses_put(tmp_path: Path, sales_metadata: TableMetadata) -> None:
    """A rootless read-only service refuses cache write-through."""
    writable = SchemaPlaneService.from_dir(tmp_path / "schema", read_only=False)
    await writable.put_table("bigquery", "bigquery", sales_metadata)
    readonly = SchemaPlaneService.from_dir(tmp_path / "schema")
    with pytest.raises(PermissionError):
        await readonly.put_table("bigquery", "bigquery", sales_metadata)


SALES_ID = "table:bigquery/epson.sales"


def _source_config(table: str) -> SchemaPlaneConfig:
    """Return a one-table bigquery source configuration."""
    return SchemaPlaneConfig(
        sources={
            "bigquery": SchemaSourceConfig(
                alias="bigquery",
                dialect="bigquery",
                dsn_env="TEST_DSN",
                allowed_schemas=["epson"],
                tables=[table],
            )
        }
    )


def _mounted_project(root: Path) -> WikiProjectConfig:
    """Create a git-backed wiki project whose MCP server will mount the schema plane."""
    (root / ".git").mkdir()
    config = WikiProjectConfig(wiki_name="ac7")
    save_project_config(root, config)
    config.storage_path(root).mkdir(parents=True, exist_ok=True)
    create_wiki_store(config.storage_path(root), wiki_name=config.wiki_name, backend=config.backend)
    return config


async def _remember_about_sales(root: Path) -> tuple[object, str]:
    """Attach a note to epson.sales through the MCP wiki_remember tool; return the server and memory id."""
    server = create_wiki_mcp_server(root)
    remembered = await server.tools["wiki_remember"].tool._execute(
        fact="sales.store_id is the T-ROC store id", link_page_id=SALES_ID, rel="about"
    )
    assert remembered.success, remembered.error
    related = await server.tools["wiki_related"].tool._execute(page_id=SALES_ID)
    memory_id = next(row["concept_id"] for row in related.result["neighbors"] if row["rel"] == "about")
    return server, memory_id


async def test_sync_preserves_memory_annotations(tmp_path: Path, sales_metadata: TableMetadata) -> None:
    """FEAT-600 AC7: a wiki_remember note about a table appears in lookup and survives a schema sync."""
    config = _mounted_project(tmp_path)
    writable = SchemaPlaneService.from_dir(
        config.schema_path(tmp_path), config=_source_config("epson.sales"), read_only=False
    )
    await writable.sync("bigquery", dsn_resolver=lambda _: "dsn", toolkit=FakeToolkit(sales_metadata))
    server, memory_id = await _remember_about_sales(tmp_path)
    lookup = server.tools["wiki_schema_lookup"].tool

    before = await lookup._execute(ref=SALES_ID)
    assert [item["concept_id"] for item in before.result["annotations"]] == [memory_id]

    sales_metadata.columns.append({"name": "region", "type": "STRING", "nullable": True})
    report = await writable.sync("bigquery", dsn_resolver=lambda _: "dsn", toolkit=FakeToolkit(sales_metadata))
    assert report.updated == [SALES_ID]

    after = await lookup._execute(ref=SALES_ID)
    assert [item["concept_id"] for item in after.result["annotations"]] == [memory_id]
    assert "region" in {column["name"] for column in after.result["columns"]}


async def test_dropped_table_leaves_memory_note(tmp_path: Path, sales_metadata: TableMetadata) -> None:
    """Dropping the annotated table leaves a dangling edge, never a deleted note."""
    config = _mounted_project(tmp_path)
    plane = config.schema_path(tmp_path)
    await SchemaPlaneService.from_dir(plane, config=_source_config("epson.sales"), read_only=False).sync(
        "bigquery", dsn_resolver=lambda _: "dsn", toolkit=FakeToolkit(sales_metadata)
    )
    server, memory_id = await _remember_about_sales(tmp_path)

    stores = TableMetadata(
        schema="epson",
        tablename="stores",
        table_type="BASE TABLE",
        full_name="epson.stores",
        columns=[{"name": "id", "type": "INT", "nullable": False}],
        primary_keys=["id"],
        completeness=Completeness.FULL,
        source="information_schema",
    )
    report = await SchemaPlaneService.from_dir(plane, config=_source_config("epson.stores"), read_only=False).sync(
        "bigquery", dsn_resolver=lambda _: "dsn", toolkit=FakeToolkit(stores)
    )
    assert report.removed == [SALES_ID]

    gone = await server.tools["wiki_schema_lookup"].tool._execute(ref=SALES_ID)
    assert gone.success is False
    note = await server.tools["wiki_page"].tool._execute(page_id=memory_id)
    assert note.success, note.error

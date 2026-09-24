"""Tests for the FEAT-600 live schema producer."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.schema.models import SchemaSourceConfig
from parrot.knowledge.wiki.schema.producers.live import introspect, toolkit_for


class FakeToolkit:
    """Minimal injected toolkit that avoids database connections."""

    def __init__(self, metadata, *, failures: set[str] | None = None) -> None:
        """Initialize responses for describe and search calls."""
        self.metadata = metadata
        self.failures = failures or set()
        self.searched_schemas: list[str] = []

    async def describe_table(self, schema: str, table: str):
        """Return metadata or emulate an unavailable table."""
        if table in self.failures:
            raise RuntimeError("down")
        return self.metadata

    async def search_schema(self, search_term: str, *, schema_name: str, limit: int):
        """Return the metadata associated with the requested schema."""
        self.searched_schemas.append(schema_name)
        return [self.metadata]


@pytest.fixture
def cfg() -> SchemaSourceConfig:
    """Return a configured BigQuery schema source."""
    return SchemaSourceConfig(
        alias="bigquery",
        dialect="bigquery",
        dsn_env="SCHEMA_DSN",
        allowed_schemas=["epson"],
        tables=["epson.sales", "epson.broken"],
    )


async def test_partial_failure_and_sample_redaction(cfg: SchemaSourceConfig, sales_metadata) -> None:
    """A failed table is reported and non-allowlisted samples are removed."""
    sales_metadata.sample_data = [{"id": 1}]

    records, failed = await introspect(
        cfg, "bigquery://project", toolkit=FakeToolkit(sales_metadata, failures={"broken"})
    )

    assert [record.metadata.tablename for record in records] == ["sales"]
    assert "epson.broken" in failed
    assert records[0].metadata.sample_data == []
    assert records[0].introspected_at.endswith("+00:00")


async def test_allowlisted_sample_is_preserved(cfg: SchemaSourceConfig, sales_metadata) -> None:
    """The configured table allowlist preserves sample data."""
    cfg.tables = ["epson.sales"]
    cfg.include_samples = ["epson.sales"]
    sales_metadata.sample_data = [{"id": 1}]

    records, failed = await introspect(cfg, "bigquery://project", toolkit=FakeToolkit(sales_metadata))

    assert failed == {}
    assert records[0].metadata.sample_data == [{"id": 1}]


async def test_empty_table_config_discovers_only_allowed_schemas(sales_metadata) -> None:
    """Discovery searches each declared schema before describing its tables."""
    config = SchemaSourceConfig(
        alias="sqlite",
        dialect="sqlite",
        dsn_env="SCHEMA_DSN",
        allowed_schemas=["main"],
    )
    toolkit = FakeToolkit(sales_metadata)

    records, failed = await introspect(config, "sqlite:///schema.db", toolkit=toolkit)

    assert failed == {}
    assert toolkit.searched_schemas == ["main"]
    assert [record.metadata.tablename for record in records] == ["sales"]


@pytest.mark.parametrize(
    ("dialect", "expected_name"),
    [("postgres", "PostgresToolkit"), ("bigquery", "BigQueryToolkit"), ("sqlite", "SQLToolkit")],
)
def test_toolkit_choice(dialect: str, expected_name: str) -> None:
    """Dialect selection does not create a database connection."""
    config = SchemaSourceConfig(alias=dialect, dialect=dialect, dsn_env="SCHEMA_DSN")

    assert type(toolkit_for(config, f"{dialect}://source")).__name__ == expected_name

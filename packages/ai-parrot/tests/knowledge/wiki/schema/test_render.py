"""Tests for schema-page rendering (FEAT-600 M1)."""

from __future__ import annotations

from parrot.knowledge.wiki.schema.models import SchemaSourceConfig, TableRecord
from parrot.knowledge.wiki.schema.render import content_hash, render_ddl, render_page, render_source_page


def _record(metadata, dialect: str = "bigquery") -> TableRecord:
    """Build a deterministic schema record for rendering tests."""
    return TableRecord(
        origin=dialect,
        dialect=dialect,
        metadata=metadata,
        content_hash=content_hash(metadata),
        introspected_at="2026-09-24T00:00:00+00:00",
    )


def test_hash_ignores_volatile(sales_metadata) -> None:
    """Volatile metadata must not alter the content hash."""
    before = content_hash(sales_metadata)
    sales_metadata.row_count = 999
    assert content_hash(sales_metadata) == before
    sales_metadata.columns[0]["type"] = "STRING"
    assert content_hash(sales_metadata) != before


def test_ddl_stable_and_dialect_specific(sales_metadata) -> None:
    """SQL rendering is stable and reflects the requested dialect."""
    rendered = render_ddl(_record(sales_metadata))
    assert rendered == render_ddl(_record(sales_metadata))
    assert rendered != render_ddl(_record(sales_metadata, "postgres"))


def test_page_edges_and_fk_target(sales_metadata) -> None:
    """Foreign keys become side-table targets and plain reference edges."""
    page, columns, edges = render_page(_record(sales_metadata))
    assert page.concept_id == "table:bigquery/epson.sales"
    assert page.source_id == "schema:bigquery"
    assert "## DDL" in page.body
    assert "## Columns" in page.body
    assert "## Relations" in page.body
    assert next(column for column in columns if column.name == "store_id").fk_target == "table:bigquery/epson.stores.id"
    assert ("schema:bigquery/epson", "table:bigquery/epson.sales", "contains", "extracted") in edges
    assert ("table:bigquery/epson.sales", "table:bigquery/epson.stores", "references", "extracted") in edges


def test_source_page_contains_only_dsn_environment_name() -> None:
    """Source pages expose a credential reference, not the credential value."""
    page = render_source_page(SchemaSourceConfig(alias="warehouse", dialect="postgres", dsn_env="WAREHOUSE_DSN"))
    assert "WAREHOUSE_DSN" in page.body
    assert "postgresql://secret" not in page.body

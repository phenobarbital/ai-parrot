"""Tests for schema-plane records and project configuration."""

from pathlib import Path

from parrot.bots.database.models import TableMetadata
from parrot.knowledge.wiki.project import PARROT_DIR, WikiProjectConfig, load_project_config
from parrot.knowledge.wiki.schema.models import ColumnRecord, TableRecord


def test_project_config_has_enabled_schema(tmp_path: Path) -> None:
    """Schema config defaults to enabled and resolves its plane path."""
    config = WikiProjectConfig()
    assert config.schema.enabled is True
    assert config.schema_path(tmp_path) == tmp_path / PARROT_DIR / "schema"


def test_project_config_without_schema_loads(tmp_path: Path) -> None:
    """Existing wiki configuration without a schema block remains valid."""
    config_path = tmp_path / PARROT_DIR / "wiki.json"
    config_path.parent.mkdir()
    config_path.write_text('{"wiki_name": "example"}', encoding="utf-8")
    assert load_project_config(tmp_path).schema.enabled is True


def test_table_metadata_accepts_ddl_source() -> None:
    """DDL is an accepted metadata provenance literal."""
    metadata = TableMetadata(
        schema="public", tablename="example", table_type="BASE TABLE", full_name="public.example", source="ddl"
    )
    assert metadata.source == "ddl"


def test_table_record_allows_canonical_metadata(sales_metadata: TableMetadata) -> None:
    """Table records retain the canonical database metadata dataclass."""
    record = TableRecord(
        origin="postgres",
        dialect="postgres",
        metadata=sales_metadata,
        content_hash="hash",
        introspected_at="2026-09-24T00:00:00Z",
    )
    assert record.metadata is sales_metadata
    assert ColumnRecord(table_id="table:postgres/epson.sales", ordinal=1, name="id", data_type="INT64").nullable

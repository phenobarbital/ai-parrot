import pytest
import yaml

from parrot.bots.database.models import (
    Completeness,
    TableMetadata,
)


class TestCompleteness:
    def test_completeness_ordering(self):
        assert Completeness.NAME_ONLY < Completeness.WITH_COLUMNS
        assert Completeness.WITH_COLUMNS < Completeness.FULL

    def test_satisfies(self):
        meta = TableMetadata(
            schema="s", tablename="t", table_type="BASE TABLE",
            full_name="s.t", completeness=Completeness.WITH_COLUMNS,
        )
        assert meta.satisfies(Completeness.NAME_ONLY)
        assert meta.satisfies(Completeness.WITH_COLUMNS)
        assert not meta.satisfies(Completeness.FULL)

    def test_satisfies_full(self):
        meta = TableMetadata(
            schema="s", tablename="t", table_type="BASE TABLE",
            full_name="s.t", completeness=Completeness.FULL,
        )
        assert meta.satisfies(Completeness.NAME_ONLY)
        assert meta.satisfies(Completeness.WITH_COLUMNS)
        assert meta.satisfies(Completeness.FULL)

    def test_satisfies_name_only(self):
        meta = TableMetadata(
            schema="s", tablename="t", table_type="BASE TABLE",
            full_name="s.t", completeness=Completeness.NAME_ONLY,
        )
        assert meta.satisfies(Completeness.NAME_ONLY)
        assert not meta.satisfies(Completeness.WITH_COLUMNS)
        assert not meta.satisfies(Completeness.FULL)


class TestTableMetadataFields:
    def test_default_completeness_is_full(self):
        meta = TableMetadata(
            schema="s", tablename="t", table_type="BASE TABLE",
            full_name="s.t",
        )
        assert meta.completeness == Completeness.FULL
        assert meta.source == "unknown"
        assert meta.loaded_at is not None

    def test_explicit_completeness(self):
        meta = TableMetadata(
            schema="s", tablename="t", table_type="BASE TABLE",
            full_name="s.t", completeness=Completeness.NAME_ONLY,
            source="frontend",
        )
        assert meta.completeness == Completeness.NAME_ONLY
        assert meta.source == "frontend"

    def test_to_yaml_emits_warning_for_stubs(self):
        meta = TableMetadata(
            schema="pokemon", tablename="stores",
            table_type="BASE TABLE", full_name='"pokemon"."stores"',
            completeness=Completeness.NAME_ONLY, source="frontend",
        )
        raw = meta.to_yaml_context()
        data = yaml.safe_load(raw)
        assert "_warning" in data
        assert "db_describe_table" in data["_warning"]

    def test_to_yaml_emits_warning_for_with_columns(self):
        meta = TableMetadata(
            schema="s", tablename="t", table_type="BASE TABLE",
            full_name="s.t", completeness=Completeness.WITH_COLUMNS,
        )
        data = yaml.safe_load(meta.to_yaml_context())
        assert "_warning" in data

    def test_to_yaml_no_warning_for_full(self):
        meta = TableMetadata(
            schema="s", tablename="t", table_type="BASE TABLE",
            full_name="s.t",
            columns=[{"name": "id", "type": "int"}],
        )
        data = yaml.safe_load(meta.to_yaml_context())
        assert "_warning" not in data

    def test_to_yaml_emits_completeness_field(self):
        meta = TableMetadata(
            schema="s", tablename="t", table_type="BASE TABLE",
            full_name="s.t", completeness=Completeness.WITH_COLUMNS,
        )
        data = yaml.safe_load(meta.to_yaml_context())
        assert data["completeness"] == "WITH_COLUMNS"

    def test_to_yaml_emits_loaded_at_field(self):
        meta = TableMetadata(
            schema="s", tablename="t", table_type="BASE TABLE",
            full_name="s.t",
        )
        data = yaml.safe_load(meta.to_yaml_context())
        assert "loaded_at" in data
        assert data["loaded_at"] is not None

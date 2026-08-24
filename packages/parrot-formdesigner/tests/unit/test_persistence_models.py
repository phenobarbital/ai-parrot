"""Unit tests for `parrot_formdesigner.core.persistence` (FEAT-457, TASK-2417)."""

import pytest
from parrot_formdesigner.core.persistence import (
    CsvFileTarget,
    FormPersistenceConfig,
    PostgresTableTarget,
    SinkCapability,
)
from pydantic import ValidationError


class TestPersistenceModels:
    def test_union_discriminates_postgres(self):
        cfg = FormPersistenceConfig.model_validate(
            {
                "data": {
                    "type": "postgres_table",
                    "connection": "survey_db",
                    "schema_name": "surveys",
                    "table": "nps_2026",
                }
            }
        )
        assert isinstance(cfg.data, PostgresTableTarget)

    def test_rejects_raw_dsn(self):
        with pytest.raises(ValidationError):
            PostgresTableTarget(
                type="postgres_table",
                connection="x",
                schema_name="s",
                table="t",
                dsn="postgresql://u:p@h/db",
            )

    def test_rejects_invalid_identifier(self):
        with pytest.raises(ValueError):
            PostgresTableTarget(
                type="postgres_table",
                connection="x",
                schema_name="bad-schema!",
                table="t",
            )

    @pytest.mark.parametrize("bad", ["../../etc/passwd", "/etc/passwd", "a/../../b"])
    def test_rejects_path_traversal(self, bad):
        with pytest.raises(ValueError):
            CsvFileTarget(type="csv_file", connection="exports", path=bad)

    @pytest.mark.parametrize("bad", ["", "multi", ";;"])
    def test_rejects_invalid_delimiter_length(self, bad):
        with pytest.raises(ValueError):
            CsvFileTarget(type="csv_file", connection="exports", path="a.csv", delimiter=bad)

    def test_accepts_single_char_delimiter(self):
        target = CsvFileTarget(
            type="csv_file", connection="exports", path="a.csv", delimiter=";"
        )
        assert target.delimiter == ";"

    def test_capabilities_enum_members(self):
        assert {c.value for c in SinkCapability} == {
            "write",
            "read",
            "list",
            "provision",
            "extend",
        }

    def test_roundtrip(self):
        cfg = FormPersistenceConfig.model_validate(
            {"data": {"type": "csv_file", "connection": "exports", "path": "nps.csv"}}
        )
        assert FormPersistenceConfig.model_validate_json(cfg.model_dump_json()) == cfg

    def test_formschema_persistence_none_placeholder(self):
        """Sanity: constructing the union directly with each type works."""
        cfg = FormPersistenceConfig.model_validate(
            {
                "data": {
                    "type": "asyncdb",
                    "connection": "mongo_alias",
                    "driver": "mongo",
                    "collection": "responses",
                }
            }
        )
        assert cfg.data.driver == "mongo"

    def test_gsheet_target_defaults(self):
        cfg = FormPersistenceConfig.model_validate(
            {
                "data": {
                    "type": "gsheet",
                    "connection": "sheets_alias",
                    "spreadsheet_id": "abc123",
                }
            }
        )
        assert cfg.data.worksheet == "Sheet1"

    def test_definition_target_optional(self):
        cfg = FormPersistenceConfig.model_validate(
            {
                "data": {"type": "csv_file", "connection": "exports", "path": "nps.csv"},
                "definition": {
                    "type": "file",
                    "connection": "defs_alias",
                    "path": "nps_2026.form.yaml",
                },
            }
        )
        assert cfg.definition is not None
        assert cfg.definition.path == "nps_2026.form.yaml"

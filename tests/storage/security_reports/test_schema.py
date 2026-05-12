"""Static shape tests for parrot/storage/security_reports/schema.sql.

These tests parse the SQL file for correctness without a live Postgres
connection. Full idempotency tests require a live DB (see test_store.py
which gates on TEST_PG_DSN).
"""
from pathlib import Path

_TESTS_DIR = Path(__file__).parent.parent.parent.parent  # worktree root
SCHEMA_PATH = _TESTS_DIR / "packages" / "ai-parrot" / "src" / "parrot" / "storage" / "security_reports" / "schema.sql"


class TestSchemaSql:
    def test_file_exists(self):
        assert SCHEMA_PATH.exists(), f"schema.sql not found at {SCHEMA_PATH}"

    def test_idempotent_keywords_present(self):
        sql = SCHEMA_PATH.read_text()
        assert "CREATE TABLE IF NOT EXISTS security_reports" in sql
        assert (
            "CREATE INDEX IF NOT EXISTS idx_security_reports_scanner_framework_produced"
            in sql
        )
        assert (
            "CREATE INDEX IF NOT EXISTS idx_security_reports_kind_produced" in sql
        )
        assert (
            "CREATE INDEX IF NOT EXISTS idx_security_reports_scope_gin" in sql
        )

    def test_required_columns(self):
        sql = SCHEMA_PATH.read_text()
        required_columns = (
            "report_id",
            "report_kind",
            "scanner",
            "framework",
            "provider",
            "scope",
            "severity_summary",
            "top_findings",
            "uri",
            "content_type",
            "content_bytes",
            "produced_at",
            "produced_by",
            "parser_version",
            "retention_class",
            "created_at",
        )
        for col in required_columns:
            assert col in sql, f"Column '{col}' missing from schema.sql"

    def test_jsonb_columns(self):
        sql = SCHEMA_PATH.read_text()
        assert "scope               JSONB" in sql or "scope\t" in sql or "scope " in sql
        assert "JSONB" in sql

    def test_timestamptz_for_produced_at(self):
        sql = SCHEMA_PATH.read_text()
        assert "TIMESTAMPTZ" in sql
        # Verify produced_at uses TIMESTAMPTZ
        lines = [line.strip() for line in sql.splitlines()]
        produced_at_lines = [l for l in lines if "produced_at" in l]
        assert any("TIMESTAMPTZ" in l for l in produced_at_lines), (
            "produced_at must use TIMESTAMPTZ for tz-aware UTC storage"
        )

    def test_gin_index_on_scope(self):
        sql = SCHEMA_PATH.read_text()
        assert "USING GIN (scope)" in sql

    def test_uuid_primary_key(self):
        sql = SCHEMA_PATH.read_text()
        assert "UUID" in sql
        assert "PRIMARY KEY" in sql

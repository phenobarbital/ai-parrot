"""Regression coverage for retirement of manual bots migration scripts."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
LEGACY_MIGRATIONS = (
    "ai-bots-homologate-botmodel.sql",
    "FEAT-add-prompt-config-ai-bots.sql",
    "FEAT-593-ai-bots-tooling-columns.sql",
    "FEAT-752-ai-bots-suggestion-columns.sql",
    "FEAT-fold-embedding-model-into-vector-store-config.sql",
    "FEAT-fold-legacy-llm-columns.sql",
    "FEAT-fix-stale-bot-tool-names.sql",
    "FEAT-638-bot-language-nullable.sql",
)
AUTOMATIC_BOTS_SQL = ROOT / "packages/ai-parrot/src/parrot/migrations/sql/bots"
MANUAL_MIGRATIONS = ROOT / "sdd/migrations"
CREATION_SQL = ROOT / "packages/ai-parrot-server/src/parrot/handlers/creation.sql"
RECREATE_SQL = MANUAL_MIGRATIONS / "botmodel-recreate-table.sql"


@pytest.mark.parametrize("filename", LEGACY_MIGRATIONS)
def test_superseded_scripts_are_retired_after_packaged_chain_exists(filename: str) -> None:
    """Retire each legacy script only when the packaged bots chain is complete."""
    assert not (MANUAL_MIGRATIONS / filename).exists()
    assert [
        path.name for path in AUTOMATIC_BOTS_SQL.glob("[0-9][0-9][0-9]_*.sql") if not path.name.endswith(".check.sql")
    ] == [
        "001_baseline.sql",
        "002_fold_embedding.sql",
        "003_fold_llm.sql",
        "004_tool_names.sql",
        "005_language_schema.sql",
    ]


def test_manual_legacy_operations_are_guarded_and_not_packaged() -> None:
    """Keep users_bots operations explicit and outside the automatic wheel resources."""
    embedding = (MANUAL_MIGRATIONS / "users-bots-fold-embedding.sql").read_text(encoding="utf-8")
    reset = (MANUAL_MIGRATIONS / "manual-bot-language-reset.sql").read_text(encoding="utf-8")
    package_data = (ROOT / "packages/ai-parrot/pyproject.toml").read_text(encoding="utf-8")

    assert "MANUAL" in embedding
    assert "to_regclass('navigator.users_bots')" in embedding
    assert "attname = 'embedding_model'" in embedding
    assert "NOT (COALESCE(vector_config, '{}'::JSONB) ? 'embedding_model')" in embedding
    assert "MANUAL, LOSSY" in reset
    assert "backup" in reset.lower()
    assert "navigator.ai_bots" in reset
    assert "navigator.users_bots" in reset
    assert '"parrot.migrations" = ["sql/*/*.sql"]' in package_data
    assert "users-bots-fold-embedding.sql" not in package_data
    assert "manual-bot-language-reset.sql" not in package_data


def test_automatic_bots_sql_excludes_users_bots_and_lossy_language_reset() -> None:
    """Ensure the shipped bots chain preserves user-bot data and language values."""
    automatic_sql = "\n".join(path.read_text(encoding="utf-8") for path in AUTOMATIC_BOTS_SQL.glob("*.sql"))

    assert "users_bots" not in automatic_sql
    assert "SET language = NULL WHERE language = 'en'" not in automatic_sql


def test_bootstrap_suggestions_and_upgrade_pointer_are_current() -> None:
    """Keep fresh-install DDL aligned with the five FEAT-752 fields."""
    creation_sql = CREATION_SQL.read_text(encoding="utf-8")

    assert "parrot self migration upgrade" in creation_sql
    assert "(49 columns)" in creation_sql
    for column in (
        "enable_suggestions BOOLEAN DEFAULT FALSE",
        "suggest_followups BOOLEAN DEFAULT FALSE",
        "suggestion_timeout_s REAL DEFAULT 4.0",
        "max_suggestions INTEGER DEFAULT 6",
        "suggestion_model VARCHAR",
    ):
        assert column in creation_sql


def test_recreate_script_remains_explicitly_manual_and_destructive() -> None:
    """Prevent the emergency recreate script from looking like a normal upgrade."""
    recreate_sql = RECREATE_SQL.read_text(encoding="utf-8")

    assert "DROP TABLE IF EXISTS navigator.ai_bots CASCADE" in recreate_sql
    assert "MANUAL AND DESTRUCTIVE" in recreate_sql
    assert "parrot self migration upgrade" in recreate_sql

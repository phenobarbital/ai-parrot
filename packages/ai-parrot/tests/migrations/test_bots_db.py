"""Live behavioral coverage for the complete packaged bots migration chain."""

from __future__ import annotations

import importlib
import json
import os
import uuid
from collections.abc import AsyncIterator

import pytest

from parrot.migrations.catalog import load_migrations
from parrot.migrations.checks import status
from parrot.migrations.providers import bots_set
from parrot.migrations.runner import upgrade


@pytest.fixture
async def migration_target(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[object, str, str, str]]:
    """Provide an isolated target backed only by the explicit migration test DSN."""
    dsn = os.environ.get("PARROT_MIGRATION_TEST_DSN")
    if not dsn:
        pytest.skip("PARROT_MIGRATION_TEST_DSN is required for migration integration tests")
    asyncpg = importlib.import_module("asyncpg")
    schema = f"migration_test_{uuid.uuid4().hex[:16]}"
    table = f"bots_{uuid.uuid4().hex[:16]}"
    connection = await asyncpg.connect(dsn)
    await connection.execute(f'CREATE SCHEMA "{schema}"')
    monkeypatch.setattr("parrot.conf.PARROT_SCHEMA", schema)
    monkeypatch.setattr("parrot.conf.PARROT_BOTS_TABLE", table)
    try:
        yield connection, schema, table, dsn
    finally:
        await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await connection.close()


async def _upgrade(dsn: str) -> object:
    """Run the configured bots set against a disposable database target."""
    return await upgrade(dsn, sets=(bots_set(),))


def _json_value(value: object) -> object:
    """Decode asyncpg's default JSON text representation when necessary."""
    return json.loads(value) if isinstance(value, str) else value


def test_bots_fold_resources_are_complete_and_isolated() -> None:
    """Package the contiguous chain without any users_bots operations or transaction wrappers."""
    migrations = load_migrations(bots_set())

    assert [migration.filename for migration in migrations] == [
        "001_baseline.sql",
        "002_fold_embedding.sql",
        "003_fold_llm.sql",
        "004_tool_names.sql",
        "005_language_schema.sql",
    ]
    successors = migrations[1:]
    assert all("users_bots" not in migration.sql for migration in successors)
    assert all("BEGIN;" not in migration.sql and "COMMIT;" not in migration.sql for migration in successors)


@pytest.mark.asyncio
async def test_fresh_current_schema_replays_and_reports_healthy(
    migration_target: tuple[object, str, str, str],
) -> None:
    """Apply all successors to a fresh baseline and replay the completed chain safely."""
    connection, schema, table, dsn = migration_target

    first = await _upgrade(dsn)
    assert first.exit_code == 0
    assert first.applied == [
        "bots/001_baseline.sql",
        "bots/002_fold_embedding.sql",
        "bots/003_fold_llm.sql",
        "bots/004_tool_names.sql",
        "bots/005_language_schema.sql",
    ]
    assert await connection.fetchval("SELECT to_regclass($1) IS NULL", f'"{schema}"."users_bots"') is True
    replay = await _upgrade(dsn)
    assert replay.exit_code == 0
    assert replay.applied == []
    report = await status(dsn, sets=(bots_set(),))
    assert report.exit_code == 0
    assert all(item.postcondition_ok is True for item in report.items)
    language = await connection.fetchrow(
        "SELECT is_nullable, column_default FROM information_schema.columns "
        "WHERE table_schema = $1 AND table_name = $2 AND column_name = 'language'",
        schema,
        table,
    )
    assert dict(language) == {"is_nullable": "YES", "column_default": None}


@pytest.mark.asyncio
async def test_legacy_values_fold_without_overwriting_explicit_destinations(
    migration_target: tuple[object, str, str, str],
) -> None:
    """Preserve snapshots, explicit JSON values, arbitrary tools, and users_bots sentinels."""
    connection, schema, table, dsn = migration_target
    target = f'"{schema}"."{table}"'
    users_target = f'"{schema}"."users_bots"'
    await connection.execute(f"""CREATE TABLE {target} (
            chatbot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR NOT NULL UNIQUE,
            embedding_model JSONB,
            vector_store_config JSONB,
            model_name VARCHAR,
            temperature DOUBLE PRECISION,
            max_tokens INTEGER,
            top_k INTEGER,
            top_p DOUBLE PRECISION,
            model_config JSONB,
            tools JSONB,
            language VARCHAR(10) NOT NULL DEFAULT 'en'
        )""")
    await connection.execute(f"""INSERT INTO {target} (
            name, embedding_model, vector_store_config, model_name, temperature,
            max_tokens, top_k, top_p, model_config, tools, language
        ) VALUES
        (
            'legacy', '{{"model":"embed-column","provider":"local"}}', '{{"other":1}}',
            'llm-column', 0.25, 512, 8, 0.75, '{{"other":"keep"}}',
            '["before","WebScraperTool",{{"arbitrary":true}},"Ibis","Tickertool"]', 'en'
        ),
        (
            'explicit', '{{"model":"ignored"}}', '{{"embedding_model":null}}',
            'ignored-model', 0.5, 1024, 16, 0.9,
            '{{"model_name":null,"model":"explicit-model","temperature":null,"max_tokens":"keep","top_k":0,"top_p":false}}',
            '"incompatible-but-preserved"', 'es'
        ),
        (
            'sql-null', '{{"model":"embed-null"}}', NULL,
            'null-model', NULL, NULL, NULL, NULL, NULL, NULL, NULL
        )""")
    await connection.execute(
        f"CREATE TABLE {users_target} (marker TEXT, embedding_model JSONB, vector_config JSONB, language TEXT)"
    )
    await connection.execute(
        f"INSERT INTO {users_target} VALUES ('sentinel', '{{\"model\":\"user\"}}', '{{\"keep\":true}}', 'en')"
    )
    languages_before = [
        tuple(row) for row in await connection.fetch(f"SELECT name, language FROM {target} ORDER BY name")
    ]
    users_before = dict(await connection.fetchrow(f"SELECT * FROM {users_target}"))

    report = await _upgrade(dsn)

    assert report.exit_code == 0
    rows = {
        row["name"]: dict(row)
        for row in await connection.fetch(
            f"SELECT name, vector_store_config, model_config, tools, language FROM {target}"
        )
    }
    assert _json_value(rows["legacy"]["vector_store_config"]) == {
        "other": 1,
        "embedding_model": {"provider": "local", "model_name": "embed-column"},
    }
    assert _json_value(rows["legacy"]["model_config"]) == {
        "other": "keep",
        "model_name": "llm-column",
        "model": "llm-column",
        "temperature": 0.25,
        "max_tokens": 512,
        "top_k": 8,
        "top_p": 0.75,
    }
    assert _json_value(rows["legacy"]["tools"]) == [
        "before",
        "web_scraping",
        {"arbitrary": True},
        "ibisworld",
        "yfinance",
    ]
    assert _json_value(rows["explicit"]["vector_store_config"]) == {"embedding_model": None}
    assert _json_value(rows["explicit"]["model_config"]) == {
        "model_name": None,
        "model": "explicit-model",
        "temperature": None,
        "max_tokens": "keep",
        "top_k": 0,
        "top_p": False,
    }
    assert _json_value(rows["explicit"]["tools"]) == "incompatible-but-preserved"
    assert _json_value(rows["sql-null"]["vector_store_config"]) == {"embedding_model": {"model_name": "embed-null"}}
    assert _json_value(rows["sql-null"]["model_config"]) == {"model_name": "null-model", "model": "null-model"}
    languages_after = [
        tuple(row) for row in await connection.fetch(f"SELECT name, language FROM {target} ORDER BY name")
    ]
    assert languages_after == languages_before
    assert dict(await connection.fetchrow(f"SELECT * FROM {users_target}")) == users_before
    legacy_columns = await connection.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = $1 AND table_name = $2 "
        "AND column_name = ANY($3::text[])",
        schema,
        table,
        ["embedding_model", "model_name", "temperature", "max_tokens", "top_k", "top_p"],
    )
    assert legacy_columns == []


@pytest.mark.asyncio
async def test_partially_dropped_sources_normalize_independently(
    migration_target: tuple[object, str, str, str],
) -> None:
    """Normalize aliases and fold each remaining scalar when other legacy columns are absent."""
    connection, schema, table, dsn = migration_target
    target = f'"{schema}"."{table}"'
    await connection.execute(f"""CREATE TABLE {target} (
            chatbot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR NOT NULL UNIQUE,
            vector_store_config JSONB,
            model_config JSONB,
            temperature DOUBLE PRECISION,
            language VARCHAR(10)
        )""")
    await connection.execute(
        f"INSERT INTO {target} (name, vector_store_config, model_config, temperature) VALUES ("
        '\'partial\', \'{"embedding_model":{"model":"embed-only"}}\', '
        '\'{"model_name":"llm-only"}\', 0.4)'
    )

    report = await _upgrade(dsn)

    assert report.exit_code == 0
    row = await connection.fetchrow(f"SELECT vector_store_config, model_config FROM {target}")
    assert _json_value(row["vector_store_config"]) == {"embedding_model": {"model_name": "embed-only"}}
    assert _json_value(row["model_config"]) == {
        "model_name": "llm-only",
        "model": "llm-only",
        "temperature": 0.4,
    }


@pytest.mark.asyncio
async def test_incompatible_config_rolls_back_backfill_and_drop_atomically(
    migration_target: tuple[object, str, str, str],
) -> None:
    """Retain the source column and value when its destination cannot safely accept a backfill."""
    connection, schema, table, dsn = migration_target
    target = f'"{schema}"."{table}"'
    await connection.execute(f"""CREATE TABLE {target} (
            chatbot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR NOT NULL UNIQUE,
            embedding_model JSONB,
            vector_store_config JSONB,
            language VARCHAR(10)
        )""")
    await connection.execute(
        f"INSERT INTO {target} (name, embedding_model, vector_store_config) "
        "VALUES ('broken', '{\"model\":\"must-survive\"}', '7')"
    )

    report = await _upgrade(dsn)

    assert report.exit_code == 2
    assert report.failed == ["bots/002_fold_embedding.sql"]
    assert report.skipped == [
        "bots/003_fold_llm.sql",
        "bots/004_tool_names.sql",
        "bots/005_language_schema.sql",
    ]
    assert (
        await connection.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = $1 AND table_name = $2 AND column_name = 'embedding_model')",
            schema,
            table,
        )
        is True
    )
    assert await connection.fetchval(f"SELECT embedding_model->>'model' FROM {target}") == "must-survive"
    assert _json_value(await connection.fetchval(f"SELECT vector_store_config FROM {target}")) == 7

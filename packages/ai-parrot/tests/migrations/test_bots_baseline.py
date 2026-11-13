"""Live behavioral coverage for the non-destructive bots baseline."""

from __future__ import annotations

import importlib
import os
import uuid
from collections.abc import AsyncIterator

import pytest

from parrot.migrations.catalog import load_migrations
from parrot.migrations.providers import bots_set
from parrot.migrations.runner import upgrade


@pytest.fixture
async def migration_target(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[object, str, str]]:
    """Provide an isolated configured target using only the migration test DSN."""
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
        yield connection, schema, table
    finally:
        await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await connection.close()


async def _upgrade() -> object:
    """Run only the configured bots baseline against the disposable target."""
    dsn = os.environ["PARROT_MIGRATION_TEST_DSN"]
    return await upgrade(dsn, sets=(bots_set(),))


def test_bots_baseline_resources_are_discoverable() -> None:
    """Expose one executable body/check pair through the packaged bots provider."""
    migrations = load_migrations(bots_set())

    assert [(migration.filename, migration.sequence) for migration in migrations] == [("001_baseline.sql", 1)]
    assert "CREATE TABLE IF NOT EXISTS" in migrations[0].sql
    assert migrations[0].check_sql.lstrip().startswith("-- FEAT-884")
    assert "SELECT COALESCE(" in migrations[0].check_sql


@pytest.mark.asyncio
async def test_fresh_baseline_has_full_shape_no_seeds_and_replays(
    migration_target: tuple[object, str, str],
) -> None:
    """Create the complete schema without examples or uuid-ossp and replay safely."""
    connection, schema, table = migration_target

    first = await _upgrade()
    assert first.exit_code == 0
    assert first.applied == ["bots/001_baseline.sql"]
    columns = await connection.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = $1 AND table_name = $2 ORDER BY ordinal_position",
        schema,
        table,
    )
    assert len(columns) == 49
    assert await connection.fetchval(f'SELECT count(*) FROM "{schema}"."{table}"') == 0
    default = await connection.fetchval(
        "SELECT pg_get_expr(defaults.adbin, defaults.adrelid) "
        "FROM pg_catalog.pg_attrdef AS defaults "
        "JOIN pg_catalog.pg_attribute AS attribute "
        "ON attribute.attrelid = defaults.adrelid AND attribute.attnum = defaults.adnum "
        "WHERE defaults.adrelid = $1::regclass AND attribute.attname = 'chatbot_id'",
        f'"{schema}"."{table}"',
    )
    assert "gen_random_uuid" in default
    assert await connection.fetchval("SELECT to_regnamespace('uuid_ossp') IS NULL") is True

    replay = await _upgrade()
    assert replay.exit_code == 0
    assert replay.applied == []


@pytest.mark.asyncio
async def test_legacy_row_is_preserved_and_missing_tooling_is_added(
    migration_target: tuple[object, str, str],
) -> None:
    """Catch up a partial legacy table without changing its stored row or UUID default."""
    connection, schema, table = migration_target
    await connection.execute(f"""CREATE TABLE "{schema}"."{table}" (
            chatbot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR NOT NULL,
            description TEXT,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            goal TEXT NOT NULL DEFAULT 'goal',
            backstory TEXT NOT NULL DEFAULT 'backstory',
            rationale TEXT NOT NULL DEFAULT 'rationale'
        )""")
    identifier = uuid.uuid4()
    await connection.execute(
        f'INSERT INTO "{schema}"."{table}" (chatbot_id, name, description) VALUES ($1, $2, $3)',
        identifier,
        "legacy",
        "preserved",
    )

    report = await _upgrade()
    assert report.exit_code == 0
    row = await connection.fetchrow(
        f"SELECT chatbot_id, name, description, toolkit_config, mcp_servers, enable_suggestions "
        f'FROM "{schema}"."{table}" WHERE chatbot_id = $1',
        identifier,
    )
    assert dict(row) == {
        "chatbot_id": identifier,
        "name": "legacy",
        "description": "preserved",
        "toolkit_config": {},
        "mcp_servers": [],
        "enable_suggestions": False,
    }
    assert (
        await connection.fetchval(
            f'INSERT INTO "{schema}"."{table}" (name) VALUES ($1) RETURNING chatbot_id', "uuid-default"
        )
        is not None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("statements", "message"),
    [
        (("CREATE TABLE {target} (chatbot_id TEXT PRIMARY KEY, name VARCHAR NOT NULL)",), "incompatible type"),
        (
            (
                "CREATE TABLE {target} (name VARCHAR NOT NULL)",
                "INSERT INTO {target} (name) VALUES ('legacy')",
            ),
            "identity",
        ),
    ],
)
async def test_incompatible_or_identityless_nonempty_legacy_tables_are_rejected(
    migration_target: tuple[object, str, str], statements: tuple[str, ...], message: str
) -> None:
    """Reject unsafe legacy shapes before additive DDL can invent or coerce data."""
    connection, schema, table = migration_target
    target = f'"{schema}"."{table}"'
    for statement in statements:
        await connection.execute(statement.format(target=target))

    report = await _upgrade()
    assert report.exit_code == 2
    assert any(message in diagnostic.lower() for diagnostic in report.diagnostics)


@pytest.mark.asyncio
async def test_custom_targets_have_distinct_scoped_objects_and_valid_postcondition(
    migration_target: tuple[object, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure independently configured custom targets do not collide."""
    connection, schema, first_table = migration_target
    first = await _upgrade()
    assert first.exit_code == 0
    second_schema = f"migration_test_{uuid.uuid4().hex[:16]}"
    second_table = f"bots_{uuid.uuid4().hex[:16]}"
    await connection.execute(f'CREATE SCHEMA "{second_schema}"')
    monkeypatch.setattr("parrot.conf.PARROT_SCHEMA", second_schema)
    monkeypatch.setattr("parrot.conf.PARROT_BOTS_TABLE", second_table)
    try:
        second = await _upgrade()
        assert second.exit_code == 0
        names = await connection.fetch(
            "SELECT namespace.nspname, relation.relname FROM pg_catalog.pg_class AS relation "
            "JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace "
            "WHERE namespace.nspname = ANY($1::text[]) AND relation.relkind = 'i' "
            "AND relation.relname LIKE 'parrot_%'",
            [schema, second_schema],
        )
        assert len({row["relname"] for row in names}) == len(names)
    finally:
        await connection.execute(f'DROP SCHEMA IF EXISTS "{second_schema}" CASCADE')

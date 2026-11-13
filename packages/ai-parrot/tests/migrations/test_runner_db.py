"""Live PostgreSQL coverage for migration runner transactions and locking."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import uuid
from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest

from parrot.migrations.catalog import load_migrations
from parrot.migrations.checks import status
from parrot.migrations.providers import bots_set
from parrot.migrations import runner as migration_runner
from parrot.migrations.runner import baseline, upgrade


@pytest.fixture
async def migration_target(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[object, str, str, str]]:
    """Provide an isolated schema using only PARROT_MIGRATION_TEST_DSN."""
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


def _target(schema: str, table: str) -> str:
    """Return a quoted disposable target relation."""
    return f'"{schema}"."{table}"'


async def _ledger_rows(connection: object, schema: str) -> list[dict[str, object]]:
    """Read the disposable ledger without relying on application stores."""
    rows = await connection.fetch(f'SELECT * FROM "{schema}"."parrot_schema_migrations" ORDER BY filename')
    return [dict(row) for row in rows]


@pytest.mark.asyncio
async def test_concurrent_runners_create_one_ledger_and_apply_once(
    migration_target: tuple[object, str, str, str],
) -> None:
    """Serialize two first-use runners and record each migration exactly once."""
    connection, schema, table, dsn = migration_target

    first, second = await asyncio.gather(
        upgrade(dsn, sets=(bots_set(),)),
        upgrade(dsn, sets=(bots_set(),)),
    )

    assert sorted((first.exit_code, second.exit_code)) == [0, 0]
    assert sorted((len(first.applied), len(second.applied))) == [0, 5]
    assert len(await _ledger_rows(connection, schema)) == 5


@pytest.mark.asyncio
async def test_lock_deadline_does_not_create_ledger(
    migration_target: tuple[object, str, str, str],
) -> None:
    """Report bounded lock contention before creating migration objects."""
    connection, schema, _table, dsn = migration_target
    asyncpg = importlib.import_module("asyncpg")
    holder = await asyncpg.connect(dsn)
    try:
        await holder.execute("SELECT pg_advisory_lock(884000001)")
        report = await upgrade(dsn, sets=(bots_set(),), lock_timeout=0.05)
    finally:
        await holder.execute("SELECT pg_advisory_unlock(884000001)")
        await holder.close()

    assert report.exit_code == 2
    assert await connection.fetchval("SELECT to_regclass($1) IS NULL", f'"{schema}"."parrot_schema_migrations"')


@pytest.mark.asyncio
async def test_failed_body_rolls_back_stamp_and_skips_successors(
    migration_target: tuple[object, str, str, str],
) -> None:
    """Keep failed DDL out of the ledger and stop only the dependent suffix."""
    connection, schema, table, dsn = migration_target
    await connection.execute(f'CREATE TABLE {_target(schema, table)} (chatbot_id TEXT PRIMARY KEY, name TEXT NOT NULL)')

    report = await upgrade(dsn, sets=(bots_set(),))

    assert report.exit_code == 2
    assert report.failed == ["bots/001_baseline.sql"]
    assert report.skipped == [
        "bots/002_fold_embedding.sql",
        "bots/003_fold_llm.sql",
        "bots/004_tool_names.sql",
        "bots/005_language_schema.sql",
    ]
    assert await connection.fetchval("SELECT count(*) FROM pg_catalog.pg_tables WHERE tablename = $1", table) == 1
    assert await connection.fetchval(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = $1 "
        "AND table_name = 'parrot_schema_migrations'",
        schema,
    ) == 1
    assert await connection.fetchval(
        f'SELECT count(*) FROM "{schema}"."parrot_schema_migrations"'
    ) == 0


@pytest.mark.asyncio
async def test_baseline_stamps_verified_prefix_without_bodies_or_partial_rows(
    migration_target: tuple[object, str, str, str],
) -> None:
    """Adopt an existing schema through one verified file and leave successors pending."""
    connection, schema, _table, dsn = migration_target
    initial = await upgrade(dsn, sets=(bots_set(),))
    assert initial.exit_code == 0
    await connection.execute(f'DROP TABLE "{schema}"."parrot_schema_migrations"')

    report = await baseline(dsn, migration_set=bots_set(), through=1)
    states = await status(dsn, sets=(bots_set(),))

    assert report.exit_code == 0
    assert report.applied == ["bots/001_baseline.sql"]
    assert [item.state for item in states.items] == ["APPLIED", "PENDING", "PENDING", "PENDING", "PENDING"]
    assert len(await _ledger_rows(connection, schema)) == 1


@pytest.mark.asyncio
async def test_changed_body_and_check_require_reapply_and_reapply_rechecks_set(
    migration_target: tuple[object, str, str, str],
) -> None:
    """Detect either immutable hash change and permit only explicit whole-set repair."""
    connection, schema, _table, dsn = migration_target
    applied = await upgrade(dsn, sets=(bots_set(),))
    assert applied.exit_code == 0
    first = await connection.fetchrow(
        f'SELECT filename FROM "{schema}"."parrot_schema_migrations" WHERE filename = $1', "001_baseline.sql"
    )
    assert first is not None

    await connection.execute(
        f'UPDATE "{schema}"."parrot_schema_migrations" SET checksum = $1 WHERE filename = $2',
        "changed-body",
        "001_baseline.sql",
    )
    changed_body = await status(dsn, sets=(bots_set(),))
    blocked_body = await upgrade(dsn, sets=(bots_set(),))
    assert changed_body.items[0].state == "CHANGED"
    assert blocked_body.exit_code == 1

    await connection.execute(
        f'UPDATE "{schema}"."parrot_schema_migrations" SET checksum = $1, check_checksum = $2 '
        "WHERE filename = $3",
        load_migrations(bots_set())[0].checksum,
        "changed-check",
        "001_baseline.sql",
    )
    changed_check = await status(dsn, sets=(bots_set(),))
    repaired = await upgrade(dsn, sets=(bots_set(),), reapply_changed=True)

    assert changed_check.items[0].state == "CHANGED"
    assert repaired.exit_code == 0
    assert repaired.failed == []
    repaired_status = await status(dsn, sets=(bots_set(),))
    assert repaired_status.exit_code == 0


@pytest.mark.asyncio
async def test_cancellation_unlocks_connection_and_allows_next_runner(
    migration_target: tuple[object, str, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Propagate cancellation only after the transaction and advisory lock are cleaned up."""
    _connection, _schema, _table, dsn = migration_target

    async def cancel_check(*_args: object, **_kwargs: object) -> tuple[str, ...]:
        """Cancel while the runner owns its dedicated locked connection."""
        raise asyncio.CancelledError()

    original_check = migration_runner.verify_postconditions
    monkeypatch.setattr("parrot.migrations.runner.verify_postconditions", cancel_check)
    with pytest.raises(asyncio.CancelledError):
        await upgrade(dsn, sets=(bots_set(),))

    monkeypatch.setattr("parrot.migrations.runner.verify_postconditions", original_check)
    report = await upgrade(dsn, sets=(bots_set(),))
    assert report.exit_code == 0


@pytest.mark.asyncio
async def test_unknown_selected_filename_is_an_error_without_body_execution(
    migration_target: tuple[object, str, str, str],
) -> None:
    """Reject an unknown selected ledger row rather than ignoring history."""
    connection, schema, _table, dsn = migration_target
    await upgrade(dsn, sets=(bots_set(),))
    await connection.execute(
        f'INSERT INTO "{schema}"."parrot_schema_migrations" '
        "(migration_set, filename, checksum, check_checksum, target_identity, operation) "
        "VALUES ('bots', '999_unknown.sql', 'body', 'check', $1::jsonb, 'upgrade')",
        json.dumps({"tables": [f"{schema}.{_table}"]}),
    )

    report = await upgrade(dsn, sets=(bots_set(),))

    assert report.exit_code == 2
    assert any("unknown selected entry" in diagnostic for diagnostic in report.diagnostics)


@pytest.mark.asyncio
async def test_target_identity_change_and_reserved_ledger_target_are_not_successful(
    migration_target: tuple[object, str, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a changed owner identity and prevent the ledger from becoming a target table."""
    connection, schema, table, dsn = migration_target
    await upgrade(dsn, sets=(bots_set(),))

    changed_table = f"bots_{uuid.uuid4().hex[:16]}"
    monkeypatch.setattr("parrot.conf.PARROT_BOTS_TABLE", changed_table)
    changed = await upgrade(dsn, sets=(bots_set(),))
    assert changed.exit_code == 2
    assert any("target identity mismatch" in diagnostic for diagnostic in changed.diagnostics)

    await connection.execute(f'DROP TABLE "{schema}"."{table}"')
    await connection.execute(f'DROP TABLE "{schema}"."parrot_schema_migrations"')
    monkeypatch.setattr("parrot.conf.PARROT_BOTS_TABLE", "parrot_schema_migrations")
    collision = await upgrade(dsn, sets=(bots_set(),))
    assert collision.exit_code == 2
    assert not await connection.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = $1 "
        "AND table_name = 'parrot_schema_migrations' AND column_name = 'chatbot_id')",
        schema,
    )


@pytest.mark.asyncio
async def test_status_is_read_only_and_denied_select_is_not_healthy(
    migration_target: tuple[object, str, str, str],
) -> None:
    """Keep a fresh status probe from creating a ledger or claiming healthy state."""
    connection, schema, _table, dsn = migration_target

    report = await status(dsn, sets=(bots_set(),))

    assert report.exit_code == 1
    assert report.failed
    assert await connection.fetchval("SELECT to_regclass($1) IS NULL", f'"{schema}"."parrot_schema_migrations"')


@pytest.mark.asyncio
async def test_separate_ledgers_share_the_database_advisory_lock(
    migration_target: tuple[object, str, str, str],
) -> None:
    """Apply two isolated schemas concurrently while using one database-wide lock."""
    connection, first_schema, _first_table, dsn = migration_target
    second_schema = f"migration_test_{uuid.uuid4().hex[:16]}"
    second_table = f"bots_{uuid.uuid4().hex[:16]}"
    await connection.execute(f'CREATE SCHEMA "{second_schema}"')

    async def run(schema: str, table: str) -> object:
        """Run one migration with configuration isolated before its first await."""
        import parrot.conf as conf

        with patch.object(conf, "PARROT_SCHEMA", schema), patch.object(conf, "PARROT_BOTS_TABLE", table):
            return await upgrade(dsn, sets=(bots_set(),))

    try:
        first, second = await asyncio.gather(
            run(first_schema, f"bots_{uuid.uuid4().hex[:16]}"),
            run(second_schema, second_table),
        )
        assert first.exit_code == 0
        assert second.exit_code == 0
        assert await connection.fetchval(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = $1 "
            "AND table_name = 'parrot_schema_migrations'",
            first_schema,
        ) == 1
        assert await connection.fetchval(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = $1 "
            "AND table_name = 'parrot_schema_migrations'",
            second_schema,
        ) == 1
    finally:
        await connection.execute(f'DROP SCHEMA IF EXISTS "{second_schema}" CASCADE')

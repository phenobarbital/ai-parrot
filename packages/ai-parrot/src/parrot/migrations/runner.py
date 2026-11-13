"""Explicit deployment-time upgrades and verified adoption."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from .catalog import load_migrations, render_sql
from .checks import verify_postconditions
from .models import MigrationItem, MigrationReport, MigrationSet

if TYPE_CHECKING:
    from .models import MigrationFile


_ADVISORY_LOCK = 884000001
_LEDGER_TABLE = "parrot_schema_migrations"
_IDENTIFIER_RE = re.compile(r"[a-z_][a-z0-9_]{0,62}\Z")


def _identity(migration: "MigrationFile") -> str:
    """Return the stable public identity for one migration file."""
    return f"{migration.migration_set}/{migration.filename}"


def _quote_identifier(value: str, label: str) -> str:
    """Validate and quote an identifier used in runner-generated SQL."""
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"Invalid {label} identifier")
    return f'"{value}"'


def _ledger_name(schema: str) -> str:
    """Return the fully qualified, validated ledger name."""
    return f"{_quote_identifier(schema, 'schema')}.{_quote_identifier(_LEDGER_TABLE, 'ledger table')}"


def _target_identity(migration_set: MigrationSet) -> tuple[str, ...]:
    """Validate and return the immutable configured target identity."""
    identity: list[str] = []
    for target in migration_set.tables:
        schema, separator, relation = target.partition(".")
        if not separator or "." in relation:
            raise ValueError("Invalid migration target identity")
        _quote_identifier(schema, "target schema")
        _quote_identifier(relation, "target relation")
        identity.append(f"{schema}.{relation}")
    return tuple(identity)


def _recorded_identity(value: object) -> tuple[str, ...] | None:
    """Decode a structured ledger identity without accepting arbitrary JSON.

    asyncpg returns jsonb columns as JSON text unless a codec is registered, so decode text first.
    """
    if isinstance(value, (str, bytes)):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    tables = value.get("tables") if isinstance(value, Mapping) else value
    if not isinstance(tables, Sequence) or isinstance(tables, (str, bytes)):
        return None
    if not all(isinstance(table, str) for table in tables):
        return None
    return tuple(tables)


def _safe_diagnostic(error: BaseException) -> str:
    """Map a database exception to a credential-free report message."""
    sqlstate = getattr(error, "sqlstate", None)
    if sqlstate == "42501":
        return "Database permission denied"
    if isinstance(sqlstate, str) and re.fullmatch(r"[0-9A-Z]{5}", sqlstate):
        return f"Migration database failure (SQLSTATE {sqlstate})"
    return "Migration database failure"


def _validate_timeouts(connect_timeout: float, lock_timeout: float, statement_timeout: float) -> None:
    """Reject non-positive timeout values before opening a connection."""
    if connect_timeout <= 0 or lock_timeout <= 0 or statement_timeout <= 0:
        raise ValueError("Migration timeouts must be positive")


async def _acquire_lock(connection: object, timeout: float) -> None:
    """Acquire the deployment-wide advisory lock before observing or mutating state."""
    deadline = time.monotonic() + timeout
    while True:
        locked = await connection.fetchval("SELECT pg_try_advisory_lock($1)", _ADVISORY_LOCK)  # type: ignore[attr-defined]
        if locked is True:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Migration lock acquisition timed out")
        await asyncio.sleep(min(0.1, remaining))


async def _create_ledger(connection: object, schema: str) -> None:
    """Create the schema and exact migration ledger while the advisory lock is held."""
    quoted_schema = _quote_identifier(schema, "schema")
    ledger = _ledger_name(schema)
    await connection.execute(f"CREATE SCHEMA IF NOT EXISTS {quoted_schema}")  # type: ignore[attr-defined]
    await connection.execute(  # type: ignore[attr-defined]
        f"CREATE TABLE IF NOT EXISTS {ledger} ("
        "migration_set text NOT NULL, "
        "filename text NOT NULL, "
        "checksum text NOT NULL, "
        "check_checksum text NOT NULL, "
        "target_identity jsonb NOT NULL, "
        "applied_at timestamptz NOT NULL DEFAULT now(), "
        "applied_by text NOT NULL DEFAULT current_user, "
        "operation text NOT NULL CHECK (operation IN ('upgrade', 'baseline', 'reapply')), "
        "PRIMARY KEY (migration_set, filename)"
        ")"
    )


async def _ledger_exists(connection: object, schema: str) -> bool:
    """Return whether the configured ledger exists without creating it."""
    return await connection.fetchval("SELECT to_regclass($1) IS NOT NULL", _ledger_name(schema)) is True  # type: ignore[attr-defined]


async def _read_ledger(connection: object, schema: str, set_names: tuple[str, ...]) -> list[Mapping[str, object]]:
    """Read all selected set rows under the caller's already-held lock."""
    rows = await connection.fetch(  # type: ignore[attr-defined]
        "SELECT migration_set, filename, checksum, check_checksum, target_identity "
        f"FROM {_ledger_name(schema)} WHERE migration_set = ANY($1::text[])",
        list(set_names),
    )
    return [dict(row) for row in rows]


def _ledger_state(
    rows: Sequence[Mapping[str, object]],
    migrations: dict[str, tuple["MigrationFile", ...]],
    sets: tuple[MigrationSet, ...],
) -> tuple[dict[tuple[str, str], Mapping[str, object]], list[str]]:
    """Validate selected ledger history and return its keyed valid rows."""
    known = {
        (migration.migration_set, migration.filename): migration
        for migration_files in migrations.values()
        for migration in migration_files
    }
    identities = {migration_set.name: _target_identity(migration_set) for migration_set in sets}
    row_map: dict[tuple[str, str], Mapping[str, object]] = {}
    diagnostics: list[str] = []
    for row in rows:
        migration_set = row.get("migration_set")
        filename = row.get("filename")
        if not isinstance(migration_set, str) or not isinstance(filename, str):
            diagnostics.append("Migration ledger contains an invalid selected row")
            continue
        key = (migration_set, filename)
        if key not in known:
            diagnostics.append(f"Migration ledger contains an unknown selected entry: {migration_set}/{filename}")
            continue
        if _recorded_identity(row.get("target_identity")) != identities[migration_set]:
            diagnostics.append(f"Migration target identity mismatch: {migration_set}")
            continue
        row_map[key] = row
    return row_map, diagnostics


def _state(row: Mapping[str, object] | None, migration: "MigrationFile") -> str:
    """Classify a migration file from a validated ledger row."""
    if row is None:
        return "PENDING"
    if row.get("checksum") != migration.checksum or row.get("check_checksum") != migration.check_checksum:
        return "CHANGED"
    return "APPLIED"


async def _stamp(
    connection: object, migration: "MigrationFile", migration_set: MigrationSet, schema: str, operation: str
) -> None:
    """Insert or update one verified ledger record in its body transaction."""
    await connection.execute(  # type: ignore[attr-defined]
        f"INSERT INTO {_ledger_name(schema)} "
        "(migration_set, filename, checksum, check_checksum, target_identity, operation) "
        "VALUES ($1, $2, $3, $4, $5::jsonb, $6) "
        "ON CONFLICT (migration_set, filename) DO UPDATE SET "
        "checksum = EXCLUDED.checksum, check_checksum = EXCLUDED.check_checksum, "
        "target_identity = EXCLUDED.target_identity, operation = EXCLUDED.operation",
        migration.migration_set,
        migration.filename,
        migration.checksum,
        migration.check_checksum,
        json.dumps({"tables": list(_target_identity(migration_set))}),
        operation,
    )


def _report(
    sets: tuple[MigrationSet, ...],
    migrations: dict[str, tuple["MigrationFile", ...]],
    states: dict[tuple[str, str], str],
    applied: list[str],
    failed: list[str],
    skipped: list[str],
    diagnostics: list[str],
    exit_code: int,
) -> MigrationReport:
    """Build a safe immutable report from runner-owned observable state."""
    items = [
        MigrationItem(
            migration_set=migration.migration_set,
            filename=migration.filename,
            state=states.get((migration.migration_set, migration.filename), "PENDING"),
            postcondition_ok=None,
            diagnostic="Migration postcondition failed" if _identity(migration) in failed else None,
        )
        for migration_set in sets
        for migration in migrations[migration_set.name]
    ]
    return MigrationReport(
        items=items,
        applied=applied,
        failed=failed,
        skipped=skipped,
        diagnostics=diagnostics,
        exit_code=exit_code,
    )


async def upgrade(
    dsn: str,
    *,
    sets: tuple[MigrationSet, ...],
    fail_fast: bool = False,
    reapply_changed: bool = False,
    connect_timeout: float = 5.0,
    lock_timeout: float = 30.0,
    statement_timeout: float = 60.0,
) -> MigrationReport:
    """Apply ordered bodies and ledger records atomically under a bounded session lock."""
    from parrot.conf import PARROT_BOTS_TABLE, PARROT_SCHEMA

    _validate_timeouts(connect_timeout, lock_timeout, statement_timeout)
    schema = _quote_identifier(PARROT_SCHEMA, "schema")[1:-1]
    bots_table = _quote_identifier(PARROT_BOTS_TABLE, "bots table")[1:-1]
    if len({migration_set.name for migration_set in sets}) != len(sets):
        raise ValueError("Migration sets must be uniquely named")
    migrations = {migration_set.name: load_migrations(migration_set) for migration_set in sets}
    states: dict[tuple[str, str], str] = {}
    applied: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []
    diagnostics: list[str] = []
    connection: object | None = None
    locked = False
    try:
        import asyncpg

        connection = await asyncpg.connect(dsn, timeout=connect_timeout)
        await connection.execute(
            "SELECT set_config('statement_timeout', $1, false)", str(int(statement_timeout * 1000))
        )
        await _acquire_lock(connection, lock_timeout)
        locked = True
        await _create_ledger(connection, schema)
        rows = await _read_ledger(connection, schema, tuple(migration_set.name for migration_set in sets))
        row_map, diagnostics = _ledger_state(rows, migrations, sets)
        for migration_set in sets:
            for migration in migrations[migration_set.name]:
                states[(migration.migration_set, migration.filename)] = _state(
                    row_map.get((migration.migration_set, migration.filename)), migration
                )
        if diagnostics:
            return _report(sets, migrations, states, applied, failed, skipped, diagnostics, 2)

        stop_all = False
        for migration_set in sets:
            set_failed = stop_all
            for migration in migrations[migration_set.name]:
                key = (migration.migration_set, migration.filename)
                identity = _identity(migration)
                current_state = states[key]
                if set_failed:
                    skipped.append(identity)
                    continue
                if current_state == "APPLIED":
                    continue
                if current_state == "CHANGED" and not reapply_changed:
                    diagnostics.append(f"Migration changed and requires explicit reapply: {identity}")
                    set_failed = True
                    if fail_fast:
                        stop_all = True
                    continue
                operation = "reapply" if current_state == "CHANGED" else "upgrade"
                try:
                    async with connection.transaction():
                        await connection.execute("SET LOCAL lock_timeout = '5s'")
                        await connection.execute(render_sql(migration.sql, schema=schema, bots_table=bots_table))
                        if await verify_postconditions(connection, (migration,), schema=schema, bots_table=bots_table):
                            raise RuntimeError("Migration postcondition failed")
                        await _stamp(connection, migration, migration_set, schema, operation)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    failed.append(identity)
                    diagnostics.append(f"Migration failed: {identity} ({_safe_diagnostic(error)})")
                    set_failed = True
                    if fail_fast:
                        stop_all = True
                    continue
                states[key] = "APPLIED"
                applied.append(identity)
            if reapply_changed and not set_failed:
                try:
                    if await verify_postconditions(
                        connection, migrations[migration_set.name], schema=schema, bots_table=bots_table
                    ):
                        raise RuntimeError("Migration postcondition failed")
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    identity = f"{migration_set.name}/postconditions"
                    failed.append(identity)
                    diagnostics.append(f"Migration failed: {identity} ({_safe_diagnostic(error)})")
                    if fail_fast:
                        stop_all = True
        exit_code = 2 if failed else 1 if diagnostics else 0
        return _report(sets, migrations, states, applied, failed, skipped, diagnostics, exit_code)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        return _report(sets, migrations, states, applied, failed, skipped, [_safe_diagnostic(error)], 2)
    finally:
        if connection is not None:
            if locked:
                try:
                    await connection.fetchval("SELECT pg_advisory_unlock($1)", _ADVISORY_LOCK)
                except Exception:
                    pass
            await connection.close()


async def baseline(
    dsn: str,
    *,
    migration_set: MigrationSet,
    through: int,
    connect_timeout: float = 5.0,
    lock_timeout: float = 30.0,
    statement_timeout: float = 60.0,
) -> MigrationReport:
    """Verify and stamp an explicit prefix without executing any body SQL."""
    from parrot.conf import PARROT_BOTS_TABLE, PARROT_SCHEMA

    _validate_timeouts(connect_timeout, lock_timeout, statement_timeout)
    schema = _quote_identifier(PARROT_SCHEMA, "schema")[1:-1]
    bots_table = _quote_identifier(PARROT_BOTS_TABLE, "bots table")[1:-1]
    migrations = {migration_set.name: load_migrations(migration_set)}
    selected = tuple(migration for migration in migrations[migration_set.name] if migration.sequence <= through)
    if not selected or selected[-1].sequence != through:
        raise ValueError("Baseline sequence must name an existing migration")
    states: dict[tuple[str, str], str] = {}
    applied: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []
    diagnostics: list[str] = []
    connection: object | None = None
    locked = False
    try:
        import asyncpg

        connection = await asyncpg.connect(dsn, timeout=connect_timeout)
        await connection.execute(
            "SELECT set_config('statement_timeout', $1, false)", str(int(statement_timeout * 1000))
        )
        await _acquire_lock(connection, lock_timeout)
        locked = True
        rows = (
            await _read_ledger(connection, schema, (migration_set.name,))
            if await _ledger_exists(connection, schema)
            else []
        )
        row_map, diagnostics = _ledger_state(rows, migrations, (migration_set,))
        for migration in migrations[migration_set.name]:
            states[(migration.migration_set, migration.filename)] = _state(
                row_map.get((migration.migration_set, migration.filename)), migration
            )
        if diagnostics:
            return _report((migration_set,), migrations, states, applied, failed, skipped, diagnostics, 2)
        changed = [
            migration for migration in selected if states[(migration.migration_set, migration.filename)] == "CHANGED"
        ]
        if changed:
            diagnostics.extend(
                f"Migration changed and cannot be baselined: {_identity(migration)}" for migration in changed
            )
            return _report((migration_set,), migrations, states, applied, failed, skipped, diagnostics, 1)
        try:
            async with connection.transaction(readonly=True):
                if await verify_postconditions(connection, selected, schema=schema, bots_table=bots_table):
                    raise RuntimeError("Migration postcondition failed")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            failed.extend(_identity(migration) for migration in selected)
            diagnostics.append(_safe_diagnostic(error))
            return _report((migration_set,), migrations, states, applied, failed, skipped, diagnostics, 2)

        async with connection.transaction():
            await _create_ledger(connection, schema)
            rows = await _read_ledger(connection, schema, (migration_set.name,))
            row_map, diagnostics = _ledger_state(rows, migrations, (migration_set,))
            if diagnostics:
                raise RuntimeError("Migration ledger changed during baseline")
            for migration in selected:
                current = _state(row_map.get((migration.migration_set, migration.filename)), migration)
                if current == "CHANGED":
                    raise RuntimeError("Migration changed during baseline")
                if current == "PENDING":
                    await _stamp(connection, migration, migration_set, schema, "baseline")
                states[(migration.migration_set, migration.filename)] = "APPLIED"
                applied.append(_identity(migration))
        return _report((migration_set,), migrations, states, applied, failed, skipped, diagnostics, 0)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        return _report((migration_set,), migrations, states, applied, failed, skipped, [_safe_diagnostic(error)], 2)
    finally:
        if connection is not None:
            if locked:
                try:
                    await connection.fetchval("SELECT pg_advisory_unlock($1)", _ADVISORY_LOCK)
                except Exception:
                    pass
            await connection.close()

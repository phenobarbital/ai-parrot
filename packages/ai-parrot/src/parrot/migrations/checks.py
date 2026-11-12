"""SELECT-only migration inspection, shared by status, doctor and startup."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from .catalog import load_migrations, render_sql
from .models import MigrationFile, MigrationItem, MigrationReport, MigrationSet

if TYPE_CHECKING:
    import asyncpg


_IDENTIFIER_RE = re.compile(r"[a-z_][a-z0-9_]{0,62}\Z")
_LEDGER_TABLE = "parrot_schema_migrations"


def _identity(migration: MigrationFile) -> str:
    """Return a stable, non-sensitive identifier for one migration file."""
    return f"{migration.migration_set}/{migration.filename}"


def _validate_identifier(value: str, label: str) -> str:
    """Validate one PostgreSQL identifier used to construct inspection SQL."""
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"Invalid {label} identifier")
    return value


def _split_target(target: str) -> tuple[str, str]:
    """Validate and split a fully qualified migration target."""
    schema, separator, relation = target.partition(".")
    if not separator or "." in relation:
        raise ValueError("Invalid migration target identity")
    return _validate_identifier(schema, "target schema"), _validate_identifier(relation, "target relation")


def _quote_identifier(value: str) -> str:
    """Quote a previously validated PostgreSQL identifier."""
    return f'"{value}"'


def _ledger_name(schema: str) -> str:
    """Return the validated, quoted ledger relation name."""
    return f"{_quote_identifier(schema)}.{_quote_identifier(_LEDGER_TABLE)}"


def _safe_database_diagnostic(error: BaseException) -> str:
    """Map a driver failure to a credential-free diagnostic."""
    sqlstate = getattr(error, "sqlstate", None)
    if sqlstate == "42501":
        return "Database permission denied"
    if isinstance(sqlstate, str) and re.fullmatch(r"[0-9A-Z]{5}", sqlstate):
        return f"Database inspection failed (SQLSTATE {sqlstate})"
    return "Database inspection failed"


def _expected_identity(migration_set: MigrationSet) -> tuple[str, ...]:
    """Return validated, ordered target identity for a migration set."""
    return tuple(f"{schema}.{relation}" for schema, relation in map(_split_target, migration_set.tables))


def _recorded_identity(value: object) -> tuple[str, ...] | None:
    """Read a ledger identity without accepting unstructured values."""
    tables = value.get("tables") if isinstance(value, Mapping) else value
    if not isinstance(tables, Sequence) or isinstance(tables, (str, bytes)):
        return None
    if not all(isinstance(table, str) for table in tables):
        return None
    return tuple(tables)


async def _relations_exist(conn: "asyncpg.Connection", migration_set: MigrationSet) -> bool:
    """Probe owned relations through pg_catalog without resolving check SQL names."""
    for target in migration_set.tables:
        schema, relation = _split_target(target)
        exists = await conn.fetchval(
            "SELECT EXISTS ("
            "SELECT 1 FROM pg_catalog.pg_class AS class "
            "JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = class.relnamespace "
            "WHERE namespace.nspname = $1 AND class.relname = $2 "
            "AND class.relkind IN ('r', 'p', 'v', 'm', 'f')"
            ")",
            schema,
            relation,
        )
        if exists is not True:
            return False
    return True


async def verify_postconditions(
    conn: "asyncpg.Connection", migrations: tuple[MigrationFile, ...], *, schema: str, bots_table: str
) -> tuple[str, ...]:
    """Return failed identities; every check must yield exactly one boolean column and row.

    Callers must probe their owned target relations before calling this shared
    executor.  It intentionally executes each packaged check as one complete
    query and never attempts to infer relation names from SQL text.
    """
    failed: list[str] = []
    for migration in migrations:
        rows = await conn.fetch(render_sql(migration.check_sql, schema=schema, bots_table=bots_table))
        if len(rows) != 1 or len(rows[0]) != 1:
            failed.append(_identity(migration))
            continue
        if type(rows[0][0]) is not bool or rows[0][0] is not True:
            failed.append(_identity(migration))
    return tuple(failed)


async def _read_ledger(
    conn: "asyncpg.Connection", *, schema: str, set_names: tuple[str, ...]
) -> Sequence[Mapping[str, object]]:
    """Read selected ledger rows after the caller has confirmed the ledger exists."""
    rows = await conn.fetch(
        "SELECT migration_set, filename, checksum, check_checksum, target_identity "
        f"FROM {_ledger_name(schema)} WHERE migration_set = ANY($1::text[])",
        list(set_names),
    )
    return [dict(row) for row in rows]


async def status(
    dsn: str,
    *,
    sets: tuple[MigrationSet, ...],
    connect_timeout: float = 5.0,
    statement_timeout: float = 60.0,
) -> MigrationReport:
    """Read selected ledger/check state without creating objects or taking a write lock."""
    from parrot.conf import PARROT_BOTS_TABLE, PARROT_SCHEMA

    schema = _validate_identifier(PARROT_SCHEMA, "schema")
    bots_table = _validate_identifier(PARROT_BOTS_TABLE, "bots table")
    if connect_timeout <= 0 or statement_timeout <= 0:
        raise ValueError("Migration timeouts must be positive")

    set_names = tuple(migration_set.name for migration_set in sets)
    if len(set_names) != len(set(set_names)):
        raise ValueError("Migration sets must be uniquely named")
    expected = {migration_set.name: _expected_identity(migration_set) for migration_set in sets}
    migrations = {migration_set.name: load_migrations(migration_set) for migration_set in sets}
    connection: "asyncpg.Connection | None" = None
    try:
        import asyncpg

        connection = await asyncpg.connect(dsn, timeout=connect_timeout)
        await connection.execute(
            "SELECT set_config('statement_timeout', $1, false)", str(int(statement_timeout * 1000))
        )
        async with connection.transaction(readonly=True):
            ledger_exists = await connection.fetchval("SELECT to_regclass($1) IS NOT NULL", _ledger_name(schema))
            rows: Sequence[Mapping[str, object]] = ()
            if ledger_exists is True:
                rows = await _read_ledger(connection, schema=schema, set_names=set_names)

            known = {
                (migration.migration_set, migration.filename): migration
                for migration_files in migrations.values()
                for migration in migration_files
            }
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
                    diagnostics.append(
                        f"Migration ledger contains an unknown selected entry: {migration_set}/{filename}"
                    )
                    continue
                row_map[key] = row

            missing_sets = {
                migration_set.name
                for migration_set in sets
                if not await _relations_exist(connection, migration_set)
            }
            failed_checks: set[str] = set()
            for migration_set in sets:
                if migration_set.name in missing_sets:
                    failed_checks.update(_identity(migration) for migration in migrations[migration_set.name])
                    continue
                failed_checks.update(
                    await verify_postconditions(
                        connection, migrations[migration_set.name], schema=schema, bots_table=bots_table
                    )
                )

            items: list[MigrationItem] = []
            applied: list[str] = []
            failed: list[str] = []
            for migration_set in sets:
                for migration in migrations[migration_set.name]:
                    identity = _identity(migration)
                    row = row_map.get((migration.migration_set, migration.filename))
                    state = "PENDING"
                    diagnostic: str | None = None
                    if row is not None:
                        recorded_identity = _recorded_identity(row.get("target_identity"))
                        if recorded_identity != expected[migration_set.name]:
                            diagnostics.append(f"Migration target identity mismatch: {migration_set.name}")
                        elif (
                            row.get("checksum") != migration.checksum
                            or row.get("check_checksum") != migration.check_checksum
                        ):
                            state = "CHANGED"
                        else:
                            state = "APPLIED"
                    postcondition_ok = identity not in failed_checks
                    if not postcondition_ok:
                        diagnostic = "Migration postcondition failed"
                        failed.append(identity)
                    if state == "APPLIED":
                        applied.append(identity)
                    items.append(
                        MigrationItem(
                            migration_set=migration.migration_set,
                            filename=migration.filename,
                            state=state,
                            postcondition_ok=postcondition_ok,
                            diagnostic=diagnostic,
                        )
                    )

            unhealthy = diagnostics or failed or any(item.state != "APPLIED" for item in items)
            return MigrationReport(
                items=items,
                applied=applied,
                failed=failed,
                skipped=[],
                diagnostics=diagnostics,
                exit_code=2 if diagnostics else 1 if unhealthy else 0,
            )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        return MigrationReport(
            items=[], applied=[], failed=[], skipped=[], diagnostics=[_safe_database_diagnostic(error)], exit_code=2
        )
    finally:
        if connection is not None:
            await connection.close()

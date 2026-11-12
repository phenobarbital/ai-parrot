"""Behavioral tests for the read-only migration inspection path."""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from parrot.migrations.checks import status, verify_postconditions
from parrot.migrations.models import MigrationFile, MigrationSet


def _migration(name: str = "first", *, checksum: str = "body", check_checksum: str = "check") -> MigrationFile:
    """Create one immutable migration fixture."""
    return MigrationFile(
        migration_set="bots",
        filename=f"001_{name}.sql",
        sequence=1,
        sql="SELECT 1;",
        check_sql="SELECT TRUE;",
        checksum=checksum,
        check_checksum=check_checksum,
    )


def _set() -> MigrationSet:
    """Create the selected migration target fixture."""
    return MigrationSet(name="bots", package="test.migrations", resource_dir="sql/bots", tables=("navigator.ai_bots",))


class _Row(list[Any]):
    """List-like record that supports positional check-value access."""


class _PermissionError(Exception):
    """Driver-shaped permission error fixture without a driver dependency."""

    sqlstate = "42501"


class _Connection:
    """Asyncpg-shaped SELECT-only connection recorder."""

    def __init__(self, *, ledger_exists: bool = True, rows: list[dict[str, object]] | None = None) -> None:
        self.ledger_exists = ledger_exists
        self.rows = rows or []
        self.relations_exist = True
        self.check_rows: list[_Row] = [_Row([True])]
        self.calls: list[str] = []
        self.closed = False
        self.raise_error: BaseException | None = None

    async def execute(self, query: str, *arguments: object) -> None:
        """Record session setup without performing DDL."""
        self.calls.append(query)

    async def fetchval(self, query: str, *arguments: object) -> object:
        """Return catalog/ledger fixture values."""
        self.calls.append(query)
        if self.raise_error is not None:
            raise self.raise_error
        if "to_regclass" in query:
            return self.ledger_exists
        return self.relations_exist

    async def fetch(self, query: str, *arguments: object) -> list[Any]:
        """Return ledger or postcondition rows."""
        self.calls.append(query)
        if self.raise_error is not None:
            raise self.raise_error
        if 'FROM "navigator"."parrot_schema_migrations"' in query:
            selected = arguments[0]
            return [row for row in self.rows if row["migration_set"] in selected]
        return self.check_rows

    @asynccontextmanager
    async def transaction(self, *, readonly: bool) -> Any:
        """Provide the required read-only transaction context."""
        assert readonly is True
        yield

    async def close(self) -> None:
        """Record connection cleanup."""
        self.closed = True


@pytest.fixture
def loaded_migrations(monkeypatch: pytest.MonkeyPatch) -> MigrationFile:
    """Make status use a deterministic packaged migration fixture."""
    migration = _migration()
    monkeypatch.setattr("parrot.migrations.checks.load_migrations", lambda migration_set: (migration,))
    return migration


@pytest.fixture
def connected(monkeypatch: pytest.MonkeyPatch) -> _Connection:
    """Install a lazy asyncpg module whose connector returns the fixture connection."""
    connection = _Connection()

    async def connect(dsn: str, *, timeout: float) -> _Connection:
        """Return the fake connection without inspecting credentials."""
        assert dsn == "postgresql://test"
        assert timeout == 5.0
        return connection

    monkeypatch.setitem(sys.modules, "asyncpg", SimpleNamespace(connect=connect))
    return connection


@pytest.mark.asyncio
async def test_missing_ledger_leaves_all_files_pending(
    connected: _Connection, loaded_migrations: MigrationFile
) -> None:
    """Report missing-ledger files as pending, never as applied."""
    connected.ledger_exists = False

    report = await status("postgresql://test", sets=(_set(),))

    assert report.exit_code == 1
    assert report.items[0].state == "PENDING"
    assert report.items[0].postcondition_ok is True
    assert all("INSERT" not in call and "CREATE" not in call and "LOCK" not in call for call in connected.calls)


@pytest.mark.asyncio
async def test_matched_hashes_with_failed_check_are_unhealthy(
    connected: _Connection, loaded_migrations: MigrationFile
) -> None:
    """Do not equate matching ledger hashes with a healthy live schema."""
    connected.rows = [
        {
            "migration_set": "bots",
            "filename": loaded_migrations.filename,
            "checksum": loaded_migrations.checksum,
            "check_checksum": loaded_migrations.check_checksum,
            "target_identity": ["navigator.ai_bots"],
        }
    ]
    connected.check_rows = [_Row([False])]

    report = await status("postgresql://test", sets=(_set(),))

    assert report.exit_code == 1
    assert report.items[0].state == "APPLIED"
    assert report.failed == ["bots/001_first.sql"]


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["checksum", "check_checksum"])
async def test_changed_body_or_check_is_changed(
    connected: _Connection, loaded_migrations: MigrationFile, field: str
) -> None:
    """Classify either immutable file checksum change as changed."""
    row: dict[str, object] = {
        "migration_set": "bots",
        "filename": loaded_migrations.filename,
        "checksum": loaded_migrations.checksum,
        "check_checksum": loaded_migrations.check_checksum,
        "target_identity": ["navigator.ai_bots"],
    }
    row[field] = "different"
    connected.rows = [row]

    report = await status("postgresql://test", sets=(_set(),))

    assert report.items[0].state == "CHANGED"


@pytest.mark.asyncio
async def test_unknown_selected_rows_and_identity_mismatch_are_errors(
    connected: _Connection, loaded_migrations: MigrationFile
) -> None:
    """Reject selected history that cannot describe this immutable target."""
    connected.rows = [
        {
            "migration_set": "bots",
            "filename": "999_unknown.sql",
            "checksum": "body",
            "check_checksum": "check",
            "target_identity": ["navigator.ai_bots"],
        },
        {
            "migration_set": "bots",
            "filename": loaded_migrations.filename,
            "checksum": loaded_migrations.checksum,
            "check_checksum": loaded_migrations.check_checksum,
            "target_identity": ["navigator.other"],
        },
    ]

    report = await status("postgresql://test", sets=(_set(),))

    assert report.exit_code == 2
    assert any("unknown selected entry" in item for item in report.diagnostics)
    assert any("target identity mismatch" in item for item in report.diagnostics)


@pytest.mark.asyncio
async def test_malformed_checks_missing_relation_and_permission_failures_are_unhealthy(
    connected: _Connection, loaded_migrations: MigrationFile
) -> None:
    """Treat invalid check shapes, missing objects, and denied inspection as non-healthy."""
    connected.check_rows = [_Row([True, False])]
    malformed = await status("postgresql://test", sets=(_set(),))
    assert malformed.failed == ["bots/001_first.sql"]

    connected.relations_exist = False
    missing = await status("postgresql://test", sets=(_set(),))
    assert missing.failed == ["bots/001_first.sql"]

    connected.raise_error = _PermissionError()
    denied = await status("postgresql://test", sets=(_set(),))
    assert denied.exit_code == 2
    assert denied.diagnostics == ["Database permission denied"]


@pytest.mark.asyncio
async def test_unselected_rows_are_not_queried_and_connection_closes(
    connected: _Connection, loaded_migrations: MigrationFile
) -> None:
    """Limit ledger reads to selected migration set names and always close."""
    connected.rows = [
        {
            "migration_set": "uninstalled",
            "filename": "999_unknown.sql",
            "checksum": "other",
            "check_checksum": "other",
            "target_identity": ["navigator.other"],
        }
    ]

    report = await status("postgresql://test", sets=(_set(),))

    assert report.exit_code == 1
    assert connected.closed is True
    ledger_call = next(call for call in connected.calls if "parrot_schema_migrations" in call)
    assert "ANY($1::text[])" in ledger_call


@pytest.mark.asyncio
async def test_verify_requires_exactly_one_boolean_value() -> None:
    """Reject zero rows, extra columns, non-booleans, and false values."""
    connection = _Connection()
    migration = _migration()
    for rows in ([], [_Row([True, False])], [_Row([1])], [_Row([False])]):
        connection.check_rows = rows
        assert await verify_postconditions(connection, (migration,), schema="navigator", bots_table="ai_bots") == (
            "bots/001_first.sql",
        )


@pytest.mark.asyncio
async def test_cancellation_closes_connection(connected: _Connection, loaded_migrations: MigrationFile) -> None:
    """Propagate cancellation only after dedicated connection cleanup."""
    connected.raise_error = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await status("postgresql://test", sets=(_set(),))

    assert connected.closed is True

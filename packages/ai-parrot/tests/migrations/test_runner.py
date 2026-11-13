"""Behavioral tests for the transactional migration runner."""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from parrot.migrations.models import MigrationFile, MigrationSet
from parrot.migrations.runner import baseline, upgrade


def _migration(migration_set: str, sequence: int, name: str) -> MigrationFile:
    """Create one deterministic migration fixture."""
    return MigrationFile(
        migration_set=migration_set,
        filename=f"{sequence:03d}_{name}.sql",
        sequence=sequence,
        sql=f"BODY {migration_set} {sequence}",
        check_sql="SELECT TRUE",
        checksum=f"body-{migration_set}-{sequence}",
        check_checksum=f"check-{migration_set}-{sequence}",
    )


def _set(name: str = "bots") -> MigrationSet:
    """Create a selected migration-set fixture."""
    return MigrationSet(name=name, package="test.migrations", resource_dir=f"sql/{name}", tables=(f"navigator.{name}",))


class _DriverError(Exception):
    """Driver-shaped failure with an SQLSTATE but no exposed message."""

    sqlstate = "XX001"


class _Connection:
    """Small asyncpg-shaped connection with observable transaction behavior."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.rows: list[dict[str, object]] = []
        self.ledger_exists = False
        self.lock_results: list[bool] = [True]
        self.closed = False
        self.fail_body: str | None = None
        self.transaction_rollbacks = 0

    async def fetchval(self, query: str, *arguments: object) -> object:
        """Serve advisory-lock and ledger-existence queries."""
        self.calls.append(query)
        if "pg_try_advisory_lock" in query:
            return self.lock_results.pop(0) if self.lock_results else False
        if "to_regclass" in query:
            return self.ledger_exists
        return True

    async def fetch(self, query: str, *arguments: object) -> list[dict[str, object]]:
        """Return selected ledger rows."""
        self.calls.append(query)
        return list(self.rows)

    async def execute(self, query: str, *arguments: object) -> None:
        """Record DDL, body and ledger writes while modeling a body failure."""
        self.calls.append(query)
        if query.startswith("CREATE TABLE"):
            self.ledger_exists = True
        if self.fail_body is not None and query == self.fail_body:
            raise _DriverError("sensitive password must not be reported")
        if query.startswith("INSERT INTO"):
            migration_set, filename, checksum, check_checksum, identity, operation = arguments
            self.rows = [
                row for row in self.rows if (row["migration_set"], row["filename"]) != (migration_set, filename)
            ]
            self.rows.append(
                {
                    "migration_set": migration_set,
                    "filename": filename,
                    "checksum": checksum,
                    "check_checksum": check_checksum,
                    "target_identity": (
                        ["navigator.bots"] if migration_set == "bots" else [f"navigator.{migration_set}"]
                    ),
                    "operation": operation,
                    "identity": identity,
                }
            )

    @asynccontextmanager
    async def transaction(self, *, readonly: bool = False) -> Any:
        """Restore ledger rows if a write transaction raises."""
        snapshot = list(self.rows)
        try:
            yield
        except BaseException:
            self.rows = snapshot
            self.transaction_rollbacks += 1
            raise

    async def close(self) -> None:
        """Record mandatory dedicated-connection cleanup."""
        self.closed = True


@pytest.fixture
def connection(monkeypatch: pytest.MonkeyPatch) -> _Connection:
    """Install the fake asyncpg module used lazily by the runner."""
    connected = _Connection()

    async def connect(dsn: str, *, timeout: float) -> _Connection:
        """Return the fixture connection without exposing the fake DSN."""
        assert dsn == "postgresql://user:secret@example/test"
        assert timeout == 5.0
        return connected

    monkeypatch.setitem(sys.modules, "asyncpg", SimpleNamespace(connect=connect))
    return connected


@pytest.fixture
def migrations(monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple[MigrationFile, ...]]:
    """Provide two independent sets, with a dependent second file in bots."""
    files = {
        "bots": (_migration("bots", 1, "first"), _migration("bots", 2, "second")),
        "other": (_migration("other", 1, "only"),),
    }
    monkeypatch.setattr("parrot.migrations.runner.load_migrations", lambda migration_set: files[migration_set.name])
    return files


@pytest.fixture
def successful_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make each invoked check visibly successful without executing SQL."""

    async def verify(connection: _Connection, files: tuple[MigrationFile, ...], **_: object) -> tuple[str, ...]:
        """Return no failed postconditions."""
        return ()

    monkeypatch.setattr("parrot.migrations.runner.verify_postconditions", verify)


@pytest.mark.asyncio
async def test_lock_precedes_ledger_creation_and_all_files_stamp(
    connection: _Connection, migrations: dict[str, tuple[MigrationFile, ...]], successful_checks: None
) -> None:
    """Acquire the bounded global lock before any ledger snapshot or DDL."""
    report = await upgrade("postgresql://user:secret@example/test", sets=(_set(),))

    assert report.exit_code == 0
    assert report.applied == ["bots/001_first.sql", "bots/002_second.sql"]
    lock_index = next(index for index, call in enumerate(connection.calls) if "pg_try_advisory_lock" in call)
    create_index = next(index for index, call in enumerate(connection.calls) if call.startswith("CREATE SCHEMA"))
    read_index = next(
        index for index, call in enumerate(connection.calls) if 'FROM "navigator"."parrot_schema_migrations"' in call
    )
    assert lock_index < create_index < read_index
    assert connection.closed is True
    assert any("pg_advisory_unlock" in call for call in connection.calls)


@pytest.mark.asyncio
async def test_failed_body_rolls_back_stamp_and_skips_successors_but_runs_independent_set(
    connection: _Connection, migrations: dict[str, tuple[MigrationFile, ...]], successful_checks: None
) -> None:
    """Keep body/check/stamp atomic and retain cross-set independence."""
    connection.fail_body = migrations["bots"][0].sql

    report = await upgrade("postgresql://user:secret@example/test", sets=(_set(), _set("other")))

    assert report.exit_code == 2
    assert report.failed == ["bots/001_first.sql"]
    assert report.skipped == ["bots/002_second.sql"]
    assert report.applied == ["other/001_only.sql"]
    assert all(row["migration_set"] != "bots" for row in connection.rows)
    assert connection.transaction_rollbacks == 1
    assert "secret" not in " ".join(report.diagnostics)


@pytest.mark.asyncio
async def test_fail_fast_skips_independent_sets(
    connection: _Connection, migrations: dict[str, tuple[MigrationFile, ...]], successful_checks: None
) -> None:
    """Stop the whole selected run only when fail-fast is requested."""
    connection.fail_body = migrations["bots"][0].sql

    report = await upgrade("postgresql://user:secret@example/test", sets=(_set(), _set("other")), fail_fast=True)

    assert report.failed == ["bots/001_first.sql"]
    assert report.skipped == ["bots/002_second.sql", "other/001_only.sql"]
    assert not connection.rows


@pytest.mark.asyncio
async def test_changed_and_unknown_history_are_rejected_without_bodies(
    connection: _Connection, migrations: dict[str, tuple[MigrationFile, ...]], successful_checks: None
) -> None:
    """Reject immutable checksum changes and unknown selected history before DDL bodies."""
    first = migrations["bots"][0]
    connection.ledger_exists = True
    connection.rows = [
        {
            "migration_set": "bots",
            "filename": "999_unknown.sql",
            "checksum": "old",
            "check_checksum": "old",
            "target_identity": ["navigator.bots"],
        },
        {
            "migration_set": "bots",
            "filename": first.filename,
            "checksum": "old",
            "check_checksum": first.check_checksum,
            "target_identity": ["navigator.bots"],
        },
    ]

    report = await upgrade("postgresql://user:secret@example/test", sets=(_set(),))

    assert report.exit_code == 2
    assert any("unknown selected entry" in diagnostic for diagnostic in report.diagnostics)
    assert not any(call.startswith("BODY") for call in connection.calls)

    connection.calls.clear()
    connection.rows = [
        {
            "migration_set": "bots",
            "filename": first.filename,
            "checksum": "old",
            "check_checksum": first.check_checksum,
            "target_identity": ["navigator.bots"],
        }
    ]
    connection.lock_results = [True]
    changed = await upgrade("postgresql://user:secret@example/test", sets=(_set(),))
    assert changed.exit_code == 1
    assert not any(call.startswith("BODY") for call in connection.calls)

    connection.calls.clear()
    connection.lock_results = [True]
    connection.rows[0]["target_identity"] = ["navigator.other"]
    mismatched = await upgrade("postgresql://user:secret@example/test", sets=(_set(),))
    assert mismatched.exit_code == 2
    assert any("target identity mismatch" in diagnostic for diagnostic in mismatched.diagnostics)


@pytest.mark.asyncio
async def test_explicit_reapply_updates_hashes_then_rechecks_entire_set(
    connection: _Connection,
    migrations: dict[str, tuple[MigrationFile, ...]],
    successful_checks: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replay changed files only by opt-in and check the full selected set afterwards."""
    first, second = migrations["bots"]
    connection.ledger_exists = True
    connection.rows = [
        {
            "migration_set": "bots",
            "filename": first.filename,
            "checksum": "old",
            "check_checksum": first.check_checksum,
            "target_identity": ["navigator.bots"],
        },
        {
            "migration_set": "bots",
            "filename": second.filename,
            "checksum": second.checksum,
            "check_checksum": second.check_checksum,
            "target_identity": ["navigator.bots"],
        },
    ]
    calls: list[tuple[str, ...]] = []

    async def verify(connection: _Connection, files: tuple[MigrationFile, ...], **_: object) -> tuple[str, ...]:
        """Record check groups to prove the final whole-set recheck."""
        calls.append(tuple(file.filename for file in files))
        return ()

    monkeypatch.setattr("parrot.migrations.runner.verify_postconditions", verify)
    report = await upgrade("postgresql://user:secret@example/test", sets=(_set(),), reapply_changed=True)

    assert report.exit_code == 0
    assert calls == [(first.filename,), (first.filename, second.filename)]
    assert next(row for row in connection.rows if row["filename"] == first.filename)["checksum"] == first.checksum


@pytest.mark.asyncio
async def test_baseline_verifies_before_creating_ledger_and_never_executes_bodies(
    connection: _Connection, migrations: dict[str, tuple[MigrationFile, ...]], successful_checks: None
) -> None:
    """Verify the full requested prefix before its first write transaction."""
    report = await baseline("postgresql://user:secret@example/test", migration_set=_set(), through=2)

    assert report.exit_code == 0
    assert report.applied == ["bots/001_first.sql", "bots/002_second.sql"]
    assert not any(call.startswith("BODY") for call in connection.calls)
    create_index = next(index for index, call in enumerate(connection.calls) if call.startswith("CREATE SCHEMA"))
    assert create_index > next(index for index, call in enumerate(connection.calls) if "pg_try_advisory_lock" in call)


@pytest.mark.asyncio
async def test_baseline_failed_check_creates_no_ledger_or_rows(
    connection: _Connection, migrations: dict[str, tuple[MigrationFile, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Avoid even ledger creation when adoption verification cannot succeed."""

    async def failed_check(connection: _Connection, files: tuple[MigrationFile, ...], **_: object) -> tuple[str, ...]:
        """Return a deterministic failed migration identity."""
        return (f"bots/{files[0].filename}",)

    monkeypatch.setattr("parrot.migrations.runner.verify_postconditions", failed_check)
    report = await baseline("postgresql://user:secret@example/test", migration_set=_set(), through=2)

    assert report.exit_code == 2
    assert connection.ledger_exists is False
    assert not connection.rows
    assert not any(call.startswith("CREATE SCHEMA") for call in connection.calls)


@pytest.mark.asyncio
async def test_lock_timeout_and_cancellation_release_connection(
    connection: _Connection,
    migrations: dict[str, tuple[MigrationFile, ...]],
    successful_checks: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bound contention and propagate cancellation only after cleanup."""
    connection.lock_results = [False]
    timed_out = await upgrade("postgresql://user:secret@example/test", sets=(_set(),), lock_timeout=0.001)
    assert timed_out.exit_code == 2
    assert connection.closed is True

    connection = _Connection()
    connection.lock_results = [True]

    async def connect(dsn: str, *, timeout: float) -> _Connection:
        """Return the cancellation fixture connection."""
        return connection

    async def cancelled_check(
        connection: _Connection, files: tuple[MigrationFile, ...], **_: object
    ) -> tuple[str, ...]:
        """Cancel after the runner has acquired its lock and entered a body transaction."""
        raise asyncio.CancelledError()

    monkeypatch.setitem(sys.modules, "asyncpg", SimpleNamespace(connect=connect))
    monkeypatch.setattr("parrot.migrations.runner.verify_postconditions", cancelled_check)
    with pytest.raises(asyncio.CancelledError):
        await upgrade("postgresql://user:secret@example/test", sets=(_set(),))

    assert connection.closed is True
    assert any("pg_advisory_unlock" in call for call in connection.calls)


def test_recorded_identity_decodes_jsonb_text_as_returned_by_asyncpg() -> None:
    """asyncpg returns jsonb as text by default; a ledger written by this runner must read back as equal."""
    from parrot.migrations.runner import _recorded_identity

    assert _recorded_identity('{"tables": ["navigator.ai_bots"]}') == ("navigator.ai_bots",)
    assert _recorded_identity('["navigator.ai_bots"]') == ("navigator.ai_bots",)
    assert _recorded_identity(["navigator.ai_bots"]) == ("navigator.ai_bots",)
    assert _recorded_identity("not json") is None
    assert _recorded_identity('"navigator.ai_bots"') is None

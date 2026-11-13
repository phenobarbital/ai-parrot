"""Migration CLI behavior and safety contracts."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

from parrot.migrations.cli import migration_group, resolve_dsn
from parrot.migrations.models import MigrationItem, MigrationReport, MigrationSet


def _set(name: str = "bots") -> MigrationSet:
    """Build one installed migration set for CLI tests."""
    return MigrationSet(name=name, package="test.migrations", resource_dir=f"sql/{name}", tables=(f"nav.{name}",))


def _report(exit_code: int = 0) -> MigrationReport:
    """Build a safe report with the requested public exit code."""
    return MigrationReport(
        items=[
            MigrationItem(
                migration_set="bots",
                filename="001_baseline.sql",
                state="APPLIED" if exit_code == 0 else "PENDING",
                postcondition_ok=exit_code == 0,
                diagnostic=None,
            )
        ],
        applied=["bots/001_baseline.sql"] if exit_code == 0 else [],
        failed=[],
        skipped=[],
        diagnostics=[],
        exit_code=exit_code,
    )


@pytest.fixture
def installed_sets(monkeypatch) -> tuple[MigrationSet, ...]:
    """Expose two deterministic installed sets without reading entry points."""
    sets = (_set(), _set("recipes"))
    monkeypatch.setattr("parrot.migrations.cli._installed_sets", lambda: sets)
    return sets


def test_help_lists_four_verbs_without_database_or_server_imports() -> None:
    """Help remains usable without asyncpg or the server distribution."""
    before = set(sys.modules)
    with mock.patch.dict(sys.modules, {"asyncpg": None, "parrot.server": None}):
        result = CliRunner().invoke(migration_group, ["--help"])
    assert result.exit_code == 0, result.output
    for verb in ("baseline", "new", "status", "upgrade"):
        assert verb in result.output
    assert "asyncpg" not in set(sys.modules) - before


@pytest.mark.parametrize("exit_code", [0, 1, 2])
def test_status_preserves_report_exit_codes(exit_code: int, installed_sets, monkeypatch) -> None:
    """Status returns healthy, drift, and database result codes unchanged."""
    status = mock.AsyncMock(return_value=_report(exit_code))
    monkeypatch.setattr("parrot.migrations.checks.status", status)
    result = CliRunner().invoke(migration_group, ["status", "--dsn", "postgresql://user:secret@host/db"])
    assert result.exit_code == exit_code, result.output
    assert "selected sets: bots" in result.output
    assert "target tables: nav.bots" in result.output
    assert "ledger:" in result.output
    assert "secret" not in result.output


def test_default_repeated_and_all_selection(installed_sets, monkeypatch) -> None:
    """Default selects bots; repeated sets and all preserve installed ordering."""
    status = mock.AsyncMock(return_value=_report())
    monkeypatch.setattr("parrot.migrations.checks.status", status)
    runner = CliRunner()

    default = runner.invoke(migration_group, ["status", "--dsn", "test"])
    repeated = runner.invoke(migration_group, ["status", "--set", "recipes", "--set", "bots", "--dsn", "test"])
    all_sets = runner.invoke(migration_group, ["status", "--all", "--dsn", "test"])

    assert default.exit_code == repeated.exit_code == all_sets.exit_code == 0
    assert [migration_set.name for migration_set in status.await_args_list[0].kwargs["sets"]] == ["bots"]
    assert [migration_set.name for migration_set in status.await_args_list[1].kwargs["sets"]] == ["recipes", "bots"]
    assert [migration_set.name for migration_set in status.await_args_list[2].kwargs["sets"]] == ["bots", "recipes"]


@pytest.mark.parametrize(
    "arguments",
    [
        ["status", "--all", "--set", "bots", "--dsn", "test"],
        ["status", "--set", "missing", "--dsn", "test"],
        ["status", "--connect-timeout", "0", "--dsn", "test"],
        ["status", "--statement-timeout", "-1", "--dsn", "test"],
        ["baseline", "--set", "bots", "--through", "bad", "--dsn", "test"],
        ["baseline", "--set", "bots", "--through", "1", "--force", "--dsn", "test"],
    ],
)
def test_configuration_and_parse_errors_exit_three(arguments: list[str], installed_sets) -> None:
    """Selection, timeout, and Click parsing failures use configuration exit 3."""
    result = CliRunner().invoke(migration_group, arguments)
    assert result.exit_code == 3, result.output
    assert "traceback" not in result.output.lower()
    if "missing" in arguments:
        assert "install" in result.output.lower()


def test_resolve_dsn_uses_mode_specific_precedence(monkeypatch, caplog) -> None:
    """Reads never elevate to admin while writes prefer it and safely log fallback."""
    monkeypatch.setattr("parrot.migrations.cli.PARROT_ADMIN_DSN", "postgresql://admin:admin-secret@host/db")
    monkeypatch.setattr("parrot.migrations.cli.default_dsn", "postgresql://runtime:runtime-secret@host/db")
    assert resolve_dsn("explicit", mutating=True) == "explicit"
    assert resolve_dsn(None, mutating=False) == "postgresql://runtime:runtime-secret@host/db"
    assert resolve_dsn(None, mutating=True) == "postgresql://admin:admin-secret@host/db"
    monkeypatch.setattr("parrot.migrations.cli.PARROT_ADMIN_DSN", None)
    assert resolve_dsn(None, mutating=True) == "postgresql://runtime:runtime-secret@host/db"
    assert "runtime database DSN" in caplog.text
    assert "secret" not in caplog.text


@pytest.mark.parametrize("verb", ["upgrade", "baseline"])
def test_mutating_commands_preserve_report_exit_codes(verb: str, installed_sets, monkeypatch) -> None:
    """Upgrade and baseline preserve runner exit codes and pass explicit selection."""
    operation = mock.AsyncMock(return_value=_report(1))
    monkeypatch.setattr(f"parrot.migrations.runner.{verb}", operation)
    arguments = [verb, "--set", "bots", "--dsn", "test"]
    if verb == "baseline":
        arguments.extend(["--through", "1"])
    result = CliRunner().invoke(migration_group, arguments)
    assert result.exit_code == 1, result.output
    assert operation.await_count == 1


def test_unexpected_database_failure_is_sanitized(installed_sets, monkeypatch) -> None:
    """Raw driver errors and credentials are never rendered."""
    status = mock.AsyncMock(side_effect=RuntimeError("postgresql://user:secret@host/db raw driver"))
    monkeypatch.setattr("parrot.migrations.checks.status", status)
    result = CliRunner().invoke(migration_group, ["status", "--dsn", "postgresql://user:secret@host/db"])
    assert result.exit_code == 2, result.output
    assert "database operation failed" in result.output
    assert "secret" not in result.output
    assert "raw driver" not in result.output


def test_new_scaffolds_locally_without_connection(tmp_path: Path, monkeypatch) -> None:
    """New accepts but does not resolve or use a DSN."""
    directory = tmp_path / "bots"
    directory.mkdir()
    resolve = mock.Mock(side_effect=AssertionError("must not resolve DSN"))
    monkeypatch.setattr("parrot.migrations.cli.resolve_dsn", resolve)

    result = CliRunner().invoke(
        migration_group,
        ["new", "bots", "add_field", "--directory", str(directory), "--dsn", "postgresql://secret"],
    )

    assert result.exit_code == 0, result.output
    assert (directory / "001_add_field.sql").is_file()
    assert (directory / "001_add_field.check.sql").is_file()
    assert "postgresql://secret" not in result.output
    resolve.assert_not_called()


def test_baseline_requires_explicit_set_and_valid_prefix(installed_sets, monkeypatch) -> None:
    """Baseline requires one explicit set and maps an invalid prefix to configuration exit 3."""
    missing = CliRunner().invoke(migration_group, ["baseline", "--through", "1", "--dsn", "test"])
    invalid = CliRunner().invoke(migration_group, ["baseline", "--set", "bots", "--through", "0", "--dsn", "test"])
    assert missing.exit_code == invalid.exit_code == 3
    assert "--set" in missing.output
    assert "positive migration sequence" in invalid.output

"""Migration commands in the active Python environment."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, NoReturn

import click

from parrot.conf import PARROT_ADMIN_DSN, PARROT_SCHEMA, default_dsn

from .models import MigrationConfigurationError, MigrationReport, MigrationSet

logger = logging.getLogger(__name__)


class _MigrationCommand(click.Command):
    """Map migration option and argument parsing failures to configuration exit 3."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        """Parse command arguments using the migration configuration exit contract."""
        try:
            return super().parse_args(ctx, args)
        except click.UsageError as error:
            error.exit_code = 3
            raise


class _MigrationRoot(click.Group):
    """Map migration command-selection failures to configuration exit 3."""

    command_class = _MigrationCommand

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        """Parse group arguments using the migration configuration exit contract."""
        try:
            return super().parse_args(ctx, args)
        except click.UsageError as error:
            error.exit_code = 3
            raise


@click.group(name="migration", cls=_MigrationRoot)
def migration_group() -> None:
    """Manage database schemas; self update updates software instead."""


def resolve_dsn(explicit: str | None, *, mutating: bool) -> str:
    """Resolve mode-specific precedence; configuration failures map to exit 3."""
    if explicit:
        return explicit
    if mutating and PARROT_ADMIN_DSN:
        return PARROT_ADMIN_DSN
    if default_dsn:
        if mutating:
            logger.warning("PARROT_ADMIN_DSN is not configured; using the runtime database DSN")
        return default_dsn
    raise MigrationConfigurationError("Database DSN is not configured; pass --dsn or configure the runtime database")


def _configuration_error(message: str) -> NoReturn:
    """Render a safe configuration failure and terminate with exit 3."""
    click.echo(f"Error: {message}", err=True)
    raise click.exceptions.Exit(3)


def _database_error() -> NoReturn:
    """Render a credential-free database failure and terminate with exit 2."""
    click.echo("Error: migration database operation failed", err=True)
    raise click.exceptions.Exit(2)


def _validate_timeouts(**timeouts: float) -> None:
    """Reject non-positive timeout values before discovery or connection."""
    invalid = [name.replace("_", "-") for name, value in timeouts.items() if value <= 0]
    if invalid:
        raise MigrationConfigurationError(f"Migration timeouts must be positive: {', '.join(invalid)}")


def _installed_sets() -> tuple[MigrationSet, ...]:
    """Discover installed sets lazily so help remains database-driver free."""
    from .catalog import discover_sets

    return discover_sets()


def _select_sets(set_names: tuple[str, ...], all_sets: bool) -> tuple[MigrationSet, ...]:
    """Resolve the default, repeated, or all-installed selection."""
    if all_sets and set_names:
        raise MigrationConfigurationError("--all cannot be combined with --set")

    installed = _installed_sets()
    by_name = {migration_set.name: migration_set for migration_set in installed}
    requested = tuple(by_name) if all_sets else set_names or ("bots",)
    unique_requested = tuple(dict.fromkeys(requested))
    unknown = [name for name in unique_requested if name not in by_name]
    if unknown:
        names = ", ".join(unknown)
        raise MigrationConfigurationError(
            f"Unknown or uninstalled migration set: {names}; install the distribution that provides it"
        )
    if not unique_requested:
        raise MigrationConfigurationError("No migration sets are installed")
    return tuple(by_name[name] for name in unique_requested)


def _select_one(set_name: str) -> MigrationSet:
    """Resolve one explicit installed set for baseline."""
    selected = _select_sets((set_name,), False)
    return selected[0]


def _emit_context(sets: tuple[MigrationSet, ...]) -> None:
    """Identify the selected sets, target tables, and configured ledger."""
    click.echo(f"selected sets: {', '.join(migration_set.name for migration_set in sets)}")
    targets = [target for migration_set in sets for target in migration_set.tables]
    click.echo(f"target tables: {', '.join(targets)}")
    click.echo(f"ledger: {PARROT_SCHEMA}.parrot_schema_migrations")


def _emit_report(report: MigrationReport) -> None:
    """Render only safe structured migration report fields."""
    for item in report.items:
        postcondition = "unknown" if item.postcondition_ok is None else "ok" if item.postcondition_ok else "failed"
        click.echo(f"{item.migration_set}/{item.filename}: {item.state} (postcondition {postcondition})")
    if report.applied:
        click.echo(f"applied: {', '.join(report.applied)}")
    if report.failed:
        click.echo(f"failed: {', '.join(report.failed)}")
    if report.skipped:
        click.echo(f"skipped: {', '.join(report.skipped)}")
    for diagnostic in report.diagnostics:
        click.echo(f"diagnostic: {diagnostic}")


def _finish_report(report: MigrationReport) -> None:
    """Render a report and preserve its exact public exit code."""
    _emit_report(report)
    if report.exit_code:
        raise click.exceptions.Exit(report.exit_code)


def _run_async(operation: Any) -> MigrationReport:
    """Run one database coroutine and sanitize unexpected driver failures."""
    try:
        return asyncio.run(operation)
    except MigrationConfigurationError as error:
        _configuration_error(str(error))
    except (ValueError, TypeError) as error:
        _configuration_error(str(error))
    except Exception:
        logger.error("Migration database operation failed")
        _database_error()


@migration_group.command(name="status")
@click.option("--set", "set_names", multiple=True)
@click.option("--all", "all_sets", is_flag=True)
@click.option("--dsn")
@click.option("--connect-timeout", type=float, default=5.0, show_default=True)
@click.option("--statement-timeout", type=float, default=60.0, show_default=True)
def status_command(
    set_names: tuple[str, ...],
    all_sets: bool,
    dsn: str | None,
    connect_timeout: float,
    statement_timeout: float,
) -> None:
    """Report selected catalog and schema state without writes."""
    try:
        _validate_timeouts(connect_timeout=connect_timeout, statement_timeout=statement_timeout)
        sets = _select_sets(set_names, all_sets)
        resolved_dsn = resolve_dsn(dsn, mutating=False)
        _emit_context(sets)
        from .checks import status

        report = _run_async(
            status(
                resolved_dsn,
                sets=sets,
                connect_timeout=connect_timeout,
                statement_timeout=statement_timeout,
            )
        )
    except MigrationConfigurationError as error:
        _configuration_error(str(error))
    _finish_report(report)


@migration_group.command(name="upgrade")
@click.option("--set", "set_names", multiple=True)
@click.option("--all", "all_sets", is_flag=True)
@click.option("--dsn")
@click.option("--fail-fast", is_flag=True)
@click.option("--reapply-changed", is_flag=True)
@click.option("--connect-timeout", type=float, default=5.0, show_default=True)
@click.option("--lock-timeout", type=float, default=30.0, show_default=True)
@click.option("--statement-timeout", type=float, default=60.0, show_default=True)
def upgrade_command(
    set_names: tuple[str, ...],
    all_sets: bool,
    dsn: str | None,
    fail_fast: bool,
    reapply_changed: bool,
    connect_timeout: float,
    lock_timeout: float,
    statement_timeout: float,
) -> None:
    """Apply pending files; changed files require explicit repair."""
    try:
        _validate_timeouts(
            connect_timeout=connect_timeout,
            lock_timeout=lock_timeout,
            statement_timeout=statement_timeout,
        )
        sets = _select_sets(set_names, all_sets)
        resolved_dsn = resolve_dsn(dsn, mutating=True)
        _emit_context(sets)
        from .runner import upgrade

        report = _run_async(
            upgrade(
                resolved_dsn,
                sets=sets,
                fail_fast=fail_fast,
                reapply_changed=reapply_changed,
                connect_timeout=connect_timeout,
                lock_timeout=lock_timeout,
                statement_timeout=statement_timeout,
            )
        )
    except MigrationConfigurationError as error:
        _configuration_error(str(error))
    _finish_report(report)


@migration_group.command(name="baseline")
@click.option("--set", "set_name", required=True)
@click.option("--through", type=int, required=True)
@click.option("--dsn")
@click.option("--connect-timeout", type=float, default=5.0, show_default=True)
@click.option("--lock-timeout", type=float, default=30.0, show_default=True)
@click.option("--statement-timeout", type=float, default=60.0, show_default=True)
def baseline_command(
    set_name: str,
    through: int,
    dsn: str | None,
    connect_timeout: float,
    lock_timeout: float,
    statement_timeout: float,
) -> None:
    """Verify and record one explicit prefix without executing bodies."""
    try:
        if through <= 0:
            raise MigrationConfigurationError("--through must name a positive migration sequence")
        _validate_timeouts(
            connect_timeout=connect_timeout,
            lock_timeout=lock_timeout,
            statement_timeout=statement_timeout,
        )
        migration_set = _select_one(set_name)
        resolved_dsn = resolve_dsn(dsn, mutating=True)
        _emit_context((migration_set,))
        from .runner import baseline

        report = _run_async(
            baseline(
                resolved_dsn,
                migration_set=migration_set,
                through=through,
                connect_timeout=connect_timeout,
                lock_timeout=lock_timeout,
                statement_timeout=statement_timeout,
            )
        )
    except MigrationConfigurationError as error:
        _configuration_error(str(error))
    _finish_report(report)


@migration_group.command(name="new")
@click.argument("set_name")
@click.argument("name")
@click.option("--directory", type=click.Path(path_type=Path), required=True)
@click.option("--dsn")
def new_command(set_name: str, name: str, directory: Path, dsn: str | None) -> None:
    """Create a source body/check pair locally; dsn is accepted but unused."""
    del dsn
    from .catalog import scaffold

    try:
        body_path, check_path = scaffold(set_name, name, directory=directory)
    except MigrationConfigurationError as error:
        _configuration_error(str(error))
    click.echo(f"created migration body: {body_path}")
    click.echo(f"created migration check: {check_path}")

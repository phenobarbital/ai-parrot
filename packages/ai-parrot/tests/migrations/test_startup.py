"""Behavioral tests for bounded, read-only migration diagnostics."""

from __future__ import annotations

import asyncio
import inspect
import logging
from unittest.mock import AsyncMock

import pytest

import parrot.migrations.startup as startup_module
from parrot.migrations.models import MigrationItem, MigrationReport
from parrot.migrations.startup import migration_doctor_check, warn_pending_migrations


def _report(
    state: str = "APPLIED", *, failed: bool = False, diagnostics: list[str] | None = None
) -> MigrationReport:
    """Build a safe migration report for one bots migration."""
    identity = "bots/001_baseline.sql"
    return MigrationReport(
        items=[
            MigrationItem(
                migration_set="bots",
                filename="001_baseline.sql",
                state=state,
                postcondition_ok=not failed,
                diagnostic="Migration postcondition failed" if failed else None,
            )
        ],
        applied=[identity] if state == "APPLIED" else [],
        failed=[identity] if failed else [],
        skipped=[],
        diagnostics=diagnostics or [],
        exit_code=2 if diagnostics else 1 if state != "APPLIED" or failed else 0,
    )


@pytest.mark.asyncio
async def test_unconfigured_probe_does_not_inspect_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Return explicit informational states without connecting when no DSN exists."""
    status = AsyncMock()
    monkeypatch.setattr("parrot.migrations.checks.status", status)
    logger = logging.getLogger("test.migrations.startup.unconfigured")

    await warn_pending_migrations(None, logger=logger)
    check = await migration_doctor_check(None)

    status.assert_not_awaited()
    assert check.informational is True
    assert check.ok is False
    assert "not configured" in check.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("report", "expected"),
    [
        (_report("PENDING"), "1 pending"),
        (_report("CHANGED"), "1 changed"),
        (_report(failed=True), "schema drift=yes"),
    ],
)
async def test_doctor_distinguishes_pending_changed_and_drift(
    monkeypatch: pytest.MonkeyPatch, report: MigrationReport, expected: str
) -> None:
    """Keep each actionable migration condition visible in doctor output."""
    monkeypatch.setattr("parrot.migrations.checks.status", AsyncMock(return_value=report))

    check = await migration_doctor_check("postgresql://runtime")

    assert check.informational is True
    assert check.ok is False
    assert expected in check.detail
    assert "upgrade" in check.fix


@pytest.mark.asyncio
async def test_unavailable_output_is_sanitized(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Never expose credentials, SQL, parameters, or raw driver errors."""
    secret = "postgresql://user:secret@db/runtime SELECT private FROM vault parameters=('token',)"
    monkeypatch.setattr("parrot.migrations.checks.status", AsyncMock(side_effect=RuntimeError(secret)))
    logger = logging.getLogger("test.migrations.startup.sanitized")

    with caplog.at_level(logging.WARNING):
        await warn_pending_migrations("postgresql://runtime", logger=logger)
    check = await migration_doctor_check("postgresql://runtime")

    output = f"{caplog.text} {check.detail} {check.fix}"
    assert "secret" not in output
    assert "SELECT" not in output
    assert "token" not in output
    assert "unavailable" in output


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("probe", "expected_budget"),
    [("startup", 2.0), ("doctor", 5.0)],
)
async def test_total_operation_timeout_is_bounded(
    monkeypatch: pytest.MonkeyPatch, probe: str, expected_budget: float
) -> None:
    """Apply the advertised budget around the complete status operation."""
    requested: list[float] = []
    original_timeout = asyncio.timeout

    def short_timeout(delay: float):
        requested.append(delay)
        return original_timeout(0.01)

    monkeypatch.setattr(startup_module.asyncio, "timeout", short_timeout)
    monkeypatch.setattr("parrot.migrations.checks.status", AsyncMock(side_effect=lambda *args, **kwargs: None))

    async def blocked_status(*args: object, **kwargs: object) -> MigrationReport:
        await asyncio.sleep(60)
        return _report()

    monkeypatch.setattr("parrot.migrations.checks.status", blocked_status)
    if probe == "startup":
        await warn_pending_migrations("postgresql://runtime", logger=logging.getLogger("test.timeout"))
    else:
        check = await migration_doctor_check("postgresql://runtime")
        assert "timed out" in check.detail

    assert requested == [expected_budget]


@pytest.mark.asyncio
@pytest.mark.parametrize("probe", ["startup", "doctor"])
async def test_cancellation_propagates(monkeypatch: pytest.MonkeyPatch, probe: str) -> None:
    """Do not turn task cancellation into a fail-open diagnostic."""
    monkeypatch.setattr("parrot.migrations.checks.status", AsyncMock(side_effect=asyncio.CancelledError))

    with pytest.raises(asyncio.CancelledError):
        if probe == "startup":
            await warn_pending_migrations("postgresql://runtime", logger=logging.getLogger("test.cancel"))
        else:
            await migration_doctor_check("postgresql://runtime")


@pytest.mark.asyncio
async def test_probe_selects_configured_bots_target(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use only the configured bots migration set and read-only status API."""
    status = AsyncMock(return_value=_report())
    monkeypatch.setattr("parrot.migrations.checks.status", status)

    await warn_pending_migrations("postgresql://runtime", logger=logging.getLogger("test.target"))

    args, kwargs = status.await_args
    assert args == ("postgresql://runtime",)
    assert len(kwargs["sets"]) == 1
    assert kwargs["sets"][0].name == "bots"
    assert kwargs["sets"][0].tables == ("navigator.ai_bots",)
    assert kwargs["connect_timeout"] == 2.0
    assert kwargs["statement_timeout"] == 2.0


def test_probe_module_has_no_sql_or_mutation_imports() -> None:
    """Keep startup diagnostics free of SQL, runner, DDL, and advisory locks."""
    source = inspect.getsource(startup_module)

    assert ".execute(" not in source
    assert ".fetch(" not in source
    assert ".fetchval(" not in source
    assert "parrot.migrations.runner" not in source
    assert "advisory_lock" not in source
    assert "CREATE TABLE" not in source

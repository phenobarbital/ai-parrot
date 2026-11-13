"""Bounded informational schema diagnostics; never apply migrations."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parrot.migrations.models import MigrationReport
    from parrot.self_.doctor import DoctorCheck


_STARTUP_TIMEOUT_SECONDS = 2.0
_DOCTOR_TIMEOUT_SECONDS = 5.0
_UPGRADE_FIX = "run `parrot self migration upgrade` before starting database-backed bots"


def _migration_counts(report: "MigrationReport") -> tuple[int, int, bool]:
    """Return pending, changed and drift indicators from a safe report."""
    pending = sum(item.state == "PENDING" for item in report.items)
    changed = sum(item.state == "CHANGED" for item in report.items)
    drift = bool(report.failed or report.diagnostics)
    return pending, changed, drift


def _is_unavailable(report: "MigrationReport") -> bool:
    """Return whether inspection failed before any migration state was available."""
    return report.exit_code == 2 and not report.items


async def _migration_status(dsn: str, *, timeout: float) -> "MigrationReport":
    """Inspect the configured bots set within one total time budget."""
    from parrot.migrations.checks import status
    from parrot.migrations.providers import bots_set

    async with asyncio.timeout(timeout):
        return await status(
            dsn,
            sets=(bots_set(),),
            connect_timeout=timeout,
            statement_timeout=timeout,
        )


async def warn_pending_migrations(dsn: str | None, *, logger: logging.Logger) -> None:
    """Bound bots-only SELECT probes to two seconds, then warn and allow startup."""
    if not dsn:
        logger.warning("Database migration state was not checked: runtime database is not configured")
        return

    try:
        report = await _migration_status(dsn, timeout=_STARTUP_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        logger.warning("Database migration state was not checked: read-only probe timed out")
        return
    except Exception:  # noqa: BLE001 - startup must fail open with a sanitized warning.
        logger.warning("Database migration state was not checked: read-only probe unavailable")
        return

    if _is_unavailable(report):
        logger.warning("Database migration state was not checked: read-only probe unavailable")
        return

    pending, changed, drift = _migration_counts(report)
    if pending or changed or drift:
        logger.warning(
            "Database migrations need attention: %d pending, %d changed, schema drift=%s; %s",
            pending,
            changed,
            "yes" if drift else "no",
            _UPGRADE_FIX,
        )
        return

    logger.info("Database migrations are applied and schema checks passed")


async def migration_doctor_check(dsn: str | None) -> DoctorCheck:
    """Return a five-second informational check with explicit unconfigured state."""
    from parrot.self_.doctor import DoctorCheck

    if not dsn:
        return DoctorCheck(
            name="database migrations",
            ok=False,
            detail="runtime database is not configured; migration state was not checked",
            fix="configure the runtime database DSN",
            informational=True,
        )

    try:
        report = await _migration_status(dsn, timeout=_DOCTOR_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        return DoctorCheck(
            name="database migrations",
            ok=False,
            detail="read-only migration probe timed out after 5 seconds",
            fix=_UPGRADE_FIX,
            informational=True,
        )
    except Exception:  # noqa: BLE001 - doctor output must not expose raw driver failures.
        return DoctorCheck(
            name="database migrations",
            ok=False,
            detail="read-only migration probe is unavailable",
            fix=_UPGRADE_FIX,
            informational=True,
        )

    if _is_unavailable(report):
        return DoctorCheck(
            name="database migrations",
            ok=False,
            detail="read-only migration probe is unavailable",
            fix=_UPGRADE_FIX,
            informational=True,
        )

    pending, changed, drift = _migration_counts(report)
    ok = not (pending or changed or drift)
    detail = (
        "all bots migrations are applied and schema checks passed"
        if ok
        else f"bots migrations: {pending} pending, {changed} changed, schema drift={'yes' if drift else 'no'}"
    )
    return DoctorCheck(
        name="database migrations",
        ok=ok,
        detail=detail,
        fix="" if ok else _UPGRADE_FIX,
        informational=True,
    )

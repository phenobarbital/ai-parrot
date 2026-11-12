"""Live validation of accounting models: drift + assertions (FEAT-713 M9). Trusted host entry point."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

from pydantic import BaseModel

from .loader import detect_drift
from .models import AssertionResult, ChartSnapshot, Period

if TYPE_CHECKING:
    from .toolkit import AccountingToolkit

logger = logging.getLogger(__name__)


class ModelLiveStatus(BaseModel, frozen=True):
    """Outcome of one model's live validation; recorded as the model's catalog flags on success."""

    tenant: str
    model: str
    drift_accounts: tuple[str, ...]
    assertion_results: tuple[AssertionResult, ...]
    audit_ids: tuple[str, ...]
    blocked: bool
    checked_at: datetime
    error: str | None = None


class LiveValidationReport(BaseModel, frozen=True):
    """Live status of every configured model."""

    models: tuple[ModelLiveStatus, ...]


def last_closed_month(today: date) -> Period:
    """The full natural month before *today*'s month."""
    first = today.replace(day=1)
    end = first - timedelta(days=1)
    return Period(from_=end.replace(day=1), to=end)


def _failed(tenant: str, model: str, checked_at: datetime, error: str) -> ModelLiveStatus:
    """A failure status; it is reported but never recorded as flags (previous flags are preserved)."""
    logger.warning("accounting live validation failed for %r/%r: %s", tenant, model, error)
    return ModelLiveStatus(
        tenant=tenant,
        model=model,
        drift_accounts=(),
        assertion_results=(),
        audit_ids=(),
        blocked=False,
        checked_at=checked_at,
        error=error,
    )


async def _validate_one(toolkit: "AccountingToolkit", tenant: str, model: str, *, today: date) -> ModelLiveStatus:
    """Refresh one model's snapshot, detect drift, run and audit every assertion; set catalog flags.

    The loaded model is initialised if needed and never replaced: the fresh snapshot is only compared against it.
    Any failure (snapshot refresh, load, compilation, execution or audit) is reported in ``error`` and leaves the
    previous catalog flags untouched.

    Args:
        toolkit: The configured toolkit serving queries (its catalog holds the flags).
        tenant: Tenant of the model.
        model: Model name.
        today: Reference date; assertions run over the last closed natural month before it.

    Returns:
        The model's live status.
    """
    checked_at = datetime.now(timezone.utc)
    spec = toolkit._catalog.specs().get((tenant, model))
    if spec is None:
        return _failed(tenant, model, checked_at, f"unknown model {model!r} for tenant {tenant!r}")
    try:
        loaded = await toolkit._ensure_loaded(tenant, model)
    except Exception as exc:  # noqa: BLE001 - reported per model, flags preserved
        return _failed(tenant, model, checked_at, f"model load failed: {exc}")
    try:
        fresh = await toolkit._snapshot_provider(tenant, model, spec)
    except Exception as exc:  # noqa: BLE001 - provider failures are reported, never fatal for other models
        return _failed(tenant, model, checked_at, f"chart snapshot refresh failed ({type(exc).__name__})")
    if not isinstance(fresh, ChartSnapshot):
        return _failed(tenant, model, checked_at, "snapshot provider returned no ChartSnapshot")
    drift = detect_drift(loaded, fresh)
    try:
        results, audit_ids = await toolkit._run_assertions(
            tenant, loaded, last_closed_month(today), tool="finance_validate_model"
        )
    except Exception as exc:  # noqa: BLE001 - reported per model, flags preserved
        return _failed(tenant, model, checked_at, f"assertion run failed: {exc}")
    assertions = loaded.spec.assertions
    blocked = any(
        result.status == "failed" and assertions[index].on_failure == "block" for index, result in enumerate(results)
    )
    status = ModelLiveStatus(
        tenant=tenant,
        model=model,
        drift_accounts=drift,
        assertion_results=results,
        audit_ids=audit_ids,
        blocked=blocked,
        checked_at=checked_at,
    )
    toolkit._catalog.set_flags(status)
    return status


async def run_live_validation(toolkit: "AccountingToolkit", *, today: date | None = None) -> LiveValidationReport:
    """Validate every configured model; never a tool."""
    today = today or datetime.now(timezone.utc).date()
    statuses = [await _validate_one(toolkit, t, m, today=today) for (t, m) in sorted(toolkit._catalog.specs())]
    return LiveValidationReport(models=tuple(statuses))

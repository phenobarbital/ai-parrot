"""Claims / T&E / Pay Periods domain models and form builders (FEAT-304).

This module provides:

* **Domain models** (Pydantic v2) that are stored as the typed content of
  :attr:`FormField.meta` for claim-related fields: :class:`ClaimTypeConfig`,
  :class:`PayPeriodConfig`, :class:`ClaimExceptionConfig`, plus their enums.
* :class:`ClaimsFormService` — builds :class:`FormSchema` objects for the three
  Claims/T&E configuration flows (Claim Type, Pay Period, Claim Exception).

Architectural boundary (D3 resolved 2026-06-14 — FieldSync is system of record):
this package produces the *form schemas* and stores *submissions*; the ``Claim``
domain entity (state machine, auditable table, Workday/Concur push) lives in the
FieldSync application layer (ai-parrot), not here. FieldSync NEVER computes
payroll amounts (Workday owns that — FEAT-321).
"""

from __future__ import annotations

import logging
from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict

from ..core.options import FieldOption
from ..core.schema import FormField, FormSchema, FormSection, FormType
from ..core.types import FieldType
from .registry import FormRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class ClaimCategory(str, Enum):
    """The measurement category a Claim Type is denominated in."""

    TIME = "time"
    AMOUNT = "amount"
    DISTANCE = "distance"


class ClaimScope(str, Enum):
    """Cascade scope at which a Claim Type is defined (Global→Client→Program)."""

    GLOBAL = "global"
    CLIENT = "client"
    PROGRAM = "program"


class ClaimEventConfig(str, Enum):
    """How a claim of this type is created relative to a shift/event."""

    ALLOW = "allow"  # rep submits manually
    AUTO_GENERATE = "auto-generate"  # generated on shift completion (via FEAT-303)


class ClaimExceptionThresholdType(str, Enum):
    """Threshold dimensions that can flag a claim for manual approval.

    This enum is intentionally **extensible**: the five members below are the
    confirmed Vision IQ set; new members may be added without breaking
    consumers (which must tolerate unknown threshold types gracefully).
    """

    DISTANCE = "distance"
    MIN_PER_CLAIM = "min_per_claim"
    DAILY_MINUTES = "daily_minutes"
    TIME_AMOUNT = "time_amount"
    DOLLAR_AMOUNT = "dollar_amount"


# ---------------------------------------------------------------------------
# Domain models (stored in FormField.meta)
# ---------------------------------------------------------------------------
class ClaimTypeConfig(BaseModel):
    """Metadata stored in :attr:`FormField.meta` for a Claim Type field."""

    model_config = ConfigDict(extra="forbid")

    category: ClaimCategory
    scope: ClaimScope
    budget_code: str | None = None
    pay_code: str | None = None
    auto_approve: bool = False
    requires_receipt: bool = False
    event_config: ClaimEventConfig = ClaimEventConfig.ALLOW


class PayPeriodConfig(BaseModel):
    """Metadata stored in :attr:`FormField.meta` for a Pay Period date group.

    FieldSync persists these (system of record) and keeps them synced with the
    Workday calendar. Workday still calculates and closes pay — FieldSync never
    computes payroll amounts.
    """

    model_config = ConfigDict(extra="forbid")

    start: date | None = None
    end: date | None = None
    paydate: date | None = None
    lockdate: date | None = None
    accrue_to_next: bool = True  # locked claims roll to next open period


class ClaimExceptionConfig(BaseModel):
    """Metadata stored in :attr:`FormField.meta` for a Claim Exception threshold."""

    model_config = ConfigDict(extra="forbid")

    threshold_type: ClaimExceptionThresholdType
    threshold_value: float
    prompt: str
    blocks_auto_approve: bool = True


# ---------------------------------------------------------------------------
# Form builder service
# ---------------------------------------------------------------------------
class ClaimsFormService:
    """Builds :class:`FormSchema` objects for the Claims/T&E configuration flows.

    All builder methods are ``async`` (per the async-first house style) even
    though they perform no I/O today — registration is async and future
    persistence calls require it. Each builder tags the form with
    ``FormType.CLAIMS_CONFIG`` and registers it via the shared
    :class:`FormRegistry`.
    """

    def __init__(self, registry: FormRegistry, *, tenant: str) -> None:
        self.registry = registry
        self.tenant = tenant
        self.logger = logging.getLogger(__name__)

    async def build_claim_type_form(
        self, scope: ClaimScope, *, form_id: str | None = None
    ) -> FormSchema:
        """Return (and register) a form for defining a Claim Type at ``scope``."""
        fid = form_id or f"claim_type_{scope.value}"
        section = FormSection(
            section_id="claim_type",
            title="Claim Type",
            fields=[
                FormField(
                    field_id="category",
                    field_type=FieldType.SELECT,
                    label="Category",
                    required=True,
                    options=[
                        FieldOption(value=c.value, label=c.value.title())
                        for c in ClaimCategory
                    ],
                ),
                FormField(
                    field_id="scope",
                    field_type=FieldType.SELECT,
                    label="Scope",
                    required=True,
                    default=scope.value,
                    options=[
                        FieldOption(value=s.value, label=s.value.title())
                        for s in ClaimScope
                    ],
                ),
                FormField(
                    field_id="budget_code",
                    field_type=FieldType.TEXT,
                    label="Budget code",
                ),
                FormField(
                    field_id="pay_code",
                    field_type=FieldType.TEXT,
                    label="Pay code",
                ),
                FormField(
                    field_id="auto_approve",
                    field_type=FieldType.BOOLEAN,
                    label="Auto-approve",
                    default=False,
                ),
                FormField(
                    field_id="requires_receipt",
                    field_type=FieldType.BOOLEAN,
                    label="Requires receipt",
                    default=False,
                ),
                FormField(
                    field_id="event_config",
                    field_type=FieldType.SELECT,
                    label="Event handling",
                    required=True,
                    default=ClaimEventConfig.ALLOW.value,
                    options=[
                        FieldOption(value=e.value, label=e.value.replace("-", " ").title())
                        for e in ClaimEventConfig
                    ],
                ),
            ],
        )
        form = FormSchema(
            form_id=fid,
            title=f"Claim Type ({scope.value})",
            form_type=FormType.CLAIMS_CONFIG,
            sections=[section],
            meta={"claim_context": "claim_type", "scope": scope.value},
        )
        await self.registry.register(form, tenant=self.tenant)
        self.logger.info("Registered claim-type form %r (tenant=%s)", fid, self.tenant)
        return form

    async def build_pay_period_form(self, *, form_id: str | None = None) -> FormSchema:
        """Return (and register) the Pay Period management/visualization form.

        FieldSync persists the resulting ``PayPeriodConfig`` (system of record),
        synced with Workday; this form does not compute payroll amounts.
        """
        fid = form_id or "pay_period"
        section = FormSection(
            section_id="pay_period",
            title="Pay Period",
            fields=[
                FormField(field_id="start", field_type=FieldType.DATE, label="Start", required=True),
                FormField(field_id="end", field_type=FieldType.DATE, label="End", required=True),
                FormField(field_id="paydate", field_type=FieldType.DATE, label="Pay date"),
                FormField(field_id="lockdate", field_type=FieldType.DATE, label="Lock date"),
                FormField(
                    field_id="accrue_to_next",
                    field_type=FieldType.BOOLEAN,
                    label="Accrue locked claims to next period",
                    default=True,
                ),
            ],
        )
        form = FormSchema(
            form_id=fid,
            title="Pay Period",
            form_type=FormType.CLAIMS_CONFIG,
            sections=[section],
            meta={"claim_context": "pay_period"},
        )
        await self.registry.register(form, tenant=self.tenant)
        self.logger.info("Registered pay-period form %r (tenant=%s)", fid, self.tenant)
        return form

    async def build_exception_config_form(
        self, *, form_id: str | None = None
    ) -> FormSchema:
        """Return (and register) the Claim Exception threshold configuration form."""
        fid = form_id or "claim_exception"
        section = FormSection(
            section_id="claim_exception",
            title="Claim Exception",
            fields=[
                FormField(
                    field_id="threshold_type",
                    field_type=FieldType.SELECT,
                    label="Threshold type",
                    required=True,
                    options=[
                        FieldOption(value=t.value, label=t.value.replace("_", " ").title())
                        for t in ClaimExceptionThresholdType
                    ],
                ),
                FormField(
                    field_id="threshold_value",
                    field_type=FieldType.NUMBER,
                    label="Threshold value",
                    required=True,
                ),
                FormField(
                    field_id="prompt",
                    field_type=FieldType.TEXT,
                    label="Approval prompt",
                    required=True,
                ),
                FormField(
                    field_id="blocks_auto_approve",
                    field_type=FieldType.BOOLEAN,
                    label="Blocks auto-approve",
                    default=True,
                ),
            ],
        )
        form = FormSchema(
            form_id=fid,
            title="Claim Exception",
            form_type=FormType.CLAIMS_CONFIG,
            sections=[section],
            meta={"claim_context": "claim_exception"},
        )
        await self.registry.register(form, tenant=self.tenant)
        self.logger.info("Registered claim-exception form %r (tenant=%s)", fid, self.tenant)
        return form

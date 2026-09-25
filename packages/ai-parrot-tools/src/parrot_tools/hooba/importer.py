"""BBVA statement → purchase-invoice drafts (FEAT-602 M10). Transport-agnostic."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Awaitable, Callable, Optional

from pydantic import BaseModel

from .bank import ImportManifest, load_manifest, write_manifest
from .models import (
    BankExpenseRow,
    BbvaStatement,
    ContactMatch,
    DeductibilityVerdict,
    DraftReceipt,
    PurchaseInvoiceDraft,
    PurchaseInvoiceLineDraft,
)
from .rules import RuleEngine

logger = logging.getLogger(__name__)

ContactFinder = Callable[[str], Awaitable[list[ContactMatch]]]
DraftCreator = Callable[[PurchaseInvoiceDraft], Awaitable[DraftReceipt]]
CONTACT_THRESHOLD = 0.85


class PlannedDraft(BaseModel):
    """One bank row, its verdict, and the draft it will become."""

    row: BankExpenseRow
    verdict: DeductibilityVerdict
    draft: PurchaseInvoiceDraft
    contact: Optional[ContactMatch] = None


class BbvaImporter:
    """Plan and apply BBVA rows as Hooba purchase-invoice drafts."""

    def __init__(self, engine: RuleEngine, find_contact: ContactFinder, create_draft: DraftCreator) -> None:
        self._engine = engine
        self._find_contact = find_contact
        self._create_draft = create_draft

    async def plan(
        self, statement: BbvaStatement, *, period: str
    ) -> tuple[list[PlannedDraft], ImportManifest, list[dict]]:
        """Build drafts for rows not yet completed; returns (planned, manifest, skipped)."""
        manifest = await asyncio.to_thread(load_manifest, statement.digest)
        if manifest is None:
            manifest = ImportManifest(
                statement_digest=statement.digest,
                period=period,
                started_at=dt.datetime.now(dt.timezone.utc),
                row_count=statement.row_count,
            )

        planned: list[PlannedDraft] = []
        skipped: list[dict] = []
        for row in statement.rows:
            if row.row_id in manifest.completed:
                continue

            verdict = self._engine.assess(row, period=period)
            if verdict is None:
                manifest.skipped[row.row_id] = "rule.skip"
                skipped.append({"row_id": row.row_id, "reason": "rule.skip"})
                continue

            contact = next(
                (
                    candidate
                    for candidate in await self._find_contact(row.concept)
                    if candidate.score >= CONTACT_THRESHOLD
                ),
                None,
            )
            notes = (
                f"BBVA {row.row_id} · {row.concept} · {verdict.legal_basis} "
                f"· review_required={verdict.review_required}"
            )
            if contact is None:
                notes += " · contact: none (no match ≥ 0.85)"

            draft = PurchaseInvoiceDraft(
                date=row.booking_date,
                simplified=verdict.hooba.simplified,
                contact_id=contact.contact_id if contact is not None else None,
                tax_included=True,
                subject_to_income_tax=verdict.hooba.subject_to_income_tax,
                correlation_key=row.row_id,
                notes=notes,
                lines=[
                    PurchaseInvoiceLineDraft(
                        name=row.concept,
                        price=abs(row.amount),
                        tax_code=verdict.hooba.tax_code,
                        income_tax_code=verdict.hooba.income_tax_code,
                        accounting_account_code=verdict.hooba.accounting_account_code,
                    )
                ],
            )
            planned.append(PlannedDraft(row=row, verdict=verdict, draft=draft, contact=contact))

        return planned, manifest, skipped

    async def apply(self, planned: list[PlannedDraft], manifest: ImportManifest) -> list[DraftReceipt]:
        """Create drafts sequentially; persist progress after each receipt (never before)."""
        receipts: list[DraftReceipt] = []
        for planned_draft in planned:
            receipt = await self._create_draft(planned_draft.draft)
            manifest.completed[planned_draft.row.row_id] = receipt.id
            await asyncio.to_thread(write_manifest, manifest)
            receipts.append(receipt)
        return receipts

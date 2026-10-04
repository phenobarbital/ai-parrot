"""FEAT-602 TASK-3733 — model contracts."""

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from parrot_tools.hooba.models import (
    BankExpenseRow,
    BbvaStatement,
    ContactMatch,
    DeductibilityVerdict,
    DraftReceipt,
    ExpenseDraftBatch,
    HoobaMapping,
    InvoiceDraft,
    InvoiceLineDraft,
    PurchaseInvoiceDraft,
    PurchaseInvoiceLineDraft,
)


def test_models_roundtrip():
    """Every Hooba model round-trips through JSON-compatible data."""
    invoice_line = InvoiceLineDraft(name="consulting", price=Decimal("100.50"))
    purchase_line = PurchaseInvoiceLineDraft(name="office supplies", price=Decimal("25.00"))
    bank_row = BankExpenseRow(
        row_index=0,
        booking_date=dt.date(2026, 9, 3),
        concept="Office supplies",
        amount=Decimal("-25.00"),
        row_id="digest:0",
    )
    receipt = DraftReceipt(
        kind="purchase_invoice",
        id=42,
        state="draft",
        correlation_key="digest:0",
        line_ids=[7],
    )
    mapping = HoobaMapping(category="office", tax_code="IVA21")
    models = [
        invoice_line,
        InvoiceDraft(contact_id=10, correlation_key="invoice-1", lines=[invoice_line]),
        purchase_line,
        PurchaseInvoiceDraft(date=dt.date(2026, 9, 3), lines=[purchase_line]),
        receipt,
        ContactMatch(contact_id=10, legal_name="ACME S.L.", score=0.95),
        bank_row,
        BbvaStatement(
            path="statement.xlsx",
            digest="digest",
            sheet="Movimientos",
            header_row=2,
            rows=[bank_row],
            skipped=1,
            row_count=2,
        ),
        mapping,
        DeductibilityVerdict(
            draft_id="draft-1",
            txn_id="digest:0",
            rule_id="office",
            deductible_pct=Decimal("1"),
            vat_deductible_pct=Decimal("1"),
            capped_amount=Decimal("1000"),
            legal_basis="LIRPF art. 28",
            invoice_required=True,
            review_required=False,
            evidence={"concept": bank_row.concept, "amount": str(bank_row.amount)},
            hooba=mapping,
        ),
        ExpenseDraftBatch(
            statement_digest="digest",
            period="2026-09",
            dry_run=False,
            planned=1,
            created=[receipt],
            skipped=[{"row_id": "digest:1", "reason": "credit"}],
            reconciled=True,
            manifest_path="manifest.json",
        ),
    ]

    for model in models:
        assert type(model).model_validate(model.model_dump(mode="json")) == model


def test_invoice_draft_requires_exactly_one_contact_selector():
    """An invoice draft requires one, and only one, contact selector."""
    line = InvoiceLineDraft(name="service", price=Decimal("1"))

    with pytest.raises(ValidationError):
        InvoiceDraft(lines=[line])
    with pytest.raises(ValidationError):
        InvoiceDraft(contact_id=1, contact_query="ACME", lines=[line])


def test_drafts_require_at_least_one_line():
    """Sales and purchase drafts reject empty line collections."""
    with pytest.raises(ValidationError):
        InvoiceDraft(contact_id=1, lines=[])
    with pytest.raises(ValidationError):
        PurchaseInvoiceDraft(date=dt.date(2026, 9, 3), lines=[])


def test_purchase_invoice_date_field_is_a_date():
    """The purchase invoice date field uses the datetime module alias safely."""
    draft = PurchaseInvoiceDraft(
        date=dt.date(2026, 9, 3),
        lines=[PurchaseInvoiceLineDraft(name="x", price=Decimal("1"))],
    )
    assert draft.date == dt.date(2026, 9, 3)

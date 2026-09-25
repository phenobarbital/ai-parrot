"""Pydantic models shared by the Hooba toolkit modules (FEAT-602 spec §2)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class HoobaStateError(RuntimeError):
    """A created entity came back in a state other than ``draft``."""


class HoobaLookupError(LookupError):
    """An invoice serie, tax, income tax, contact or document type could not be resolved."""


class InvoiceLineDraft(BaseModel):
    """One product line of a sales-invoice draft."""

    name: str
    price: Decimal
    quantity: Decimal = Decimal("1")
    discount: Decimal = Decimal("0")
    tax_code: str = "IVA21"
    income_tax_code: Optional[str] = None
    notes: Optional[str] = None


class InvoiceDraft(BaseModel):
    """A sales invoice to create in ``draft`` state."""

    contact_id: Optional[int] = None
    contact_query: Optional[str] = None
    invoice_serie_code: Optional[str] = None
    operation_date: Optional[dt.date] = None
    reference: Optional[str] = None
    notes: Optional[str] = None
    simplified: bool = False
    correlation_key: Optional[str] = None
    lines: list[InvoiceLineDraft] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_contact_selector(self) -> "InvoiceDraft":
        """Require exactly one contact selector."""
        if (self.contact_id is None) == (self.contact_query is None):
            raise ValueError("exactly one of contact_id or contact_query is required")
        return self


class PurchaseInvoiceLineDraft(BaseModel):
    """One line of a purchase-invoice (expense) draft."""

    name: str
    price: Decimal
    quantity: Decimal = Decimal("1")
    tax_code: str = "IVA21"
    income_tax_code: Optional[str] = None
    accounting_account_code: Optional[str] = None
    notes: Optional[str] = None


class PurchaseInvoiceDraft(BaseModel):
    """A purchase invoice (gasto / compra) to create in ``draft`` state."""

    date: dt.date
    number: Optional[str] = None
    simplified: bool = False
    contact_id: Optional[int] = None
    contact_query: Optional[str] = None
    tax_included: bool = True
    subject_to_income_tax: bool = False
    notes: Optional[str] = None
    correlation_key: Optional[str] = None
    lines: list[PurchaseInvoiceLineDraft] = Field(min_length=1)


class DraftReceipt(BaseModel):
    """What Hooba returned for a created (or reused) draft."""

    kind: Literal["invoice", "purchase_invoice"]
    id: int
    state: str
    number: Optional[str] = None
    url: Optional[str] = None
    line_ids: list[int] = Field(default_factory=list)
    correlation_key: str
    reused: bool = False


class ContactMatch(BaseModel):
    """A fuzzy match between a free-text name and a Hooba contact."""

    contact_id: int
    legal_name: str
    score: float


class BankExpenseRow(BaseModel):
    """One BBVA debit row."""

    row_index: int
    booking_date: dt.date
    value_date: Optional[dt.date] = None
    concept: str
    movement: Optional[str] = None
    amount: Decimal
    currency: str = "EUR"
    balance: Optional[Decimal] = None
    observations: Optional[str] = None
    row_id: str


class BbvaStatement(BaseModel):
    """A parsed BBVA statement and its debit rows."""

    path: str
    digest: str
    sheet: str
    header_row: int
    rows: list[BankExpenseRow]
    skipped: int
    row_count: int


class HoobaMapping(BaseModel):
    """Mapping from a deductibility rule to Hooba fields."""

    category: str
    tax_code: str
    subject_to_income_tax: bool = False
    income_tax_code: Optional[str] = None
    simplified: bool = True
    accounting_account_code: Optional[str] = None


class DeductibilityVerdict(BaseModel):
    """Deductibility assessment for a bank transaction."""

    draft_id: str
    txn_id: str
    rule_id: str
    deductible_pct: Decimal
    vat_deductible_pct: Decimal
    capped_amount: Optional[Decimal] = None
    legal_basis: str
    invoice_required: bool
    review_required: bool
    status: Literal["draft", "approved", "rejected", "registered"] = "draft"
    evidence: dict
    hooba: HoobaMapping


class ExpenseDraftBatch(BaseModel):
    """Results and reconciliation data for a BBVA expense-draft import."""

    statement_digest: str
    period: str
    dry_run: bool
    planned: int
    created: list[DraftReceipt]
    skipped: list[dict]
    reconciled: bool
    manifest_path: str

"""Hooba (app.hooba.com) automation for AI-Parrot agents — FEAT-602.

Drafts only: nothing in this package issues invoices or confirms purchase invoices.
"""

from .models import (
    BankExpenseRow,
    BbvaStatement,
    ContactMatch,
    DeductibilityVerdict,
    DraftReceipt,
    ExpenseDraftBatch,
    HoobaLookupError,
    HoobaMapping,
    HoobaStateError,
    InvoiceDraft,
    InvoiceLineDraft,
    PurchaseInvoiceDraft,
    PurchaseInvoiceLineDraft,
)
from .settings import HoobaSettings
from .toolkit import HoobaToolkit

__all__ = [
    "BankExpenseRow",
    "BbvaStatement",
    "ContactMatch",
    "DeductibilityVerdict",
    "DraftReceipt",
    "ExpenseDraftBatch",
    "HoobaLookupError",
    "HoobaMapping",
    "HoobaStateError",
    "InvoiceDraft",
    "InvoiceLineDraft",
    "PurchaseInvoiceDraft",
    "PurchaseInvoiceLineDraft",
    "HoobaSettings",
    "HoobaToolkit",
]

"""Match Hooba purchase invoices to the bank charges that paid them (pure functions, no I/O).

A purchase invoice pays out as one bank debit, but the amount registered in Hooba is not always
the amount charged: only the deductible share of a mixed-use supply may be registered, or the
invoice may be in a foreign currency. Such drafts carry the charged amount in their notes as a
``[bank:<amount>]`` marker; every other draft is expected to be charged its ``totalAmount``.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from decimal import Decimal
from typing import Iterable, Optional

from pydantic import BaseModel

from .models import BankExpenseRow

#: ``[bank:161.10]`` — the amount the bank actually charged for this invoice.
BANK_MARKER_RE = re.compile(r"\[bank:(-?\d+(?:\.\d+)?)\]")
#: Legal-form and filler words that never identify a supplier on a bank statement line.
_STOPWORDS = frozenset(
    {
        "S.L.",
        "SL",
        "SLU",
        "SA",
        "SAU",
        "S.A.",
        "S.A.U.",
        "INC",
        "INC.",
        "LTD",
        "LIMITED",
        "PBC",
        "CIA",
        "DE",
        "DEL",
        "LA",
        "LOS",
        "LAS",
        "Y",
        "BUSINESS",
        "SPAIN",
        "ESPANA",
        "ESPAGNE",
        "IRELAND",
        "TECHNOLOGY",
        "GENERAL",
        "SEGUROS",
        "GRUPO",
        "SERVICIOS",
        "COMPANY",
    }
)


class ChargeMatch(BaseModel):
    """One purchase invoice paired with the bank debit that paid it."""

    purchase_invoice_id: int
    number: Optional[str]
    supplier: str
    invoice_date: dt.date
    registered_amount: Decimal
    expected_charge: Decimal
    charge_date: dt.date
    charge_amount: Decimal
    concept: str
    movement: Optional[str]
    row_id: str


def bank_marker(amount: Decimal) -> str:
    """Notes marker recording the amount the bank will charge for an invoice."""
    return f"[bank:{amount}]"


def expected_charge(record: dict) -> Decimal:
    """Amount the bank should have charged for a purchase-invoice record (marker, else its total)."""
    marker = BANK_MARKER_RE.search(record.get("notes") or "")
    return Decimal(marker.group(1)) if marker else Decimal(str(record.get("totalAmount") or 0))


def _fold(value: str) -> str:
    """Uppercase ASCII fold, so ``Tesorería`` matches a bank line reading ``TESORERIA``."""
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().upper()


def supplier_tokens(contact: dict) -> set[str]:
    """Words of a contact's legal and trade names that can identify it on a bank statement line."""
    words = re.findall(r"[A-Z0-9]+", _fold(f"{contact.get('legalName') or ''} {contact.get('tradeName') or ''}"))
    return {word for word in words if len(word) >= 4 and word not in _STOPWORDS}


def match_charges(
    records: Iterable[dict],
    contacts: dict[int, dict],
    rows: Iterable[BankExpenseRow],
    *,
    days_before: int = 2,
    days_after: int = 12,
    tolerance: Decimal = Decimal("0.01"),
) -> tuple[list[ChargeMatch], list[dict]]:
    """Pair each purchase invoice with at most one debit: same supplier, amount and a nearby value date.

    Candidates are assigned greedily by date distance across all invoices, so a monthly
    subscription never takes the charge that belongs to the next month's invoice.

    Returns:
        ``(matches, unmatched_records)``.
    """
    records = list(records)
    debits = [row for row in rows if row.amount < 0]
    candidates: list[tuple[int, Decimal, int, int]] = []
    for r_index, record in enumerate(records):
        tokens = supplier_tokens(contacts.get(int(record.get("contactId") or 0), {}))
        if not tokens:
            continue
        invoice_date = dt.date.fromisoformat(record["date"])
        wanted = expected_charge(record)
        for d_index, row in enumerate(debits):
            charge_date = row.value_date or row.booking_date
            delta = (charge_date - invoice_date).days
            text = _fold(f"{row.concept} {row.observations or ''}")
            if (
                -days_before <= delta <= days_after
                and abs(-row.amount - wanted) <= tolerance
                and tokens & set(re.findall(r"[A-Z0-9]+", text))
            ):
                candidates.append((abs(delta), abs(-row.amount - wanted), r_index, d_index))

    matches: list[ChargeMatch] = []
    used_records: set[int] = set()
    used_debits: set[int] = set()
    for _, _, r_index, d_index in sorted(candidates):
        if r_index in used_records or d_index in used_debits:
            continue
        used_records.add(r_index)
        used_debits.add(d_index)
        record, row = records[r_index], debits[d_index]
        matches.append(
            ChargeMatch(
                purchase_invoice_id=int(record["id"]),
                number=record.get("number"),
                supplier=contacts.get(int(record.get("contactId") or 0), {}).get("legalName") or "",
                invoice_date=dt.date.fromisoformat(record["date"]),
                registered_amount=Decimal(str(record.get("totalAmount") or 0)),
                expected_charge=expected_charge(record),
                charge_date=row.value_date or row.booking_date,
                charge_amount=-row.amount,
                concept=row.concept,
                movement=row.movement,
                row_id=row.row_id,
            )
        )
    matches.sort(key=lambda match: (match.invoice_date, match.purchase_invoice_id))
    unmatched = [record for index, record in enumerate(records) if index not in used_records]
    return matches, unmatched


def payment_method_urn(match: ChargeMatch) -> str:
    """Hooba payment-method URN for the kind of bank movement that paid the invoice."""
    text = _fold(f"{match.movement or ''} {match.concept}")
    if "TARJETA" in text:
        return "urn:payment-method:card"
    if "ADEUDO" in text or "RECIBO" in text or "DOMICILI" in text:
        return "urn:payment-method:direct-debit"
    if "TRANSFERENCIA" in text:
        return "urn:payment-method:bank-transfer"
    return "urn:payment-method:custom"

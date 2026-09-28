"""hooba_reconcile_bank_statement: pairing purchase invoices with the bank debits that paid them."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Optional

import pytest

from parrot_tools.hooba import HoobaSettings, HoobaToolkit
from parrot_tools.hooba.models import BankExpenseRow, BbvaStatement
from parrot_tools.hooba.reconcile import match_charges, payment_method_urn, supplier_tokens

CONTACTS = {
    1: {"id": 1, "legalName": "Anthropic, PBC"},
    2: {"id": 2, "legalName": "Electricidad Eleia, S.L.", "tradeName": "Eleia"},
    3: {"id": 3, "legalName": "Tesorería General de la Seguridad Social", "tradeName": "TGSS"},
    4: {"id": 4, "legalName": "OpenAI Ireland Limited"},
}


def _row(index: int, value: str, concept: str, amount: str, movement: str = "Pago con tarjeta") -> BankExpenseRow:
    date = dt.date.fromisoformat(value)
    return BankExpenseRow(
        row_index=index,
        booking_date=date + dt.timedelta(days=2),
        value_date=date,
        concept=concept,
        movement=movement,
        amount=Decimal(amount),
        row_id=f"r{index}",
    )


def _invoice(id_: int, contact: int, date: str, total: str, notes: str = "") -> dict:
    return {
        "id": id_,
        "contactId": contact,
        "date": date,
        "totalAmount": float(total),
        "notes": notes,
        "number": f"N{id_}",
    }


def test_monthly_subscription_takes_its_own_month_charge():
    """Two identical monthly invoices: each gets the nearest charge, not the next month's."""
    invoices = [_invoice(10, 1, "2026-07-22", "90"), _invoice(11, 1, "2026-08-22", "90")]
    rows = [
        _row(0, "2026-08-22", "Anthropic* claude sub", "-90"),
        _row(1, "2026-07-22", "Anthropic* claude sub", "-90"),
    ]

    matches, unmatched = match_charges(invoices, CONTACTS, rows)

    assert {(m.purchase_invoice_id, m.row_id) for m in matches} == {(10, "r1"), (11, "r0")}
    assert unmatched == []


def test_bank_marker_matches_partially_registered_invoice():
    """Only 10 % of the supply is registered (16.11) but the bank charged the full 161.10."""
    invoices = [_invoice(20, 2, "2026-07-06", "16.11", "Parte afecta 10% [bank:161.10] [parrot:k]")]
    rows = [_row(0, "2026-07-13", "Adeudo electricidad eleia, s.l.", "-161.10", movement="Adeudo nº 1")]

    matches, _ = match_charges(invoices, CONTACTS, rows)

    assert len(matches) == 1
    assert matches[0].registered_amount == Decimal("16.11")
    assert matches[0].charge_amount == Decimal("161.10")
    assert payment_method_urn(matches[0]) == "urn:payment-method:direct-debit"


def test_one_cent_rounding_tolerance_and_supplier_guard():
    """OpenAI rounds VAT per line (88.87) vs Hooba per invoice (88.86); another supplier never matches."""
    invoices = [_invoice(30, 4, "2026-09-05", "88.86"), _invoice(31, 1, "2026-09-05", "88.86")]
    rows = [_row(0, "2026-09-05", "Openai *chatgpt subscr", "-88.87")]

    matches, unmatched = match_charges(invoices, CONTACTS, rows)

    assert [m.purchase_invoice_id for m in matches] == [30]
    assert [r["id"] for r in unmatched] == [31]


def test_out_of_window_and_trade_name_tokens():
    """A charge 40 days later is not this invoice's; TGSS matches via its trade name."""
    assert "TGSS" in supplier_tokens(CONTACTS[3])
    invoices = [_invoice(40, 3, "2026-07-31", "299.57"), _invoice(41, 1, "2026-06-22", "90")]
    rows = [
        _row(0, "2026-07-31", "Adeudo de cuota de la seguridad social TGSS. COTIZACION", "-299.57", "N 2026"),
        _row(1, "2026-08-01", "Anthropic* claude sub", "-90"),
    ]

    matches, unmatched = match_charges(invoices, CONTACTS, rows)

    assert [m.purchase_invoice_id for m in matches] == [40]
    assert [r["id"] for r in unmatched] == [41]


class _ScriptedHooba:
    """Minimal in-memory Hooba for the reconcile tool: records every write."""

    def __init__(self) -> None:
        self.invoices = {
            50: {
                "id": 50,
                "contactId": 1,
                "date": "2026-07-22",
                "number": "A-19",
                "state": "draft",
                "totalAmount": 90.0,
                "outstandingAmount": 90.0,
                "notes": "",
            },
            51: {
                "id": 51,
                "contactId": 1,
                "date": "2026-08-22",
                "number": "A-20",
                "state": "confirmed",
                "totalAmount": 90.0,
                "outstandingAmount": 90.0,
                "notes": "",
            },
            52: {
                "id": 52,
                "contactId": 4,
                "date": "2026-09-05",
                "number": "O-20",
                "state": "draft",
                "totalAmount": 88.86,
                "outstandingAmount": 88.86,
                "notes": "",
            },
            53: {
                "id": 53,
                "contactId": 3,
                "date": "2026-07-31",
                "number": "T-07",
                "state": "draft",
                "totalAmount": 299.57,
                "outstandingAmount": 299.57,
                "notes": "",
            },
        }
        self.writes: list[tuple[str, str, Optional[dict]]] = []

    async def __call__(self, method: str, path: str, *, params: Optional[dict] = None, data: Any = None) -> Any:
        if method == "GET" and path == "/accounts/{accountId}/purchase-invoices":
            return (
                [{"purchaseInvoice": inv} for inv in self.invoices.values()]
                if (params or {}).get("offset") == 0
                else []
            )
        if method == "GET" and path == "/accounts/{accountId}/contacts":
            return [{"contact": c} for c in CONTACTS.values()] if (params or {}).get("offset") == 0 else []
        if method == "GET" and path.startswith("/accounts/{accountId}/purchase-invoices/"):
            return {"purchaseInvoice": self.invoices[int(path.rsplit("/", 1)[1])]}
        if method == "GET" and path == "/payment-methods":
            return [
                {"id": 7, "urn": "urn:payment-method:card"},
                {"id": 4, "urn": "urn:payment-method:direct-debit"},
                {"id": 1, "urn": "urn:payment-method:bank-transfer"},
                {"id": 3, "urn": "urn:payment-method:custom"},
            ]
        if method == "GET" and path == "/accounts/{accountId}/account-bank-accounts":
            return [{"id": 9, "default": False}, {"id": 32558, "default": True}]
        self.writes.append((method, path, data))
        invoice_id = int(path.split("/")[4].split(":")[0])
        if path.endswith(":confirm"):
            self.invoices[invoice_id]["state"] = "confirmed"
        elif path.endswith("/purchase-invoice-collections"):
            self.invoices[invoice_id]["outstandingAmount"] = 0.0
        return {}


@pytest.fixture
def reconcile_toolkit(monkeypatch):
    fake = _ScriptedHooba()
    toolkit = HoobaToolkit(HoobaSettings(base_url="https://hooba.invalid", account_id=1))
    toolkit._call = fake
    statement = BbvaStatement(
        path="x.xlsx",
        digest="d",
        sheet="s",
        header_row=2,
        skipped=0,
        row_count=4,
        rows=[
            _row(0, "2026-07-22", "Anthropic* claude sub", "-90"),
            _row(1, "2026-08-22", "Anthropic* claude sub", "-90"),
            _row(2, "2026-09-05", "Openai *chatgpt subscr", "-88.87"),
            _row(3, "2026-07-31", "Adeudo de cuota de la seguridad social TGSS", "-299.57", "Adeudo nº 1"),
        ],
    )

    async def fake_parse(path):
        return statement

    monkeypatch.setattr("parrot_tools.hooba.toolkit.parse_bbva_statement", fake_parse)
    return toolkit, fake


async def test_reconcile_dry_run_writes_nothing(reconcile_toolkit):
    toolkit, fake = reconcile_toolkit

    result = await toolkit.hooba_reconcile_bank_statement("x.xlsx")

    assert result["status"] == "success", result
    assert [m["purchase_invoice_id"] for m in result["result"]["matched"]] == [50, 53, 51, 52]
    assert fake.writes == []


async def test_reconcile_apply_confirms_drafts_and_registers_payments(reconcile_toolkit):
    toolkit, fake = reconcile_toolkit

    result = await toolkit.hooba_reconcile_bank_statement("x.xlsx", dry_run=False)

    assert result["status"] == "success", result
    confirms = [path for method, path, _ in fake.writes if path.endswith(":confirm")]
    assert confirms == [
        "/accounts/{accountId}/purchase-invoices/50:confirm",
        "/accounts/{accountId}/purchase-invoices/53:confirm",
        "/accounts/{accountId}/purchase-invoices/52:confirm",
    ]  # 51 was already confirmed
    payments = {path.split("/")[4]: data for method, path, data in fake.writes if path.endswith("collections")}
    assert payments["50"] == {"date": "2026-07-22", "amount": 90.0, "paymentMethodId": 7}  # card: no bank account
    assert payments["53"]["bankAccountId"] == 32558  # direct debit: settled through the bank account
    assert payments["52"]["amount"] == 88.86  # the outstanding amount, not the 88.87 charged
    assert toolkit.operation_kinds()["hooba_reconcile_bank_statement"].value == "submit"

    again = await toolkit.hooba_reconcile_bank_statement("x.xlsx", dry_run=False)
    assert again["result"]["matched"] == []  # everything paid: nothing left open to match
    assert len(fake.writes) == 7

"""FEAT-602 TASK-3743 — draft tools (fake transport, no HTTP)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Optional

import pytest
from aiohttp import web

from parrot_tools.hooba import HoobaSettings, HoobaToolkit
from parrot_tools.hooba.models import InvoiceDraft, InvoiceLineDraft, PurchaseInvoiceDraft, PurchaseInvoiceLineDraft

from .fixtures.make_bbva_fixture import build_bbva_workbook


class FakeHooba:
    """Scripted responses for _call keyed by (method, path); records every call."""

    def __init__(self, responses: dict[tuple[str, str], Any]) -> None:
        self.responses = dict(responses)
        self.calls: list[tuple[str, str, Optional[dict]]] = []

    async def __call__(
        self, method: str, path: str, *, params: Optional[dict] = None, data: Optional[dict] = None
    ) -> Any:
        key = (method.upper(), path)
        self.calls.append((key[0], key[1], data))
        if key not in self.responses:
            raise AssertionError(f"FakeHooba: no scripted response for {key}; calls so far: {self.calls}")
        response = self.responses[key]
        return response(data) if callable(response) else response


class _StubApi:
    """Minimal `_api` stand-in — avoids loading the real pinned spec in tests."""

    def __init__(self, cookies: Optional[dict] = None) -> None:
        self._cookies = cookies or {"sid": "fake"}

    async def _ensure_session(self, force: bool = False) -> None:
        return None

    def get_cookies(self) -> dict:
        return dict(self._cookies)


def _make_toolkit(
    fake_call: FakeHooba, *, rules_path: Optional[str] = None, base_url: Optional[str] = None
) -> HoobaToolkit:
    """Build a HoobaToolkit whose ``_api`` never touches the network and whose ``_call`` is scripted."""
    settings = HoobaSettings(account_id=123, base_url=base_url or "https://api.hooba.com")
    toolkit = HoobaToolkit(settings=settings, api=_StubApi(), rules_path=rules_path)
    toolkit._call = fake_call
    return toolkit


@pytest.fixture(autouse=True)
def _state_dir(tmp_path, monkeypatch):
    """Keep BBVA import manifests isolated for each test."""
    monkeypatch.setenv("PARROT_STATE_DIR", str(tmp_path / "state"))


async def test_create_invoice_draft_resolves_ids_and_posts_lines():
    fake = FakeHooba(
        {
            ("GET", "/accounts/{accountId}/invoices"): [],
            ("GET", "/accounts/{accountId}/contacts"): [{"id": 10, "legalName": "Acme Corp"}],
            ("GET", "/accounts/{accountId}/invoice-series"): [
                {"id": 7, "code": "A", "default": True, "defaultForSimplified": False},
            ],
            ("POST", "/accounts/{accountId}/invoices"): {"id": 501, "number": "F-1"},
            ("GET", "/accounts/{accountId}/invoices/501/invoice-lines"): [],
            ("GET", "/taxes"): [{"id": 55, "operationType": "sale", "percentage": 21}],
            ("POST", "/accounts/{accountId}/invoices/501/invoice-lines"): {
                "invoiceLine": {"id": 900, "name": "Consulting", "price": "100.00"}
            },
            ("GET", "/accounts/{accountId}/invoices/501"): {"id": 501, "state": "draft", "number": "F-1"},
        }
    )
    toolkit = _make_toolkit(fake)

    draft = InvoiceDraft(
        contact_query="Acme Corp",
        lines=[InvoiceLineDraft(name="Consulting", price=Decimal("100.00"))],
    )
    result = await toolkit.hooba_create_invoice_draft(draft)

    assert result["status"] == "success"
    receipt = result["result"]
    assert receipt["id"] == 501
    assert receipt["state"] == "draft"
    assert receipt["reused"] is False
    assert receipt["line_ids"] == [900]

    call_keys = [(method, path) for method, path, _ in fake.calls]
    # Lookups happen before the header POST; the header POST happens before the line POST.
    assert call_keys.index(("GET", "/accounts/{accountId}/contacts")) < call_keys.index(
        ("POST", "/accounts/{accountId}/invoices")
    )
    assert call_keys.index(("GET", "/accounts/{accountId}/invoice-series")) < call_keys.index(
        ("POST", "/accounts/{accountId}/invoices")
    )
    assert call_keys.index(("GET", "/taxes")) < call_keys.index(
        ("POST", "/accounts/{accountId}/invoices/501/invoice-lines")
    )

    line_call = next(
        (method, path, data)
        for method, path, data in fake.calls
        if (method, path) == ("POST", "/accounts/{accountId}/invoices/501/invoice-lines")
    )
    assert line_call[2]["type"] == "product"
    assert line_call[2]["name"] == "Consulting"
    assert line_call[2]["taxId"] == 55
    assert line_call[2]["incomeTaxId"] is None


async def test_create_draft_rejects_non_draft_state():
    fake = FakeHooba(
        {
            ("GET", "/accounts/{accountId}/invoices"): [],
            ("GET", "/accounts/{accountId}/invoice-series"): [{"id": 7, "default": True}],
            ("POST", "/accounts/{accountId}/invoices"): {"id": 502},
            ("GET", "/accounts/{accountId}/invoices/502/invoice-lines"): [],
            ("GET", "/taxes"): [{"id": 55, "operationType": "sale", "percentage": 21}],
            ("POST", "/accounts/{accountId}/invoices/502/invoice-lines"): {"invoiceLine": {"id": 901}},
            ("GET", "/accounts/{accountId}/invoices/502"): {"id": 502, "state": "issued"},
        }
    )
    toolkit = _make_toolkit(fake)
    draft = InvoiceDraft(contact_id=10, lines=[InvoiceLineDraft(name="Line", price=Decimal("5"))])

    result = await toolkit.hooba_create_invoice_draft(draft)

    assert result["status"] == "error"
    assert "issued" in result["error"]


async def test_create_draft_reuses_existing_by_correlation_key():
    key = "corr-1"
    fake = FakeHooba(
        {
            ("GET", "/accounts/{accountId}/invoices"): [
                {"id": 600, "notes": f"prior note [parrot:{key}]", "number": "F-2"}
            ],
            ("GET", "/accounts/{accountId}/invoices/600/invoice-lines"): [
                {"invoiceLine": {"id": 700, "name": "Line A", "price": "10.00"}}
            ],
            ("GET", "/taxes"): [{"id": 55, "operationType": "sale", "percentage": 21}],
            ("POST", "/accounts/{accountId}/invoices/600/invoice-lines"): {
                "invoiceLine": {"id": 701, "name": "Line B", "price": "20.00"}
            },
            ("GET", "/accounts/{accountId}/invoices/600"): {"id": 600, "state": "draft", "number": "F-2"},
        }
    )
    toolkit = _make_toolkit(fake)
    draft = InvoiceDraft(
        contact_id=10,
        correlation_key=key,
        lines=[
            InvoiceLineDraft(name="Line A", price=Decimal("10.00")),
            InvoiceLineDraft(name="Line B", price=Decimal("20.00")),
        ],
    )

    result = await toolkit.hooba_create_invoice_draft(draft)

    assert result["status"] == "success"
    receipt = result["result"]
    assert receipt["reused"] is True
    assert set(receipt["line_ids"]) == {700, 701}

    line_posts = [
        (method, path, data) for method, path, data in fake.calls if method == "POST" and path.endswith("invoice-lines")
    ]
    assert len(line_posts) == 1
    assert line_posts[0][2]["name"] == "Line B"

    header_posts = [call for call in fake.calls if call[:2] == ("POST", "/accounts/{accountId}/invoices")]
    assert header_posts == []


async def test_create_purchase_invoice_draft_simplified():
    fake = FakeHooba(
        {
            ("GET", "/accounts/{accountId}/purchase-invoices"): [],
            ("POST", "/accounts/{accountId}/purchase-invoices"): {"id": 701, "number": "G-1"},
            ("GET", "/accounts/{accountId}/purchase-invoices/701/purchase-invoice-lines"): [],
            ("GET", "/taxes"): [{"id": 66, "operationType": "purchase", "percentage": 21}],
            ("POST", "/accounts/{accountId}/purchase-invoices/701/purchase-invoice-lines"): {
                "purchaseInvoiceLine": {"id": 950, "name": "Software", "price": "9.99"}
            },
            ("GET", "/accounts/{accountId}/purchase-invoices/701"): {"id": 701, "state": "draft", "number": "G-1"},
        }
    )
    toolkit = _make_toolkit(fake)
    draft = PurchaseInvoiceDraft(
        date=dt.date(2026, 9, 10),
        simplified=True,
        tax_included=True,
        lines=[PurchaseInvoiceLineDraft(name="Software", price=Decimal("9.99"), tax_code="IVA21")],
    )

    result = await toolkit.hooba_create_purchase_invoice_draft(draft)

    assert result["status"] == "success"
    receipt = result["result"]
    assert receipt["kind"] == "purchase_invoice"
    assert receipt["id"] == 701
    assert receipt["line_ids"] == [950]

    line_call = next(
        (method, path, data)
        for method, path, data in fake.calls
        if (method, path) == ("POST", "/accounts/{accountId}/purchase-invoices/701/purchase-invoice-lines")
    )
    assert "type" not in line_call[2]
    assert line_call[2]["taxId"] == 66
    assert line_call[2]["accountingAccountId"] is None

    header_call = next(
        (method, path, data)
        for method, path, data in fake.calls
        if (method, path) == ("POST", "/accounts/{accountId}/purchase-invoices")
    )
    assert header_call[2]["contactId"] is None


async def test_unresolvable_tax_is_error_not_guess():
    fake = FakeHooba(
        {
            ("GET", "/accounts/{accountId}/invoices"): [],
            ("GET", "/accounts/{accountId}/invoice-series"): [{"id": 7, "default": True}],
            ("POST", "/accounts/{accountId}/invoices"): {"id": 503},
            ("GET", "/accounts/{accountId}/invoices/503/invoice-lines"): [],
            ("GET", "/taxes"): [{"id": 55, "operationType": "sale", "percentage": 10}],
        }
    )
    toolkit = _make_toolkit(fake)
    draft = InvoiceDraft(
        contact_id=10,
        lines=[InvoiceLineDraft(name="Mystery", price=Decimal("1"), tax_code="IVA99")],
    )

    result = await toolkit.hooba_create_invoice_draft(draft)

    assert result["status"] == "error"
    assert "tax" in result["error"].lower()
    line_posts = [call for call in fake.calls if call[0] == "POST" and call[1].endswith("invoice-lines")]
    assert line_posts == []


async def test_attach_document_multipart(aiohttp_server, tmp_path):
    received: dict[str, Any] = {}

    async def upload_handler(request: web.Request) -> web.Response:
        received["headers"] = dict(request.headers)
        reader = await request.multipart()
        fields: dict[str, Any] = {}
        async for part in reader:
            if part.name == "file":
                fields["file"] = await part.read()
                fields["filename"] = part.filename
            else:
                fields[part.name] = (await part.read()).decode()
        received["fields"] = fields
        return web.json_response({"id": 999}, status=201)

    app = web.Application()
    app.router.add_post("/accounts/{accountId}/documents/{documentTypeId}/{entityRecordId}", upload_handler)
    server = await aiohttp_server(app)

    fake = FakeHooba(
        {
            ("GET", "/accounts/{accountId}/document-types"): [
                {"documentType": {"id": 7}, "entity": {"urn": "urn:entity:invoice"}},
            ],
        }
    )
    base_url = str(server.make_url("")).rstrip("/")
    toolkit = _make_toolkit(fake, base_url=base_url)
    toolkit._api = _StubApi(cookies={"sid": "s3cr3t"})

    file_path = tmp_path / "receipt.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake")

    result = await toolkit.hooba_attach_document("invoice", 501, str(file_path))

    assert result["status"] == "success"
    assert result["result"] == {"id": 999}
    assert received["fields"]["data"] == "{}"
    assert received["fields"]["filename"] == "receipt.pdf"
    assert received["fields"]["file"] == b"%PDF-1.4 fake"
    assert "sid=s3cr3t" in received["headers"].get("Cookie", "")
    assert received["headers"].get("x-hooba-language") == "es"


async def test_import_bbva_dry_run_posts_nothing(tmp_path, monkeypatch):
    workbook = build_bbva_workbook(tmp_path / "bbva.xlsx")
    fake = FakeHooba({("GET", "/accounts/{accountId}/contacts"): []})
    toolkit = _make_toolkit(fake)

    result = await toolkit.hooba_import_bbva_statement(str(workbook), period="2026-09", dry_run=True)

    assert result["status"] == "success"
    batch = result["result"]
    assert batch["dry_run"] is True
    assert batch["planned"] == 4
    assert batch["created"] == []
    assert batch["manifest_path"].endswith(".manifest.json")
    assert all(method != "POST" for method, _, _ in fake.calls)

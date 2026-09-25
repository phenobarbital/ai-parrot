"""A fake api.hooba.com for FEAT-602 integration tests (aiohttp.web)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from aiohttp import web

ACCOUNT_ID = 23549
USERNAME, PASSWORD = "user@example.test", "not-a-real-password"


@dataclass
class FakeHoobaState:
    """Everything the fake server stored or saw."""

    requests: list[tuple[str, str]] = field(default_factory=list)  # (METHOD, path)
    invoices: dict[int, dict[str, Any]] = field(default_factory=dict)
    purchase_invoices: dict[int, dict[str, Any]] = field(default_factory=dict)
    documents: list[dict[str, Any]] = field(default_factory=list)
    expire_after: int | None = None  # invalidate sid after N authenticated requests
    logins: int = 0
    contacts: list[dict[str, Any]] = field(default_factory=list)
    invoice_series: list[dict[str, Any]] = field(default_factory=list)
    taxes: list[dict[str, Any]] = field(default_factory=list)
    income_taxes: list[dict[str, Any]] = field(default_factory=list)
    document_types: list[dict[str, Any]] = field(default_factory=list)
    invoice_counter: int = 0
    purchase_invoice_counter: int = 0
    contact_counter: int = 0


def _require_auth(request: web.Request, state: FakeHoobaState) -> Optional[web.Response]:
    """Return 401 if no valid sid cookie, else None."""
    sid = request.cookies.get("sid")
    if not sid or sid != f"valid-{state.logins}":
        return web.Response(status=401, text="Unauthorized")
    return None


def _record_request(state: FakeHoobaState, method: str, path: str) -> None:
    """Record the request for test assertions."""
    state.requests.append((method, path))


async def _handle_login(request: web.Request) -> web.Response:
    """POST /auth/login - set sid cookie."""
    state = request.app["state"]
    data = await request.json()
    if data.get("username") != USERNAME or data.get("password") != PASSWORD:
        return web.Response(status=401, json={"error": "invalid credentials"})

    state.logins += 1
    sid = f"valid-{state.logins}"
    resp = web.json_response({"sid": sid, "userId": 1})
    resp.set_cookie("sid", sid, httponly=True, path="/")
    return resp


async def _handle_whoami(request: web.Request) -> web.Response:
    """GET /accounts/{accountId}/check - session check."""
    state = request.app["state"]
    if err := _require_auth(request, state):
        return err
    _record_request(state, "GET", request.path)
    return web.json_response(
        {
            "accountId": ACCOUNT_ID,
            "userId": 1,
            "memberId": 10,
            "subscriptionId": 100,
        }
    )


async def _handle_member(request: web.Request) -> web.Response:
    """GET /accounts/{accountId}/member - member info."""
    state = request.app["state"]
    if err := _require_auth(request, state):
        return err
    _record_request(state, "GET", request.path)
    return web.json_response(
        {
            "id": 10,
            "userId": 1,
            "accountId": ACCOUNT_ID,
            "subscriptionId": 100,
        }
    )


async def _handle_contacts(request: web.Request) -> web.Response:
    """GET /accounts/{accountId}/contacts."""
    state = request.app["state"]
    if err := _require_auth(request, state):
        return err
    _record_request(state, "GET", request.path)
    return web.json_response(state.contacts)


async def _handle_invoice_series(request: web.Request) -> web.Response:
    """GET /accounts/{accountId}/invoice-series."""
    state = request.app["state"]
    if err := _require_auth(request, state):
        return err
    _record_request(state, "GET", request.path)
    return web.json_response(state.invoice_series)


async def _handle_taxes(request: web.Request) -> web.Response:
    """GET /taxes."""
    state = request.app["state"]
    if err := _require_auth(request, state):
        return err
    _record_request(state, "GET", request.path)
    return web.json_response(state.taxes)


async def _handle_income_taxes(request: web.Request) -> web.Response:
    """GET /income-taxes."""
    state = request.app["state"]
    if err := _require_auth(request, state):
        return err
    _record_request(state, "GET", request.path)
    return web.json_response(state.income_taxes)


async def _handle_document_types(request: web.Request) -> web.Response:
    """GET /accounts/{accountId}/document-types."""
    state = request.app["state"]
    if err := _require_auth(request, state):
        return err
    _record_request(state, "GET", request.path)
    return web.json_response(state.document_types)


async def _handle_invoices(request: web.Request) -> web.Response:
    """GET/POST /accounts/{accountId}/invoices."""
    state = request.app["state"]
    if err := _require_auth(request, state):
        return err
    _record_request(state, request.method, request.path)

    if request.method == "GET":
        return web.json_response(list(state.invoices.values()))

    # POST - create invoice draft
    data = await request.json()
    state.invoice_counter += 1
    invoice_id = 1000 + state.invoice_counter
    invoice = {
        "id": invoice_id,
        "number": f"F-{state.invoice_counter}",
        "state": "draft",
        "contactId": data.get("contactId"),
        "invoiceSerieCode": data.get("invoiceSerieCode"),
        "operationDate": data.get("operationDate"),
        "reference": data.get("reference"),
        "simplified": data.get("simplified", False),
    }
    state.invoices[invoice_id] = invoice
    return web.json_response(invoice)


async def _handle_invoice_lines(request: web.Request) -> web.Response:
    """GET/POST /accounts/{accountId}/invoices/{id}/invoice-lines."""
    state = request.app["state"]
    if err := _require_auth(request, state):
        return err
    _record_request(state, request.method, request.path)

    invoice_id = int(request.match_info["id"])
    if invoice_id not in state.invoices:
        return web.Response(status=404, text="Invoice not found")

    if request.method == "GET":
        return web.json_response([])

    # POST - add line
    data = await request.json()
    line_id = invoice_id * 100 + len(state.invoices[invoice_id].get("lines", [])) + 1
    line = {
        "id": line_id,
        "name": data.get("name"),
        "price": str(data.get("price", 0)),
        "quantity": str(data.get("quantity", 1)),
    }
    if "lines" not in state.invoices[invoice_id]:
        state.invoices[invoice_id]["lines"] = []
    state.invoices[invoice_id]["lines"].append(line)
    return web.json_response({"invoiceLine": line})


async def _handle_invoice(request: web.Request) -> web.Response:
    """GET /accounts/{accountId}/invoices/{id}."""
    state = request.app["state"]
    if err := _require_auth(request, state):
        return err
    _record_request(state, "GET", request.path)

    invoice_id = int(request.match_info["id"])
    if invoice_id not in state.invoices:
        return web.Response(status=404, text="Invoice not found")
    return web.json_response(state.invoices[invoice_id])


async def _handle_invoice_download(request: web.Request) -> web.Response:
    """GET /accounts/{accountId}/invoices/{id}/download - return fake PDF."""
    state = request.app["state"]
    if err := _require_auth(request, state):
        return err
    _record_request(state, "GET", request.path)
    return web.Response(body=b"%PDF-fake-invoice", content_type="application/pdf")


async def _handle_purchase_invoices(request: web.Request) -> web.Response:
    """GET/POST /accounts/{accountId}/purchase-invoices."""
    state = request.app["state"]
    if err := _require_auth(request, state):
        return err
    _record_request(state, request.method, request.path)

    if request.method == "GET":
        return web.json_response(list(state.purchase_invoices.values()))

    # POST - create purchase invoice draft
    data = await request.json()
    state.purchase_invoice_counter += 1
    invoice_id = 2000 + state.purchase_invoice_counter
    invoice = {
        "id": invoice_id,
        "number": data.get("number"),
        "state": "draft",
        "date": data.get("date"),
        "contactId": data.get("contactId"),
        "simplified": data.get("simplified", False),
    }
    state.purchase_invoices[invoice_id] = invoice
    return web.json_response(invoice)


async def _handle_purchase_invoice_lines(request: web.Request) -> web.Response:
    """GET/POST /accounts/{accountId}/purchase-invoices/{id}/purchase-invoice-lines."""
    state = request.app["state"]
    if err := _require_auth(request, state):
        return err
    _record_request(state, request.method, request.path)

    invoice_id = int(request.match_info["id"])
    if invoice_id not in state.purchase_invoices:
        return web.Response(status=404, text="Purchase invoice not found")

    if request.method == "GET":
        return web.json_response([])

    # POST - add line
    data = await request.json()
    line_id = invoice_id * 100 + len(state.purchase_invoices[invoice_id].get("lines", [])) + 1
    line = {
        "id": line_id,
        "name": data.get("name"),
        "price": str(data.get("price", 0)),
        "quantity": str(data.get("quantity", 1)),
    }
    if "lines" not in state.purchase_invoices[invoice_id]:
        state.purchase_invoices[invoice_id]["lines"] = []
    state.purchase_invoices[invoice_id]["lines"].append(line)
    return web.json_response({"purchaseInvoiceLine": line})


async def _handle_purchase_invoice(request: web.Request) -> web.Response:
    """GET /accounts/{accountId}/purchase-invoices/{id}."""
    state = request.app["state"]
    if err := _require_auth(request, state):
        return err
    _record_request(state, "GET", request.path)

    invoice_id = int(request.match_info["id"])
    if invoice_id not in state.purchase_invoices:
        return web.Response(status=404, text="Purchase invoice not found")
    return web.json_response(state.purchase_invoices[invoice_id])


async def _handle_documents(request: web.Request) -> web.Response:
    """POST /accounts/{accountId}/documents - upload document."""
    state = request.app["state"]
    if err := _require_auth(request, state):
        return err
    _record_request(state, "POST", request.path)

    # Handle multipart form data
    reader = await request.multipart()
    entity = None
    entity_id = None
    file_content = None
    file_name = None

    async for field in reader:
        if field.name == "entity":
            entity = await field.text()
        elif field.name == "entityId":
            entity_id = int(await field.text())
        elif field.name == "file":
            file_content = await field.read()
            file_name = field.filename

    doc_id = len(state.documents) + 1
    doc = {
        "id": doc_id,
        "entity": entity,
        "entityId": entity_id,
        "fileName": file_name,
        "size": len(file_content) if file_content else 0,
    }
    state.documents.append(doc)
    return web.json_response(doc)


async def _handle_invoice_series_list(request: web.Request) -> web.Response:
    """GET /accounts/{accountId}/invoice-series - list series."""
    state = request.app["state"]
    if err := _require_auth(request, state):
        return err
    _record_request(state, "GET", request.path)
    return web.json_response(state.invoice_series)


def build_fake_hooba_app(state: FakeHoobaState) -> web.Application:
    """Routes listed in Scope; 401 without a valid sid; created entities start in state 'draft'."""
    app = web.Application()
    app["state"] = state

    # Auth
    app.router.add_post("/auth/login", _handle_login)

    # Account
    app.router.add_get(f"/accounts/{ACCOUNT_ID}/check", _handle_whoami)
    app.router.add_get(f"/accounts/{ACCOUNT_ID}/member", _handle_member)

    # Contacts
    app.router.add_get(f"/accounts/{ACCOUNT_ID}/contacts", _handle_contacts)

    # Invoice series
    app.router.add_get(f"/accounts/{ACCOUNT_ID}/invoice-series", _handle_invoice_series_list)

    # Taxes
    app.router.add_get("/taxes", _handle_taxes)
    app.router.add_get("/income-taxes", _handle_income_taxes)

    # Document types
    app.router.add_get(f"/accounts/{ACCOUNT_ID}/document-types", _handle_document_types)

    # Invoices
    app.router.add_get(f"/accounts/{ACCOUNT_ID}/invoices", _handle_invoices)
    app.router.add_post(f"/accounts/{ACCOUNT_ID}/invoices", _handle_invoices)
    app.router.add_get(f"/accounts/{ACCOUNT_ID}/invoices/{{id}}", _handle_invoice)
    app.router.add_get(f"/accounts/{ACCOUNT_ID}/invoices/{{id}}/invoice-lines", _handle_invoice_lines)
    app.router.add_post(f"/accounts/{ACCOUNT_ID}/invoices/{{id}}/invoice-lines", _handle_invoice_lines)
    app.router.add_get(f"/accounts/{ACCOUNT_ID}/invoices/{{id}}/download", _handle_invoice_download)

    # Purchase invoices
    app.router.add_get(f"/accounts/{ACCOUNT_ID}/purchase-invoices", _handle_purchase_invoices)
    app.router.add_post(f"/accounts/{ACCOUNT_ID}/purchase-invoices", _handle_purchase_invoices)
    app.router.add_get(f"/accounts/{ACCOUNT_ID}/purchase-invoices/{{id}}", _handle_purchase_invoice)
    app.router.add_get(
        f"/accounts/{ACCOUNT_ID}/purchase-invoices/{{id}}/purchase-invoice-lines", _handle_purchase_invoice_lines
    )
    app.router.add_post(
        f"/accounts/{ACCOUNT_ID}/purchase-invoices/{{id}}/purchase-invoice-lines", _handle_purchase_invoice_lines
    )

    # Documents
    app.router.add_post(f"/accounts/{ACCOUNT_ID}/documents", _handle_documents)

    return app

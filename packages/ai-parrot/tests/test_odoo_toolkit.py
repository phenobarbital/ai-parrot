"""Unit tests for OdooToolkit.

The transport is replaced with an AsyncMock so tests are deterministic and
network-free. Each test asserts both: (a) execute_kw is called with the right
model/method/args/kwargs, and (b) the returned envelope/entity is the correct
Pydantic class with the expected fields.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── Stub heavy parrot.utils dependencies ────────────────────────────────────

if "parrot.utils.types" not in sys.modules:
    _utils_types_stub = types.ModuleType("parrot.utils.types")
    _utils_types_stub.SafeDict = dict
    _utils_types_stub.cPrint = lambda *a, **kw: None
    sys.modules["parrot.utils.types"] = _utils_types_stub

if "parrot.utils" not in sys.modules:
    _utils_stub = types.ModuleType("parrot.utils")
    _utils_stub.SafeDict = dict
    _utils_stub.cPrint = lambda *a, **kw: None
    sys.modules["parrot.utils"] = _utils_stub

# ─────────────────────────────────────────────────────────────────────────────

from parrot.interfaces.odoointerface import OdooConfig  # noqa: E402
from parrot_tools.odoo.models.entities import (  # noqa: E402
    AccountMove,
    ResPartner,
    SaleOrder,
)
from parrot_tools.odoo.models.envelopes import (  # noqa: E402
    BinaryFieldResult,
    BulkCreateResult,
    BulkDeleteResult,
    BulkUpdateResult,
    CreateResult,
    DeleteResult,
    ImportResult,
    ModelsResult,
    RecordResult,
    SearchResult,
    ServerInfoResult,
    UpdateResult,
)
from parrot_tools.odoo.toolkit import OdooToolkit  # noqa: E402


# ── Fixtures ────────────────────────────────────────────────────────────────


def _fake_transport(uid: int = 1) -> MagicMock:
    """Build a fake AbstractOdooTransport with AsyncMock methods."""
    transport = MagicMock()
    transport.config = OdooConfig(
        url="https://odoo.example.com",
        database="testdb",
        username="admin",
        password="secret",
        timeout=10,
        verify_ssl=False,
    )
    transport.uid = uid
    transport.name = "jsonrpc"
    transport.authenticate = AsyncMock(return_value=uid)
    transport.execute_kw = AsyncMock(return_value=None)
    transport.version = AsyncMock(return_value={
        "server_serie": "19.0", "server_version": "19.0+e", "protocol_version": 1,
    })
    transport.close = AsyncMock(return_value=None)
    return transport


def _make_toolkit(transport: MagicMock | None = None) -> OdooToolkit:
    return OdooToolkit(
        url="https://odoo.example.com",
        database="testdb",
        username="admin",
        password="secret",
        verify_ssl=False,
        transport=transport or _fake_transport(),
    )


# ── Tool discovery / schema ─────────────────────────────────────────────────


def test_get_tools_exposes_expected_surface():
    toolkit = _make_toolkit()
    tool_names = {t.name for t in toolkit.get_tools()}

    expected = {
        # discovery
        "server_info", "list_models", "fields_get",
        # generic CRUD
        "search_records", "get_record",
        "create_record", "create_records",
        "update_record", "update_records",
        "delete_record", "delete_records",
        "import_records",
        # partner helpers
        "find_partner", "create_partner", "update_partner_contact_info",
        # sales helpers
        "create_quotation", "confirm_sale_order",
        # invoicing helpers
        "create_invoice", "post_invoice", "register_payment",
        # binary helpers
        "set_binary_field", "attach_document",
    }
    missing = expected - tool_names
    assert not missing, f"missing tools: {missing}"


def test_each_tool_has_args_schema():
    toolkit = _make_toolkit()
    for tool in toolkit.get_tools():
        # tools without parameters (server_info, list_models) get an
        # empty auto-generated schema, which is still not None.
        assert tool.args_schema is not None, f"{tool.name} missing args_schema"


# ── Generic CRUD ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_records_calls_search_read_and_search_count():
    transport = _fake_transport()
    transport.execute_kw.side_effect = [
        [{"id": 1, "name": "Acme"}, {"id": 2, "name": "Beta"}],  # search_read
        2,  # search_count
    ]
    toolkit = _make_toolkit(transport)

    result = await toolkit.search_records(
        model="res.partner",
        domain=[("is_company", "=", True)],
        fields=["name"],
        limit=5,
    )

    assert isinstance(result, SearchResult)
    assert result.total == 2
    assert result.model == "res.partner"
    assert [r["name"] for r in result.records] == ["Acme", "Beta"]

    # Inspect the first call (search_read)
    first_call = transport.execute_kw.call_args_list[0]
    assert first_call.args[0] == "res.partner"
    assert first_call.args[1] == "search_read"
    assert first_call.args[2] == [[("is_company", "=", True)]]
    assert first_call.args[3] == {"fields": ["name"], "limit": 5, "offset": 0}


@pytest.mark.asyncio
async def test_get_record_uses_read():
    transport = _fake_transport()
    transport.execute_kw.return_value = [{"id": 7, "name": "Acme"}]
    toolkit = _make_toolkit(transport)

    result = await toolkit.get_record(model="res.partner", record_id=7)

    assert isinstance(result, RecordResult)
    assert result.record == {"id": 7, "name": "Acme"}
    assert result.model == "res.partner"
    transport.execute_kw.assert_awaited_once_with(
        "res.partner", "read", [[7]], {}
    )


@pytest.mark.asyncio
async def test_create_record_then_reads_back():
    transport = _fake_transport()
    transport.execute_kw.side_effect = [42, [{"id": 42, "name": "New"}]]
    toolkit = _make_toolkit(transport)

    result = await toolkit.create_record(
        model="res.partner", values={"name": "New"}
    )

    assert isinstance(result, CreateResult)
    assert result.record_id == 42
    assert result.success is True
    assert result.record["id"] == 42

    create_call = transport.execute_kw.call_args_list[0]
    assert create_call.args[:3] == ("res.partner", "create", [{"name": "New"}])


@pytest.mark.asyncio
async def test_create_records_bulk():
    transport = _fake_transport()
    transport.execute_kw.return_value = [11, 12, 13]
    toolkit = _make_toolkit(transport)

    result = await toolkit.create_records(
        model="res.partner",
        vals_list=[{"name": "A"}, {"name": "B"}, {"name": "C"}],
    )

    assert isinstance(result, BulkCreateResult)
    assert result.created_ids == [11, 12, 13]
    assert result.count == 3


@pytest.mark.asyncio
async def test_update_record():
    transport = _fake_transport()
    transport.execute_kw.side_effect = [True, [{"id": 5, "name": "X"}]]
    toolkit = _make_toolkit(transport)

    result = await toolkit.update_record(
        model="res.partner", record_id=5, values={"name": "X"}
    )

    assert isinstance(result, UpdateResult)
    assert result.success is True
    write_call = transport.execute_kw.call_args_list[0]
    assert write_call.args[:3] == ("res.partner", "write", [[5], {"name": "X"}])


@pytest.mark.asyncio
async def test_update_records_bulk():
    transport = _fake_transport()
    transport.execute_kw.return_value = True
    toolkit = _make_toolkit(transport)

    result = await toolkit.update_records(
        model="res.partner", record_ids=[1, 2, 3], values={"active": False}
    )

    assert isinstance(result, BulkUpdateResult)
    assert result.count == 3
    transport.execute_kw.assert_awaited_once_with(
        "res.partner", "write", [[1, 2, 3], {"active": False}], None
    )


@pytest.mark.asyncio
async def test_delete_record():
    transport = _fake_transport()
    transport.execute_kw.return_value = True
    toolkit = _make_toolkit(transport)

    result = await toolkit.delete_record(model="res.partner", record_id=99)

    assert isinstance(result, DeleteResult)
    assert result.success is True
    assert result.deleted_id == 99
    transport.execute_kw.assert_awaited_once_with(
        "res.partner", "unlink", [[99]], None
    )


@pytest.mark.asyncio
async def test_delete_records_bulk():
    transport = _fake_transport()
    transport.execute_kw.return_value = True
    toolkit = _make_toolkit(transport)

    result = await toolkit.delete_records(
        model="res.partner", record_ids=[3, 4, 5]
    )

    assert isinstance(result, BulkDeleteResult)
    assert result.count == 3
    transport.execute_kw.assert_awaited_once_with(
        "res.partner", "unlink", [[3, 4, 5]], None
    )


@pytest.mark.asyncio
async def test_import_records_returns_envelope():
    transport = _fake_transport()
    transport.execute_kw.return_value = {"ids": [1, 2], "messages": []}
    toolkit = _make_toolkit(transport)

    result = await toolkit.import_records(
        model="res.partner",
        fields=["id", "name"],
        data=[["__ext.acme", "Acme"], ["__ext.beta", "Beta"]],
    )

    assert isinstance(result, ImportResult)
    assert result.imported == 2
    assert result.errors == []
    transport.execute_kw.assert_awaited_once_with(
        "res.partner", "load",
        [["id", "name"], [["__ext.acme", "Acme"], ["__ext.beta", "Beta"]]],
        {},
    )


# ── Discovery ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_server_info_returns_typed_envelope():
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    result = await toolkit.server_info()

    assert isinstance(result, ServerInfoResult)
    assert result.server_serie == "19.0"
    assert result.connected is True
    assert result.transport == "jsonrpc"
    assert result.uid == 1


@pytest.mark.asyncio
async def test_list_models_collects_acl_per_model():
    transport = _fake_transport()
    transport.execute_kw.return_value = True  # all access rights granted
    toolkit = _make_toolkit(transport)

    result = await toolkit.list_models()

    assert isinstance(result, ModelsResult)
    assert result.total == 10
    techs = {m.model for m in result.models}
    assert {"res.partner", "sale.order", "account.move"} <= techs


@pytest.mark.asyncio
async def test_fields_get_passes_attributes():
    transport = _fake_transport()
    transport.execute_kw.return_value = {"name": {"type": "char", "string": "Name"}}
    toolkit = _make_toolkit(transport)

    fields = await toolkit.fields_get(
        model="res.partner", attributes=["string", "type"]
    )

    assert "name" in fields
    transport.execute_kw.assert_awaited_once_with(
        "res.partner", "fields_get", [], {"attributes": ["string", "type"]}
    )


# ── Partner helpers ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_find_partner_returns_typed_models():
    transport = _fake_transport()
    transport.execute_kw.return_value = [
        {"id": 1, "name": "Acme", "is_company": True, "email": "a@acme.com"},
    ]
    toolkit = _make_toolkit(transport)

    partners = await toolkit.find_partner(name="Acme", is_company=True)

    assert len(partners) == 1
    assert isinstance(partners[0], ResPartner)
    assert partners[0].id == 1
    assert partners[0].email == "a@acme.com"


@pytest.mark.asyncio
async def test_create_partner_returns_typed_model():
    transport = _fake_transport()
    transport.execute_kw.side_effect = [
        21,
        [{"id": 21, "name": "NewCo", "is_company": True}],
    ]
    toolkit = _make_toolkit(transport)

    partner = await toolkit.create_partner(name="NewCo", is_company=True)

    assert isinstance(partner, ResPartner)
    assert partner.id == 21
    assert partner.name == "NewCo"


@pytest.mark.asyncio
async def test_update_partner_contact_info_requires_at_least_one_field():
    toolkit = _make_toolkit()
    with pytest.raises(ValueError):
        await toolkit.update_partner_contact_info(partner_id=1)


# ── Sales / invoicing helpers ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_quotation_builds_one2many_commands():
    transport = _fake_transport()
    transport.execute_kw.side_effect = [
        100,
        [{"id": 100, "name": "S00100", "state": "draft"}],
    ]
    toolkit = _make_toolkit(transport)

    quote = await toolkit.create_quotation(
        partner_id=7,
        order_lines=[{"product_id": 3, "product_uom_qty": 2.0, "price_unit": 50.0}],
    )

    assert isinstance(quote, SaleOrder)
    create_call = transport.execute_kw.call_args_list[0]
    payload = create_call.args[2][0]  # values dict
    assert payload["partner_id"] == 7
    # Odoo One2many command tuple: (0, 0, vals)
    assert payload["order_line"][0][0] == 0
    assert payload["order_line"][0][1] == 0
    assert payload["order_line"][0][2]["product_id"] == 3


@pytest.mark.asyncio
async def test_confirm_sale_order_calls_action_confirm():
    transport = _fake_transport()
    transport.execute_kw.side_effect = [
        True,
        [{"id": 100, "name": "S00100", "state": "sale"}],
    ]
    toolkit = _make_toolkit(transport)

    result = await toolkit.confirm_sale_order(sale_order_id=100)

    assert isinstance(result, SaleOrder)
    confirm_call = transport.execute_kw.call_args_list[0]
    assert confirm_call.args[:3] == ("sale.order", "action_confirm", [[100]])


@pytest.mark.asyncio
async def test_create_invoice_uses_invoice_line_ids_one2many():
    transport = _fake_transport()
    transport.execute_kw.side_effect = [
        500,
        [{"id": 500, "move_type": "out_invoice", "state": "draft"}],
    ]
    toolkit = _make_toolkit(transport)

    invoice = await toolkit.create_invoice(
        partner_id=9,
        invoice_lines=[{"price_unit": 100.0, "quantity": 1.0, "name": "Service"}],
    )

    assert isinstance(invoice, AccountMove)
    create_call = transport.execute_kw.call_args_list[0]
    payload = create_call.args[2][0]
    assert payload["move_type"] == "out_invoice"
    assert payload["invoice_line_ids"][0][0] == 0


@pytest.mark.asyncio
async def test_post_invoice_calls_action_post():
    transport = _fake_transport()
    transport.execute_kw.side_effect = [
        True,
        [{"id": 500, "state": "posted"}],
    ]
    toolkit = _make_toolkit(transport)

    result = await toolkit.post_invoice(invoice_id=500)
    assert isinstance(result, AccountMove)
    post_call = transport.execute_kw.call_args_list[0]
    assert post_call.args[:3] == ("account.move", "action_post", [[500]])


@pytest.mark.asyncio
async def test_register_payment_creates_wizard_then_runs():
    transport = _fake_transport()
    transport.execute_kw.side_effect = [
        99,  # wizard id from create
        {"type": "ir.actions.act_window", "res_id": 7},  # action_create_payments
    ]
    toolkit = _make_toolkit(transport)

    result = await toolkit.register_payment(
        invoice_id=500, journal_id=2, amount=42.0
    )

    assert isinstance(result, dict)
    create_call = transport.execute_kw.call_args_list[0]
    assert create_call.args[0] == "account.payment.register"
    assert create_call.args[1] == "create"
    # ctx with active_model/active_ids must be passed via kwargs
    assert create_call.args[3]["context"]["active_model"] == "account.move"
    assert create_call.args[3]["context"]["active_ids"] == [500]


# ── Binary helpers ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_binary_field_writes_base64_payload():
    transport = _fake_transport()
    transport.execute_kw.return_value = True
    toolkit = _make_toolkit(transport)

    # Pass already-base64'd data so no aiohttp call happens
    import base64
    raw = b"hello"
    payload = base64.b64encode(raw).decode("ascii")

    result = await toolkit.set_binary_field(
        model="res.partner", record_id=1, field_name="image_1920", source=payload
    )

    assert isinstance(result, BinaryFieldResult)
    assert result.size_bytes == len(raw)
    write_call = transport.execute_kw.call_args_list[0]
    assert write_call.args[:2] == ("res.partner", "write")
    assert write_call.args[2][0] == [1]  # ids
    assert "image_1920" in write_call.args[2][1]


@pytest.mark.asyncio
async def test_attach_document_creates_ir_attachment():
    transport = _fake_transport()
    transport.execute_kw.return_value = 333
    toolkit = _make_toolkit(transport)

    import base64
    payload = base64.b64encode(b"PDF-bytes").decode("ascii")

    result = await toolkit.attach_document(
        res_model="res.partner",
        res_id=12,
        name="invoice.pdf",
        source=payload,
        mimetype="application/pdf",
    )

    assert isinstance(result, BinaryFieldResult)
    assert result.record_id == 333
    create_call = transport.execute_kw.call_args_list[0]
    assert create_call.args[0] == "ir.attachment"
    assert create_call.args[1] == "create"
    vals = create_call.args[2][0]
    assert vals["res_model"] == "res.partner"
    assert vals["res_id"] == 12
    assert vals["mimetype"] == "application/pdf"


# ── Lazy authentication ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pre_execute_authenticates_only_once():
    transport = _fake_transport(uid=None)  # not yet authenticated

    # authenticate() is what flips uid → 1
    async def fake_auth():
        transport.uid = 1
        return 1
    transport.authenticate = AsyncMock(side_effect=fake_auth)
    transport.execute_kw.return_value = True

    toolkit = _make_toolkit(transport)
    await toolkit.delete_record(model="res.partner", record_id=1)
    await toolkit.delete_record(model="res.partner", record_id=2)

    transport.authenticate.assert_awaited_once()

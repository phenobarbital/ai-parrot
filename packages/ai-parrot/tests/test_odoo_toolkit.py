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
    transport.version = AsyncMock(
        return_value={
            "server_serie": "19.0",
            "server_version": "19.0+e",
            "protocol_version": 1,
        }
    )
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
        "odoo_server_info",
        "odoo_list_models",
        "odoo_fields_get",
        # generic CRUD
        "odoo_search_records",
        "odoo_get_record",
        "odoo_create_record",
        "odoo_create_records",
        "odoo_update_record",
        "odoo_update_records",
        "odoo_delete_record",
        "odoo_delete_records",
        "odoo_import_records",
        # partner helpers
        "odoo_find_partner",
        "odoo_create_partner",
        "odoo_update_partner_contact_info",
        # sales helpers
        "odoo_create_quotation",
        "odoo_confirm_sale_order",
        # invoicing helpers
        "odoo_create_invoice",
        "odoo_post_invoice",
        "odoo_register_payment",
        # binary helpers
        "odoo_set_binary_field",
        "odoo_attach_document",
    }
    missing = expected - tool_names
    assert not missing, f"missing tools: {missing}"


def test_each_tool_has_args_schema():
    toolkit = _make_toolkit()
    for tool in toolkit.get_tools():
        # tools without parameters (server_info, list_models) get an
        # empty auto-generated schema, which is still not None.
        assert tool.args_schema is not None, f"{tool.name} missing args_schema"


def test_write_tools_have_permissions():
    toolkit = _make_toolkit()
    tools = {tool.name: tool for tool in toolkit.get_tools()}

    assert tools["odoo_create_record"]._required_permissions == frozenset({"odoo.write"})
    assert tools["odoo_update_record"]._required_permissions == frozenset({"odoo.write"})
    assert tools["odoo_import_records"]._required_permissions == frozenset({"odoo.write"})
    assert tools["odoo_post_invoice"]._required_permissions == frozenset({"odoo.write"})
    assert tools["odoo_register_payment"]._required_permissions == frozenset({"odoo.write"})
    assert tools["odoo_delete_record"]._required_permissions == frozenset({"odoo.delete"})


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

    # Pass explicit fields to bypass smart-field selection (which would call fields_get first)
    result = await toolkit.get_record(model="res.partner", record_id=7, fields=["id", "name"])

    assert isinstance(result, RecordResult)
    assert result.record == {"id": 7, "name": "Acme"}
    assert result.model == "res.partner"
    assert result.metadata is not None
    assert result.metadata.fields_returned == 2
    assert result.metadata.field_selection_method == "requested"
    transport.execute_kw.assert_awaited_once_with(
        "res.partner", "read", [[7]], {"fields": ["id", "name"]}
    )


@pytest.mark.asyncio
async def test_create_record_then_reads_back():
    transport = _fake_transport()
    transport.execute_kw.side_effect = [42, [{"id": 42, "name": "New"}]]
    toolkit = _make_toolkit(transport)

    result = await toolkit.create_record(model="res.partner", values={"name": "New"})

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

    result = await toolkit.update_record(model="res.partner", record_id=5, values={"name": "X"})

    assert isinstance(result, UpdateResult)
    assert result.success is True
    write_call = transport.execute_kw.call_args_list[0]
    assert write_call.args[:3] == ("res.partner", "write", [[5], {"name": "X"}])


@pytest.mark.asyncio
async def test_update_records_bulk():
    transport = _fake_transport()
    transport.execute_kw.return_value = True
    toolkit = _make_toolkit(transport)

    result = await toolkit.update_records(model="res.partner", record_ids=[1, 2, 3], values={"active": False})

    assert isinstance(result, BulkUpdateResult)
    assert result.count == 3
    transport.execute_kw.assert_awaited_once_with("res.partner", "write", [[1, 2, 3], {"active": False}], None)


@pytest.mark.asyncio
async def test_delete_record():
    transport = _fake_transport()
    transport.execute_kw.return_value = True
    toolkit = _make_toolkit(transport)

    result = await toolkit.delete_record(model="res.partner", record_id=99)

    assert isinstance(result, DeleteResult)
    assert result.success is True
    assert result.deleted_id == 99
    transport.execute_kw.assert_awaited_once_with("res.partner", "unlink", [[99]], None)


@pytest.mark.asyncio
async def test_delete_records_bulk():
    transport = _fake_transport()
    transport.execute_kw.return_value = True
    toolkit = _make_toolkit(transport)

    result = await toolkit.delete_records(model="res.partner", record_ids=[3, 4, 5])

    assert isinstance(result, BulkDeleteResult)
    assert result.count == 3
    transport.execute_kw.assert_awaited_once_with("res.partner", "unlink", [[3, 4, 5]], None)


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
        "res.partner",
        "load",
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

    fields = await toolkit.fields_get(model="res.partner", attributes=["string", "type"])

    assert "name" in fields
    transport.execute_kw.assert_awaited_once_with("res.partner", "fields_get", [], {"attributes": ["string", "type"]})


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

    result = await toolkit.register_payment(invoice_id=500, journal_id=2, amount=42.0)

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

    result = await toolkit.set_binary_field(model="res.partner", record_id=1, field_name="image_1920", source=payload)

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


# ── Phase 1: Smart Field Selection ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_records_auto_fields_when_fields_omitted():
    """When fields=None, search_records calls fields_get and uses smart selection."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    fields_meta = {
        "name": {"type": "char", "string": "Name"},
        "state": {"type": "selection", "string": "Status"},
        "image_1920": {"type": "binary", "string": "Image"},
    }
    # fields_get, search_read, search_count
    transport.execute_kw.side_effect = [
        fields_meta,
        [{"id": 1, "name": "Test", "state": "draft"}],
        1,
    ]
    result = await toolkit.search_records(model="res.partner")

    assert isinstance(result, SearchResult)
    assert result.metadata is not None
    assert result.metadata.field_selection_method == "auto"
    assert result.metadata.total_fields_available == 3
    # Binary fields must not appear in auto-selected fields
    assert "image_1920" not in (result.fields or [])


@pytest.mark.asyncio
async def test_search_records_explicit_fields_bypasses_smart_selection():
    """When explicit fields are given, fields_get is NOT called."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    transport.execute_kw.side_effect = [
        [{"id": 1, "name": "Test"}],
        1,
    ]
    result = await toolkit.search_records(model="res.partner", fields=["name"])

    assert result.fields == ["name"]
    assert result.metadata is not None
    assert result.metadata.field_selection_method == "requested"
    # Only 2 calls: search_read + search_count (no fields_get)
    assert transport.execute_kw.await_count == 2


@pytest.mark.asyncio
async def test_get_record_auto_fields_when_fields_omitted():
    """When fields=None, get_record uses smart selection."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    fields_meta = {
        "name": {"type": "char", "string": "Name"},
        "notes": {"type": "html", "string": "Notes"},
    }
    # fields_get, read
    transport.execute_kw.side_effect = [
        fields_meta,
        [{"id": 1, "name": "Alice"}],
    ]
    result = await toolkit.get_record(model="res.partner", record_id=1)

    assert isinstance(result, RecordResult)
    assert result.metadata is not None
    assert result.metadata.field_selection_method == "auto"
    assert result.metadata.total_fields_available == 2


@pytest.mark.asyncio
async def test_fields_cache_prevents_redundant_fields_get():
    """A second call to search_records for the same model must NOT call fields_get again."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    fields_meta = {"name": {"type": "char", "string": "Name"}}
    transport.execute_kw.side_effect = [
        fields_meta,                        # fields_get (first call)
        [{"id": 1, "name": "A"}], 1,       # search_read + search_count (first call)
        [{"id": 2, "name": "B"}], 2,       # search_read + search_count (second call)
    ]
    await toolkit.search_records(model="res.partner")
    await toolkit.search_records(model="res.partner")

    # fields_get should have been called only once (5 total calls, not 6)
    assert transport.execute_kw.await_count == 5


# ── Phase 1: Aggregate Records ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aggregate_records_calls_read_group_for_odoo_16_18():
    """For Odoo versions < 19, uses read_group."""
    transport = _fake_transport()
    # version() returns 17.0
    transport.version.return_value = {"server_serie": "17.0", "server_version": "17.0"}
    toolkit = _make_toolkit(transport)

    groups_data = [{"state": "sale", "amount_total": 1000.0, "__count": 5}]
    # server_info() calls transport.version() directly — not execute_kw
    transport.execute_kw.side_effect = [
        groups_data,  # read_group (first and only execute_kw call)
    ]
    result = await toolkit.aggregate_records(
        model="sale.order",
        group_by=["state"],
        measures=["amount_total:sum"],
    )

    from parrot_tools.odoo.models.envelopes import AggregateResult
    assert isinstance(result, AggregateResult)
    assert result.model == "sale.order"
    assert result.group_by == ["state"]
    assert result.count == 1


@pytest.mark.asyncio
async def test_aggregate_records_calls_formatted_read_group_for_odoo_19():
    """For Odoo 19+, uses formatted_read_group."""
    transport = _fake_transport()
    transport.version.return_value = {"server_serie": "19.0", "server_version": "19.0"}
    toolkit = _make_toolkit(transport)

    groups_data = [{"state": "sale", "amount_total": 2000.0}]
    # server_info() calls transport.version() directly — not execute_kw
    transport.execute_kw.side_effect = [
        groups_data,  # formatted_read_group (first and only execute_kw call)
    ]
    result = await toolkit.aggregate_records(
        model="sale.order",
        group_by=["state"],
    )

    assert result.count == 1
    # Verify formatted_read_group was called (second call)
    calls = transport.execute_kw.call_args_list
    assert any("formatted_read_group" in str(c) for c in calls)


@pytest.mark.asyncio
async def test_aggregate_records_rejects_invalid_aggregator():
    """Unknown aggregator names raise ValueError."""
    transport = _fake_transport()
    transport.version.return_value = {"server_serie": "17.0", "server_version": "17.0"}
    toolkit = _make_toolkit(transport)

    # ValueError is raised before any execute_kw call (during measure validation)
    with pytest.raises(ValueError, match="aggregator"):
        await toolkit.aggregate_records(
            model="sale.order",
            group_by=["state"],
            measures=["amount_total:evil"],
        )


# ── Phase 1: Domain Builder ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_domain_and_operator():
    """AND conditions produce correct & prefix."""
    toolkit = _make_toolkit()
    result = await toolkit.build_domain(
        conditions=[
            {"field": "name", "operator": "ilike", "value": "test"},
            {"field": "active", "operator": "=", "value": True},
        ],
        logical_operator="and",
    )
    from parrot_tools.odoo.models.envelopes import DomainBuildResult
    assert isinstance(result, DomainBuildResult)
    assert result.valid is True
    assert "&" in result.domain
    assert ("name", "ilike", "test") in result.domain


@pytest.mark.asyncio
async def test_build_domain_or_operator():
    """OR conditions produce correct | prefix."""
    toolkit = _make_toolkit()
    result = await toolkit.build_domain(
        conditions=[
            {"field": "email", "operator": "ilike", "value": "@acme"},
            {"field": "phone", "operator": "!=", "value": False},
        ],
        logical_operator="or",
    )
    assert result.valid is True
    assert "|" in result.domain


@pytest.mark.asyncio
async def test_build_domain_invalid_operator():
    """Unsafe operators produce valid=False with a warning."""
    toolkit = _make_toolkit()
    result = await toolkit.build_domain(
        conditions=[{"field": "name", "operator": "EVIL; DROP TABLE", "value": "x"}]
    )
    assert result.valid is False
    assert len(result.warnings) > 0


@pytest.mark.asyncio
async def test_build_domain_empty_conditions():
    """Empty conditions list returns empty domain."""
    toolkit = _make_toolkit()
    result = await toolkit.build_domain(conditions=[])
    assert result.domain == []
    assert result.valid is True


@pytest.mark.asyncio
async def test_build_domain_single_condition_no_prefix():
    """Single condition needs no prefix operator."""
    toolkit = _make_toolkit()
    result = await toolkit.build_domain(
        conditions=[{"field": "name", "operator": "=", "value": "Alice"}]
    )
    assert result.valid is True
    assert len(result.domain) == 1  # just one triplet, no prefix


# ── Phase 1: get_odoo_profile ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_odoo_profile_returns_typed_envelope():
    """get_odoo_profile assembles server version, user context, and modules."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    transport.execute_kw.side_effect = [
        {"lang": "en_US"},          # context_get
        [{"name": "sale", "shortdesc": "Sales", "installed_version": "17.0.1.0"}],  # module list
    ]
    result = await toolkit.get_odoo_profile()

    from parrot_tools.odoo.models.envelopes import OdooProfileResult
    assert isinstance(result, OdooProfileResult)
    assert result.server_version != "" or result.server_serie != ""
    assert result.transport in ("jsonrpc", "json2", "xmlrpc", "auto", "unknown")


@pytest.mark.asyncio
async def test_get_odoo_profile_skips_modules_when_disabled():
    """include_modules=False must not call ir.module.module."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    transport.execute_kw.side_effect = [{"lang": "en_US"}]  # only context_get
    result = await toolkit.get_odoo_profile(include_modules=False)

    assert result.installed_modules == []
    assert transport.execute_kw.await_count == 1


# ── Phase 1: schema_catalog ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schema_catalog_returns_typed_envelope():
    """schema_catalog returns a SchemaCatalogResult with model list."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    transport.execute_kw.return_value = [
        {"model": "sale.order", "name": "Sales Order", "info": ""},
        {"model": "sale.order.line", "name": "Sales Order Line", "info": ""},
    ]
    result = await toolkit.schema_catalog()

    from parrot_tools.odoo.models.envelopes import SchemaCatalogResult
    assert isinstance(result, SchemaCatalogResult)
    assert result.total == 2


@pytest.mark.asyncio
async def test_schema_catalog_with_query():
    """schema_catalog passes query filter to ir.model domain."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    transport.execute_kw.return_value = [{"model": "sale.order", "name": "Sales Order", "info": ""}]
    result = await toolkit.schema_catalog(query="sale")

    assert result.total == 1
    # Verify the domain contained an ilike filter
    call_kwargs = transport.execute_kw.call_args
    domain_arg = call_kwargs[0][2][0] if call_kwargs[0][2] else []
    domain_str = str(domain_arg)
    assert "sale" in domain_str or "ilike" in domain_str


# ── Phase 1: inspect_model_relationships ─────────────────────────────────────


@pytest.mark.asyncio
async def test_inspect_model_relationships_groups_fields_by_type():
    """inspect_model_relationships correctly partitions relational fields."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    transport.execute_kw.return_value = {
        "partner_id": {"type": "many2one", "string": "Partner", "relation": "res.partner"},
        "line_ids": {"type": "one2many", "string": "Lines", "relation": "sale.order.line"},
        "tag_ids": {"type": "many2many", "string": "Tags", "relation": "account.tag"},
        "name": {"type": "char", "string": "Name", "required": True},
    }
    result = await toolkit.inspect_model_relationships(model="sale.order")

    from parrot_tools.odoo.models.envelopes import ModelRelationshipsResult
    assert isinstance(result, ModelRelationshipsResult)
    assert any(f["name"] == "partner_id" for f in result.many2one)
    assert any(f["name"] == "line_ids" for f in result.one2many)
    assert any(f["name"] == "tag_ids" for f in result.many2many)
    assert any(f["name"] == "name" for f in result.required_fields)
    assert len(result.create_hints) > 0


# ── Phase 1: diagnose_access ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_diagnose_access_when_allowed():
    """diagnose_access reports acl_allowed=True when check_access_rights returns True."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    # check_access_rights → True, ir.model.access → [], ir.rule → [], groups → [{groups_id:[1]}], res.groups → [{full_name:"..."}]
    transport.execute_kw.side_effect = [
        True,   # check_access_rights
        [],     # ir.model.access
        [],     # ir.rule
        [{"groups_id": [1]}],           # res.users.read
        [{"full_name": "Technical"}],   # res.groups.read
    ]
    result = await toolkit.diagnose_access(model="res.partner", operation="read")

    from parrot_tools.odoo.models.envelopes import AccessDiagnosisResult
    assert isinstance(result, AccessDiagnosisResult)
    assert result.acl_allowed is True
    assert "permission" in result.diagnosis.lower() or "acl" in result.diagnosis.lower()


@pytest.mark.asyncio
async def test_diagnose_access_when_denied():
    """diagnose_access reports acl_allowed=False when check_access_rights returns False."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    transport.execute_kw.side_effect = [
        False,  # check_access_rights
        [],     # ir.model.access
        [],     # ir.rule
        [{"groups_id": []}],  # res.users.read
    ]
    result = await toolkit.diagnose_access(model="res.partner", operation="write")

    assert result.acl_allowed is False
    assert "not" in result.diagnosis.lower()


# ── Phase 1: health_check ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_check_no_network_call():
    """health_check makes no Odoo network call."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    result = await toolkit.health_check()

    from parrot_tools.odoo.models.envelopes import HealthCheckResult
    assert isinstance(result, HealthCheckResult)
    # health_check should not have called execute_kw
    transport.execute_kw.assert_not_awaited()
    assert result.connected is True  # transport uid=1 (from _fake_transport)
    assert result.tool_count > 0


# ── Phase 1: search_employee & search_holidays ────────────────────────────────


@pytest.mark.asyncio
async def test_search_employee_returns_typed_entities():
    """search_employee returns a list of HrEmployee instances."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    transport.execute_kw.return_value = [
        {
            "id": 1, "display_name": "Alice", "name": "Alice",
            "job_id": [1, "Engineer"], "department_id": [2, "R&D"],
            "work_email": "alice@example.com", "work_phone": "555-1234",
            "company_id": [1, "My Company"], "active": True,
        }
    ]
    result = await toolkit.search_employee(name="Alice")

    from parrot_tools.odoo.models.entities import HrEmployee
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], HrEmployee)
    assert result[0].name == "Alice"


@pytest.mark.asyncio
async def test_search_holidays_date_range():
    """search_holidays queries hr.leave with a date domain."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    transport.execute_kw.return_value = [
        {
            "id": 10, "display_name": "Leave #10", "name": "Annual Leave",
            "employee_id": [1, "Alice"], "date_from": "2026-06-01",
            "date_to": "2026-06-05", "number_of_days": 5.0,
            "state": "validate",
        }
    ]
    result = await toolkit.search_holidays(start_date="2026-06-01", end_date="2026-06-30")

    from parrot_tools.odoo.models.entities import HrLeave
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], HrLeave)
    assert result[0].state == "validate"


@pytest.mark.asyncio
async def test_search_holidays_with_employee_filter():
    """search_holidays adds employee_id to domain when provided."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    transport.execute_kw.return_value = []
    await toolkit.search_holidays(
        start_date="2026-06-01", end_date="2026-06-30", employee_id=5
    )

    call_args = transport.execute_kw.call_args
    domain_arg = call_args[0][2][0]  # positional args[2][0] = domain
    assert any(
        len(item) == 3 and item[0] == "employee_id" and item[2] == 5
        for item in domain_arg
        if isinstance(item, (list, tuple))
    )

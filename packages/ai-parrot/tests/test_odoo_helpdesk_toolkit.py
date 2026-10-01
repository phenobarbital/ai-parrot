"""Unit tests for OdooHelpdeskToolkit with an AsyncMock transport."""
from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

if "parrot.utils.types" not in sys.modules:
    _utils_types_stub = types.ModuleType("parrot.utils.types")
    _utils_types_stub.SafeDict = dict
    _utils_types_stub.cPrint = lambda *args, **kwargs: None
    sys.modules["parrot.utils.types"] = _utils_types_stub

if "parrot.utils" not in sys.modules:
    _utils_stub = types.ModuleType("parrot.utils")
    _utils_stub.SafeDict = dict
    _utils_stub.cPrint = lambda *args, **kwargs: None
    sys.modules["parrot.utils"] = _utils_stub

from parrot.interfaces.odoointerface import OdooConfig  # noqa: E402
from parrot_tools.odoo import OdooHelpdeskToolkit, OdooToolkit  # noqa: E402
from parrot_tools.odoo.models.helpdesk_envelopes import TicketListResult, TicketResult  # noqa: E402

ROLES_ROW = [{"id": 1, "new_stage_id": [4, "New"], "reopen_stage_id": [22, "Open"], "done_stage_id": False, "cancel_stage_id": False, "close_stage_id": [21, "Closed"], "sh_staff_replied_stage_id": [22, "Open"], "sh_customer_replied_stage_id": False}]
STAGES_ROWS = [{"id": 4, "name": "New", "sequence": 0, "sh_next_stage": [22, "Open"], "is_done_button_visible": False, "is_cancel_button_visible": False}, {"id": 22, "name": "Open", "sequence": 1, "sh_next_stage": [21, "Closed"], "is_done_button_visible": False, "is_cancel_button_visible": False}, {"id": 21, "name": "Closed", "sequence": 4, "sh_next_stage": False, "is_done_button_visible": False, "is_cancel_button_visible": False}]


def _fake_transport(uid: int = 2241) -> MagicMock:
    """Build a deterministic fake Odoo transport."""
    transport = MagicMock()
    transport.config = OdooConfig(url="https://odoo.example.com", database="testdb", username="admin", password="secret", timeout=10, verify_ssl=False)
    transport.uid = uid
    transport.name = "json2"
    transport.authenticate = AsyncMock(return_value=uid)
    transport.execute_kw = AsyncMock(return_value=None)
    transport.version = AsyncMock(return_value={"server_serie": "19.0", "server_version": "19.0+e", "protocol_version": 1})
    transport.close = AsyncMock(return_value=None)
    return transport


def _make_helpdesk_toolkit(transport: MagicMock | None = None) -> OdooHelpdeskToolkit:
    """Build a toolkit with dedicated helpdesk configuration."""
    return OdooHelpdeskToolkit(url="https://odoo.example.com", database="", username="hd", password="key", timeout=30, transport=transport or _fake_transport())


def test_init_uses_helpdesk_keys_not_generic_odoo_keys(monkeypatch):
    """Helpdesk credentials never fall through to generic Odoo keys."""
    import parrot_tools.odoo.helpdesk as hd
    import parrot_tools.odoo.toolkit as base

    monkeypatch.setattr(hd, "ODOO_HELPDESK_URL", "https://hd.example.com")
    monkeypatch.setattr(hd, "ODOO_HELPDESK_USER", "hd-user")
    monkeypatch.setattr(hd, "ODOO_HELPDESK_APIKEY", "hd-key")
    monkeypatch.setattr(hd, "ODOO_HELPDESK_DATABASE", "")
    monkeypatch.setattr(base, "ODOO_URL", "https://generic.example.com")
    monkeypatch.setattr(base, "ODOO_DATABASE", "prod")
    toolkit = OdooHelpdeskToolkit()
    assert (toolkit.config.url, toolkit.config.username, toolkit.config.password, toolkit.config.database) == ("https://hd.example.com", "hd-user", "hd-key", "")


def test_init_keeps_empty_database_when_generic_database_is_set(monkeypatch):
    """An explicit empty database is retained after base construction."""
    import parrot_tools.odoo.toolkit as base

    monkeypatch.setattr(base, "ODOO_DATABASE", "prod")
    assert OdooHelpdeskToolkit(url="url", database="", username="user", password="key").config.database == ""


def test_init_prefers_apikey_over_password(monkeypatch):
    """The dedicated API key takes precedence over the dedicated password."""
    import parrot_tools.odoo.helpdesk as hd

    monkeypatch.setattr(hd, "ODOO_HELPDESK_APIKEY", "api-key")
    monkeypatch.setattr(hd, "ODOO_HELPDESK_PASSWORD", "password")
    assert OdooHelpdeskToolkit().config.password == "api-key"


def test_init_explicit_args_win(monkeypatch):
    """Explicit arguments override all dedicated configuration values."""
    import parrot_tools.odoo.helpdesk as hd

    monkeypatch.setattr(hd, "ODOO_HELPDESK_URL", "configured")
    toolkit = OdooHelpdeskToolkit(url="explicit", database="db", username="user", password="key")
    assert (toolkit.config.url, toolkit.config.database, toolkit.config.username, toolkit.config.password) == ("explicit", "db", "user", "key")


def test_confirming_tools_is_union_with_base():
    """Helpdesk confirmation rules retain inherited shell confirmations."""
    assert OdooToolkit.confirming_tools <= OdooHelpdeskToolkit.confirming_tools
    assert {"cancel_ticket", "merge_tickets", "mass_update_tickets"} <= OdooHelpdeskToolkit.confirming_tools


def test_get_tools_registers_helpdesk_and_inherited_tools():
    """The inherited prefix registers both generic and helpdesk tools."""
    toolkit = _make_helpdesk_toolkit()
    names = {tool.name for tool in toolkit.get_tools()}
    assert toolkit.tool_prefix == "odoo"
    assert {"odoo_get_ticket", "odoo_search_records"} <= names


@pytest.mark.asyncio
async def test_list_models_includes_helpdesk_models():
    """The override checks ACLs for helpdesk models as well as core models."""
    transport = _fake_transport()
    transport.execute_kw.return_value = True
    result = await _make_helpdesk_toolkit(transport).list_models()
    assert "sh.helpdesk.ticket" in {model.model for model in result.models}


@pytest.mark.asyncio
async def test_resolve_ref_exact_ilike_ambiguous_missing():
    """Resolvers use exact then ilike and reject ambiguity or absence."""
    transport = _fake_transport()
    toolkit = _make_helpdesk_toolkit(transport)
    transport.execute_kw.side_effect = [[{"id": 4, "name": "New"}]]
    assert await toolkit._resolve_ref("stage", "New") == 4
    transport.execute_kw.side_effect = [[], [{"id": 22, "name": "Open"}]]
    assert await toolkit._resolve_ref("stage", "Op") == 22
    transport.execute_kw.side_effect = [[], [{"id": 4, "name": "New"}, {"id": 22, "name": "Open"}]]
    with pytest.raises(ValueError, match="Ambiguous stage"):
        await toolkit._resolve_ref("stage", "n")
    transport.execute_kw.side_effect = [[], []]
    with pytest.raises(ValueError, match="No stage"):
        await toolkit._resolve_ref("stage", "Missing")


@pytest.mark.asyncio
async def test_company_stage_config_is_cached():
    """Company stage roles require two RPCs once and then use the cache."""
    transport = _fake_transport()
    transport.execute_kw.side_effect = [[{"company_id": [1, "Company"]}], ROLES_ROW]
    toolkit = _make_helpdesk_toolkit(transport)
    assert (await toolkit._company_stage_config())["close"] == 21
    assert (await toolkit._company_stage_config())["close"] == 21
    assert transport.execute_kw.await_count == 2


@pytest.mark.asyncio
async def test_only_open_uses_company_close_and_cancel_stages():
    """Configured close stages are preferred over terminal-stage inference."""
    toolkit = _make_helpdesk_toolkit()
    toolkit._stage_roles = {"close": 21, "cancel": 23}
    assert await toolkit._closed_stage_ids() == [21, 23]


@pytest.mark.asyncio
async def test_only_open_falls_back_to_last_stage():
    """An unconfigured company excludes terminal stages from only-open results."""
    toolkit = _make_helpdesk_toolkit()
    toolkit._stage_roles = {"close": None, "cancel": None}
    toolkit._stages_cache = {4: STAGES_ROWS[0], 21: STAGES_ROWS[2]}
    assert await toolkit._closed_stage_ids() == [21]


@pytest.mark.asyncio
async def test_search_tickets_builds_domain_and_uses_list_fields():
    """Search uses compact default fields and appends only-open exclusion."""
    transport = _fake_transport()
    transport.execute_kw.side_effect = [[{"company_id": [1, "Company"]}], ROLES_ROW, [], 0, STAGES_ROWS]
    toolkit = _make_helpdesk_toolkit(transport)
    result = await toolkit.search_tickets(stage=4, only_open=True)
    assert isinstance(result, TicketListResult)
    call = transport.execute_kw.call_args_list[2]
    assert call.args[0:2] == ("sh.helpdesk.ticket", "search_read")
    assert ("stage_id", "=", 4) in call.args[2][0]
    assert ("stage_id", "not in", [21]) in call.args[2][0]
    assert call.args[3]["fields"] == toolkit._TICKET_LIST_FIELDS


@pytest.mark.asyncio
async def test_get_ticket_loads_extra_fields_and_lifecycle():
    """Ticket reads normalize extra fields and the company-derived lifecycle role."""
    transport = _fake_transport()
    ticket = {"id": 9, "name": "HD-9", "stage_id": [4, "New"], "state": "customer_replied"}
    transport.execute_kw.side_effect = [[ticket], [{"field_name": "serial", "name": "Serial", "value": "A1"}], STAGES_ROWS, [{"company_id": [1, "Company"]}], ROLES_ROW]
    result = await _make_helpdesk_toolkit(transport).get_ticket(9)
    assert isinstance(result, TicketResult)
    assert result.ticket.extra_fields == {"serial": "A1"}
    assert result.ticket.lifecycle.role == "new"

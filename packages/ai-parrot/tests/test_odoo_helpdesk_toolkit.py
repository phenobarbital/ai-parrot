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

from parrot.interfaces.odoointerface import OdooConfig, OdooRPCError  # noqa: E402
from parrot_tools.odoo import OdooHelpdeskToolkit, OdooToolkit  # noqa: E402
from parrot_tools.odoo.helpdesk import TICKET_MODEL  # noqa: E402
from parrot_tools.odoo.models.helpdesk_envelopes import TicketListResult, TicketResult  # noqa: E402

ROLES_ROW = [
    {
        "id": 1,
        "new_stage_id": [4, "New"],
        "reopen_stage_id": [22, "Open"],
        "done_stage_id": False,
        "cancel_stage_id": False,
        "close_stage_id": [21, "Closed"],
        "sh_staff_replied_stage_id": [22, "Open"],
        "sh_customer_replied_stage_id": False,
    }
]
STAGES_ROWS = [
    {
        "id": 4,
        "name": "New",
        "sequence": 0,
        "sh_next_stage": [22, "Open"],
        "is_done_button_visible": False,
        "is_cancel_button_visible": False,
    },
    {
        "id": 22,
        "name": "Open",
        "sequence": 1,
        "sh_next_stage": [21, "Closed"],
        "is_done_button_visible": False,
        "is_cancel_button_visible": False,
    },
    {
        "id": 21,
        "name": "Closed",
        "sequence": 4,
        "sh_next_stage": False,
        "is_done_button_visible": False,
        "is_cancel_button_visible": False,
    },
]


def _fake_transport(uid: int = 2241) -> MagicMock:
    """Build a deterministic fake Odoo transport."""
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
    transport.name = "json2"
    transport.authenticate = AsyncMock(return_value=uid)
    transport.execute_kw = AsyncMock(return_value=None)
    transport.version = AsyncMock(
        return_value={"server_serie": "19.0", "server_version": "19.0+e", "protocol_version": 1}
    )
    transport.close = AsyncMock(return_value=None)
    return transport


def _make_helpdesk_toolkit(transport: MagicMock | None = None) -> OdooHelpdeskToolkit:
    """Build a toolkit with dedicated helpdesk configuration."""
    return OdooHelpdeskToolkit(
        url="https://odoo.example.com",
        database="",
        username="hd",
        password="key",
        timeout=30,
        transport=transport or _fake_transport(),
    )


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
    assert (toolkit.config.url, toolkit.config.username, toolkit.config.password, toolkit.config.database) == (
        "https://hd.example.com",
        "hd-user",
        "hd-key",
        "",
    )


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
    assert (toolkit.config.url, toolkit.config.database, toolkit.config.username, toolkit.config.password) == (
        "explicit",
        "db",
        "user",
        "key",
    )


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
    transport.execute_kw.side_effect = [
        [ticket],
        [{"field_name": "serial", "name": "Serial", "value": "A1"}],
        STAGES_ROWS,
        [{"company_id": [1, "Company"]}],
        ROLES_ROW,
    ]
    result = await _make_helpdesk_toolkit(transport).get_ticket(9)
    assert isinstance(result, TicketResult)
    assert result.ticket.extra_fields == {"serial": "A1"}
    assert result.ticket.lifecycle.role == "new"


# ── M6: writes, comments, assignment ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_ticket_resolves_refs_and_calls_create():
    """Ticket creation resolves named references before the create RPC."""
    transport = _fake_transport()
    ticket = {"id": 70, "name": "HD-70", "stage_id": [4, "New"], "state": "customer_replied"}
    transport.execute_kw.side_effect = [
        [{"id": 15, "name": "Black Screen"}],
        [{"id": 3, "name": "High"}],
        70,
        [ticket],
        [],
        STAGES_ROWS,
        [{"company_id": [1, "Company"]}],
        ROLES_ROW,
    ]
    toolkit = _make_helpdesk_toolkit(transport)
    result = await toolkit.create_ticket(subject="x", partner_id=2243, category="Black Screen", priority="High")
    create_call = transport.execute_kw.await_args_list[2]
    assert create_call.args == (
        TICKET_MODEL,
        "create",
        [{"partner_id": 2243, "state": "customer_replied", "email_subject": "x", "category_id": 15, "priority": 3}],
        None,
    )
    assert isinstance(result, TicketResult)


@pytest.mark.asyncio
async def test_create_ticket_creates_partner_when_email_unknown():
    """An unmatched customer email creates the partner with that email as its name."""
    transport = _fake_transport()
    transport.execute_kw.side_effect = [[], 99]
    toolkit = _make_helpdesk_toolkit(transport)
    assert await toolkit._find_or_create_partner(None, "a@b.c", None) == 99
    assert transport.execute_kw.await_args_list[1].args == (
        "res.partner",
        "create",
        [{"name": "a@b.c", "email": "a@b.c"}],
        None,
    )


@pytest.mark.asyncio
async def test_update_ticket_rejects_lifecycle_fields():
    """The descriptive patch surface excludes lifecycle and assignment fields."""
    import inspect

    toolkit = _make_helpdesk_toolkit()
    assert not {"stage", "assignee", "user_id", "stage_id"} & set(inspect.signature(toolkit.update_ticket).parameters)
    with pytest.raises(ValueError, match="nothing to update"):
        await toolkit.update_ticket(ticket_id=1)


@pytest.mark.asyncio
async def test_add_ticket_comment_reports_reopen():
    """A public comment reports the observed Closed-to-Open stage change."""
    transport = _fake_transport()
    toolkit = _make_helpdesk_toolkit(transport)
    transport.execute_kw.side_effect = [
        [{"id": 1, "stage_id": [21, "Closed"]}],
        [2268],
        [{"id": 1, "stage_id": [22, "Open"]}],
    ]
    result = await toolkit.add_ticket_comment(ticket_id=1, body="hi", internal=False)
    assert result.reopened is True and result.message_id == 2268 and result.stage_after == "Open"
    call = transport.execute_kw.await_args_list[1]
    assert call.args[:3] == (TICKET_MODEL, "message_post", [[1]])
    assert call.args[3]["subtype_xmlid"] == "mail.mt_comment"


@pytest.mark.asyncio
async def test_take_assign_reassign_call_tuples():
    """Take, direct assignment, and reassign-wizard RPCs use verified tuples."""
    transport = _fake_transport()
    toolkit = _make_helpdesk_toolkit(transport)
    toolkit._assignment_result = AsyncMock()

    await toolkit.take_ticket(1)
    assert transport.execute_kw.await_args_list[0].args == (TICKET_MODEL, "action_take_ticket", [[1]], None)

    transport.execute_kw.reset_mock()
    await toolkit.assign_ticket(1, 2103, [2241])
    assert transport.execute_kw.await_args_list[0].args == (
        TICKET_MODEL,
        "write",
        [[1], {"user_id": 2103, "sh_user_ids": [[6, 0, [2241]]]}],
        None,
    )

    transport.execute_kw.reset_mock()
    transport.execute_kw.side_effect = [3, True]
    await toolkit.reassign_ticket(1, 2103)
    assert transport.execute_kw.await_args_list[0].args == (
        "sh.helpdesk.reassign.wizard",
        "create",
        [{"ticket_id": 1, "new_user_id": 2103}],
        None,
    )
    assert transport.execute_kw.await_args_list[1].args == (
        "sh.helpdesk.reassign.wizard",
        "action_confirm",
        [[3]],
        None,
    )


# -- M7: transitions ---------------------------------------------------------


def _stage_reads(before, after, close_before=False, close_after=False):
    return [
        [{"id": 1, "stage_id": before, "close_date": close_before}],
        [{"id": 1, "stage_id": after, "close_date": close_after}],
    ]


def _transition_toolkit(side_effect, roles=None):
    from parrot_tools.odoo.models.helpdesk_entities import HelpdeskTicket

    transport = _fake_transport()
    toolkit = _make_helpdesk_toolkit(transport)
    toolkit._load_ticket = AsyncMock(return_value=HelpdeskTicket(id=1))
    toolkit._stage_roles = roles or {"reopen": 22, "close": 21, "done": None, "cancel": None}
    toolkit._stages_cache = {}
    transport.execute_kw.side_effect = side_effect
    return transport, toolkit


def _calls(transport):
    return [c.args for c in transport.execute_kw.await_args_list]


@pytest.mark.asyncio
async def test_close_ticket_applied_via_action():
    reads = _stage_reads([22, "Open"], [21, "Closed"], False, "2026-09-30 22:37:43")
    transport, tk = _transition_toolkit([reads[0], None, reads[1]])
    result = await tk.close_ticket(1)
    assert result.applied and result.method_used == "action"
    assert (TICKET_MODEL, "action_closed", [[1]], None) in _calls(transport)


@pytest.mark.asyncio
async def test_resolve_ticket_noop_reports_not_applied():
    reads = _stage_reads([22, "Open"], [22, "Open"])
    transport, tk = _transition_toolkit([reads[0], None, reads[1]])
    result = await tk.resolve_ticket(1)
    assert result.applied is False and result.method_used == "none"
    assert any("no change" in w for w in result.warnings)
    assert not any(c[1] == "write" for c in _calls(transport))


@pytest.mark.asyncio
async def test_reopen_ticket_falls_back_to_stage_write():
    closed, open_ = [21, "Closed"], [22, "Open"]
    transport, tk = _transition_toolkit(
        [
            [{"id": 1, "stage_id": closed, "close_date": "x"}],
            None,
            [{"id": 1, "stage_id": closed, "close_date": "x"}],
            True,
            [{"id": 1, "stage_id": open_, "close_date": "x"}],
        ]
    )
    result = await tk.reopen_ticket(1)
    writes = [c for c in _calls(transport) if c[1] == "write"]
    assert writes == [(TICKET_MODEL, "write", [[1], {"stage_id": 22}], None)]
    assert result.method_used == "stage_write" and result.applied is True


@pytest.mark.asyncio
async def test_move_ticket_to_stage_expected_stage_mismatch_raises_before_rpc():
    transport, tk = _transition_toolkit([[{"id": 1, "stage_id": [4, "New"], "close_date": False}]])
    with pytest.raises(ValueError, match="expected"):
        await tk.move_ticket_to_stage(ticket_id=1, stage=21, expected_current_stage=22)
    assert not any(c[1] == "write" for c in _calls(transport))


@pytest.mark.asyncio
async def test_cancel_ticket_writes_reason_then_action():
    reads = _stage_reads([22, "Open"], [22, "Open"])
    transport, tk = _transition_toolkit([reads[0], True, None, reads[1]])
    result = await tk.cancel_ticket(1, "dup")
    calls = _calls(transport)
    assert calls[1] == (TICKET_MODEL, "write", [[1], {"cancel_reason": "dup"}], None)
    assert calls[2] == (TICKET_MODEL, "action_cancel", [[1]], None)
    assert [c for c in calls if c[1] == "write"] == [calls[1]]
    assert result.applied is False


# ── M8: SLA ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_sla_policy_values():
    """SLA creation resolves references and sends Softhealer wire field names."""
    transport = _fake_transport()
    toolkit = _make_helpdesk_toolkit(transport)
    transport.execute_kw.side_effect = [
        [{"id": 1, "name": "Compliance"}],
        [{"id": 21, "name": "Closed"}],
        7,
        [{"id": 7, "name": "Close in 1h", "sh_team_id": [1, "Compliance"], "sh_hours": 1}],
    ]
    result = await toolkit.create_sla_policy(name="Close in 1h", team="Compliance", hours=1, stage="Closed")
    create_call = transport.execute_kw.await_args_list[2]
    assert create_call.args[:2] == ("sh.helpdesk.sla", "create")
    assert create_call.args[2][0] == {
        "name": "Close in 1h",
        "sh_team_id": 1,
        "sh_days": 0,
        "sh_hours": 1,
        "sh_minutes": 0,
        "sh_sla_target_type": "reaching_stage",
        "sh_stage_id": 21,
    }
    assert result.policy.id == 7 and result.url.endswith("&model=sh.helpdesk.sla&view_type=form")


@pytest.mark.asyncio
async def test_get_ticket_sla_status_envelope():
    """Ticket SLA status combines the ticket summary with its policy status rows."""
    transport = _fake_transport()
    toolkit = _make_helpdesk_toolkit(transport)
    transport.execute_kw.side_effect = [
        [{"id": 1, "sh_status": "sla_failed", "sh_sla_deadline": "2026-10-01 10:00:00", "sh_sla_policy_ids": [7]}],
        [
            {"id": 11, "sh_ticket_id": [1, "HD-1"], "sh_sla_id": [7, "Close in 1h"], "sh_status": "sla_passed"},
            {"id": 12, "sh_ticket_id": [1, "HD-1"], "sh_sla_id": [8, "Reply in 1h"], "sh_status": "sla_failed"},
        ],
    ]
    result = await toolkit.get_ticket_sla_status(1)
    assert result.overall_status == "sla_failed"
    assert result.deadline == "2026-10-01 10:00:00"
    assert len(result.statuses) == 2
    status_call = transport.execute_kw.await_args_list[1]
    assert status_call.args[:3] == ("sh.helpdesk.sla.status", "search_read", [[("sh_ticket_id", "=", 1)]])


@pytest.mark.asyncio
async def test_update_sla_policy_patch():
    """SLA updates write only supplied wire fields and reject an empty patch."""
    transport = _fake_transport()
    toolkit = _make_helpdesk_toolkit(transport)
    transport.execute_kw.side_effect = [True, [{"id": 7, "name": "Close in 2h", "sh_hours": 2}]]
    result = await toolkit.update_sla_policy(7, name="Close in 2h", hours=2)
    assert transport.execute_kw.await_args_list[0].args == (
        "sh.helpdesk.sla",
        "write",
        [[7], {"name": "Close in 2h", "sh_hours": 2}],
        None,
    )
    assert result.policy.name == "Close in 2h"
    with pytest.raises(ValueError, match="nothing to update"):
        await toolkit.update_sla_policy(7)


@pytest.mark.asyncio
async def test_list_ticket_alarms_envelope():
    """Ticket alarm rows are returned in the typed list envelope."""
    transport = _fake_transport()
    transport.execute_kw.return_value = [
        {"id": 4, "name": "Reminder", "type": "email", "sh_remind_before": 30, "sh_reminder_unit": "minutes"}
    ]
    result = await _make_helpdesk_toolkit(transport).list_ticket_alarms()
    assert result.total == 1 and result.alarms[0].name == "Reminder"


# ── M9: stats, wizards, timer ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ticket_stats_odoo19_formatted_read_group():
    """Odoo 19 ticket statistics use formatted_read_group and normalize false keys."""
    transport = _fake_transport()
    toolkit = _make_helpdesk_toolkit(transport)
    transport.execute_kw.side_effect = [[{"stage_id": [4, "New"], "__count": 22}, {"stage_id": False, "__count": 1}]]
    result = await toolkit.ticket_stats()
    assert transport.execute_kw.await_args.args == (
        TICKET_MODEL,
        "formatted_read_group",
        [[]],
        {"groupby": ["stage_id"], "aggregates": ["__count"]},
    )
    assert [(group.key, group.count) for group in result.groups] == [(4, 22), (None, 1)]
    assert result.total == 23 and result.source_method == "formatted_read_group"


@pytest.mark.asyncio
async def test_ticket_stats_odoo17_read_group():
    """Odoo 17 ticket statistics use the compatible read_group shape."""
    transport = _fake_transport()
    transport.version.return_value = {"server_serie": "17.0"}
    transport.execute_kw.return_value = [{"stage_id": [4, "New"], "stage_id_count": 3}]
    result = await _make_helpdesk_toolkit(transport).ticket_stats()
    assert transport.execute_kw.await_args.args == (
        TICKET_MODEL,
        "read_group",
        [[]],
        {"groupby": ["stage_id"], "fields": ["id:count"], "lazy": False},
    )
    assert result.source_method == "read_group" and result.total == 3


@pytest.mark.asyncio
async def test_ticket_stats_fallback_search_count():
    """Stage aggregation failures fall back to one search_count per configured stage."""
    transport = _fake_transport()
    toolkit = _make_helpdesk_toolkit(transport)
    transport.execute_kw.side_effect = [
        OdooRPCError("unsupported aggregate"),
        [STAGES_ROWS[0], STAGES_ROWS[2]],
        7,
        2,
    ]
    result = await toolkit.ticket_stats()
    assert result.source_method == "search_count" and [(group.key, group.count) for group in result.groups] == [(4, 7), (21, 2)]
    assert transport.execute_kw.await_args_list[2].args == (TICKET_MODEL, "search_count", [[("stage_id", "=", 4)]], None)


@pytest.mark.asyncio
async def test_merge_tickets_wizard_calls():
    """Merge creates the verified wizard values and checks the target postcondition."""
    transport = _fake_transport()
    toolkit = _make_helpdesk_toolkit(transport)
    transport.execute_kw.side_effect = [
        [{"id": 1, "partner_id": [7, "Ada"]}],
        [1],
        None,
        [{"id": 3, "sh_merge_ticket_count": 2}],
    ]
    result = await toolkit.merge_tickets([2, 3], into_ticket_id=3)
    assert transport.execute_kw.await_args_list[1].args == (
        "sh.helpdesk.ticket.merge.ticket.wizard",
        "create",
        [
            {
                "sh_helpdesk_ticket_ids": [[6, 0, [2, 3]]],
                "sh_select_type": "existing",
                "sh_select_merge_type": "close",
                "sh_merge_history": True,
                "sh_partner_id": 7,
                "sh_existing_ticket": 3,
            }
        ],
        None,
    )
    assert transport.execute_kw.await_args_list[2].args == (
        "sh.helpdesk.ticket.merge.ticket.wizard",
        "action_merge_tickets",
        [[1]],
        None,
    )
    assert result.applied is True and result.result_ticket_id == 3


@pytest.mark.asyncio
async def test_mass_update_tickets_wizard_calls():
    """Mass updates enable only the selected stage control and invoke update_record."""
    transport = _fake_transport()
    toolkit = _make_helpdesk_toolkit(transport)
    transport.execute_kw.side_effect = [[2], None]
    result = await toolkit.mass_update_tickets([1, 3], stage=22)
    assert transport.execute_kw.await_args_list[0].args == (
        "sh.helpdesk.ticket.mass.update.wizard",
        "create",
        [{"helpdesks_ticket_ids": [[6, 0, [1, 3]]], "check_helpdesks_state": True, "helpdesk_stages": 22}],
        None,
    )
    assert transport.execute_kw.await_args_list[1].args == (
        "sh.helpdesk.ticket.mass.update.wizard",
        "update_record",
        [[2]],
        None,
    )
    assert result.applied is True


@pytest.mark.asyncio
async def test_start_ticket_timer_surfaces_config_error_as_warning():
    """Tenant timer configuration errors are structured warnings rather than RPC failures."""
    transport = _fake_transport()
    transport.execute_kw.side_effect = OdooRPCError("Please Set Default Project from configuration!")
    result = await _make_helpdesk_toolkit(transport).start_ticket_timer(1)
    assert result.running is False and "Default Project" in result.warnings[0]

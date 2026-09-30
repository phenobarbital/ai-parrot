"""Tests for the helpdesk Pydantic layer (entities here; inputs/envelopes appended later)."""
from __future__ import annotations

from parrot_tools.odoo.models.helpdesk_entities import HelpdeskLifecycle, HelpdeskSla, HelpdeskStage, HelpdeskTicket


LIVE_TICKET = {
    "id": 70,
    "name": "TICKET#9813547",
    "stage_id": [4, "New"],
    "state": "customer_replied",
    "user_id": False,
    "sh_user_ids": [],
    "open_boolean": False,
    "done_stage_boolean": False,
    "closed_stage_boolean": False,
    "cancel_stage_boolean": False,
    "close_date": False,
    "cancel_reason": False,
    "sh_sla_deadline": False,
    "sh_status": False,
}


def test_helpdesk_ticket_roundtrip_live_shape():
    """Validate the observed ticket shape and its reply-direction alias."""
    ticket = HelpdeskTicket.model_validate(LIVE_TICKET)

    assert ticket.replied_status == "customer_replied"
    assert ticket.stage_id == [4, "New"]
    assert ticket.extra_fields == {}
    assert ticket.lifecycle is None
    assert ticket.model_dump(by_alias=True)["state"] == "customer_replied"


def test_helpdesk_ticket_accepts_replied_status_by_name():
    """Accept the friendly reply-direction name as well as Odoo's ``state`` key."""
    assert HelpdeskTicket(replied_status="staff_replied").replied_status == "staff_replied"


def test_helpdesk_stage_and_sla_optional_fields():
    """Accept optional many2one fields and preserve unknown tenant fields."""
    stage = HelpdeskStage.model_validate(
        {"id": 22, "name": "Open", "sh_next_stage": [23, "Pending close"], "tenant_stage_field": True}
    )
    sla = HelpdeskSla.model_validate({"id": 1, "name": "p", "sh_team_id": [1, "Compliance"], "sh_days": 0})

    assert stage.sh_next_stage == [23, "Pending close"]
    assert stage.tenant_stage_field is True
    assert sla.sh_team_id == [1, "Compliance"]
    assert sla.sh_days == 0

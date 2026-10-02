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


from parrot_tools.odoo.models.helpdesk_inputs import (  # noqa: E402
    CreateSlaPolicyInput,
    CreateTicketInput,
    MassUpdateTicketsInput,
    UpdateTicketInput,
)


def test_create_ticket_input_requires_partner_ref():
    """Require a customer reference when creating a ticket."""
    import pytest

    with pytest.raises(ValueError, match="partner_id, partner_email or partner_name"):
        CreateTicketInput(subject="x")
    assert CreateTicketInput(subject="x", partner_email="a@b.c").partner_email == "a@b.c"


def test_create_sla_policy_input_validators():
    """Validate SLA duration and stage requirements."""
    import pytest

    with pytest.raises(ValueError, match="days, hours or minutes"):
        CreateSlaPolicyInput(name="Policy", team="Compliance")
    with pytest.raises(ValueError, match="stage is required"):
        CreateSlaPolicyInput(name="Policy", team="Compliance", hours=1)
    policy = CreateSlaPolicyInput(name="Policy", team="Compliance", hours=1, stage="Closed")
    assert policy.hours == 1


def test_mass_update_input_requires_change():
    """Require a mass-update operation in addition to ticket ids."""
    import pytest

    with pytest.raises(ValueError, match="at least one change"):
        MassUpdateTicketsInput(ticket_ids=[1])
    assert MassUpdateTicketsInput(ticket_ids=[1], stage="Open").stage == "Open"


def test_update_ticket_input_has_no_lifecycle_fields():
    """Keep lifecycle, assignment, and SLA updates out of the ticket patch schema."""
    forbidden = {"stage", "stage_id", "assignee", "user_id", "sh_user_ids"}
    fields = set(UpdateTicketInput.model_fields)
    assert not fields & forbidden
    assert not any(field.startswith("sh_sla") for field in fields)


import parrot_tools.odoo.models as odoo_models  # noqa: E402


def test_models_init_exports_helpdesk_classes():
    """Expose every required helpdesk model through the Odoo model package."""
    for name in (
        "HelpdeskTicket",
        "HelpdeskLifecycle",
        "TicketResult",
        "TicketTransitionResult",
        "StatsGroup",
        "CreateTicketInput",
        "UpdateTicketInput",
        "SearchTicketsInput",
        "CreateSlaPolicyInput",
        "MergeTicketsInput",
    ):
        assert hasattr(odoo_models, name), name
        assert name in odoo_models.__all__, name

    result = odoo_models.TicketTransitionResult(
        ticket_id=1,
        action="action_closed",
        applied=True,
        method_used="action",
        ticket=odoo_models.HelpdeskTicket(id=1),
    )
    assert result.warnings == []

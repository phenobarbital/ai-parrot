"""Shape tests for parrot_tools.odoo.helpdesk_normalize (pure, no network)."""

from __future__ import annotations

from parrot_tools.odoo.helpdesk_normalize import (
    extra_fields_to_dict,
    lifecycle_from_record,
    normalize_stats_groups,
    normalize_ticket,
)

ROWS = [
    {"field_name": "poke_locationid", "name": "Location Id", "value": "LOC-1"},
    {"field_name": "owner", "name": "Owner", "value": False},
    {"name": "no field name", "value": "x"},
    "garbage",
    {"field_name": "poke_locationid", "name": "Location Id", "value": "LOC-2"},
]


def test_extra_fields_to_dict_shapes() -> None:
    """Fold valid, malformed, and duplicate extra-field rows."""
    values, labels = extra_fields_to_dict(ROWS)
    assert values == {"poke_locationid": "LOC-2", "owner": ""}
    assert labels["poke_locationid"] == "Location Id"
    assert extra_fields_to_dict(None) == ({}, {})
    assert extra_fields_to_dict(False) == ({}, {})  # type: ignore[arg-type]


def test_lifecycle_from_record_flags_and_next_stage() -> None:
    """Derive lifecycle flags, stage transitions, roles, and false-stage defaults."""
    stages = {21: {"sh_next_stage": False}, 4: {"sh_next_stage": [22, "Open"]}}
    roles = {"new": 4, "reopen": 22, "done": None, "cancel": None, "close": 21}
    lifecycle = lifecycle_from_record({"stage_id": [4, "New"], "open_boolean": False}, stages, roles)
    assert (
        lifecycle.stage_id,
        lifecycle.stage_name,
        lifecycle.next_stage_id,
        lifecycle.next_stage_name,
        lifecycle.role,
    ) == (4, "New", 22, "Open", "new")

    closed = lifecycle_from_record(
        {"stage_id": [21, "Closed"], "closed_stage_boolean": True, "open_boolean": True}, stages, roles
    )
    assert (closed.is_closed, closed.can_reopen, closed.role, closed.next_stage_id) == (True, True, "close", None)

    empty = lifecycle_from_record({"stage_id": False})
    assert (empty.stage_id, empty.stage_name, empty.next_stage_id, empty.next_stage_name, empty.role) == (
        None,
        None,
        None,
        None,
        None,
    )
    assert not (empty.is_closed or empty.is_cancelled or empty.is_done or empty.can_reopen)


def test_normalize_ticket_preserves_raw_and_adds_derived() -> None:
    """Retain tenant raw fields while attaching values and lifecycle data."""
    ticket = normalize_ticket(
        {
            "id": 1,
            "state": "staff_replied",
            "stage_id": [21, "Closed"],
            "closed_stage_boolean": True,
            "custom_x": 1,
        },
        ROWS,
    )
    assert ticket.replied_status == "staff_replied"
    assert ticket.extra_fields["poke_locationid"] == "LOC-2"
    assert ticket.lifecycle is not None
    assert ticket.lifecycle.is_closed
    assert ticket.model_dump()["custom_x"] == 1


def test_normalize_stats_groups_both_shapes() -> None:
    """Normalise legacy, formatted, and selection aggregate group rows."""
    legacy = [{"stage_id": [4, "New"], "stage_id_count": 22}, {"stage_id": False, "stage_id_count": 1}]
    modern = [{"stage_id": [4, "New"], "__count": 22}, {"stage_id": False, "__count": 1}]
    for rows, method in ((legacy, "read_group"), (modern, "formatted_read_group")):
        groups = normalize_stats_groups(rows, "stage_id", method)
        assert [(group.key, group.label, group.count) for group in groups] == [(4, "New", 22), (None, "(none)", 1)]

    selection = normalize_stats_groups([{"sh_status": "sla_failed", "sh_status_count": 3}], "sh_status", "read_group")
    assert [(group.key, group.label, group.count) for group in selection] == [("sla_failed", "sla_failed", 3)]

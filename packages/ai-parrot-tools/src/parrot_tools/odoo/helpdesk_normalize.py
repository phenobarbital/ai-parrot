"""Pure normalisation helpers for the Softhealer helpdesk (no I/O, no async).

Turns Odoo wire dicts into the derived parts of :class:`HelpdeskTicket` and normalises the two
aggregation result shapes. Everything here must be safe on malformed tenant data: skip, never raise.
"""

from __future__ import annotations

from typing import Any

from parrot_tools.odoo.models.helpdesk_entities import HelpdeskLifecycle, HelpdeskTicket
from parrot_tools.odoo.models.helpdesk_envelopes import StatsGroup

_ROLE_KEYS = ("new", "reopen", "done", "cancel", "close")


def _m2o_id(value: Any) -> int | None:
    """``[id, name]`` → id; ``False``/``None``/anything else → ``None``."""
    return int(value[0]) if isinstance(value, (list, tuple)) and value and isinstance(value[0], int) else None


def _m2o_name(value: Any) -> str | None:
    """Return the display name from an Odoo many2one value when present."""
    return str(value[1]) if isinstance(value, (list, tuple)) and len(value) > 1 else None


def extra_fields_to_dict(rows: list[dict[str, Any]] | None) -> tuple[dict[str, str], dict[str, str]]:
    """Fold ``sh.helpdesk.ticket.extra_fields`` rows into ``(values, labels)`` keyed by ``field_name``.

    ``False``/``None`` values become ``""``; a duplicate ``field_name`` keeps the last row; rows without a
    ``field_name`` are skipped; a non-list input yields ``({}, {})``.
    """
    values: dict[str, str] = {}
    labels: dict[str, str] = {}
    if not isinstance(rows, list):
        return values, labels
    for row in rows:
        if not isinstance(row, dict):
            continue
        field_name = row.get("field_name")
        if not field_name:
            continue
        field_name = str(field_name)
        value = row.get("value")
        values[field_name] = "" if value is False or value is None else str(value)
        label = row.get("name")
        labels[field_name] = str(label) if label else field_name
    return values, labels


def lifecycle_from_record(
    record: dict[str, Any],
    stages: dict[int, dict[str, Any]] | None = None,
    stage_roles: dict[str, int | None] | None = None,
) -> HelpdeskLifecycle:
    """Derive the lifecycle block from ``stage_id`` + the computed booleans (+ next stage and company role)."""
    stage_id = _m2o_id(record.get("stage_id"))
    nxt = (stages or {}).get(stage_id or -1, {}).get("sh_next_stage") if stage_id is not None else None
    role = next(
        (key for key in _ROLE_KEYS if stage_roles and stage_roles.get(key) == stage_id and stage_id is not None), None
    )
    return HelpdeskLifecycle(
        stage_id=stage_id,
        stage_name=_m2o_name(record.get("stage_id")),
        is_closed=bool(record.get("closed_stage_boolean")),
        is_cancelled=bool(record.get("cancel_stage_boolean")),
        is_done=bool(record.get("done_stage_boolean")),
        can_reopen=bool(record.get("open_boolean")),
        next_stage_id=_m2o_id(nxt),
        next_stage_name=_m2o_name(nxt),
        role=role,
    )


def normalize_ticket(
    record: dict[str, Any],
    extra_rows: list[dict[str, Any]] | None = None,
    stages: dict[int, dict[str, Any]] | None = None,
    stage_roles: dict[str, int | None] | None = None,
) -> HelpdeskTicket:
    """Build a :class:`HelpdeskTicket` preserving every raw field, adding ``extra_fields`` and ``lifecycle``."""
    ticket = HelpdeskTicket.model_validate(dict(record))
    ticket.extra_fields, _labels = extra_fields_to_dict(extra_rows)
    ticket.lifecycle = lifecycle_from_record(record, stages, stage_roles)
    return ticket


def normalize_stats_groups(groups: list[dict[str, Any]], group_by: str, source_method: str) -> list[StatsGroup]:
    """Map ``read_group`` (``<group_by>_count``/``__count``) and ``formatted_read_group`` (``__count``) rows to ``StatsGroup``."""
    out: list[StatsGroup] = []
    for row in groups or []:
        if not isinstance(row, dict):
            continue
        raw_count = row.get("__count") if "__count" in row else row.get(f"{group_by}_count", 0)
        try:
            count = int(raw_count)
        except (TypeError, ValueError):
            continue
        raw = row.get(group_by)
        if raw is False or raw is None:
            key = None
            label = "(none)"
        else:
            key = _m2o_id(raw)
            if key is None:
                key = str(raw)
                label = key
            else:
                label = _m2o_name(raw) or str(key)
        out.append(StatsGroup(key=key, label=label, count=count))
    return out

# TASK-3896: Pure normalisation boundary (`helpdesk_normalize.py`)

**Feature**: FEAT-616 — OdooHelpdeskToolkit — typed helpdesk tools for the Softhealer helpdesk (Odoo 19)
**Spec**: `sdd/specs/odoo-toolkit-upgrades.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3895
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 4** (G7, AC14, AC15, AC21 lifecycle role; design research S8/S11). Four pure
functions (no I/O, no async) turn Odoo wire dicts into the derived parts of `HelpdeskTicket`
(`extra_fields`, `lifecycle`) and normalise the two aggregation shapes (`read_group` vs
`formatted_read_group`) into `StatsGroup` rows. Keeping this pure makes the shape edge cases testable
without the toolkit.

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk_normalize.py` with `extra_fields_to_dict`,
  `lifecycle_from_record`, `normalize_ticket`, `normalize_stats_groups` (signatures fixed by spec §3 M4).
- Create `packages/ai-parrot/tests/test_odoo_helpdesk_normalize.py`.

**NOT in scope**: any RPC, the toolkit, changes to the models.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk_normalize.py` | CREATE | four pure functions |
| `packages/ai-parrot/tests/test_odoo_helpdesk_normalize.py` | CREATE | shape tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from __future__ import annotations
from typing import Any
from parrot_tools.odoo.models.helpdesk_entities import HelpdeskLifecycle, HelpdeskTicket   # created by TASK-3893; re-exported by TASK-3895
from parrot_tools.odoo.models.helpdesk_envelopes import StatsGroup                          # created by TASK-3895
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/odoo/models/helpdesk_entities.py  (TASK-3893)
class HelpdeskLifecycle(BaseModel): stage_id, stage_name, is_closed, is_cancelled, is_done, can_reopen, next_stage_id, next_stage_name, role
class HelpdeskTicket(_OdooEntity): ... extra_fields: dict[str, str]; lifecycle: Optional[HelpdeskLifecycle]; replied_status alias "state"
# packages/ai-parrot-tools/src/parrot_tools/odoo/models/helpdesk_envelopes.py  (TASK-3895)
class StatsGroup(BaseModel): key: Optional[int | str]; label: str; count: int

# Odoo wire facts (spec §6 Live-verified): many2one = [id, name] | False; extra_fields rows = {"field_name", "name" (label), "value"};
#   read_group rows carry "<field>_count" (or "__count" when lazy=False on 17+); formatted_read_group rows carry "__count".
```

### Does NOT Exist
- ~~`HelpdeskTicket.from_odoo()`~~ — normalisation is a function, not a classmethod.
- ~~async normalisers / any `self`~~ — module-level pure functions only.
- ~~`extra_fields` rows with `field_label` / `field_type`~~ — the row keys are `field_name`, `name`, `value` (verified live).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk_normalize.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/test_odoo_helpdesk_normalize.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Never raise on a malformed row — skip it (rows are tenant data).
- `False` from Odoo means "empty" everywhere: `False` many2one → `None`; `False` value → `""`.
- `normalize_ticket` must not drop raw keys: build the entity from the raw dict, then set the two derived fields.

---

## Implementation Blueprint

### Steps (in order)
1. Write `extra_fields_to_dict` and `lifecycle_from_record` — *why*: leaf functions, independently testable.
2. Write `normalize_ticket` on top of them — *why*: single entry point TASK-3897 calls.
3. Write `normalize_stats_groups` — *why*: TASK-3901's `ticket_stats` depends on it (S11).
4. Tests for every shape listed in the checklist.

### `packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk_normalize.py` (CREATE)
```python
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
        # FILL IN: skip non-dict rows and rows whose field_name is missing/False; coerce value with "" for False/None,
        #   str() otherwise; label = row.get("name") or field_name — bounded by the docstring contract (AC14)
        ...
    return values, labels


def lifecycle_from_record(
    record: dict[str, Any],
    stages: dict[int, dict[str, Any]] | None = None,
    stage_roles: dict[str, int | None] | None = None,
) -> HelpdeskLifecycle:
    """Derive the lifecycle block from ``stage_id`` + the computed booleans (+ next stage and company role)."""
    stage_id = _m2o_id(record.get("stage_id"))
    nxt = (stages or {}).get(stage_id or -1, {}).get("sh_next_stage") if stage_id is not None else None
    role = next((k for k in _ROLE_KEYS if stage_roles and stage_roles.get(k) == stage_id and stage_id is not None), None)
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
        # FILL IN: count = row.get("__count") if present else row.get(f"{group_by}_count", 0); raw = row.get(group_by);
        #   many2one → key=id, label=name; selection/char → key=label=str(raw); False/None → key=None, label="(none)" — AC15
        ...
    return out
```
**Why this shape**: spec §3 M4 fixes the four signatures and their docstring contracts; `_m2o_id`/`_m2o_name` centralise the `[id, name] | False` wire rule used by all of them. `lifecycle_from_record` is written in full because its rules are exactly the spec's; only the two loops are left as `FILL IN`.

### `packages/ai-parrot/tests/test_odoo_helpdesk_normalize.py` (CREATE)
```python
"""Shape tests for parrot_tools.odoo.helpdesk_normalize (pure, no network)."""
from __future__ import annotations

from parrot_tools.odoo.helpdesk_normalize import (
    extra_fields_to_dict, lifecycle_from_record, normalize_stats_groups, normalize_ticket,
)

ROWS = [
    {"field_name": "poke_locationid", "name": "Location Id", "value": "LOC-1"},
    {"field_name": "owner", "name": "Owner", "value": False},
    {"name": "no field name", "value": "x"},
    "garbage",
    {"field_name": "poke_locationid", "name": "Location Id", "value": "LOC-2"},
]


def test_extra_fields_to_dict_shapes():
    values, labels = extra_fields_to_dict(ROWS)
    assert values == {"poke_locationid": "LOC-2", "owner": ""}
    assert labels["poke_locationid"] == "Location Id"
    assert extra_fields_to_dict(None) == ({}, {})
    assert extra_fields_to_dict(False) == ({}, {})  # type: ignore[arg-type]


def test_lifecycle_from_record_flags_and_next_stage():
    stages = {21: {"sh_next_stage": False}, 4: {"sh_next_stage": [22, "Open"]}}
    roles = {"new": 4, "reopen": 22, "done": None, "cancel": None, "close": 21}
    lc = lifecycle_from_record({"stage_id": [4, "New"], "open_boolean": False}, stages, roles)
    assert (lc.stage_id, lc.stage_name, lc.next_stage_id, lc.next_stage_name, lc.role) == (4, "New", 22, "Open", "new")
    # FILL IN: Closed ticket → is_closed True, can_reopen True, role "close", next_stage None; stage_id False → all None/False


def test_normalize_ticket_preserves_raw_and_adds_derived():
    # FILL IN: normalize_ticket({"id": 1, "state": "staff_replied", "stage_id": [21, "Closed"], "closed_stage_boolean": True, "custom_x": 1}, ROWS)
    #   → replied_status == "staff_replied", extra_fields["poke_locationid"] == "LOC-2", lifecycle.is_closed, model_dump()["custom_x"] == 1
    ...


def test_normalize_stats_groups_both_shapes():
    legacy = [{"stage_id": [4, "New"], "stage_id_count": 22}, {"stage_id": False, "stage_id_count": 1}]
    modern = [{"stage_id": [4, "New"], "__count": 22}, {"stage_id": False, "__count": 1}]
    for rows, method in ((legacy, "read_group"), (modern, "formatted_read_group")):
        groups = normalize_stats_groups(rows, "stage_id", method)
        assert [(g.key, g.label, g.count) for g in groups] == [(4, "New", 22), (None, "(none)", 1)]
    # FILL IN: selection group_by (e.g. "sh_status": "sla_failed") → key == label == "sla_failed"
```
**Why**: one test per function, each covering the missing / `False` / malformed / duplicate shapes S8 asked for, and both aggregation shapes S11 asked for.

### FILL IN checklist
- [ ] `extra_fields_to_dict` loop body; bounded by docstring contract / AC14
- [ ] `normalize_stats_groups` loop body; bounded by AC15
- [ ] three test `FILL IN`s; bounded by the same ACs

---

## Acceptance Criteria

- [ ] AC14 (spec): `extra_fields` dict derived; raw fields preserved; `lifecycle` derived.
- [ ] AC15 (spec, normaliser part): both aggregation shapes → identical `StatsGroup` rows.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk_normalize.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/test_odoo_helpdesk_normalize.py -q`

---

## Test Specification

See the blueprint: four tests, no fixtures beyond module constants.

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug odoo-toolkit-upgrades --feature-id FEAT-616`.
2. **Read the spec** (§2 rule 5, §3 M4).
3. **Check dependencies** — TASK-3895 `done`.
4. **Verify the Codebase Contract** — `grep -n 'class HelpdeskLifecycle\|class StatsGroup' packages/ai-parrot-tools/src/parrot_tools/odoo/models/helpdesk_*.py`.
5. **Update status** in the per-spec index → `"in-progress"`, commit only that file.
6. **Implement** from the blueprint.
7. **Verify** — Validation Commands.
8. **Commit the code** — only the two new files.
9. **Close the task** — `scripts/sdd/close_task.sh TASK-3896 odoo-toolkit-upgrades verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

**Completed by**: sdd-worker (FEAT-616)
**Date**: 2026-10-01
**Notes**: gpt-5.6-terra (codex): helpdesk_normalize.py + tests; test_odoo_*.py 187 passed. Diff reviewed vs contract; task tests run with `pytest --noconftest` (repo conftest broken by pre-existing venv issue); merge-tier sweep red on unrelated failures, accepted by user.

**Deviations from spec**: none | describe if any

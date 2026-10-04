# TASK-3893: Helpdesk entity models (`models/helpdesk_entities.py`)

**Feature**: FEAT-616 — OdooHelpdeskToolkit — typed helpdesk tools for the Softhealer helpdesk (Odoo 19)
**Spec**: `sdd/specs/odoo-toolkit-upgrades.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements the entity third of spec §3 **Module 3** (G2, G7, AC4, AC14). Entities mirror the Odoo wire
fields of the Softhealer helpdesk models (verified live, spec §6 "Live-verified Odoo facts") and follow
`_OdooEntity` (`extra="allow"`), so unknown tenant fields round-trip. `HelpdeskTicket` additionally carries
two **derived** fields (`extra_fields`, `lifecycle`) that TASK-3896's normaliser fills, and exposes the
misleading Odoo `state` field as `replied_status` (spec §7 "state is reply direction").

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/odoo/models/helpdesk_entities.py` with: `HelpdeskLifecycle`,
  `HelpdeskTicket`, `HelpdeskStage`, `HelpdeskTeam`, `HelpdeskCategory`, `HelpdeskSubcategory`, `HelpdeskPriority`,
  `HelpdeskTicketType`, `HelpdeskTag`, `HelpdeskStageInfo`, `HelpdeskSla`, `HelpdeskSlaStatus`, `HelpdeskTicketAlarm`,
  `HelpdeskMessage` — exactly the field sets of spec §2 Data Models.
- Create `packages/ai-parrot/tests/test_odoo_helpdesk_models.py` with the entity tests (TASK-3894/3895 append theirs).
- No re-export yet (TASK-3895 edits `models/__init__.py`).

**NOT in scope**: inputs (TASK-3894), envelopes (TASK-3895), the normaliser (TASK-3896).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/models/helpdesk_entities.py` | CREATE | 14 entity classes |
| `packages/ai-parrot/tests/test_odoo_helpdesk_models.py` | CREATE | entity tests (other model tasks append) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from __future__ import annotations
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field                        # verified: entities.py:16
from .entities import Many2one, _OdooEntity                              # verified: entities.py:19 (Many2one) / :22 (_OdooEntity)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/odoo/models/entities.py  (verified at b3141f286)
Many2one = Union[tuple[int, str], list[Any], bool, None]                 # line 19
class _OdooEntity(BaseModel):                                            # line 22
    model_config = ConfigDict(extra="allow", populate_by_name=True)      # line 25
    id: Optional[int] = Field(default=None, ...)                         # line 27
    display_name: Optional[str] = Field(default=None, ...)               # line 28
class SaleOrder(_OdooEntity):                                            # line 129 — style reference (Optional fields, Many2one, list[int])
```

### Does NOT Exist
- ~~`parrot_tools.odoo.models.helpdesk`~~ — three sibling modules (`helpdesk_entities`, `helpdesk_inputs`, `helpdesk_envelopes`), not one.
- ~~`HelpdeskTicket.state`~~ as a declared field — declared as `replied_status` with `alias="state"`; the raw key still round-trips via `extra="allow"`.
- ~~`HelpdeskTicket.stage_name` / `.is_closed`~~ top-level — those live inside `lifecycle: HelpdeskLifecycle`.
- ~~`helpdesk.stages.fold` / `.is_close`~~ — not on the instance; do not declare them.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/odoo/models/helpdesk_entities.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/test_odoo_helpdesk_models.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/models/entities.py#_OdooEntity"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Every wire field `Optional[...] = None`; relational many2one fields typed `Optional[Many2one]`; x2many typed `Optional[list[int]]`.
- Keep Odoo's misspelling `timehseet_ids` (spec §7).
- `HelpdeskLifecycle` and `HelpdeskMessage` are plain `BaseModel`s (derived / not an Odoo record).
- Google docstrings; 120 columns.

---

## Implementation Blueprint

### Steps (in order)
1. Write the module with the base pieces (`HelpdeskLifecycle`, `HelpdeskTicket`) — *why*: the ticket is what every tool returns.
2. Add the twelve smaller entities — *why*: one class per Odoo model the toolkit reads (spec §2).
3. Create the test module with the entity tests — *why*: pins the alias and the live wire shape (AC14 precondition).

### `packages/ai-parrot-tools/src/parrot_tools/odoo/models/helpdesk_entities.py` (CREATE)
```python
"""Pydantic entities for the Softhealer helpdesk models (``sh.helpdesk.*`` / ``helpdesk.*``).

All Odoo-backed classes subclass :class:`_OdooEntity` (``extra="allow"``) so tenant-specific
fields round-trip. ``HelpdeskTicket.extra_fields`` and ``.lifecycle`` are DERIVED by
``parrot_tools.odoo.helpdesk_normalize`` — Odoo never sends them.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .entities import Many2one, _OdooEntity


class HelpdeskLifecycle(BaseModel):
    """Lifecycle derived from ``stage_id`` + the Softhealer computed booleans + company stage roles."""

    stage_id: Optional[int] = None
    stage_name: Optional[str] = None
    is_closed: bool = False
    is_cancelled: bool = False
    is_done: bool = False
    can_reopen: bool = False
    next_stage_id: Optional[int] = None
    next_stage_name: Optional[str] = None
    role: Optional[Literal["new", "reopen", "done", "cancel", "close"]] = None


class HelpdeskTicket(_OdooEntity):
    """``sh.helpdesk.ticket`` — wire fields plus derived ``extra_fields`` / ``lifecycle``."""

    name: Optional[str] = None
    description: Optional[str] = None
    comment: Optional[str] = None
    customer_comment: Optional[str] = None
    email: Optional[str] = None
    email_cc: Optional[str] = None
    email_subject: Optional[str] = None
    mobile_no: Optional[str] = None
    person_name: Optional[str] = None
    partner_id: Optional[Many2one] = None
    stage_id: Optional[Many2one] = None
    team_id: Optional[Many2one] = None
    team_head: Optional[Many2one] = None
    user_id: Optional[Many2one] = None
    category_id: Optional[Many2one] = None
    sub_category_id: Optional[Many2one] = None
    ticket_type: Optional[Many2one] = None
    subject_id: Optional[Many2one] = None
    priority: Optional[Many2one] = None
    company_id: Optional[Many2one] = None
    sh_user_ids: Optional[list[int]] = None
    tag_ids: Optional[list[int]] = None
    sh_sla_policy_ids: Optional[list[int]] = None
    sh_sla_status_ids: Optional[list[int]] = None
    sh_ticket_alarm_ids: Optional[list[int]] = None
    attachment_ids: Optional[list[int]] = None
    timehseet_ids: Optional[list[int]] = None  # Odoo's own misspelling — keep the wire name
    priority_new: Optional[str] = None
    replied_status: Optional[str] = Field(default=None, alias="state", description="'customer_replied' | 'staff_replied' — NOT the lifecycle")
    # FILL IN: the 7 computed booleans (open_boolean, done_stage_boolean, closed_stage_boolean, cancel_stage_boolean,
    #   reopen_stage_boolean, done_button_boolean, cancel_button_boolean) as Optional[bool] = None — spec §2
    # FILL IN: close_date, close_by (Many2one), cancel_date, cancel_by (Many2one), cancel_reason, replied_date,
    #   sh_due_date, sh_sla_deadline, sh_status, create_date, write_date, ticket_from_portal, ticket_from_website,
    #   ticket_running, dynamic_form_submission_id (Many2one) — spec §2 (dates as Optional[str])
    extra_fields: dict[str, str] = Field(default_factory=dict, description="TROC extra fields (field_name → value), derived")
    lifecycle: Optional[HelpdeskLifecycle] = Field(default=None, description="Derived lifecycle block")
```
**Why this shape**: spec §2 Data Models fixes the field list; `replied_status` with `alias="state"` works because `_OdooEntity` sets `populate_by_name=True` (entities.py:25), so both `HelpdeskTicket(state=…)` and `HelpdeskTicket(replied_status=…)` validate.

### `…/models/helpdesk_entities.py` (CREATE — continued, same file)
```python
class HelpdeskStage(_OdooEntity):
    """``helpdesk.stages``."""
    name: Optional[str] = None
    sequence: Optional[int] = None
    is_done_button_visible: Optional[bool] = None
    is_cancel_button_visible: Optional[bool] = None
    sh_next_stage: Optional[Many2one] = None
    sh_group_ids: Optional[list[int]] = None
    mail_template_ids: Optional[list[int]] = None
    company_id: Optional[Many2one] = None


class HelpdeskTeam(_OdooEntity):
    """``sh.helpdesk.team``."""
    name: Optional[str] = None
    team_head: Optional[Many2one] = None
    team_members: Optional[list[int]] = None
    category_ids: Optional[list[int]] = None
    sh_resource_calendar_id: Optional[Many2one] = None
    alias_name: Optional[str] = None


# FILL IN: HelpdeskCategory(name, sequence, team_id, company_id, is_helpdesk_manager), HelpdeskSubcategory(name, parent_category_id),
#   HelpdeskPriority(name, sequence, color: Optional[str]), HelpdeskTicketType(name, sla_count), HelpdeskTag(name, color: Optional[int]),
#   HelpdeskStageInfo(stage_task_id, stage_name, date_in, date_out, date_in_by, date_out_by, day_diff, time_diff, total_time_diff),
#   HelpdeskSla(name, sh_team_id, sh_days, sh_hours, sh_minutes, sh_sla_target_type, sh_stage_id, sh_ticket_type_id, company_id, sla_ticket_count),
#   HelpdeskSlaStatus(sh_ticket_id, sh_sla_id, sh_sla_stage_id, sh_deadline, sh_done_sla_date, sh_exceeded_hours, sh_status, sh_create_date),
#   HelpdeskTicketAlarm(name, type, sh_remind_before, sh_reminder_unit) — all Optional, Many2one for *_id fields — spec §2


class HelpdeskMessage(BaseModel):
    """One ``mail.message`` row on a ticket (not an Odoo entity: shaped by the toolkit)."""

    model_config = ConfigDict(extra="ignore")

    id: int
    date: Optional[str] = None
    author_id: Optional[Many2one] = None
    message_type: Optional[str] = None
    subtype: Optional[str] = None
    body: str = ""
    is_internal: bool = False
```
**Why**: each class mirrors one `fields_get` result recorded in `sdd/state/FEAT-616/findings/live/03_fields.json`; the executor may consult that file to confirm a field type but must not add fields beyond the spec's list.

### `packages/ai-parrot/tests/test_odoo_helpdesk_models.py` (CREATE)
```python
"""Tests for the helpdesk Pydantic layer (entities here; inputs/envelopes appended by TASK-3894/3895)."""
from __future__ import annotations

import pytest

from parrot_tools.odoo.models.helpdesk_entities import HelpdeskLifecycle, HelpdeskSla, HelpdeskStage, HelpdeskTicket

# Wire-shaped ticket (first "ticket" snapshot in sdd/state/FEAT-616/findings/live/13_action_verification.json, names redacted)
LIVE_TICKET = {
    "id": 70, "name": "TICKET#9813547", "stage_id": [4, "New"], "state": "customer_replied", "user_id": False,
    "sh_user_ids": [], "open_boolean": False, "done_stage_boolean": False, "closed_stage_boolean": False,
    "cancel_stage_boolean": False, "close_date": False, "cancel_reason": False, "sh_sla_deadline": False, "sh_status": False,
}


def test_helpdesk_ticket_roundtrip_live_shape():
    ticket = HelpdeskTicket.model_validate(LIVE_TICKET)
    assert ticket.replied_status == "customer_replied"
    assert ticket.stage_id == [4, "New"]
    assert ticket.extra_fields == {} and ticket.lifecycle is None
    # FILL IN: assert the raw "state" key survives in ticket.model_dump(by_alias=True) — extra="allow"/alias contract


def test_helpdesk_ticket_accepts_replied_status_by_name():
    # FILL IN: HelpdeskTicket(replied_status="staff_replied").replied_status == "staff_replied" (populate_by_name)
    ...


def test_helpdesk_stage_and_sla_optional_fields():
    # FILL IN: HelpdeskStage.model_validate({"id": 22, "name": "Open", "sh_next_stage": [23, "Pending close"]}) and
    #   HelpdeskSla.model_validate({"id": 1, "name": "p", "sh_team_id": [1, "Compliance"], "sh_days": 0}) — unknown keys allowed
    ...
```
**Why**: the fixture is the real wire shape observed on staging; these three tests are the AC14 precondition every later task relies on.

### FILL IN checklist
- [ ] `HelpdeskTicket` — the two `FILL IN` field groups; bounded by spec §2 field list
- [ ] the ten small entities listed in the second `FILL IN`; bounded by spec §2 / `03_fields.json`
- [ ] three test bodies; bounded by AC4/AC14

---

## Acceptance Criteria

- [ ] AC4 (spec, entities part): all 14 classes importable from `parrot_tools.odoo.models.helpdesk_entities`.
- [ ] `HelpdeskTicket.model_validate({"id": 1, "state": "customer_replied"}).replied_status == "customer_replied"`.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/odoo/models/helpdesk_entities.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/test_odoo_helpdesk_models.py -q`

---

## Test Specification

See the blueprint: three entity tests in the new `test_odoo_helpdesk_models.py`.

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug odoo-toolkit-upgrades --feature-id FEAT-616`.
2. **Read the spec** (§2 Data Models, §3 M3, §6 live facts).
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** — `grep -n '_OdooEntity\|Many2one' packages/ai-parrot-tools/src/parrot_tools/odoo/models/entities.py`.
5. **Update status** in `sdd/tasks/index/odoo-toolkit-upgrades.json` → `"in-progress"`, commit only that file.
6. **Implement** from the blueprint.
7. **Verify** — import smoke + ruff.
8. **Commit the code** — only the two new files.
9. **Close the task** — `scripts/sdd/close_task.sh TASK-3893 odoo-toolkit-upgrades verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

**Completed by**: sdd-worker (FEAT-616)
**Date**: 2026-10-01
**Notes**: gpt-5.6-terra (codex): 14 helpdesk entity models; transport+models tests 19 passed. Diff reviewed vs contract; task tests run with `pytest --noconftest` (repo conftest broken by pre-existing venv issue); merge-tier sweep red on unrelated failures, accepted by user.

**Deviations from spec**: none | describe if any

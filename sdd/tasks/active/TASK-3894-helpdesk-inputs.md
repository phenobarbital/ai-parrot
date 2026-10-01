# TASK-3894: Helpdesk tool input schemas (`models/helpdesk_inputs.py`)

**Feature**: FEAT-616 — OdooHelpdeskToolkit — typed helpdesk tools for the Softhealer helpdesk (Odoo 19)
**Spec**: `sdd/specs/odoo-toolkit-upgrades.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3893
**Assigned-to**: unassigned

---

## Context

Implements the input third of spec §3 **Module 3** (G2, AC4, AC8). One `_OdooBaseInput` subclass per tool,
decorated onto the tool via `@tool_schema` by TASK-3897–3901. Reference fields accept an id **or** a name
(`Ref = Union[int, str]`), resolved server-side by the toolkit. `UpdateTicketInput` is an explicit patch
model that deliberately has no lifecycle / assignment / SLA fields (design research S9).

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/odoo/models/helpdesk_inputs.py` with `Ref`, and every input class
  of spec §2 Data Models (`TicketIdInput` … `StopTicketTimerInput`), including the three validators
  (`CreateTicketInput` partner ref, `CreateSlaPolicyInput` duration/stage, `MassUpdateTicketsInput` at-least-one-change).
- Every field carries `Field(..., description=...)` — the description is what the LLM sees.
- Append the input tests to `packages/ai-parrot/tests/test_odoo_helpdesk_models.py` (created by TASK-3893).

**NOT in scope**: entities (TASK-3893), envelopes/exports (TASK-3895).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/models/helpdesk_inputs.py` | CREATE | ~35 input classes |
| `packages/ai-parrot/tests/test_odoo_helpdesk_models.py` | MODIFY | append input validator tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from __future__ import annotations
from typing import Any, Literal, Optional, Union
from pydantic import Field, model_validator                              # pydantic v2; inputs.py:11 imports BaseModel, ConfigDict, Field
from .inputs import OdooDomain, _OdooBaseInput                          # verified: inputs.py:16 (OdooDomain) / :19 (_OdooBaseInput)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py  (verified at b3141f286)
OdooDomain = list[Any]                                                   # line 16
class _OdooBaseInput(BaseModel):                                         # line 19
    model_config = ConfigDict(extra="ignore", protected_namespaces=())   # line 22
class SearchRecordsInput(_OdooBaseInput):                                # line 39 — style reference: Field(default=…, ge=…, le=…, description=…)
class CreateQuotationInput(_OdooBaseInput):                              # line 169 — style reference for nested list inputs
```

### Does NOT Exist
- ~~`UpdateTicketInput.stage` / `.stage_id` / `.assignee` / `.user_id` / `.sh_user_ids` / any `sla` field~~ — forbidden by AC8; transitions, assignment and SLA have their own inputs.
- ~~`Ref` in `inputs.py`~~ — defined once in `helpdesk_inputs.py`.
- ~~`pydantic.validator`~~ (v1) — use `model_validator(mode="after")`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/odoo/models/helpdesk_inputs.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/test_odoo_helpdesk_models.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py#_OdooBaseInput"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Class names and field names are fixed by spec §2 (TASK-3897–3901 reference them verbatim).
- `limit` fields: `ge=1`; `SearchTicketsInput.limit` `le=500`, default 50.
- Dates are ISO strings (`Optional[str]`), not `datetime` (Odoo wire format).

---

## Implementation Blueprint

### Steps (in order)
1. Write `Ref`, `TicketIdInput` and the read inputs — *why*: TASK-3897 needs them first.
2. Write the write/assignment/transition inputs with the validators — *why*: AC8 is enforced here, not in the toolkit.
3. Write SLA, reference, stats, wizard and timer inputs — *why*: TASK-3900/3901 import them.

### `packages/ai-parrot-tools/src/parrot_tools/odoo/models/helpdesk_inputs.py` (CREATE)
```python
"""Pydantic input schemas for :class:`~parrot_tools.odoo.helpdesk.OdooHelpdeskToolkit` tools."""
from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import Field, model_validator

from .inputs import OdooDomain, _OdooBaseInput

#: An Odoo id, or the record's name (resolved server-side; ambiguous names are rejected).
Ref = Union[int, str]
_REF_DESC = "Odoo id, or the record's name (exact match first, then unique partial match)"


class TicketIdInput(_OdooBaseInput):
    ticket_id: int = Field(..., ge=1, description="sh.helpdesk.ticket id")


class GetTicketInput(TicketIdInput):
    include_extra_fields: bool = Field(default=True, description="Fold sh.helpdesk.ticket.extra_fields into extra_fields")
    include_history: bool = Field(default=False, description="Also load the stage history lines")


class SearchTicketsInput(_OdooBaseInput):
    query: Optional[str] = Field(default=None, description="Substring matched against name, email_subject and email")
    stage: Optional[Ref] = Field(default=None, description=f"Stage — {_REF_DESC}")
    team: Optional[Ref] = Field(default=None, description=f"Team — {_REF_DESC}")
    assignee: Optional[Ref] = Field(default=None, description="Assignee user — id, login or name")
    category: Optional[Ref] = Field(default=None, description=f"Category — {_REF_DESC}")
    priority: Optional[Ref] = Field(default=None, description=f"Priority — {_REF_DESC}")
    ticket_type: Optional[Ref] = Field(default=None, description=f"Ticket type — {_REF_DESC}")
    partner_id: Optional[int] = Field(default=None, ge=1, description="Customer partner id")
    created_after: Optional[str] = Field(default=None, description="ISO datetime lower bound on create_date")
    created_before: Optional[str] = Field(default=None, description="ISO datetime upper bound on create_date")
    only_open: bool = Field(default=False, description="Exclude the company's close and cancel stages")
    domain: Optional[OdooDomain] = Field(default=None, description="Extra Odoo domain clauses, AND-ed")
    fields: Optional[list[str]] = Field(default=None, description="Fields to return; default = compact list")
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    order: str = Field(default="id desc")


class CreateTicketInput(_OdooBaseInput):
    subject: str = Field(..., description="Ticket subject (email_subject)")
    partner_id: Optional[int] = Field(default=None, ge=1)
    partner_email: Optional[str] = Field(default=None, description="Find (or create) the customer by email")
    partner_name: Optional[str] = Field(default=None, description="Find (or create) the customer by exact name")
    # FILL IN: description, category, sub_category, priority, team, ticket_type (Ref), tags (list[Ref]), assignee (Ref),
    #   email, mobile_no, person_name, due_date (ISO), replied_status Literal[...] = "customer_replied" — spec §2

    @model_validator(mode="after")
    def _require_partner_ref(self) -> "CreateTicketInput":
        if self.partner_id is None and not self.partner_email and not self.partner_name:
            raise ValueError("one of partner_id, partner_email or partner_name is required")
        return self


class UpdateTicketInput(TicketIdInput):
    """Explicit patch — NO stage / assignee / SLA fields (those have dedicated tools)."""
    # FILL IN: subject, description, comment, customer_comment, email, email_cc, mobile_no, person_name, due_date
    #   (Optional[str]); category, sub_category, priority, team, ticket_type (Optional[Ref]); tags (Optional[list[Ref]]) — AC8
```
**Why this shape**: spec §2 fixes every name; the validator lives on the input so the toolkit can assume a partner reference exists (S9: the schema, not the tool body, is the boundary).

### `…/models/helpdesk_inputs.py` (CREATE — continued, same file)
```python
class AddTicketCommentInput(TicketIdInput):
    body: str = Field(..., description="Message body (HTML allowed)")
    internal: bool = Field(default=True, description="True = internal note (never reopens); False = public comment (may reopen a closed ticket)")
    attachment_ids: Optional[list[int]] = None


class MoveTicketToStageInput(TicketIdInput):
    stage: Ref = Field(..., description=f"Target stage — {_REF_DESC}")
    expected_current_stage: Optional[Ref] = Field(default=None, description="Guard: abort when the ticket is not in this stage")


class ReopenTicketInput(TicketIdInput):
    to_stage: Optional[Ref] = Field(default=None, description="Stage to reopen into; default = company reopen stage, else 'Open'")


class CancelTicketInput(TicketIdInput):
    reason: str = Field(..., min_length=1, description="Stored in cancel_reason before action_cancel")


class CreateSlaPolicyInput(_OdooBaseInput):
    name: str
    team: Ref = Field(..., description=f"Team the policy applies to — {_REF_DESC}")
    days: int = Field(default=0, ge=0)
    hours: int = Field(default=0, ge=0)
    minutes: int = Field(default=0, ge=0)
    target_type: Literal["reaching_stage", "assign_to"] = "reaching_stage"
    stage: Optional[Ref] = Field(default=None, description="Required when target_type == 'reaching_stage'")
    ticket_type: Optional[Ref] = None

    @model_validator(mode="after")
    def _check_duration_and_stage(self) -> "CreateSlaPolicyInput":
        # FILL IN: raise ValueError when days+hours+minutes == 0; raise when target_type == "reaching_stage" and stage is None — spec §3 M3
        return self


# FILL IN (same file): ListMyTicketsInput, GetTicketHistoryInput, GetTicketMessagesInput, GetTicketExtraFieldsInput, AttachToTicketInput,
#   AssignTicketInput, TakeTicketInput, ReassignTicketInput, CloseTicketInput, ResolveTicketInput, ApproveTicketInput, ListSlaPoliciesInput,
#   UpdateSlaPolicyInput, GetTicketSlaStatusInput, ListTicketAlarmsInput, ListReferenceInput, TicketStatsInput, MergeTicketsInput
#   (ticket_ids min_length=2, merged_action Literal[...] = "close"), MassUpdateTicketsInput (+ validator: at least one change),
#   StartTicketTimerInput, StopTicketTimerInput — field sets verbatim from spec §2 Data Models
```
**Why**: the remaining classes are one-liners against the spec table; the two validators encode the only judgement calls.

### `packages/ai-parrot/tests/test_odoo_helpdesk_models.py` (MODIFY)
```python
# occurrences: 1 (verified at task time by TASK-3893's blueprint: grep -c 'def test_helpdesk_stage_and_sla_optional_fields' packages/ai-parrot/tests/test_odoo_helpdesk_models.py)
# AFTER — append at end of file
from parrot_tools.odoo.models.helpdesk_inputs import CreateSlaPolicyInput, CreateTicketInput, MassUpdateTicketsInput, UpdateTicketInput  # noqa: E402


def test_create_ticket_input_requires_partner_ref():
    with pytest.raises(ValueError, match="partner_id, partner_email or partner_name"):
        CreateTicketInput(subject="x")
    assert CreateTicketInput(subject="x", partner_email="a@b.c").partner_email == "a@b.c"


def test_create_sla_policy_input_validators():
    # FILL IN: zero duration raises; reaching_stage without stage raises; valid (team="Compliance", hours=1, stage="Closed") passes
    ...


def test_mass_update_input_requires_change():
    # FILL IN: MassUpdateTicketsInput(ticket_ids=[1]) raises; with stage="Open" passes
    ...


def test_update_ticket_input_has_no_lifecycle_fields():
    forbidden = {"stage", "stage_id", "assignee", "user_id", "sh_user_ids"}
    fields = set(UpdateTicketInput.model_fields)
    assert not fields & forbidden
    assert not any(f.startswith("sh_sla") for f in fields)   # AC8
```
**Why**: AC8 is a schema property, so it is tested on the input class itself; the imports go at the append point (hence `noqa: E402`).

### FILL IN checklist
- [ ] `CreateTicketInput` / `UpdateTicketInput` remaining fields; bounded by spec §2 and AC8
- [ ] `CreateSlaPolicyInput._check_duration_and_stage`; bounded by spec §3 M3
- [ ] the 22 remaining input classes incl. `MassUpdateTicketsInput` validator; bounded by spec §2

---

## Acceptance Criteria

- [ ] AC4 (spec, inputs part): every input class of spec §2 importable from `parrot_tools.odoo.models.helpdesk_inputs`.
- [ ] AC8 (spec): `UpdateTicketInput.model_fields` contains none of `stage`, `stage_id`, `assignee`, `user_id`, `sh_user_ids`, and no key starting with `sh_sla`.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/odoo/models/helpdesk_inputs.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/test_odoo_helpdesk_models.py -q`

---

## Test Specification

See the blueprint: four input tests appended to `test_odoo_helpdesk_models.py`.

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug odoo-toolkit-upgrades --feature-id FEAT-616`.
2. **Read the spec** (§2 Data Models — inputs block, §3 M3).
3. **Check dependencies** — TASK-3893 must be `done` (it creates the test module).
4. **Verify the Codebase Contract** — `grep -n 'OdooDomain\|class _OdooBaseInput' packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py`.
5. **Update status** in the per-spec index → `"in-progress"`, commit only that file.
6. **Implement** from the blueprint.
7. **Verify** — `PYTHONPATH=… python -c "from parrot_tools.odoo.models.helpdesk_inputs import UpdateTicketInput; print(list(UpdateTicketInput.model_fields))"` + ruff.
8. **Commit the code** — only the two listed files.
9. **Close the task** — `scripts/sdd/close_task.sh TASK-3894 odoo-toolkit-upgrades verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any

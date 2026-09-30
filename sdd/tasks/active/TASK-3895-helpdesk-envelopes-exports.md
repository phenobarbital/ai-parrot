# TASK-3895: Helpdesk result envelopes + model re-exports

**Feature**: FEAT-616 — OdooHelpdeskToolkit — typed helpdesk tools for the Softhealer helpdesk (Odoo 19)
**Spec**: `sdd/specs/odoo-toolkit-upgrades.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3893, TASK-3894
**Assigned-to**: unassigned

---

## Context

Implements the envelope third of spec §3 **Module 3** (G2, AC4) and closes the model layer: every helpdesk
tool returns one of these structured outputs, and `parrot_tools.odoo.models` re-exports the whole
helpdesk layer so downstream code imports from one place (spec §6 Integration Points).

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/odoo/models/helpdesk_envelopes.py` with every envelope of
  spec §2 Data Models (`HelpdeskReferenceItem` … `TicketTimerResult`, incl. `StatsGroup`).
- Modify `models/__init__.py`: import + `__all__` for all classes of `helpdesk_entities`, `helpdesk_inputs`, `helpdesk_envelopes`.
- Append the export test to `test_odoo_helpdesk_models.py`.

**NOT in scope**: the toolkit, the normaliser, `parrot_tools/odoo/__init__.py` (TASK-3897 exports the toolkit class).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/models/helpdesk_envelopes.py` | CREATE | ~18 envelope classes |
| `packages/ai-parrot-tools/src/parrot_tools/odoo/models/__init__.py` | MODIFY | re-export the helpdesk models |
| `packages/ai-parrot/tests/test_odoo_helpdesk_models.py` | MODIFY | append the exports test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from __future__ import annotations
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field                        # verified: envelopes.py:11
from .envelopes import FieldSelectionMetadata                            # verified: envelopes.py:14
from .entities import Many2one                                           # verified: entities.py:19
from .helpdesk_entities import (HelpdeskLifecycle, HelpdeskMessage, HelpdeskSla, HelpdeskSlaStatus, HelpdeskStageInfo, HelpdeskTicket, HelpdeskTicketAlarm)   # created by TASK-3893
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/odoo/models/envelopes.py  (verified at b3141f286)
class FieldSelectionMetadata(BaseModel)                                  # line 14
class SearchResult(BaseModel):                                           # line 52 — style reference
    records: list[dict[str, Any]] = Field(default_factory=list); total: int = 0; limit: Optional[int] = None; offset: int = 0; model: str
    model_config = ConfigDict(protected_namespaces=())                   # line 63 (needed whenever a field is named model_*)

# packages/ai-parrot-tools/src/parrot_tools/odoo/models/__init__.py  (verified at b3141f286, 109 lines)
from .entities import (... StockPicking,)                                # lines 2-14
from .envelopes import (... ServerInfoResult, UpdateResult,)             # lines 15-31
from .inputs import (... AttachDocumentInput, ...)                       # lines 32-56; `    AttachDocumentInput,` is line 33
__all__ = [ ... "AttachDocumentInput", ]                                 # lines 58-109; `    "AttachDocumentInput",` is line 108
```

### Does NOT Exist
- ~~`HelpdeskTicketResult`~~ — the class is `TicketResult` (spec §2); do not rename.
- ~~`models/helpdesk.py`~~ — three sibling modules only.
- ~~`__all__` in `helpdesk_entities.py` / `helpdesk_inputs.py`~~ — not required; `models/__init__.py` lists names explicitly.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/odoo/models/helpdesk_envelopes.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/odoo/models/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_odoo_helpdesk_models.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/models/envelopes.py#FieldSelectionMetadata"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Envelope field names are fixed by spec §2 (TASK-3897–3901 construct them by keyword).
- `TicketTransitionResult.method_used: Literal["action", "stage_write", "none"]`; `TicketStatsResult.source_method: str`.
- Lists default via `Field(default_factory=list)`.

---

## Implementation Blueprint

### Steps (in order)
1. Create the envelope module — *why*: TASK-3897 imports it.
2. Extend `models/__init__.py` imports and `__all__` — *why*: single import surface (AC4).
3. Append `test_models_init_exports_helpdesk_classes` — *why*: proves AC4 mechanically.

### `packages/ai-parrot-tools/src/parrot_tools/odoo/models/helpdesk_envelopes.py` (CREATE)
```python
"""Result envelopes returned by :class:`~parrot_tools.odoo.helpdesk.OdooHelpdeskToolkit` tools."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .entities import Many2one
from .envelopes import FieldSelectionMetadata
from .helpdesk_entities import (
    HelpdeskMessage, HelpdeskSla, HelpdeskSlaStatus, HelpdeskStageInfo, HelpdeskTicket, HelpdeskTicketAlarm,
)


class HelpdeskReferenceItem(BaseModel):
    id: int
    name: str
    extra: dict[str, Any] = Field(default_factory=dict)


class HelpdeskReferenceResult(BaseModel):
    """Result of the ``list_helpdesk_*`` reference-data tools."""
    kind: str = Field(..., description="Odoo model technical name")
    items: list[HelpdeskReferenceItem] = Field(default_factory=list)
    total: int = 0


class TicketResult(BaseModel):
    ticket: HelpdeskTicket
    url: str
    model: str = "sh.helpdesk.ticket"
    model_config = ConfigDict(protected_namespaces=())


class TicketListResult(BaseModel):
    tickets: list[HelpdeskTicket] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0
    fields: list[str] = Field(default_factory=list)
    metadata: Optional[FieldSelectionMetadata] = None


class TicketTransitionResult(BaseModel):
    """Outcome of a transition tool — ``applied`` is computed from a post-condition read, never assumed."""
    ticket_id: int
    action: str
    applied: bool
    method_used: Literal["action", "stage_write", "none"]
    from_stage: Optional[str] = None
    to_stage: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    ticket: HelpdeskTicket


class StatsGroup(BaseModel):
    key: Optional[int | str] = None
    label: str
    count: int


# FILL IN: TicketHistoryResult, TicketMessagesResult, TicketExtraFieldsResult(ticket_id, fields, labels, count), TicketCommentResult
#   (ticket_id, message_id, internal, reopened, stage_after), TicketAssignmentResult(ticket_id, assignee: Optional[Many2one],
#   additional_assignees, method_used: str, ticket), SlaPolicyResult(policy, url), SlaPolicyListResult, SlaStatusResult(ticket_id,
#   overall_status, deadline, statuses), TicketAlarmListResult, TicketStatsResult(group_by, groups, total, source_method),
#   WizardResult(wizard_model, wizard_id, ticket_ids, applied, result_ticket_id, message), TicketTimerResult(ticket_id, running,
#   started_at, duration_hours, warnings) — field sets verbatim from spec §2 Data Models
```
**Why this shape**: mirrors `envelopes.py` conventions (plain `BaseModel`, `Field(default_factory=list)`, `protected_namespaces` when a field is named `model`).

### `packages/ai-parrot-tools/src/parrot_tools/odoo/models/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    AttachDocumentInput,' packages/ai-parrot-tools/src/parrot_tools/odoo/models/__init__.py)
# AFTER the closing `)` of the `from .inputs import (` block (its last entry `    AttachDocumentInput,` is line 33; the `)` follows it) — insert:
from .helpdesk_entities import (
    HelpdeskCategory, HelpdeskLifecycle, HelpdeskMessage, HelpdeskPriority, HelpdeskSla, HelpdeskSlaStatus, HelpdeskStage,
    HelpdeskStageInfo, HelpdeskSubcategory, HelpdeskTag, HelpdeskTeam, HelpdeskTicket, HelpdeskTicketAlarm, HelpdeskTicketType,
)
from .helpdesk_envelopes import (
    HelpdeskReferenceItem, HelpdeskReferenceResult, SlaPolicyListResult, SlaPolicyResult, SlaStatusResult, StatsGroup,
    TicketAlarmListResult, TicketAssignmentResult, TicketCommentResult, TicketExtraFieldsResult, TicketHistoryResult,
    TicketListResult, TicketMessagesResult, TicketResult, TicketStatsResult, TicketTimerResult, TicketTransitionResult, WizardResult,
)
# FILL IN: from .helpdesk_inputs import (<every class TASK-3894 created, incl. Ref>) — spec §2 inputs block

# occurrences: 1 (verified: grep -c '    "AttachDocumentInput",' packages/ai-parrot-tools/src/parrot_tools/odoo/models/__init__.py)
# AFTER — insert below `    "AttachDocumentInput",` (verified: models/__init__.py:108), still inside the `__all__` list:
    # helpdesk (FEAT-616)
    "HelpdeskCategory", "HelpdeskLifecycle", "HelpdeskMessage", "HelpdeskPriority", "HelpdeskSla", "HelpdeskSlaStatus",
    "HelpdeskStage", "HelpdeskStageInfo", "HelpdeskSubcategory", "HelpdeskTag", "HelpdeskTeam", "HelpdeskTicket",
    "HelpdeskTicketAlarm", "HelpdeskTicketType",
    # FILL IN: every envelope and input class name as a string — must equal the imported names above
```
**Why**: keeps the existing import order (entities → envelopes → inputs) and appends the helpdesk groups; `__all__` must list exactly the imported names or `ruff` F401/F822 fires.

### `packages/ai-parrot/tests/test_odoo_helpdesk_models.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3894: grep -c 'def test_update_ticket_input_has_no_lifecycle_fields' packages/ai-parrot/tests/test_odoo_helpdesk_models.py)
# AFTER — append at end of file
import parrot_tools.odoo.models as odoo_models  # noqa: E402


def test_models_init_exports_helpdesk_classes():
    for name in ("HelpdeskTicket", "HelpdeskLifecycle", "TicketResult", "TicketTransitionResult", "StatsGroup",
                 "CreateTicketInput", "UpdateTicketInput", "SearchTicketsInput", "CreateSlaPolicyInput", "MergeTicketsInput"):
        assert hasattr(odoo_models, name), name
        assert name in odoo_models.__all__, name
    # FILL IN: TicketTransitionResult(ticket_id=1, action="action_closed", applied=True, method_used="action",
    #   ticket=HelpdeskTicket(id=1)).warnings == [] — envelope defaults
```
**Why**: AC4 verified by attribute + `__all__` membership.

### FILL IN checklist
- [ ] `helpdesk_envelopes.py` remaining twelve envelopes; bounded by spec §2
- [ ] `models/__init__.py` inputs import + `__all__` strings; bounded by "names equal imports" (ruff)
- [ ] test tail; bounded by AC4

---

## Acceptance Criteria

- [ ] AC4 (spec): every class in spec §2 importable from `parrot_tools.odoo.models`.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/odoo/models/` clean (no unused or undefined `__all__` names).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/test_odoo_helpdesk_models.py -q`
- `pytest packages/ai-parrot/tests/test_odoo_toolkit.py -q` — the base package import must still work.

---

## Test Specification

See the blueprint (`test_models_init_exports_helpdesk_classes`) plus the tests TASK-3893/3894 added.

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug odoo-toolkit-upgrades --feature-id FEAT-616`.
2. **Read the spec** (§2 envelopes block, §3 M3, §6 Edit Sites).
3. **Check dependencies** — TASK-3893 and TASK-3894 `done`.
4. **Verify the Codebase Contract** — re-run both `grep -c` on `models/__init__.py`.
5. **Update status** in the per-spec index → `"in-progress"`, commit only that file.
6. **Implement** from the blueprint.
7. **Verify** — Validation Commands + ruff.
8. **Commit the code** — only the three listed files.
9. **Close the task** — `scripts/sdd/close_task.sh TASK-3895 odoo-toolkit-upgrades verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any

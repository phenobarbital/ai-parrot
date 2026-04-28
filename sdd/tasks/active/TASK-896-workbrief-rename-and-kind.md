# TASK-896: Rename `BugBrief → WorkBrief` and add `kind` field

**Feature**: FEAT-132 — feat-129-upgrades
**Spec**: `sdd/specs/feat-129-upgrades.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation task for FEAT-132. The dev-loop intake currently exposes a
single `BugBrief` model that does not declare the work kind, so every
ticket gets opened as a Jira `Bug`. Spec §1 G1 requires the model to
carry an explicit `kind ∈ {"bug", "enhancement", "new_feature"}` and
to be renamed to `WorkBrief` to reflect the broader scope. A
back-compat alias keeps every existing import (`from
parrot.flows.dev_loop import BugBrief`) green.

This is the foundation every other task in this feature builds on
(intent classifier reads `kind`, ResearchNode maps it to issuetype,
form passes it through). Land it FIRST.

Implements spec §3 Module 1.

---

## Scope

- Rename `BugBrief` → `WorkBrief` in
  `packages/ai-parrot/src/parrot/flows/dev_loop/models.py`.
- Add a `WorkKind` literal alias and a `kind: WorkKind` field on
  `WorkBrief` defaulting to `"bug"`. Place the field as the FIRST
  declared field on the model so the JSON-schema rendering used by the
  dispatcher's `_build_prompt` surfaces it at the top.
- Add a module-level alias `BugBrief = WorkBrief` and re-export both
  symbols from `parrot.flows.dev_loop.__init__`. Update `__all__`.
- Extend the unit-test suite (`tests/flows/dev_loop/test_models.py`)
  with the three new contract tests listed in §4 of the spec
  (`test_workbrief_default_kind_is_bug`,
  `test_workbrief_kind_literal_rejects_invalid`,
  `test_bugbrief_alias_is_workbrief`).
- Verify NO other test or non-test source file in
  `packages/ai-parrot/` breaks — pre-existing `BugBrief` imports
  must continue to work without edits.

**NOT in scope**:
- `IntentClassifierNode` (TASK-898).
- Issuetype routing in `ResearchNode` (TASK-900).
- `BugIntakeNode` scope-down (TASK-899).
- UI form changes (TASK-902).
- Removing the legacy `BugBrief` symbol — keep it as an alias forever
  unless a future migration explicitly retires it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` | MODIFY | Rename class to `WorkBrief`; add `WorkKind` Literal alias and `kind` field; export `BugBrief = WorkBrief`. |
| `packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py` | MODIFY | Re-export both `WorkBrief` and `BugBrief`; add to `__all__`. |
| `packages/ai-parrot/tests/flows/dev_loop/test_models.py` | MODIFY | Add the three new tests; keep existing `BugBrief`-shaped tests green. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing — file currently exports these.
from parrot.flows.dev_loop.models import (
    BugBrief,
    AcceptanceCriterion,
    ShellCriterion,
    FlowtaskCriterion,
    ManualCriterion,
    LogSource,
    CriterionResult,
    QAReport,
    DevelopmentOutput,
    ResearchOutput,
    ClaudeCodeDispatchProfile,
    DispatchEvent,
)
# verified: parrot/flows/dev_loop/models.py (top of file)
# verified: parrot/flows/dev_loop/__init__.py:23-35

from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
# verified: models.py:18-20 (already imports these — Literal is already in use
# for AcceptanceCriterion.kind etc.)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models.py
class BugBrief(BaseModel):                                # line 105 (current)
    summary: str = Field(..., min_length=10, max_length=255, ...)
    description: str = Field(default="", ...)
    affected_component: str
    log_sources: List[LogSource] = Field(default_factory=list)
    acceptance_criteria: List[AcceptanceCriterion] = Field(..., min_length=1)
    escalation_assignee: str
    reporter: str
    existing_issue_key: Optional[str] = None              # added in 8d151ee4

# packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py
__all__ = [
    "AcceptanceCriterion",
    "BugBrief",                                            # keep as alias
    "ClaudeCodeDispatcher",
    "ClaudeCodeDispatchProfile",
    "CriterionResult",
    "DevelopmentOutput",
    "DispatchEvent",
    "DispatchExecutionError",
    "DispatchOutputValidationError",
    "FlowStreamMultiplexer",
    "FlowtaskCriterion",
    "LogSource",
    "ManualCriterion",
    "QAReport",
    "ResearchOutput",
    "ShellCriterion",
    "build_dev_loop_flow",
    "cleanup_worktree",
    "flow_stream_ws",
    "register_pull_request_webhook",
]
# verified: parrot/flows/dev_loop/__init__.py
```

### Pattern reference — discriminated literal already in use

```python
# models.py — FlowtaskCriterion / ShellCriterion / ManualCriterion
# all use `kind: Literal[...] = "..."`. Mirror that pattern for
# WorkKind:
WorkKind = Literal["bug", "enhancement", "new_feature"]
```

### Does NOT Exist

- ~~`parrot.flows.dev_loop.WorkBrief`~~ — does NOT yet exist; this task
  introduces it.
- ~~`WorkKind` as a top-level export from `parrot.flows.dev_loop`~~ —
  internal type alias only. Public surface exposes the literal via
  `WorkBrief.kind`'s pydantic schema. Do NOT add `WorkKind` to
  `__init__.py.__all__`.
- ~~`BugBrief.kind`~~ as a separate runtime field on the alias — there
  is only ONE field; both `BugBrief.kind` and `WorkBrief.kind` resolve
  to the same descriptor because `BugBrief is WorkBrief`.
- ~~Renaming `kind` to `intent` / `category` / `type`~~ — the spec
  pins `kind` as the canonical field name. Do not invent alternatives.
- ~~`populate_by_name=True` on `WorkBrief`~~ — the new `kind` field
  has no `validation_alias`. Don't add ConfigDict unless a later task
  needs it.

---

## Implementation Notes

### Pattern to Follow

```python
# Mirror the existing `LogSource.kind` literal style:
class LogSource(BaseModel):
    kind: Literal["cloudwatch", "elasticsearch", "attached_file"]
    locator: str = Field(...)
    time_window_minutes: int = Field(default=60, ge=1, le=1440)

# WorkKind alias + WorkBrief.kind:
WorkKind = Literal["bug", "enhancement", "new_feature"]

class WorkBrief(BaseModel):
    """User-facing input contract for the dev-loop flow.

    Renamed from BugBrief in FEAT-132. The legacy name is preserved as
    a module-level alias (`BugBrief = WorkBrief`) so existing
    `from parrot.flows.dev_loop import BugBrief` callers keep working
    without edits.
    """

    kind: WorkKind = Field(
        default="bug",
        description=(
            "Intake classification: 'bug' for defect triage, "
            "'enhancement' for changes to existing behaviour, "
            "'new_feature' for net-new capability. Picked up by "
            "IntentClassifierNode for routing and by ResearchNode for "
            "Jira issuetype selection."
        ),
    )
    # ... remaining fields unchanged ...


BugBrief = WorkBrief  # back-compat alias (FEAT-132)
```

### Key Constraints

- `kind` MUST default to `"bug"` so existing call sites (tests,
  `examples/dev_loop/server.py`, prior consumers) construct without
  passing `kind=`.
- Order matters for the dispatcher prompt rendering: place `kind`
  FIRST in the field declaration order. Pydantic preserves
  declaration order in `model_json_schema().properties`.
- Do NOT add a `validation_alias` for `kind`. If we later need to
  accept `intent` or `category` as input, add it then.

### References in Codebase

- `parrot/flows/dev_loop/models.py` — file under edit.
- `parrot/flows/dev_loop/__init__.py` — re-export.
- `parrot/flows/dev_loop/dispatcher.py:_build_prompt` — reads
  `model_json_schema()`. Verify it still produces a clean field list
  with `kind` at the top.
- `tests/flows/dev_loop/test_models.py` — extend.

---

## Acceptance Criteria

- [ ] `WorkBrief` exists in `models.py`; `BugBrief = WorkBrief` alias
  is declared at module level.
- [ ] `WorkBrief.kind: WorkKind = Field(default="bug", ...)` is the
  FIRST declared field.
- [ ] `parrot.flows.dev_loop.__init__` re-exports both names; `__all__`
  contains `WorkBrief` and `BugBrief`.
- [ ] All three new tests pass:
  `test_workbrief_default_kind_is_bug`,
  `test_workbrief_kind_literal_rejects_invalid`,
  `test_bugbrief_alias_is_workbrief`.
- [ ] Full pre-existing dev_loop suite stays green:
  `pytest packages/ai-parrot/tests/flows/dev_loop/ -q` reports no
  regressions vs the baseline at this branch's HEAD.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/`.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_models.py
from parrot.flows.dev_loop import BugBrief, WorkBrief
from parrot.flows.dev_loop.models import WorkKind  # internal — verify import path
import pytest


class TestWorkBriefKind:
    def test_workbrief_default_kind_is_bug(self, sample_brief_kwargs):
        brief = WorkBrief(**sample_brief_kwargs)
        assert brief.kind == "bug"

    def test_workbrief_kind_literal_rejects_invalid(self, sample_brief_kwargs):
        with pytest.raises(ValueError):
            WorkBrief(kind="story", **sample_brief_kwargs)

    def test_bugbrief_alias_is_workbrief(self):
        assert BugBrief is WorkBrief
```

`sample_brief_kwargs` lives in `conftest.py` — extend if missing, or
inline a minimal dict (summary ≥10 chars, ≥1 acceptance criterion,
reporter, escalation_assignee, affected_component).

---

## Agent Instructions

1. Read the spec section §3 Module 1 and §6 (Codebase Contract)
   before touching code.
2. Confirm `parrot/flows/dev_loop/models.py` still has `BugBrief` at
   line 105 (or thereabouts — git history may have shifted line
   numbers; check the import works).
3. Implement the rename + alias + new field.
4. Run the affected tests:
   `pytest packages/ai-parrot/tests/flows/dev_loop/test_models.py -v`.
5. Run the full dev_loop suite to catch any module that referenced
   `BugBrief` by attribute lookup:
   `pytest packages/ai-parrot/tests/flows/dev_loop/ -q`.
6. Commit on the feature worktree with a message matching the SDD
   convention (e.g. `feat(dev_loop): TASK-896 — WorkBrief rename + kind field`).
7. Move this file to `sdd/tasks/done/`, update `sdd/tasks/.index.json`,
   fill in the Completion Note below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any

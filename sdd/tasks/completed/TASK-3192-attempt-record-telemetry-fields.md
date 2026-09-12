# TASK-3192: Add telemetry fields to AttemptRecord

**Feature**: FEAT-554 — Empirical Token-Budget Sizing for sdd-coder Bedrock Seats
**Spec**: `sdd/specs/sdd-coder-bedrock-token-telemetry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (models file). `AttemptRecord` is what
`AttemptTelemetryCollector.record()` returns and what TASK-3193 projects into a
JSONL row. It needs to carry the identity and telemetry the collector will
receive: a unique attempt id (the `attempt` number restarts at 1 on every
`_run_task` invocation, `engine.py:592`, so it cannot be the join key), the
dispatcher-resolved model, the per-turn series, and the ledger report.

Purely additive Pydantic fields with defaults, on a file nothing else in this
feature touches — which is why it carries a Delegation Contract.

---

## Scope

- Add `Tuple` to the module's `typing` import.
- Add ten fields to `AttemptRecord`, all with defaults.
- Write a test that an `AttemptRecord` built the way `record()` builds it today
  still validates, and that the new defaults are the documented ones.

**NOT in scope**: populating any of them (TASK-3193), the row projection
(TASK-3191), `TaskResult`/`CoderJob` (unchanged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | `Tuple` import + ten `AttemptRecord` fields |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py` | MODIFY | Defaults + backward-compat test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from typing import Any, Dict, List, Literal, Optional  # verified: parrot/flows/dev_loop/sdd_coder/models.py:6
from pydantic import BaseModel, Field                   # already imported in the module
```
`Tuple` is NOT currently imported — this task adds it.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py
class AttemptRecord(BaseModel):                                       # line 115
    """Per-attempt telemetry (spec G9, design research S8)."""
    attempt: int = Field(..., ge=1, le=3)                             # line 116
    seat_label: str                                                   # line 117
    backend: str = ""                                                 # line 118
    model: str = ""                                                   # line 119
    started_at: str                                                   # line 120
    ended_at: str = ""                                                # line 121
    duration_s: float = 0.0                                           # line 122
    usage: Dict[str, Any] = Field(default_factory=dict)               # line 125
    error: str = ""                                                   # line 126

class TaskResult(BaseModel):                                          # line 129
    attempts: List[AttemptRecord] = Field(default_factory=list)
class CoderJob(BaseModel):                                            # line 153
```

### Does NOT Exist
- ~~`AttemptRecord.attempt_uid` / `.job_id` / `.resolved_model` / `.turns` /
  `.terminal` / `.error_class` / `.declared_files` / `.declared_files_known` /
  `.turns_with_unknown_usage` / `.turn_series` / `.budget_report`~~ — all added here.
- ~~`typing.Tuple` already imported in this module~~ — it is not; line 6 imports
  `Any, Dict, List, Literal, Optional` only.
- ~~`List[List[int]]` for `turn_series`~~ — rejects a turn with unknown usage
  (spec §10 R6). Use the nullable tuple form.
- ~~Removing or renaming `error`~~ — it stays; it is the human-facing full exception
  string. `error_class` is additive and is the only one that reaches the dataset.

---

## Implementation Notes

### Key Constraints
- Every new field has a default, so `AttemptTelemetryCollector.record()`
  (`engine.py:125`) keeps working unchanged until TASK-3193 populates them.
- `attempt_uid` defaults to `""` rather than generating a uuid: the engine mints
  it once per attempt (TASK-3193) and a model-level default would hand out a
  different id to every copy of the record.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py:476-486` — the
  same optional-field-with-default compatibility rule.

---

## Implementation Blueprint

### Steps (in order)
1. Add `Tuple` to the `typing` import — *why*: `turn_series`'s element type needs it and the module does not import it today.
2. Append the ten fields after `error` inside `AttemptRecord` — *why*: they extend the existing telemetry block, and inserting before `error` would break the disambiguating context this blueprint anchors on.
3. Add the test — *why*: the whole point of the defaults is that nothing else has to change yet.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` (MODIFY — import)
```python
# occurrences: 1 (verified: grep -c 'from typing import Any, Dict, List, Literal, Optional' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py)
# REPLACE the line `from typing import Any, Dict, List, Literal, Optional` (verified: packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:6)
from typing import Any, Dict, List, Literal, Optional, Tuple
```

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` (MODIFY — fields)
```python
# occurrences: 1 (verified: the three-line context below appears once; a bare
#   `    error: str = ""` appears TWICE in this file, so the anchor is the context)
# AFTER — insert below the three-line context
#     `    duration_s: float = 0.0`
#     `    usage: Dict[str, Any] = Field(default_factory=dict)`
#     `    error: str = ""`
#   (verified: packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:122-126)
    attempt_uid: str = ""
    """Globally unique id for this attempt, minted by the engine.

    The telemetry join key. `attempt` cannot serve: it restarts at 1 on every
    `_run_task` invocation (verified: engine.py:592) while each chunk gets a
    fresh job id (jobs.py:30), so a task re-dispatched in a later job reuses
    the same number (spec §10 R3). Defaults empty; the engine sets it.
    """
    job_id: str = ""
    resolved_model: str = ""
    """The model the dispatcher actually resolved, which can differ from the
    roster seat's configured `model` via `_resolve_model`'s client fallbacks
    (verified: dispatchers/llm.py:879)."""
    turns: int = 0
    terminal: str = "completed"
    """One of "completed", "failed" or "salvaged"."""
    error_class: str = ""
    """Exception type name only. The full message stays in `error` and never
    reaches the dataset (spec §10 R5)."""
    declared_files: Optional[int] = None
    """Count of files the task declared, captured DURING the attempt: the task
    file lives in the worktree that `/sdd-done` removes (spec §10 R8)."""
    declared_files_known: bool = False
    turns_with_unknown_usage: int = 0
    turn_series: List[Tuple[int, Optional[int], Optional[int]]] = Field(default_factory=list)
    """Per turn: (round_number, input_tokens or None, output_tokens or None)."""
    budget_report: Dict[str, Any] = Field(default_factory=dict)
    """`BudgetReport.model_dump()` when an observational ledger was bound."""
```
**Why this shape**: All defaults, so `record()` and every existing test keep working until TASK-3193 populates them. `turn_series` uses the nullable tuple form because a provider that reports no usage for a round is normal and a zero there would silently bias every downstream percentile. `budget_report` is a plain dict to avoid importing `parrot.clients` into this model module.

### FILL IN checklist
*(none — fully determined; this task carries a Delegation Contract)*

---

## Delegation Contract

```json
{
  "schema_version": 1,
  "task_id": "TASK-3192",
  "spec_path": "sdd/specs/sdd-coder-bedrock-token-telemetry.spec.md",
  "design_complete": true,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py",
      "action": "modify",
      "expected_sha256": "e45c0fd66b01812ac24f544127348fb88532d4d9ed5be5b012e83e461528d76f",
      "planned_changes": "Add Tuple to the typing import; append ten defaulted telemetry fields to AttemptRecord after its error field",
      "blocks": ["impl-typing-import", "impl-attempt-record-fields"]
    }
  ],
  "references": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py",
      "sha256": "e45c0fd66b01812ac24f544127348fb88532d4d9ed5be5b012e83e461528d76f",
      "start_line": 115,
      "end_line": 126,
      "purpose": "AttemptRecord as it exists today, and the insertion anchor"
    }
  ],
  "implementation_blocks": ["impl-typing-import", "impl-attempt-record-fields"],
  "acceptance_criteria": [
    "AttemptRecord accepts the pre-FEAT-554 kwarg set and the ten new fields default",
    "turn_series accepts a (round, None, None) entry",
    "pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py passes"
  ],
  "validation_commands": [
    ["pytest", "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py", "-q"],
    ["ruff", "check", "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py"]
  ]
}
```

```python id=impl-typing-import
# Apply to packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:
# replace the single typing import line on line 6 with this one.
from typing import Any, Dict, List, Literal, Optional, Tuple
```

```python id=impl-attempt-record-fields
# Apply to packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:
# insert immediately after AttemptRecord's `error: str = ""` field (line 126),
# identified by the unique three-line context duration_s / usage / error.
    attempt_uid: str = ""
    """Globally unique id for this attempt, minted by the engine.

    The telemetry join key. `attempt` cannot serve: it restarts at 1 on every
    `_run_task` invocation (engine.py:592) while each chunk gets a fresh job id
    (jobs.py:30), so a task re-dispatched in a later job reuses the same
    number. Defaults empty; the engine sets it.
    """
    job_id: str = ""
    resolved_model: str = ""
    """The model the dispatcher actually resolved, which can differ from the
    roster seat's configured `model` via `_resolve_model`'s client fallbacks
    (dispatchers/llm.py:879)."""
    turns: int = 0
    terminal: str = "completed"
    """One of "completed", "failed" or "salvaged"."""
    error_class: str = ""
    """Exception type name only. The full message stays in `error` and never
    reaches the dataset."""
    declared_files: Optional[int] = None
    """Count of files the task declared, captured DURING the attempt: the task
    file lives in the worktree that /sdd-done removes."""
    declared_files_known: bool = False
    turns_with_unknown_usage: int = 0
    turn_series: List[Tuple[int, Optional[int], Optional[int]]] = Field(default_factory=list)
    """Per turn: (round_number, input_tokens or None, output_tokens or None)."""
    budget_report: Dict[str, Any] = Field(default_factory=dict)
    """BudgetReport.model_dump() when an observational ledger was bound."""
```

---

## Acceptance Criteria

- [ ] `AttemptRecord(attempt=1, seat_label="qwen", started_at="t")` still validates, with every new field at its documented default.
- [ ] `attempt_uid` defaults to `""` — NOT a generated uuid.
- [ ] `turn_series=[(7, None, None)]` validates; `turn_series=[[7, None, None]]` also coerces (Pydantic tuple coercion) and `turn_series=[(0, 1, 1)]` raises nothing (no ge constraint on the tuple positions — the constraint lives on `TurnUsage`).
- [ ] `TaskResult(task_id="T", outcome="merged", attempts=[record])` still validates.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py  (append)
from parrot.flows.dev_loop.sdd_coder.models import AttemptRecord, TaskResult


class TestAttemptRecordTelemetryFields:
    def test_pre_feat554_kwargs_still_validate(self):
        rec = AttemptRecord(attempt=1, seat_label="qwen", started_at="2026-09-12T00:00:00+00:00")
        assert rec.attempt_uid == ""
        assert rec.turn_series == []
        assert rec.budget_report == {}
        assert rec.declared_files is None
        assert rec.declared_files_known is False
        assert rec.terminal == "completed"

    def test_turn_series_accepts_unknown_usage(self):
        rec = AttemptRecord(
            attempt=1, seat_label="qwen", started_at="t", turn_series=[(7, None, None)]
        )
        assert rec.turn_series[0] == (7, None, None)

    def test_nested_in_task_result(self):
        rec = AttemptRecord(attempt=1, seat_label="qwen", started_at="t")
        assert TaskResult(task_id="TASK-1", outcome="merged", attempts=[rec]).attempts[0] is rec
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §3 Module 4 and §10 R3/R6.
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — re-run `sha256sum packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py`; if it no longer matches the Delegation Contract's digest, refresh the packet in this file FIRST, then proceed.
4. **Update status** in `sdd/tasks/index/sdd-coder-bedrock-token-telemetry.json` → `"in-progress"`.
5. **Implement** from the blueprint; do not remove or rename `error`.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3192-attempt-record-telemetry-fields.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-coder (codex-spark attempt 1 failed on CLI arg incompatibility; qwen seat attempt 2 succeeded) via parrot-sdd-coder orchestrator, merged by sdd-worker
**Date**: 2026-09-12
**Notes**: Added the ten telemetry fields to `AttemptRecord`
(`attempt_uid`, `job_id`, `resolved_model`, `turns`, `terminal`,
`error_class`, `declared_files`, `declared_files_known`,
`turns_with_unknown_usage`, `turn_series`, `budget_report`), all purely
additive with documented defaults; `attempt_uid` defaults to `""` (not a
generated uuid), and `turn_series` uses `List[Tuple[int, Optional[int],
Optional[int]]]` so a turn with unknown usage is representable. Attempt 1
on the codex-spark seat failed before any model call
(`codex exec` rejected `--ask-for-approval` — a CLI/dispatcher argument
mismatch, not a code issue); attempt 2 on the qwen seat succeeded. All 11
tests pass; `ruff check` clean.

**Deviations from spec**: none

Seat: codex-spark→qwen (retry) · Backend: codex (failed)→nova · Model: gpt-5.3-codex-spark (failed)→qwen.qwen3-coder-480b-a35b-instruct · Attempts: 2 · Duration: 75.1s · Tokens: 335118/2778

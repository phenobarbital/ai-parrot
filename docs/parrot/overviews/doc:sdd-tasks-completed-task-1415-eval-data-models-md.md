---
type: Wiki Overview
title: 'TASK-1415: Eval data models (`parrot/eval/models.py`)'
id: doc:sdd-tasks-completed-task-1415-eval-data-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundation of the harness. Every other module imports these Pydantic v2 models.
  Implements spec §2
relates_to:
- concept: mod:parrot.eval
  rel: mentions
---

# TASK-1415: Eval data models (`parrot/eval/models.py`)

**Feature**: FEAT-217 — Generic Agent Evaluation Harness
**Spec**: `sdd/specs/generic-evaluation-harness.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation of the harness. Every other module imports these Pydantic v2 models. Implements spec §2
"Data Models". No behavior — pure data contracts, frozen at I/O boundaries.

---

## Scope

- Create the `parrot/eval/` package (`__init__.py`) and `parrot/eval/models.py`.
- Implement all models from spec §2: `EvalTask`, `ToolCallRecord`, `TurnRecord`, `TokenUsage`,
  `Trajectory`, `MetricScore`, `EvalResult`, `EvalDataset`.
- `EvalTask` uses `ConfigDict(frozen=True, extra="allow")`; `Trajectory` uses `extra="allow"`.
- Use forward ref `"SandboxSpec | None"` for `EvalTask.sandbox_spec` (defined in TASK-1417); add a
  `model_rebuild()` hook or `TYPE_CHECKING` import note so the forward ref resolves once
  `SandboxSpec` exists. Do NOT import `SandboxSpec` at module top (would create a cycle).
- Export the model names from `parrot/eval/__init__.py`.

**NOT in scope**: `SandboxSpec` itself (TASK-1417), any evaluator/runner/registry logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/eval/__init__.py` | CREATE | Package init + public exports |
| `packages/ai-parrot/src/parrot/eval/models.py` | CREATE | All Pydantic models |
| `packages/ai-parrot/tests/eval/__init__.py` | CREATE | Test package init |
| `packages/ai-parrot/tests/eval/test_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field   # pydantic v2 — used throughout the repo
from typing import Any, Literal
```

### Existing Signatures to Use
Copy model definitions verbatim from spec §2 "Data Models". No existing codebase classes are
extended by this task.

### Does NOT Exist
- ~~`parrot.eval` (any submodule)~~ — this task creates the package.
- ~~`SandboxSpec`~~ — defined later in TASK-1417; use a forward reference only.

---

## Implementation Notes

### Pattern to Follow
Mirror existing Pydantic v2 usage in the repo (e.g. `parrot/stores/models.py`). Pydantic v2 syntax:
`model_config = ConfigDict(...)`, `Field(default_factory=...)`.

### Key Constraints
- Pydantic v2 only. `frozen=True` on `EvalTask`. `extra="allow"` where the spec specifies it.
- No blocking I/O, no logic — data only.
- Keep import-time side-effect free (no DB, no network).

---

## Acceptance Criteria

- [ ] `from parrot.eval import EvalTask, Trajectory, EvalResult, EvalDataset, MetricScore` resolves.
- [ ] `EvalTask` is frozen (mutation raises `ValidationError`).
- [ ] A `Trajectory` round-trips through `.model_dump()` / `.model_validate()`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/eval/test_models.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/eval/models.py`

---

## Test Specification

```python
import pytest
from pydantic import ValidationError
from parrot.eval import EvalTask, Trajectory, EvalResult, MetricScore

def test_eval_task_frozen():
    t = EvalTask(task_id="t1", inputs={"q": "hi"})
    with pytest.raises(ValidationError):
        t.task_id = "x"

def test_trajectory_roundtrip():
    tr = Trajectory(task_id="t1", attempt=1)
    assert Trajectory.model_validate(tr.model_dump()).attempt == 1

def test_eval_result_holds_scores():
    tr = Trajectory(task_id="t1", attempt=1)
    r = EvalResult(task_id="t1", attempt=1, scores=[MetricScore(name="m", value=1.0)],
                   passed=True, trajectory=tr)
    assert r.passed and r.scores[0].value == 1.0
```

---

## Agent Instructions

Standard SDD flow: read the spec, verify the contract, set index status `in-progress`, implement per
scope, run tests + ruff, move this file to `sdd/tasks/completed/`, set index `done`, fill the note.

---

## Completion Note

Implemented all Pydantic v2 models from spec §2: EvalTask (frozen), ToolCallRecord, TurnRecord, TokenUsage, Trajectory, MetricScore, EvalResult, EvalDataset. All 6 unit tests pass. Ruff clean.

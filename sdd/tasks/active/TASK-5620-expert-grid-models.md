# TASK-5620: Scope-grid and stage models (ExpertStageConfig, ScopeGrid, ScopeMatch, ScopeGridError)

**Feature**: FEAT-890 — Expert stages, dispatch modes, generic gate host and SDD expert delegation
**Spec**: `sdd/specs/expert-stages-and-delegation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: TASK-5612
**Assigned-to**: unassigned

---

## Context

Spec §2 Data Models, Modules 4–5. Pure data models shared by the stage node, compiler and SDD consult.

---

## Scope

- Create `parrot/experts/grid/models.py` with `ExpertStageConfig`, `ScopeMatch(projects, tags)`, `ScopeGrid`, `ScopeGridError` + `ScopeGridErrorCode` (UNKNOWN_EXPERT, CAPABILITY_MISMATCH, UNKNOWN_GATE_KIND, CYCLE, INVALID).
- Validators: `subagent` ⇒ exactly one expert; `experts` non-empty; stage names unique within a grid.
- `grid/__init__.py` exports.

**NOT in scope**: Loader/compiler (TASK-5625).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/grid/__init__.py` | CREATE | exports |
| `packages/ai-parrot/src/parrot/experts/grid/models.py` | CREATE | models |
| `packages/ai-parrot/tests/experts/test_grid_models.py` | CREATE | tests |

---

## Codebase Contract

> Verified against `6adcc8976e` (dev). Re-check line numbers before editing.

### Verified Imports
```python
from parrot.bots.flows.core.gates import GateSpec  # TASK-5612
```

### Existing Signatures to Use
```python
# none — this task only creates new modules
```

### Does NOT Exist
- ~~`parrot.flows.dev_loop` imports inside `parrot/bots/flows/core/gates/` or `parrot/experts/`~~ — forbidden (spec Decisions `gate-core-independent-of-dev-loop`).
- ~~HelixDB client / `HelixGateStore`~~ — no client in the repo; spec §8 Q1 open — do NOT implement.
- ~~`ExpertManifest.stage`~~, ~~`RosterSeat.tier`~~, ~~`WikiSource.remember`~~, ~~`DecisionService.propose`/`.record`~~ — do not exist.


---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/experts/grid/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/experts/grid/models.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/experts/test_grid_models.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Conventions: `.claude/rules/codebase-conventions.md` (Pydantic v2, Google docstrings, `self.logger`, async I/O, no print).
- Worktree tests need `PYTHONPATH=packages/ai-parrot/src` (plus `packages/ai-parrot-integrations/src` / `packages/ai-parrot-tools/src` when touched).

---

## Implementation Blueprint

### Steps (in order)
1. Create files.
2. Fill validators.
3. Tests for each validator.

### Blocks

```python
# packages/ai-parrot/src/parrot/experts/grid/models.py  (CREATE)
"""Scope grid models (FEAT-890 M5)."""
from __future__ import annotations
from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from parrot.bots.flows.core.gates import GateSpec

StageMode = Literal["subagent", "pipeline", "mob", "inline"]

class ExpertStageConfig(BaseModel):
    """One stage of a scope."""
    model_config = ConfigDict(extra="forbid")
    stage: str
    experts: list[str] = Field(min_length=1)
    mode: StageMode
    gate: GateSpec | None = None
    synthesis: str | None = None
    strict: bool = False
    conductor: str | None = None   # inline mode only: agent name of the conductor
    # FILL IN: model_validator — subagent ⇒ len(experts)==1; inline ⇒ conductor required

class ScopeMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projects: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

class ScopeGrid(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: str
    description: str = ""
    match: ScopeMatch | None = None
    stages: list[ExpertStageConfig] = Field(min_length=1)
    # FILL IN: unique stage names

class ScopeGridErrorCode(str, Enum):
    UNKNOWN_EXPERT = "UNKNOWN_EXPERT"
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
    UNKNOWN_GATE_KIND = "UNKNOWN_GATE_KIND"
    CYCLE = "CYCLE"
    INVALID = "INVALID"

class ScopeGridError(Exception):
    def __init__(self, code: ScopeGridErrorCode, message: str) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code = code
```
**Why**: `conductor` is the one field the spec skeleton implies for inline mode (a conductor agent receives experts' layers).

### FILL IN checklist
- [ ] validators
- [ ] tests

---

## Acceptance Criteria

- [ ] Models validate as specified.

## Validation Commands
- `pytest packages/ai-parrot/tests/experts/test_grid_models.py -q`

---

## Agent Instructions

1. Verify the Codebase Contract before writing code; fix stale entries in this file first.
2. Implement only the files listed above.
3. Run `ruff check --fix` on touched files and the Validation Commands.
4. Commit code, then close the task with `parrot sdd task close TASK-5620 expert-stages-and-delegation verified`.

---

## Completion Note

*(Agent fills this in when done)*

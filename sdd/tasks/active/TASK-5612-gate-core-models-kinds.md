# TASK-5612: Gate core — models, errors, kind registry and GateStore protocol

**Feature**: FEAT-890 — Expert stages, dispatch modes, generic gate host and SDD expert delegation
**Spec**: `sdd/specs/expert-stages-and-delegation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2.1 / Module 1. First half of the generic gate host: the data model and kind registry that every other gate task imports. Must not import dev-loop (spec Decisions).

---

## Scope

- Create package `parrot.bots.flows.core.gates` with `models.py` (`GateSpec`, `GateRecord`, `PreReviewVerdict`, `GateEvent`, `GateError` + `GateErrorCode`), `kinds.py` (`register_gate_kind`, `is_registered`, `registered_kinds`) and the `GateStore` Protocol.
- Export the public names from `gates/__init__.py`.
- Write unit tests for model validation and the kind registry.

**NOT in scope**: GateHost (TASK-5613), stores (TASK-5614/5615), dev-loop adapter (TASK-5616).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/gates/__init__.py` | CREATE | public exports |
| `packages/ai-parrot/src/parrot/bots/flows/core/gates/models.py` | CREATE | models, errors, GateStore protocol |
| `packages/ai-parrot/src/parrot/bots/flows/core/gates/kinds.py` | CREATE | string gate-kind registry |
| `packages/ai-parrot/tests/flows/gates/__init__.py` | CREATE | test package |
| `packages/ai-parrot/tests/flows/gates/test_gate_models.py` | CREATE | unit tests |

---

## Codebase Contract

> Verified against `6adcc8976e` (dev). Re-check line numbers before editing.

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field  # third-party, already a dependency
```

### Existing Signatures to Use
```python
# none from parrot — this package is a leaf (must not import parrot.flows.dev_loop)
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
      "path": "packages/ai-parrot/src/parrot/bots/flows/core/gates/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/flows/core/gates/models.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/flows/core/gates/kinds.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/gates/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/gates/test_gate_models.py",
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
1. Create `models.py` exactly as the block — the field names are fixed by spec §2 Data Models.
2. Create `kinds.py`; fill the registration body.
3. Create `__init__.py` re-exporting every public name.
4. Write tests: extra field rejected, frozen, kind idempotency + conflict, unknown kind lookup.

### Blocks

```python
# packages/ai-parrot/src/parrot/bots/flows/core/gates/models.py  (CREATE)
"""Generic gate data model (FEAT-890 M1). Must not import parrot.flows.dev_loop."""
from __future__ import annotations
from enum import Enum
from typing import Literal, Protocol, runtime_checkable
from pydantic import BaseModel, ConfigDict, Field

GateStatusValue = Literal["pending", "approved", "rejected", "expired"]

class GateErrorCode(str, Enum):
    UNKNOWN_KIND = "UNKNOWN_KIND"
    GATE_KIND_CONFLICT = "GATE_KIND_CONFLICT"
    NOT_FOUND = "NOT_FOUND"
    NOT_PENDING = "NOT_PENDING"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"

class GateError(Exception):
    """Typed gate failure carrying a GateErrorCode."""
    def __init__(self, code: GateErrorCode, message: str) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code = code

class GateSpec(BaseModel):
    """What to gate on; kind must be registered (kinds.py)."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: str
    title: str
    instructions: str = ""
    questions: list[str] = Field(default_factory=list)
    ttl_seconds: int | None = None
    on_expiry: Literal["fail", "approve"] = "fail"
    pre_review: str | None = None  # expert slug with the "review" capability

class PreReviewVerdict(BaseModel):
    """Advisory output of a pre_review expert — never resolves a gate (AC4)."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    expert: str
    recommendation: Literal["approve", "reject", "unsure"]
    summary: str
    error: str = ""

class GateRecord(BaseModel):
    """Persisted gate state."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    gate_id: str
    kind: str
    owner: str
    status: GateStatusValue = "pending"
    spec: GateSpec
    payload_ref: str = ""
    opened_at: float
    expires_at: float | None = None
    resolved_by: str = ""
    resolved_at: float | None = None
    comment: str = ""
    answers: dict[str, str] = Field(default_factory=dict)
    pre_review: PreReviewVerdict | None = None

class GateEvent(BaseModel):
    """Lifecycle event emitted by GateHost."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["opened", "resolved", "expired"]
    record: GateRecord

@runtime_checkable
class GateStore(Protocol):
    """Persistence for gate records (Redis, SQLite; HelixDB deferred — spec §8 Q1)."""
    async def put(self, record: GateRecord) -> None: ...
    async def get(self, gate_id: str) -> GateRecord | None: ...
    async def pending(self, owner: str | None = None) -> list[GateRecord]: ...
```
**Why**: frozen models make every state change an explicit `model_copy(update=...)` in GateHost, mirroring dev-loop's `_Frozen` actions; string `kind` keeps dev-loop Literals out (codex S9).

```python
# packages/ai-parrot/src/parrot/bots/flows/core/gates/kinds.py  (CREATE)
"""Process-wide registry of string gate kinds."""
from __future__ import annotations
from .models import GateError, GateErrorCode

_KINDS: dict[str, str] = {}

def register_gate_kind(kind: str, *, description: str = "") -> None:
    """Register ``kind``; idempotent for an identical description, GATE_KIND_CONFLICT otherwise."""
    # FILL IN: reject empty/whitespace kind with ValueError; conflict check — bounded by spec §3 M1 skeleton

def is_registered(kind: str) -> bool:
    """Return True when ``kind`` was registered."""
    return kind in _KINDS

def registered_kinds() -> dict[str, str]:
    """Return a copy of the registry."""
    return dict(_KINDS)
```
**Why**: dev-loop registers its six legacy kinds here (TASK-5616), experts register theirs; nothing hard-codes a Literal.

```python
# packages/ai-parrot/src/parrot/bots/flows/core/gates/__init__.py  (CREATE) — re-export models.py and kinds.py public names in __all__
```

### FILL IN checklist
- [ ] `register_gate_kind` body (empty kind → ValueError; same kind + different description → GateError(GATE_KIND_CONFLICT))
- [ ] test bodies

---

## Acceptance Criteria

- [ ] `GateSpec`, `GateRecord`, `PreReviewVerdict`, `GateEvent`, `GateStore`, `GateError` importable from `parrot.bots.flows.core.gates`.
- [ ] No module in the package imports `parrot.flows.dev_loop` (AC2).
- [ ] Tests pass.

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/gates/test_gate_models.py -q`

---

## Agent Instructions

1. Verify the Codebase Contract before writing code; fix stale entries in this file first.
2. Implement only the files listed above.
3. Run `ruff check --fix` on touched files and the Validation Commands.
4. Commit code, then close the task with `parrot sdd task close TASK-5612 expert-stages-and-delegation verified`.

---

## Completion Note

*(Agent fills this in when done)*

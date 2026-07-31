---
type: Wiki Overview
title: 'TASK-1418: `StateBackend` + `DictStateBackend` (`parrot/eval/sandbox/state.py`)'
id: doc:sdd-tasks-completed-task-1418-state-backend-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The resettable, in-memory world state owned by the sandbox (NOT by any toolkit).
  Generic
relates_to:
- concept: mod:parrot.eval
  rel: mentions
---

# TASK-1418: `StateBackend` + `DictStateBackend` (`parrot/eval/sandbox/state.py`)

**Feature**: FEAT-217 — Generic Agent Evaluation Harness
**Spec**: `sdd/specs/generic-evaluation-harness.spec.md`
**Spec section**: §2 + §3 Module 4 (brainstorm §13.1)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1417
**Assigned-to**: unassigned

---

## Context

The resettable, in-memory world state owned by the sandbox (NOT by any toolkit). Generic
collection store keyed as `{collection: {entity_id: {field: value}}}`. It is the input to
state-based scoring and must produce **deterministic snapshots** for stable diffs/baselines.

---

## Scope

- Create `parrot/eval/sandbox/state.py` with:
  - `StateBackend(ABC)` — `async reset(seed_state)`, `async snapshot()`.
  - `DictStateBackend(StateBackend)` — dict-of-dicts store with CRUD-ish ops the fake drivers (later
    tasks) will call: `create(collection, entity_id, fields)`, `get`, `update`, `delete`,
    `list(collection)`, `query(collection, predicate)`.
  - `reset(seed_state)` loads a deep copy of `seed_state` (or empties the store if `None`).
  - `snapshot()` returns a **deep copy** with collections AND entity keys sorted (deterministic).
- Export from `parrot/eval/__init__.py`.

**NOT in scope**: `InMemoryStateSandbox`, `ToolkitBinder`, fake drivers (TASK-1419/1420).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/eval/sandbox/state.py` | CREATE | StateBackend + DictStateBackend |
| `packages/ai-parrot/src/parrot/eval/__init__.py` | MODIFY | Export the backends |
| `packages/ai-parrot/tests/eval/test_state_backend.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import copy
from abc import ABC, abstractmethod
from typing import Any, Callable
```

### Does NOT Exist
- ~~Any shared `parrot` in-memory store / fake repository~~ — tests use `unittest.mock` only; build
  this from scratch.

---

## Implementation Notes

### Key Constraints
- **Determinism is an acceptance criterion**: sort collection names and entity ids in `snapshot()`;
  return deep copies so callers cannot mutate internal state (no aliasing).
- Async API (`reset`/`snapshot` are `async`) even though the work is in-memory — keeps the `Sandbox`
  contract uniform.
- No logging noise on hot paths; `self.logger` for reset/seed events only.

### Pattern to Follow
```python
async def snapshot(self) -> dict[str, Any]:
    return {c: {eid: copy.deepcopy(self._data[c][eid]) for eid in sorted(self._data[c])}
            for c in sorted(self._data)}
```

---

## Acceptance Criteria

- [ ] `from parrot.eval import DictStateBackend` resolves.
- [ ] `snapshot()` is deterministic: two calls after the same mutations are equal and key-sorted.
- [ ] `snapshot()` is a deep copy: mutating the result does not change the backend.
- [ ] CRUD ops behave (`create`/`get`/`update`/`delete`/`list`/`query`).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/eval/test_state_backend.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/eval/sandbox/state.py`

---

## Test Specification

```python
import pytest
from parrot.eval import DictStateBackend

async def test_reset_and_snapshot_deepcopy():
    b = DictStateBackend()
    await b.reset({"issues": {"P-1": {"assignee": None}}})
    snap = await b.snapshot()
    snap["issues"]["P-1"]["assignee"] = "x"
    assert (await b.snapshot())["issues"]["P-1"]["assignee"] is None  # no aliasing

async def test_snapshot_sorted_deterministic():
    b = DictStateBackend()
    await b.reset(None)
    await b.create("issues", "P-2", {"a": 1})
    await b.create("issues", "P-1", {"a": 2})
    assert list((await b.snapshot())["issues"].keys()) == ["P-1", "P-2"]
```

---

## Agent Instructions

Standard SDD flow: verify the contract, set index `in-progress`, implement, run tests + ruff, move to
`completed/`, set index `done`, fill the note.

---

## Completion Note

*(Agent fills this in when done)*

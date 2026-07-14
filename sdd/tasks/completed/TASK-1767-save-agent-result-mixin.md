# TASK-1767: PersistenceMixin._save_agent_result() — incremental per-agent writes

**Feature**: FEAT-306 — Crew Per-Agent Result Persistence & Deterministic Execution Document
**Spec**: `sdd/specs/crew-per-agent-result-persistence.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1765
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** of FEAT-306. `PersistenceMixin` persists only the crew-level result
(`_save_result`). This task adds the sibling method `_save_agent_result()` that writes one
document per finished agent to collection `crew_agent_results`, with the same fire-and-forget,
warning-only, lazily-resolved-backend semantics. The crew wiring that CALLS it is TASK-1769.

---

## Scope

- Add to `packages/ai-parrot/src/parrot/bots/flows/core/storage/persistence.py`:
  ```python
  async def _save_agent_result(
      self,
      node_result: Any,
      *,
      execution_id: str,
      method: str,
      collection: str = "crew_agent_results",
      **kwargs: Any,
  ) -> None:
  ```
  Behaviour:
  - Return immediately when `getattr(self, "_persist_results", True)` is `False` OR
    `getattr(self, "_persist_agent_results", True)` is `False`.
  - Resolve backend via existing `self._ensure_result_storage()`.
  - Build the per-agent document (spec §2 shape):
    ```python
    {
        "execution_id": execution_id,
        "crew_name": getattr(self, "name", "unknown"),
        "method": method,
        "node_id": getattr(node_result, "node_id", None) or getattr(node_result, "agent_id", "unknown"),
        "node_execution_id": getattr(node_result, "execution_id", None),
        "timestamp": time.time(),
        "result": node_result.to_dict() if hasattr(node_result, "to_dict") else str(node_result),
        **kwargs,   # user_id, session_id
    }
    ```
    with `data.setdefault("user_id", "unknown")` (mirror `_save_result` line 101).
  - `await storage.save(collection, data)` inside try/except → `logger.warning` only.
- Update the module docstring's host-attribute list to mention the optional
  `self._persist_agent_results` flag (default `True` via getattr).
- Extend `tests/bots/flows/core/storage/test_persistence_mixin.py` with the new tests.

**NOT in scope**: calling this method from crew.py (TASK-1769), `fetch()` (TASK-1766),
`CrewExecutionDocument` (TASK-1768), changes to `_save_result` / `aclose` / factory.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/persistence.py` | MODIFY | Add `_save_agent_result()` + docstring update |
| `tests/bots/flows/core/storage/test_persistence_mixin.py` | MODIFY | Unit tests for the new method |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact references. Verify anything not listed before using it.

### Verified Imports
```python
from parrot.bots.flows.core.storage import PersistenceMixin      # storage/__init__.py re-export
from parrot.bots.flows.core.storage.backends import ResultStorage, get_result_storage  # backends/__init__.py
from parrot.bots.flows.core.result import NodeResult             # result.py:39
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/core/storage/persistence.py
class PersistenceMixin:                                            # line 29
    def _ensure_result_storage(self) -> ResultStorage              # line 45 — REUSE, do not duplicate
    async def _save_result(self, result, method, *, collection="crew_executions", **kwargs) -> None  # line 65
        # THE TEMPLATE for the new method:
        #   opt-out check       line 86:  if not getattr(self, "_persist_results", True): return
        #   logger fallback     line 89:  getattr(self, "logger", logging.getLogger(__name__))
        #   document build      lines 92-101 (crew_name via getattr(self, "name", "unknown"))
        #   save + warn-only    lines 102-108
    async def aclose(self) -> None                                 # line 110 — drains _persist_tasks; NO changes needed

# NodeResult.to_dict() — created by TASK-1765 (verify it exists in result.py before starting;
# if TASK-1765 is not yet merged into the worktree branch, STOP and implement it first)

# tests/bots/flows/core/storage/test_persistence_mixin.py
class _FakeStorage(ResultStorage):                                 # line 11 — capture-saves fake, REUSE
class _Host(PersistenceMixin):                                     # line 25 — minimal host, REUSE/extend
```

### Does NOT Exist
- ~~`PersistenceMixin._save_agent_result()`~~ — THIS TASK creates it.
- ~~`self._persist_agent_results` initialised anywhere~~ — no host sets it yet (TASK-1769
  will); that is WHY the getattr default must be `True`.
- ~~`_save_agent_result` scheduling its own `create_task`~~ — it is a plain awaitable like
  `_save_result`; the CALLER (crew.py, TASK-1769) owns task creation and `_persist_tasks`.
- ~~A `NodeResult` import inside persistence.py~~ — keep the method duck-typed
  (`hasattr(node_result, "to_dict")`), matching `_save_result`'s treatment of `result`.

---

## Implementation Notes

### Pattern to Follow
Mirror `_save_result` (persistence.py:65-108) line-for-line in structure: opt-out → logger →
try → resolve storage → build dict → save → except → warning. Same docstring style.

### Key Constraints
- Double opt-out: `_persist_results` (global) AND `_persist_agent_results` (granular) — both
  read via `getattr(..., True)`.
- Failures NEVER propagate — warning log only.
- Async throughout; Google-style docstring + type hints.

### References in Codebase
- `persistence.py:65-108` — the exact template.
- `tests/bots/flows/core/storage/test_persistence_mixin.py:49-115` — existing test style
  (`_Host`, `_FakeStorage`, monkeypatched `get_result_storage`).

---

## Acceptance Criteria

- [ ] `_save_agent_result` skips (no backend contact) when `_persist_results=False`
- [ ] `_save_agent_result` skips when `_persist_agent_results=False` (host attr set)
- [ ] Persisted document matches the §2 per-agent shape (execution_id, node_id, node_execution_id, result dict)
- [ ] Backend exception → `logger.warning`, no raise
- [ ] Host without `_persist_agent_results` attr behaves as enabled (getattr default)
- [ ] All tests pass: `pytest tests/bots/flows/core/storage/test_persistence_mixin.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/flows/core/storage/persistence.py`

---

## Test Specification

```python
# tests/bots/flows/core/storage/test_persistence_mixin.py — ADD:

async def test_save_agent_result_skips_when_globally_disabled():
    host = _Host(persist=False)
    await host._save_agent_result(_node("a1"), execution_id="E1", method="run_sequential")
    assert host._result_storage is None  # backend never resolved

async def test_save_agent_result_skips_when_granularly_disabled():
    host = _Host(persist=True)
    host._persist_agent_results = False
    ...

async def test_save_agent_result_document_shape(monkeypatch):
    # NodeResult(node_id="a1", ...) → saved doc has execution_id="E1",
    # node_id="a1", node_execution_id=<uuid>, collection == "crew_agent_results",
    # result == node.to_dict()

async def test_save_agent_result_swallows_backend_exceptions(monkeypatch, caplog):
    ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1765 must be in `sdd/tasks/completed/` (NodeResult.to_dict exists)
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/crew-per-agent-result-persistence.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1767-save-agent-result-mixin.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-14
**Notes**: Added `_save_agent_result()` to `PersistenceMixin`, mirroring
`_save_result()`'s structure exactly (double opt-out via
`getattr(self, "_persist_results", True)` and
`getattr(self, "_persist_agent_results", True)`, lazy backend resolution,
warning-only failure). Updated the module docstring to document the new
optional `self._persist_agent_results` host attribute. Extended
`test_persistence_mixin.py` with 7 new tests covering both opt-outs,
document shape, user_id default, host-without-attr behaviour, exception
swallowing, and str() fallback. 16/16 tests pass; `ruff check` clean.

**Deviations from spec**: none

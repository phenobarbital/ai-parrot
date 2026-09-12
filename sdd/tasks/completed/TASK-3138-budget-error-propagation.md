# TASK-3138: `BudgetError` Propagation Through Tool Execution, Tool Manager and Model Switching

**Feature**: FEAT-550 — Cumulative Question Token Budgets for Bedrock and Mantle
**Spec**: `sdd/specs/token-budget-bedrock.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3132
**Assigned-to**: unassigned

---

## Context

Module 3 "Exception rule" (spec §3 Module 3): "Explicitly re-raise `BudgetError` before
broad tool error conversion, malformed-arguments catches, `InvokeError` wrapping, or
fallback selection." Today:

- `AbstractTool.execute` converts any exception into a `ToolResult` (`tools/abstract.py:1143`),
  letting `AuthorizationRequired` / `CredentialRequired` through by explicit `isinstance`.
- `ToolManager.execute_tool_call` serializes any exception into model input (`tools/manager.py:2274`).
- `ModelSwitchingMixin._fallback_call` switches to the secondary on any exception
  (`model_switching.py:215`); `_contrastive_call` gathers with `return_exceptions=True`
  and treats a failed branch as "the other one survives" (`:267-300`).

A child ledger denial (`BudgetExhausted`) or any other `BudgetError` raised inside a tool
(e.g. a tool invoking a child bot) must reach the answer **owner**, never become a
tool-success result, never trigger fallback to another model, and never let the other
contrastive branch keep spending.

This task touches no file shared with TASK-3136/3137 → `parallel: true`.

---

## Scope

- `packages/ai-parrot/src/parrot/tools/abstract.py` — in `execute()`'s
  `except Exception as e:` (line 1143) add an `isinstance(e, BudgetError)` re-raise next to
  the existing `AuthorizationRequired` / `CredentialRequired` re-raises.
- `packages/ai-parrot/src/parrot/tools/manager.py` — in `execute_tool_call` add
  `except BudgetError: raise` **before** `except Exception as e:` (line 2274).
- `packages/ai-parrot/src/parrot/bots/mixins/model_switching.py`:
  - `should_switch_on()` returns `False` for `BudgetError` (never fall back on budget control);
  - `_fallback_call`: `except BudgetError: raise` before `except Exception as primary_err:`;
  - `_contrastive_call`: after the `CancelledError` checks, if either result is a
    `BudgetError`, re-raise it (primary's first) — do not return the surviving branch.
- Add `InvokeError` wrapping guard: `AbstractClient._handle_invoke_error` callers wrap
  everything (`except Exception as exc: raise self._handle_invoke_error(exc)` in both
  providers) — this task adds a **helper** on `AbstractClient`? **No** — that file is
  TASK-3136's; instead the provider tasks (TASK-3141/3143) add `except BudgetError: raise`
  in their `invoke()`; note it here as a cross-reference only.
- Tests: `packages/ai-parrot/tests/unit/clients/test_token_budget_boundaries.py` is owned by
  TASK-3136/3137; to stay parallel, create
  `packages/ai-parrot/tests/unit/tools/test_token_budget_propagation.py` for the tool/
  manager/mixin cases (spec §4 row "Exception propagation").

**NOT in scope**: bot boundary translation (TASK-3137), provider `invoke()` guards (TASK-3141/3143).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/abstract.py` | MODIFY | Re-raise `BudgetError` in `execute()` |
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | Re-raise `BudgetError` in `execute_tool_call()` |
| `packages/ai-parrot/src/parrot/bots/mixins/model_switching.py` | MODIFY | No fallback / contrastive merge on `BudgetError` |
| `packages/ai-parrot/tests/unit/tools/test_token_budget_propagation.py` | CREATE | Propagation tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against dev `755c61347` on 2026-09-11.

### Verified Imports
```python
from parrot.core.exceptions import BudgetError, BudgetExhausted   # TASK-3132
# tools/abstract.py: lazy imports inside except block already use `from ..auth.exceptions import AuthorizationRequired` (line 1148)
# tools/manager.py: `import asyncio` (:4), `from ..auth.exceptions import AuthorizationRequired` (:19)
# model_switching.py: `import asyncio` (:40), `from ...exceptions import ConfigError` (:46)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool(EventEmitterMixin, ABC):                                  # line 281
    async def execute(self, *args, **kwargs) -> ToolResult:                  # line 872
        ...
        except Exception as e:                                               # line 1143
            from ..auth.exceptions import AuthorizationRequired               # line 1148 ← anchor (1 occurrence)
            if isinstance(e, AuthorizationRequired): raise
            from ..auth.credentials import CredentialRequired as _CR
            if isinstance(e, _CR): raise

# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager(MCPToolManagerMixin):                                      # line 265
    async def execute_tool_call(self, content_block, permission_context=None) -> Dict[str, Any]:   # line 2253
        try:
            tool_result = await self.execute_tool(tool_name, tool_input, permission_context=permission_context)   # line 2272 ← anchor (1 occurrence)
            return {...}
        except Exception as e:                                               # line 2274
            return {"type": "tool_result", "tool_use_id": tool_id, "is_error": True, "content": str(e)}

# packages/ai-parrot/src/parrot/bots/mixins/model_switching.py
class ModelSwitchingMixin:                                                   # line 57
    def should_switch_on(self, error: Exception) -> bool:                    # line 153 ("switch on any exception except asyncio.CancelledError")
    async def _fallback_call(self, client, method, **llm_kwargs):            # line 204
        except asyncio.CancelledError: raise                                 # line 213
        except Exception as primary_err:                                     # line 215 ← anchor (1 occurrence)
    async def _contrastive_call(self, client, method, **llm_kwargs):         # line 259
        primary_res, secondary_res = await asyncio.gather(..., return_exceptions=True)   # line 267-271
        primary_failed = isinstance(primary_res, BaseException)              # line 277 ← anchor (1 occurrence)
```

### Does NOT Exist
- ~~`ToolResult.status == "budget_exhausted"`~~ — do NOT invent a tool status; budget control is an exception, not a result (spec §3 Module 3 exception rule).
- ~~`ToolManager.execute_tool` swallowing~~ — `execute_tool` (line 1608) classifies with `except BaseException … re-raised` (line 1661); it already re-raises. Only `execute_tool_call` (2274) converts. Do not edit `execute_tool`.
- ~~`ModelSwitchingMixin.should_switch_on` being consulted by `_contrastive_call`~~ — it is not; the contrastive guard must be explicit.
- ~~`BudgetError` in `parrot.exceptions`~~ — it lives in `parrot.core.exceptions`.

---

## Implementation Notes

### Pattern to Follow
```python
# tools/abstract.py — mirror the existing AuthorizationRequired escape hatch
from ..core.exceptions import BudgetError
if isinstance(e, BudgetError):
    raise  # budget control propagates to the answer owner (FEAT-550 §3 M3)
```

### Key Constraints
- Order matters in `_contrastive_call`: check `CancelledError` (existing), **then**
  `BudgetError` (new), then the existing failed/survivor logic. If the primary raised
  `BudgetError`, the secondary result (success or not) is discarded — the root performs
  one finalization (spec §3 Module 3 "drain siblings, and let the root perform one
  finalization"). Log at warning with both branch labels.
- `should_switch_on`: keep the docstring's contract but add `BudgetError` to the
  never-switch set; `_fallback_call` still gets an explicit `except BudgetError: raise`
  so a subclass overriding `should_switch_on` cannot re-enable fallback on budget control.
- `AbstractTool.execute` emits `ToolCallFailedEvent` before returning an error result;
  the `BudgetError` re-raise must happen **before** that emission (place it with the
  `AuthorizationRequired` check, which is also before the event).
- No change to `ToolResult`, no change to `execute_tool`.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/abstract.py:1143-1160` — the escape-hatch pattern to copy.
- `packages/ai-parrot/src/parrot/bots/mixins/model_switching.py:204-258` — fallback flow.

---

## Implementation Blueprint

### Steps (in order)
1. `tools/abstract.py` re-raise — *why*: a tool calling a child bot must not turn exhaustion into a tool success.
2. `tools/manager.py` re-raise — *why*: `execute_tool_call` would otherwise feed the error text back to the model as input.
3. `model_switching.py` three guards — *why*: fallback/contrastive must not bypass the ledger via another model.
4. Tests with stub tools and a stub mixin host.

### `packages/ai-parrot/src/parrot/tools/abstract.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            from ..auth.exceptions import AuthorizationRequired' packages/ai-parrot/src/parrot/tools/abstract.py)
# BEFORE — insert above `            from ..auth.exceptions import AuthorizationRequired` (verified: tools/abstract.py:1148)
            # FEAT-550 §3 M3: budget control is never converted into a ToolResult —
            # it propagates to the question's answer owner.
            from ..core.exceptions import BudgetError

            if isinstance(e, BudgetError):
                raise
```
**Why**: identical shape to the two existing escape hatches, placed first so no event/scrub code runs for budget control.

### `packages/ai-parrot/src/parrot/tools/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            tool_result = await self.execute_tool(tool_name, tool_input, permission_context=permission_context)' packages/ai-parrot/src/parrot/tools/manager.py)
# AFTER the `return {"type": "tool_result", ...}` line that follows that anchor and BEFORE `        except Exception as e:` (verified: manager.py:2272-2274) — insert:
        except BudgetError:
            raise  # FEAT-550 §3 M3: never serialize budget control as model input
```
Add `from ..core.exceptions import BudgetError` next to `from ..auth.exceptions import AuthorizationRequired` (manager.py:19).
**Why**: `except` clauses are matched in order; the narrower clause must precede the broad one.

### `packages/ai-parrot/src/parrot/bots/mixins/model_switching.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        except Exception as primary_err:' packages/ai-parrot/src/parrot/bots/mixins/model_switching.py)
# BEFORE — insert above `        except Exception as primary_err:` (verified: model_switching.py:215)
        except BudgetError:
            raise  # FEAT-550: budget control never triggers cross-provider fallback
```
```python
# occurrences: 1 (verified: grep -c '        primary_failed = isinstance(primary_res, BaseException)' packages/ai-parrot/src/parrot/bots/mixins/model_switching.py)
# BEFORE — insert above `        primary_failed = isinstance(primary_res, BaseException)` (verified: model_switching.py:277)
        # FEAT-550 §3 M3: an exhausted branch cannot be bypassed via the other branch —
        # surface budget control to the root, which performs the single finalization.
        for _label, _res in (("primary", primary_res), ("secondary", secondary_res)):
            if isinstance(_res, BudgetError):
                self.logger.warning("Contrastive call: %s branch raised %s — propagating budget control", _label, type(_res).__name__)
                raise _res
```
```python
# FILL IN: in should_switch_on (model_switching.py:153-168) add `if isinstance(error, BudgetError): return False` next to the
#          CancelledError check — bounded by spec §3 M3 "fallback selection". Add `from ...core.exceptions import BudgetError`
#          next to `from ...exceptions import ConfigError` (model_switching.py:46).
```
**Why**: three independent gates because each path can be reached without the others (mixin subclasses override `should_switch_on`; contrastive never calls it).

### `packages/ai-parrot/tests/unit/tools/test_token_budget_propagation.py` (CREATE)
```python
"""FEAT-550 M3 — BudgetError propagation through tools, manager and model switching (spec §4 'Exception propagation')."""
from __future__ import annotations

import pytest

from parrot.core.exceptions import BudgetExhausted
from parrot.tools.abstract import AbstractTool
from parrot.tools.manager import ToolManager


class _ExhaustingTool(AbstractTool):
    name = "exhaust"
    description = "raises budget exhaustion"

    async def _execute(self, **kwargs):
        raise BudgetExhausted("child out of budget")


class _PlainFailingTool(AbstractTool):
    name = "boom"
    description = "raises a plain error"

    async def _execute(self, **kwargs):
        raise RuntimeError("boom")


class TestToolPropagation:
    async def test_abstract_tool_execute_reraises_budget_error(self):
        with pytest.raises(BudgetExhausted):
            await _ExhaustingTool().execute()

    async def test_plain_error_still_converted(self):
        result = await _PlainFailingTool().execute()
        assert result.status != "success"

    async def test_manager_execute_tool_call_reraises(self):
        # FILL IN: ToolManager() + register_tool(_ExhaustingTool()); execute_tool_call({"name": "exhaust", "input": {}, "id": "t1"}) raises BudgetExhausted;
        #          the plain tool returns {"is_error": True,...}. Bounded by spec §3 M3.
        raise NotImplementedError


class TestModelSwitching:
    async def test_fallback_not_triggered_on_budget_error(self):
        # FILL IN: build a minimal ModelSwitchingMixin host (see tests for model_switching if present, else stub execute_llm_call on a base class)
        #          whose primary raises BudgetExhausted; assert secondary is never awaited and the error propagates. Bounded by spec §3 M3.
        raise NotImplementedError

    async def test_contrastive_reraises_budget_error_instead_of_survivor(self):
        # FILL IN: primary returns AIMessage, secondary raises BudgetExhausted -> _contrastive_call raises BudgetExhausted. Bounded by spec §3 M3.
        raise NotImplementedError
```
**Why**: spec §4 row "Exception propagation: Tool conversion, malformed-tool handling, invoke wrapping, fallback and contrastive gather do not swallow budget control" (invoke wrapping is asserted in the provider tasks).

### FILL IN checklist
- [ ] `model_switching.py::should_switch_on` — `BudgetError` → `False`; bounded by spec §3 M3
- [ ] `test_token_budget_propagation.py` FILL IN bodies — look for an existing model-switching test host under `packages/ai-parrot/tests/` first (`grep -rl ModelSwitchingMixin packages/ai-parrot/tests`) and reuse its fixture

---

## Acceptance Criteria

- [ ] `AbstractTool.execute` re-raises any `BudgetError`; other exceptions still become `ToolResult`
- [ ] `ToolManager.execute_tool_call` re-raises `BudgetError`; other exceptions still serialize as `is_error` results
- [ ] `_fallback_call` re-raises `BudgetError` without calling the secondary; `should_switch_on(BudgetError(...))` is `False`
- [ ] `_contrastive_call` re-raises a `BudgetError` from either branch instead of returning the survivor
- [ ] `pytest packages/ai-parrot/tests/unit/tools/test_token_budget_propagation.py -q` passes; existing `tests/unit/tools` and any model-switching tests pass
- [ ] `ruff check` clean on the three modified modules

---

## Test Specification

Scaffold above. Add `test_authorization_required_still_escapes` to prove the existing escape hatch order is intact.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §3 Module 3 "Exception rule"
2. **Check dependencies** — TASK-3132 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-run the four `grep -c` anchors
4. **Update status** in `sdd/tasks/index/token-budget-bedrock.json` → `"in-progress"`
5. **Implement** from the Blueprint
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3138-budget-error-propagation.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker orchestrator (parrot-sdd-coder pool: codex-spark CLI arg error on attempt 1,
qwen timed out on attempt 2 — no code was produced by either; orchestrator implemented directly as attempt 3)
**Date**: 2026-09-11
**Notes**: Added the `BudgetError` re-raise guard to `AbstractTool.execute()`'s except block
(placed before the existing `AuthorizationRequired`/`CredentialRequired` escape hatches, per the
blueprint), `except BudgetError: raise` before the broad `except Exception` in
`ToolManager.execute_tool_call`, and three independent guards in `ModelSwitchingMixin`:
`should_switch_on()` returns `False` for `BudgetError`, `_fallback_call` re-raises `BudgetError`
before calling the secondary, and `_contrastive_call` re-raises a `BudgetError` from either branch
(primary checked first) instead of returning the surviving branch. Created
`packages/ai-parrot/tests/unit/tools/test_token_budget_propagation.py` reusing the
`FakeClient`/`SwitchingBot`/`make_bot` fixture pattern from
`tests/bots/test_model_switching_mixin.py` (per the task's own instruction to look for an
existing model-switching test host first) — 8 tests covering tool re-raise, manager re-raise,
the `AuthorizationRequired` escape-hatch-still-works regression check, `should_switch_on` veto,
fallback non-triggering, and both contrastive scenarios (one branch raises, both raise —
primary wins).
Verified: `pytest packages/ai-parrot/tests/unit/tools/test_token_budget_propagation.py -v` → 8
passed; `pytest packages/ai-parrot/tests/unit/tools -q` → 127 passed / 7 pre-existing failures
confirmed identical on `dev` HEAD (test-order pollution in the infographic/adhoc-dataset suites,
unrelated to this task — same 7 tests fail in isolation from `dev` too); `pytest packages/ai-parrot/
tests/bots/test_model_switching_mixin.py -q` → 21 passed (no regressions); `ruff check` clean on
`tools/abstract.py`, `bots/mixins/model_switching.py` and the new test file; `tools/manager.py`'s
only ruff finding (`F821 Undefined name AbstractToolkit` at a forward-ref type hint, one line
shifted by my added import) is confirmed pre-existing on `dev` HEAD, not introduced by this task.

**Deviations from spec**: none

Seat: codex-spark (attempt 1, CLI `--ask-for-approval` arg incompatibility, 1.1s) → qwen (attempt 2,
timed out after 552.7s, no code produced) → sdd-worker orchestrator (attempt 3, implemented directly)
· Backend: codex → nova → orchestrator (Claude Sonnet 5) · Attempts: 2 (pool, both non-productive) + 1
(orchestrator) · Duration: 1.1s + 552.7s (pool) + orchestrator implementation/test-authoring time ·
Tokens: pool attempts produced no billable output (dispatch-level failures).

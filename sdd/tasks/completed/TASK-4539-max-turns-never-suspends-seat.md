# TASK-4539: A max_turns overrun never suspends the seat

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:d88684064bdb`

---

## Context

Observed during FEAT-709's own implementation run. TASK-4536 (9 declared files) drove the `glm` seat
(nova, `zai.glm-4.7-flash`) into the dev-loop turn cap and raised

```
DispatchExecutionError: LLM code dispatch exceeded max_turns=60;
the forced final_output turn did not recover a result (...)
```

after 61 turns and 2.08M input tokens. `_classify_failure_reason` has no branch for a turn-budget
overrun, so the `error_class in ("DispatchExecutionError", "DispatchOutputValidationError")` arm falls
through to `return "dispatch_error"` and `_classify_and_suspend` suspends the whole seat for 30 minutes
(`coder-suspension:f4a10399fae37cea3f61e6ae`, `source=engine`). The seat and its Mantle endpoint were
healthy throughout; the retry went to `qwen`, which hit the same cap and was salvaged incomplete.

A turn-budget overrun is a task-size / budget property, not a seat fault. Suspending on it removes a
healthy model from the roster for every *other* task in the run.

Related: this branch already added per-task `max_turns` scaling (`TestProfileTurnScaling` in
`test_engine_dispatch.py`), which makes the overrun rarer but does not change what happens when it occurs.

---

## Scope

- `_classify_failure_reason`: a `DispatchExecutionError` whose message reports a turn-budget overrun is
  **non-suspendable** — return `None`, so `_classify_and_suspend` logs and returns without touching the pool.
- The check runs before the generic `dispatch_error` fallback and must not weaken the existing timeout
  detection (`"TimeoutError"` / `"wall-clock cap"` still classify as `timeout` and still suspend).
- Retry behaviour is unchanged: the task still fails this attempt and still goes through the normal ladder
  (`_select_retry_seat`); only the suspension is dropped.

**NOT in scope**: `max_turns` defaults or the per-file scaling; the task-tier gate (TASK-4540); any other
`_classify_failure_reason` arm.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `_classify_failure_reason` max_turns arm |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` | MODIFY | regression tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `feat-FEAT-709-language-agnostic-validation-runners` @ `616450ad0` (2026-10-20).

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
def _classify_failure_reason(self, error: str, error_class: str, outcome: Optional[str] = None) -> Optional[str]   # line 3680
async def _classify_and_suspend(self, ctx, pool, execution_id, task, seat, attempt_rec, error, job_id) -> None      # after it
#   reason = self._classify_failure_reason(error, attempt_rec.error_class)
#   if reason is None:  ->  logs "Non-suspendable failure" and returns (no pool.suspend)

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
#   raise DispatchExecutionError(
#       f"LLM code dispatch exceeded max_turns={profile.max_turns}; "
#       f"the forced final_output turn did not recover a result ({salvage_error})")
```

### Anchor
```python
# occurrences: 1 (verified: grep -c '            return "dispatch_error"' .../engine.py)
            return "dispatch_error"
```

### Does NOT Exist
- ~~a `max_turns` branch in `_classify_failure_reason`~~ — added here
- ~~a `turn_budget` suspension reason~~ — the overrun must not produce a reason at all

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._classify_failure_reason",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._classify_and_suspend"
  ]
}
```

---

## Implementation Notes

- Match on the stable fragment `"exceeded max_turns="`, which the dispatcher always emits for this failure.
  Do not match on the bare word `max_turns` — it appears in unrelated diagnostics.
- Order matters: the timeout checks come first (a dispatch that both timed out and exhausted turns is a
  timeout and still suspends), then the max_turns arm, then `invalid_output` / `dispatch_error`.
- `_classify_and_suspend` needs no change — returning `None` already takes its non-suspendable path.

---

## Implementation Blueprint

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY)
```python
# INSIDE `if error_class in ("DispatchExecutionError", "DispatchOutputValidationError"):`
# AFTER the wrapped-timeout check, BEFORE `if error_class == "DispatchOutputValidationError":`
            if "exceeded max_turns=" in error:
                return None
```

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` (MODIFY)
```python
# FILL IN: three cases —
#   1. _classify_failure_reason(<the real max_turns message>, "DispatchExecutionError") is None
#   2. _classify_and_suspend with that error never calls pool.suspend
#   3. a wall-clock-cap DispatchExecutionError still returns "timeout" (no regression)
```

### FILL IN checklist
- [ ] `_classify_failure_reason` max_turns arm
- [ ] three regression tests

---

## Acceptance Criteria

- [ ] `_classify_failure_reason` returns `None` for the real max_turns message with `"DispatchExecutionError"`.
- [ ] `_classify_and_suspend` with that error does not call `pool.suspend`.
- [ ] A `DispatchExecutionError` carrying `"wall-clock cap"` still returns `"timeout"`; a
      `DispatchOutputValidationError` still returns `"invalid_output"`; an unrelated
      `DispatchExecutionError` still returns `"dispatch_error"`.
- [ ] `ruff check` clean on every touched `.py` file

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py -q`

---

## Test Specification

Tests live in the file declared above; write the cases named in Acceptance Criteria. sdd_coder tests reuse
the hermetic-root fixture in `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py`.

---

## Agent Instructions

1. Work in the feature worktree, never on `dev`.
2. Verify the Codebase Contract first.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Stage only the files listed above.
5. Close with `scripts/sdd/close_task.sh TASK-4539 language-agnostic-validation-runners verified`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

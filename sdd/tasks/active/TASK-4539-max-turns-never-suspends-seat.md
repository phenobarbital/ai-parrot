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
overrun, so the `error_class in ("DispatchExecutionError", "DispatchOutputValidationError")` arm fell
through to `return "dispatch_error"` and `_classify_and_suspend` suspended the whole seat for 30 minutes
(`coder-suspension:f4a10399fae37cea3f61e6ae`, `source=engine`). The seat and its Mantle endpoint were
healthy throughout; the retry went to `qwen`, which hit the same cap and was salvaged incomplete.

A turn-budget overrun is a task-size / budget property, not a seat fault. Suspending on it removes a
healthy model from the roster for every *other* task in the run. This sits in the same area as the
spec's existing rule that validation reds never suspend (S8), which is why it rides with FEAT-709.

Related: PR #1748 added per-task `max_turns` scaling (`DEV_LOOP_LLM_TURNS_PER_FILE`), which makes the
overrun rarer but does not change what happens when it still occurs.

---

## Scope

- `_classify_failure_reason`: a `DispatchExecutionError` whose message reports a turn-budget overrun is
  **non-suspendable** — return `None`, so `_classify_and_suspend` logs and returns without touching the pool.
- The check runs before the generic `dispatch_error` fallback and must not weaken the existing timeout
  detection (`"TimeoutError"` / `"wall-clock cap"` still classify as `timeout` and still suspend).
- Retry behaviour is unchanged: the task still fails this attempt and still goes through the normal ladder
  (`_select_retry_seat`); only the suspension is dropped.

**NOT in scope**: changing `max_turns` defaults or the per-file scaling (PR #1748); the task-tier gate
(TASK-4532); any other `_classify_failure_reason` arm.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `_classify_failure_reason` max_turns arm |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` | MODIFY | regression tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `aef30d6b4` (2026-10-20). Re-run `grep -c` on every anchor before editing.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
def _classify_failure_reason(self, error: str, error_class: str, outcome: Optional[str] = None) -> Optional[str]   # line 3403
async def _classify_and_suspend(self, ctx, pool, execution_id, task, seat, attempt_rec, error, job_id) -> None     # line 3476
#   :3499  reason = self._classify_failure_reason(error, attempt_rec.error_class)
#   :3500  if reason is None:  ->  logs "Non-suspendable failure" and returns (no pool.suspend)

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
#   :650-653  raise DispatchExecutionError(
#                 f"LLM code dispatch exceeded max_turns={profile.max_turns}; "
#                 f"the forced final_output turn did not recover a result ({salvage_error})")
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
  timeout and still suspends), then the max_turns arm, then the existing `invalid_output` /
  `dispatch_error` arms.
- `_classify_and_suspend` needs no change — returning `None` already takes its non-suspendable path, which
  logs `"Non-suspendable failure for %s on %s"` and returns before `effective_key`/`pool.suspend`.

---

## Implementation Blueprint

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY)
```python
# INSIDE the `if error_class in ("DispatchExecutionError", "DispatchOutputValidationError"):` block,
# AFTER the wrapped-timeout check and BEFORE `if error_class == "DispatchOutputValidationError":`
            # A turn-budget overrun is a task-size/budget property, not a seat fault: the model and
            # its endpoint are healthy, the task simply needed more turns than the profile allowed.
            # Suspending here pulled a healthy seat out of the roster for every other task in the run
            # (issue:d88684064bdb). The attempt still fails and still goes through the retry ladder.
            if "exceeded max_turns=" in error:
                return None
```
**Why**: this is the only arm that currently reaches `dispatch_error` for a turn overrun.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` (MODIFY)
```python
# FILL IN: three cases, using the engine fixture already in this module —
#   1. _classify_failure_reason(<the real max_turns message>, "DispatchExecutionError") is None
#   2. _classify_and_suspend with that error never calls pool.suspend (spy/fake pool)
#   3. a wall-clock-cap DispatchExecutionError still returns "timeout" (no regression)
```

### FILL IN checklist
- [ ] `_classify_failure_reason` max_turns arm
- [ ] three regression tests

---

## Acceptance Criteria

- [ ] `_classify_failure_reason("LLM code dispatch exceeded max_turns=60; the forced final_output turn did not recover a result (...)", "DispatchExecutionError")` returns `None`.
- [ ] `_classify_and_suspend` with that error does not call `pool.suspend` and logs the non-suspendable path.
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

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug language-agnostic-validation-runners --feature-id FEAT-709`), never on `dev`.
2. Verify the Codebase Contract first; fix stale entries in this file before coding.
3. Implement from the blueprint; complete every `FILL IN`; never change a fixed signature or path.
4. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Stage only the files listed above.
6. Close with `scripts/sdd/close_task.sh TASK-4539 language-agnostic-validation-runners verified`, then fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

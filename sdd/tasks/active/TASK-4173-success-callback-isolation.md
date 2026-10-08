# TASK-4173: Isolate a raising success_callback so deliveries and send_result still run

**Feature**: FEAT-644 — SchedulerManager base — target-agnostic scheduler (db | redis | code backends) with AgentSchedulerManager as a subclass
**Spec**: `sdd/specs/scheduler-manager-base.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**discovered_from**: issue:37f02d3c2474

---

## Context

Promoted from ledger issue `issue:37f02d3c2474` (bug/minor, discovered during
FEAT-635) by `/sdd-fix`, which routed it to the open FEAT-644 (spec G8 / AC17
already own the issue):

> Scheduler: raising `success_callback` skips all delivery callbacks and `send_result`.

`AgentSchedulerManager._handle_job_success`
(`packages/ai-parrot-server/src/parrot/scheduler/manager.py:761`) calls the
user's `success_callback` **outside** any try/except, before the delivery loop.
If it raises, the exception escapes to `_process_job_success`'s safety net
(`manager.py:916`), so none of the registry callbacks run, `send_result` is never
sent, and no delivery outcome is stamped.

This task lands the fix on the **current** manager, ahead of the FEAT-644
rewrite, so the bug is closed now. The rewrite (TASK-4157 `_process_job_success`
in `base.py`, spec §3 line 154) must preserve this behaviour; its regression test
(`test_success_callback_raise_does_not_skip_delivery`, spec §4) is migrated with
the rest of `test_delivery_outcomes.py` by TASK-4160.

---

## Scope

- Wrap the `success_callback` invocation in `_handle_job_success` in its own
  try/except; on error log it and append a `failed` outcome named
  `success_callback` as the **first** outcome, then continue to the delivery
  callbacks and `send_result`.
- Add `test_success_callback_raise_does_not_skip_delivery` (and a non-raising
  counterpart) to `test_delivery_outcomes.py`.

**NOT in scope**: renaming `agent_name` → `target_name` (TASK-4153);
`base.py` / `_process_job_success` (TASK-4157); `_process_job_success`'s
outer safety net; any other test file.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | Isolate `success_callback` inside `_handle_job_success` |
| `packages/ai-parrot-server/tests/scheduler/test_delivery_outcomes.py` | MODIFY | Regression tests for issue 37f02d3c2474 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import inspect  # verified: manager.py:12 (already imported)
from unittest.mock import AsyncMock, MagicMock, patch  # verified: test_delivery_outcomes.py:4
from parrot.scheduler.manager import AgentSchedulerManager  # verified: test_delivery_outcomes.py:8
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/scheduler/manager.py
class AgentSchedulerManager:
    @staticmethod
    def _callback_outcome(name: str, response: Any = None,
                          error: Optional[BaseException | str] = None) -> Dict[str, Any]:  # line 733
        # error is not None -> {"callback": name, "status": "failed", "error": str(error)}
    async def _handle_job_success(self, schedule_id: str, agent_name: str, result: Any,
                                  success_callback: Optional[Callable],
                                  send_result: Optional[Dict[str, Any]],
                                  callbacks: Optional[List[Dict[str, Any]]] = None,
                                  ) -> List[Dict[str, Any]]:  # line 761
        # lines 772-775 (the defect):
        #     if success_callback:
        #         callback_result = success_callback(result)
        #         if inspect.isawaitable(callback_result):
        #             await callback_result
    async def _send_result_email(self, schedule_id, agent_name, result, send_result) -> Optional[Dict[str, Any]]:  # line 803

# packages/ai-parrot-server/tests/scheduler/test_delivery_outcomes.py
@pytest.fixture
def manager(): ...                       # line 11 — AgentSchedulerManager() without infrastructure
def _cb(response=None, exc=None): ...    # line 36 — AsyncMock fake callback
async def test_handle_job_success_isolates_callbacks(manager): ...  # line 41 — style to copy
```

### Does NOT Exist
- ~~`self._run_success_callback`~~ / ~~`_safe_call`~~ helper — inline the try/except.
- ~~a `"success_callback"` key in `_aggregate_delivery_status`~~ — it reduces by
  `status` only; the new outcome needs no change there.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/scheduler/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/scheduler/test_delivery_outcomes.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._handle_job_success",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._callback_outcome"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Catch `Exception` with the same `# noqa: BLE001` style the delivery loop uses.
- Log with `self.logger.error(..., exc_info=True)` — the user callback is user code.
- A successful `success_callback` adds **no** outcome (keeps existing tests and
  `delivery_status` semantics unchanged).

---

## Implementation Blueprint

### Steps (in order)
1. Replace lines 772-775 of `manager.py` with the guarded block below — *why*: a
   user hook must not suppress the configured deliveries.
2. Append the two tests to `test_delivery_outcomes.py` after
   `test_send_result_failure_recorded` — *why*: pins the issue's regression.
3. Run the Validation Commands and `ruff check` on both files.

### `packages/ai-parrot-server/src/parrot/scheduler/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'callback_result = success_callback(result)' manager.py)
# REPLACE lines 772-775 (`if success_callback:` … `await callback_result`) with:
        if success_callback:
            try:
                callback_result = success_callback(result)
                if inspect.isawaitable(callback_result):
                    await callback_result
            except Exception as exc:  # noqa: BLE001 - a user hook must not skip deliveries
                self.logger.error(
                    "success_callback for schedule %s raised: %s", schedule_id, exc, exc_info=True
                )
                outcomes.append(self._callback_outcome("success_callback", error=exc))
```
**Why**: the delivery loop and `send_result` below already isolate themselves;
the user hook was the only unguarded step.

### `packages/ai-parrot-server/tests/scheduler/test_delivery_outcomes.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def test_send_result_failure_recorded')
# INSERT after the body of test_send_result_failure_recorded (before the parametrize block):
async def test_success_callback_raise_does_not_skip_delivery(manager):
    """A raising success_callback is recorded and deliveries still run (issue 37f02d3c2474)."""
    # FILL IN: success_callback = AsyncMock(side_effect=RuntimeError("hook")); one registry
    #          callback via patch build_scheduler_callback -> _cb(response={"status": "sent"});
    #          _send_result_email patched to {"status": "success"}
    # FILL IN: assert outcome callbacks == ["success_callback", "send_email_report", "send_result"],
    #          statuses == ["failed", "sent", "sent"], error mentions "hook", both deliveries awaited


async def test_success_callback_ok_adds_no_outcome(manager):
    """A successful sync success_callback is called with the result and adds no outcome."""
    # FILL IN: success_callback = MagicMock(return_value=None); no callbacks/send_result;
    #          assert outcomes == [] and success_callback.assert_called_once_with("res")
```

### FILL IN checklist
- [ ] Both test bodies, following `test_handle_job_success_isolates_callbacks`.

---

## Acceptance Criteria

- [ ] A raising `success_callback` yields a first outcome `{"callback": "success_callback", "status": "failed", ...}`
      and registry callbacks + `send_result` still run.
- [ ] A non-raising `success_callback` behaves as before (no outcome added).
- [ ] All existing tests in `test_delivery_outcomes.py` and `packages/ai-parrot/tests/test_schedules.py` still pass.
- [ ] `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/scheduler/test_delivery_outcomes.py -q`
- `pytest packages/ai-parrot/tests/test_schedules.py -q`

---

## Test Specification

See the blueprint test stubs.

---

## Agent Instructions

1. Work in the FEAT-644 worktree `.claude/worktrees/feat-FEAT-644-scheduler-manager-base`.
2. Update this task to `"in-progress"` in `sdd/tasks/index/scheduler-manager-base.json`.
3. Implement from the blueprint, run the Validation Commands, commit only the two listed files.
4. Close with `scripts/sdd/close_task.sh TASK-4173 scheduler-manager-base verified`.
5. Fill in the Completion Note and commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none

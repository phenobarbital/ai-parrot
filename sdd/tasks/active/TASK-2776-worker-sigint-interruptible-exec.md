# TASK-2776: Make worker execution safely interruptible with SIGINT

**Feature**: FEAT-521 - REPL Worker Idle/Busy Detection & Memory Guardrails
**Spec**: `sdd/specs/repl-worker-idle-detection-memory-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 supplies the child-side half of interrupt-before-kill while preserving the existing request/response envelope and namespace.

## Scope

- Catch `KeyboardInterrupt` around `WorkerNamespace.exec()` execution and return `ExecResult(status="error")` with a bounded interruption message in both `result` and `error`.
- Preserve any namespace mutations completed before interruption and report partial-side-effect risk.
- Make `serve()` survive SIGINT while blocked in `read_frame()` and safely complete/retry the response write path when interruption races frame output.
- Log idle/racing interrupts without emitting unsolicited protocol frames.
- Leave rlimits, `PR_SET_PDEATHSIG`, framing, and `_execute_code()` untouched.

**NOT in scope**: host-side signal delivery/deadlines, observer wiring, memory enforcement, or tests owned by TASK-2781.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repl_worker/worker.py` | MODIFY | Convert SIGINT/KeyboardInterrupt into safe bounded behavior |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.tools.repl_worker.protocol import ExecRequest, ExecResult, ErrorResponse, read_frame, write_frame
```

### Existing Signatures to Use

```python
# worker.py:182-200
class WorkerNamespace:
    def exec(self, request: ExecRequest) -> ExecResult: ...

# worker.py:273-327
def serve(config: WorkerConfig, in_stream: BinaryIO, out_stream: BinaryIO,
          output_dir: Optional[str] = None, repl_kwargs: Optional[dict[str, Any]] = None,
          started_at: float | None = None) -> None: ...

def apply_rlimits(config: WorkerConfig) -> None: ...  # worker.py:108
def set_parent_death_signal() -> None: ...  # worker.py:81
```

### Does NOT Exist

- ~~Any SIGINT handler in `worker.py`~~ does not exist; only a local `signal` import for `PR_SET_PDEATHSIG` exists.
- ~~`ExecResult.status == "interrupted"`~~ must not be introduced; status stays `"error"`.
- ~~Unsolicited interrupt/heartbeat frames~~ must not be introduced.

## Implementation Notes

- `KeyboardInterrupt` derives from `BaseException`, so existing `except Exception` branches do not catch it.
- Keep exactly one response per request and preserve control-pipe ordering.
- The returned message must mention the exceeded deadline, namespace preservation, and possible partial side effects.
- Do not modify `PythonREPLTool._execute_code`.

## Acceptance Criteria

- [ ] SIGINT during a pure-Python loop yields a bounded `ExecResult(status="error")` and the worker stays alive.
- [ ] Previously bound variables remain accessible after interruption.
- [ ] SIGINT while idle does not kill the worker; the next ping succeeds.
- [ ] Existing framing and worker startup behavior remain unchanged.
- [ ] `black` and `ruff` pass.

## Test Specification

TASK-2781 creates real-subprocess tests for mid-exec and idle SIGINT behavior.

## Agent Instructions

Re-read `worker.py:182-200` and `worker.py:273-327`. Preserve all FEAT-380/500 startup and framing behavior while adding only explicit `KeyboardInterrupt` paths.

---

## Completion Note

**Completed by**: unassigned
**Date**: pending
**Notes**: pending

**Deviations from spec**: none

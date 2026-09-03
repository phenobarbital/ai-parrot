# TASK-2777: Wire observer lifecycle and diagnostics into WorkerHandle

**Feature**: FEAT-521 - REPL Worker Idle/Busy Detection & Memory Guardrails
**Spec**: `sdd/specs/repl-worker-idle-detection-memory-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2774, TASK-2775
**Assigned-to**: unassigned

---

## Context

This is the lifecycle/diagnostics half of spec §3 Module 4. It attaches `ProcessObserver` to each child and makes observer state authoritative for bootstrap and death reporting without yet changing deadline signalling.

## Scope

- Add `observer: ProcessObserver | None` and its task to `WorkerHandle`.
- Start observation immediately after stdio draining, mark requests busy/idle around `_roundtrip()`, and deterministically stop observation in `kill()`.
- Route hard RSS callback through `_kill_process()` and record the observer memory verdict.
- Consult `observer.memory_verdict` before stderr heuristics in `_classify_death()`.
- Include `observer.describe()` in namespace-loss and bootstrap failure details.
- Use observer history for CPU progress/stall bootstrap diagnostics and honor `bootstrap_stall_ms` early failure.
- Append exactly one soft-pressure hint line to the next string or dict result, preserving `{status,result,error}` keys.

**NOT in scope**: SIGINT delivery or two-stage deadline orchestration (TASK-2778), pool behavior, or test implementation.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py` | MODIFY | Own observer, diagnostics, memory classification, result hint, teardown |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.tools.repl_worker.observer import ProcessObserver
from parrot.tools.repl_worker.protocol import ExecResult, NamespaceLossError, ReadyResponse, WorkerConfig
```

### Existing Signatures to Use

```python
class WorkerHandle:  # handle.py:151
    async def start(self) -> None: ...  # :276
    async def _await_ready(self) -> None: ...  # :329
    async def _send(self, request: Any, timeout_s: float, *, lethal: bool = False) -> Any: ...  # :504
    async def _kill_process(self) -> None: ...  # :617
    async def _classify_death(self) -> str: ...  # :661
    def _build_loss_error(self, cause: str, detail: str) -> dict[str, Any]: ...  # :691
    async def execute(self, code: str, debug: bool = False) -> str | dict: ...  # :714
    async def kill(self) -> None: ...  # :855
```

### Does NOT Exist

- ~~`WorkerHandle.observer`~~, ~~`_observer_task`~~, and ~~`_in_flight`~~ do not exist yet.
- ~~Deterministic observer memory verdict classification~~ does not exist; stderr markers are currently first.
- ~~Observer-based bootstrap diagnostics and result memory suffixes~~ do not exist.

## Implementation Notes

- Follow `_stdio_task` ownership: create in `start()`, cancel/await in `kill()`, never leak exceptions.
- Busy state must cover only the ordered round-trip and clear in `finally` on every outcome.
- Hard-breach kill must use `_lifecycle_executor` through existing `_kill_process()` and avoid request-lock deadlocks.
- Preserve current pending-reply behavior and all non-lethal namespace timeouts.

## Acceptance Criteria

- [ ] Every spawned worker owns exactly one observer task until killed.
- [ ] Busy/idle state clears on success, timeout, cancellation, and pipe failure.
- [ ] Hard RSS death is classified as `memory` without stderr markers.
- [ ] Bootstrap and loss errors name verdict and last observation.
- [ ] Soft warning is appended once to the next result and does not alter envelope shape.
- [ ] Killing a handle leaves no observer/readiness/stdio task behind.

## Test Specification

TASK-2781 covers lifecycle/bootstrap diagnostics; TASK-2782 covers soft/hard memory behavior.

## Agent Instructions

Confirm TASK-2774 and TASK-2775 are completed. Re-verify all listed methods because this file is shared with TASK-2778; keep changes narrowly within observer ownership and diagnostics.

---

## Completion Note

**Completed by**: unassigned
**Date**: pending
**Notes**: pending

**Deviations from spec**: none

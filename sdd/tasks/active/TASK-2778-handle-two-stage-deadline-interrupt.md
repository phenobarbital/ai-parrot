# TASK-2778: Add two-stage deadline interruption and in-process verdict

**Feature**: FEAT-521 - REPL Worker Idle/Busy Detection & Memory Guardrails
**Spec**: `sdd/specs/repl-worker-idle-detection-memory-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2776, TASK-2777
**Assigned-to**: unassigned

---

## Context

This is the deadline/interrupt half of spec §3 Module 4. It attempts namespace-preserving SIGINT before the existing deterministic SIGKILL fallback and gives in-process callers the same verdict surface.

## Scope

- Add `WorkerHandle.interrupt()` using `Popen.send_signal(SIGINT)` on `_lifecycle_executor`.
- On execution deadline, send SIGINT only for a live busy worker when `interrupt_before_kill` is enabled, then wait up to `interrupt_grace_ms` for its already-ordered reply.
- Return the worker's interrupted error response without clearing `known_vars` when a reply arrives.
- Fall back to SIGKILL and timeout loss error within `deadline_ms + interrupt_grace_ms + _DEADLINE_GRACE_MS` when interruption fails.
- Preserve disabled/non-POSIX behavior and every non-exec timeout contract.
- Add `InProcessHandle.verdict() -> "unavailable"` and debug-log ignored observer/memory settings through the existing construction path without adding in-process enforcement.

**NOT in scope**: observer implementation, child-side interrupt handling, pool memory pressure, or tests owned by TASK-2781.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py` | MODIFY | Interrupt API and two-stage deadline |
| `packages/ai-parrot/src/parrot/tools/repl_worker/inprocess.py` | MODIFY | Uniform unavailable verdict |
| `packages/ai-parrot/src/parrot/tools/pythonrepl.py` | MODIFY | Log ignored worker guardrails for in-process mode if required by construction path |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio  # handle.py:21
from parrot.tools.repl_worker.protocol import ExecRequest, ExecResult, WorkerConfig
```

### Existing Signatures to Use

```python
class WorkerHandle:
    async def _send(self, request: Any, timeout_s: float, *, lethal: bool = False) -> Any: ...
    async def _kill_process(self) -> None: ...
    async def execute(self, code: str, debug: bool = False) -> str | dict: ...

class InProcessHandle:  # inprocess.py:51
    async def execute(self, code: str, debug: bool = False) -> str | dict: ...
    async def kill(self) -> None: ...

_DEADLINE_GRACE_MS = 250  # handle.py:135
```

### Does NOT Exist

- ~~`WorkerHandle.interrupt()`~~ does not exist.
- ~~`InProcessHandle.verdict()`~~ does not exist.
- ~~Per-snippet kill/measurement for in-process mode~~ is impossible and must not be added.

## Implementation Notes

- Signals use `_lifecycle_executor`, never the pipe executor.
- Avoid issuing SIGINT when the observer says settled/booting/unavailable or the process is already dead.
- Shield the pending reply so the first deadline does not cancel the executor future needed during interrupt grace.
- Preserve the strictly ordered single-reply control protocol.

## Acceptance Criteria

- [ ] Pure-Python runaway code returns interrupted error and keeps namespace.
- [ ] SIGINT-resistant code is killed by the bounded fallback and reports observer details.
- [ ] `interrupt_before_kill=False` preserves immediate kill behavior.
- [ ] Non-POSIX behavior remains functional with interrupt disabled.
- [ ] `InProcessHandle.verdict()` returns `"unavailable"`; no memory/interrupt enforcement is implied.

## Test Specification

TASK-2781 owns real-worker deadline, SIGKILL fallback, namespace preservation, idle signal, bootstrap, and in-process tests.

## Agent Instructions

Confirm TASK-2776 and TASK-2777 are completed. Re-read `_send`, `_kill_process`, and `execute` before editing; preserve deadline bounds and pending-reply cleanup.

---

## Completion Note

**Completed by**: unassigned
**Date**: pending
**Notes**: pending

**Deviations from spec**: none

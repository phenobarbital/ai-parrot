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

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-03
**Notes**: `WorkerHandle` now owns `self.observer: ProcessObserver | None` +
`self._observer_task`, created in `start()` right after `_stdio_task` and
torn down in `kill()` (cancel + await, mirroring `_ready_task`/`_stdio_task`
exactly). `_send()` brackets `_roundtrip()` with `observer.mark_busy()`/
`mark_idle()` via an outer `try/finally` so idle clears on success, timeout,
cancellation, and pipe failure alike (verified: `mark_idle()` always fires
regardless of which of the three `except` branches — or none — is taken).
`_on_observer_hard_breach()` is wired as the observer's `on_hard_breach`
callback and routes through `_kill_process()` on `_lifecycle_executor`, per
the existing kill-path convention. `_classify_death()` now consults
`observer.memory_verdict` before the stderr-marker heuristic, and
`_build_loss_error()` folds `observer.describe()` into every namespace-loss
detail. `execute()` appends `_soft_memory_hint()` (a new `_format_bytes()`
helper renders GiB/MiB) to the next string-typed `result`/`output` on a
soft breach, preserving the `{status,result,error}` envelope shape exactly.
`_await_ready()`'s `TimeoutError` branch replaced the old one-shot
`probe_process_state()` snapshot with a new `_describe_bootstrap_progress()`
helper reading `observer.cpu_progress()`/`last()` (spec: "no longer takes a
one-shot probe... reads the observer's ring"); a new `_watch_bootstrap_stall()`
background task (started only when `bootstrap_stall_ms > 0`) independently
polls the observer and calls the existing idempotent `_fail_ready()` to
resolve the bootstrap EARLIER on a sustained CPU-flat stall, without
touching `_await_ready()`'s own control flow — verified this races safely
and fails ~0.5s in against a `bootstrap_stall_ms=500` config (vs. a 30s
budget) with a message naming pid, elapsed stall, and the observer's
state/wchan. All four new behaviors (busy/idle wiring, hard-breach kill +
memory-first death classification, soft-hint + 90% hysteresis, early
bootstrap-stall failure) were verified end-to-end against real subprocess
workers since TASK-2781/2782 own the corresponding automated tests.

**Regression check**: ran the full `packages/ai-parrot/tests/repl_worker/`
suite before and after this change (via a scoped `git stash`): baseline is
46 failed / 73 passed / 11 errors (pre-existing `report_dir=tmp_path`
output_dir-guard breakage per spec §7 risks); after this change it is 47
failed / 72 passed / 11 errors — exactly one net-new failure,
`test_bootstrap_diagnostics.py::test_silent_child_reports_proc_state`,
which asserts the OLD one-shot-probe message format
(`"process: state=S"`). That test manually constructs a `WorkerHandle` and
calls `_await_ready()` directly WITHOUT `start()`, so it never gets an
`observer` — `_describe_bootstrap_progress()` correctly no-ops (returns
`""`) rather than crashing, but the message text it asserts on is now
stale by design (spec §3 Module 4: the one-shot probe is replaced, not
supplemented). Left `test_bootstrap_diagnostics.py` untouched — it is not
in this task's file list; **flagging for TASK-2781** ("covers
lifecycle/bootstrap diagnostics" per this task's Test Specification), which
should update that assertion to the new observer-derived format (or drive
the test handle through an observer-equipped bootstrap).

**Deviations from spec**: none — one documented, in-scope simplification
noted above (`test_silent_child_reports_proc_state` needs a TASK-2781
follow-up, not a deviation in `handle.py` itself).

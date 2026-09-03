# TASK-2781: Add worker interrupt and handle integration tests

**Feature**: FEAT-521 - REPL Worker Idle/Busy Detection & Memory Guardrails
**Spec**: `sdd/specs/repl-worker-idle-detection-memory-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2776, TASK-2777, TASK-2778
**Assigned-to**: unassigned

---

## Context

This task implements spec §3 Module 6 coverage for child SIGINT behavior, two-stage handle deadlines, observer diagnostics, namespace preservation, and in-process degradation.

## Scope

- Create real-worker tests for SIGINT during a pure-Python loop and while idle.
- Test deadline-first interrupt preserves a previously bound variable and returns no namespace-loss text.
- Test SIGINT-blocked worker fallback reaches SIGKILL within the configured bound and reports verdict/sample detail.
- Test bootstrap errors report booting/CPU progress and `bootstrap_stall_ms` can fail early.
- Test loss messages name computing or stalled state.
- Test `InProcessHandle.verdict() == "unavailable"` and ignored guardrails are logged.
- Update the runaway-loop E2E expectation from namespace reconstruction to namespace preservation.
- Add the observed long-running groupby/overhead integration case with a stable measurement strategy.

**NOT in scope**: hard/soft RSS tests, pool reserve/eviction tests, or implementation fixes outside dependency contracts.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/repl_worker/test_interrupt.py` | CREATE | Real child SIGINT tests |
| `packages/ai-parrot/tests/repl_worker/test_handle.py` | MODIFY | Deadline fallback, verdict, namespace tests |
| `packages/ai-parrot/tests/repl_worker/test_bootstrap_diagnostics.py` | MODIFY | Observer-backed bootstrap/stall tests |
| `packages/ai-parrot/tests/repl_worker/test_inprocess.py` | MODIFY | Unavailable verdict/degradation tests |
| `packages/ai-parrot/tests/repl_worker/test_integration.py` | MODIFY | Runaway preservation and observed groupby E2E |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.tools.repl_worker.handle import WorkerBootstrapError, WorkerHandle, probe_process_state
from parrot.tools.repl_worker.protocol import WorkerConfig
from parrot.tools.pythonrepl import PythonREPLTool
```

### Existing Signatures to Use

```python
# test_bootstrap_diagnostics.py:41
async def _await_ready_against_silent_child(executor, budget_ms: int) -> str: ...

# test_inprocess.py:30
def report_dir(tmp_path, monkeypatch): ...

# test_integration.py:28,34
async def _shutdown(tool: PythonREPLTool) -> None: ...
async def tool(tmp_path): ...

# test_handle.py existing classes
class TestDeadline: ...  # :64
class TestReadiness: ...  # :201
class TestConcurrencyRegressions: ...  # :378
```

### Does NOT Exist

- ~~`test_interrupt.py`~~ does not exist yet.
- ~~A reliable `time.sleep` SIGINT-ignore fixture~~ does not exist; use an explicit signal mask/handler as specified.
- ~~In-process process isolation~~ does not exist and must not be asserted.

## Implementation Notes

- Use real subprocesses for signal semantics and always kill/shutdown them in `finally`.
- Reuse the existing `report_dir`/`_shutdown` patterns to avoid output-dir guard failures.
- Use generous CI timing tolerance while still asserting the spec's absolute deadline bound.
- Skip POSIX-only signal assertions explicitly on Windows.

## Acceptance Criteria

- [ ] Interruptible deadline keeps worker and namespace alive.
- [ ] Ignored SIGINT reaches deterministic SIGKILL with verdict detail inside the bound.
- [ ] Idle SIGINT is harmless and next ping succeeds.
- [ ] Bootstrap stall diagnostics and early failure are covered.
- [ ] In-process mode reports unavailable without enforcement.
- [ ] Long groupby completes under observation and records overhead below 2% using a non-flaky benchmark method.
- [ ] All named test files pass.

## Test Specification

Implement the interrupt/handle cases listed in spec §4 plus `test_e2e_runaway_loop_keeps_namespace` and `test_e2e_long_groupby_completes_under_observation`.

## Agent Instructions

Confirm dependency tasks are completed. Re-read existing timing/concurrency tests before adding subprocess cases and preserve cleanup on assertion failures.

---

## Completion Note

**Completed by**: unassigned
**Date**: pending
**Notes**: pending

**Deviations from spec**: none

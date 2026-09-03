# TASK-2782: Add memory guardrail, pool pressure, and E2E tests

**Feature**: FEAT-521 - REPL Worker Idle/Busy Detection & Memory Guardrails
**Spec**: `sdd/specs/repl-worker-idle-detection-memory-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2777, TASK-2778, TASK-2779
**Assigned-to**: unassigned

---

## Context

This task implements spec §3 Module 6 coverage for deterministic RSS kills, soft hints, host reserve enforcement, spare eviction, aggregate telemetry, and pool restart behavior.

## Scope

- Test a real worker crossing the hard RSS limit is killed within one poll interval and classified `memory` without stderr markers.
- Test soft pressure appends exactly one hint to the next string/dict result and resets after hysteresis.
- Test acquire/prewarm behavior with monkeypatched host availability and finite/unlimited cgroup v2 values.
- Test pressure maintenance evicts prewarmed spares only.
- Test `memory_summary()`, aggregate INFO logging, and memory-aware restart logging.
- Add an E2E memory bomb that kills the worker rather than the host and verifies session restart on the next call.
- Preserve the unmodified integration return-envelope contract tests.

**NOT in scope**: synthetic observer verdict tests, interrupt-only tests, calibration documentation, or changing implementation behavior beyond reported defects.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/repl_worker/test_memory_guardrails.py` | CREATE | Soft/hard RSS and memory-bomb tests |
| `packages/ai-parrot/tests/repl_worker/test_pool.py` | MODIFY | Host reserve, cgroup, eviction, summary/log tests |
| `packages/ai-parrot/tests/repl_worker/test_integration.py` | MODIFY | Memory restart E2E and envelope regression assertion |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.tools.repl_worker.handle import WorkerHandle
from parrot.tools.repl_worker.pool import WorkerPool, WorkerPoolExhaustedError
from parrot.tools.repl_worker.protocol import WorkerConfig
from parrot.tools.pythonrepl import PythonREPLTool
```

### Existing Signatures to Use

```python
# test_pool.py:27
def worker_config(): ...

class TestWorkerPool: ...  # test_pool.py:36
class TestRestartLoopVisibility: ...  # :197

# test_integration.py:28
async def _shutdown(tool: PythonREPLTool) -> None: ...

# public API from TASK-2779
class WorkerPool:
    def memory_summary(self) -> dict[str, int]: ...
```

### Does NOT Exist

- ~~`test_memory_guardrails.py`~~ does not exist yet.
- ~~Existing host-reserve/cgroup test fixtures~~ do not exist.
- Do not depend on stderr text to assert the hard-memory cause.

## Implementation Notes

- Keep allocations bounded enough for CI and configure hard limits far below host memory.
- Assert the host process RSS delta stays below 100 MiB in the E2E case.
- Monkeypatch psutil/cgroup reads for deterministic reserve tests; do not depend on the runner's actual cgroup layout.
- Always shut down pools/workers in `finally`.

## Acceptance Criteria

- [ ] Hard limit produces cause `memory` with measured RSS within one poll interval.
- [ ] Soft hint and 90% re-arm semantics are covered for string and dict results.
- [ ] Reserve blocks spawn/prewarm but not existing sessions or spare consumption.
- [ ] Pressure kills spares and never bound sessions.
- [ ] Summary/log values reflect observer samples.
- [ ] E2E memory bomb leaves host healthy and next session call uses a restarted worker.
- [ ] Relevant tests and existing envelope tests pass.

## Test Specification

Implement the memory/pool cases from spec §4 and `test_e2e_memory_bomb_kills_worker_not_host`.

## Agent Instructions

Confirm dependency tasks are completed. Reuse existing real-worker fixtures and cleanup patterns; keep resource thresholds deterministic and safe for CI hosts.

---

## Completion Note

**Completed by**: unassigned
**Date**: pending
**Notes**: pending

**Deviations from spec**: none

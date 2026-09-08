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

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-03
**Notes**: Created `test_memory_guardrails.py` (8 tests, all real subprocess,
reusing the combined `report_dir` fixture pattern established in
TASK-2781): `TestHardLimit` (deterministic kill, cause `memory`, no stderr
dependence, `verdict=` folded in), `TestSoftLimit` (hint on a STRING
result, on the `result` field of a dict result — NOT the `error` field,
matching the exact spec wording "the next execute() result... gets a
trailing line" — and 90%-hysteresis clearing), `TestE2EMemoryBomb`
(host RSS delta < 100 MiB, session transparently restarted on the next
call). Discovered empirically that a freshly-booted worker's OWN baseline
RSS (pandas/numpy/matplotlib imported) is ~248 MiB — the initial 200 MiB
soft-limit test config was below that baseline and fired unconditionally;
retuned to 320 MiB soft / 150 MiB extra allocation (clears the baseline,
crosses the limit only after the deliberate allocation).

`test_pool.py`: added the SAME combined `report_dir` fixture (STATIC_DIR
module patch + env var) and applied it file-wide via a scoped
find/replace — brought the file's existing 16 tests from partial-pass to
16/16 as a direct side effect (matching TASK-2781's established pattern).
Added `TestCgroupV2Availability` (6 tests: finite/unlimited/missing/
malformed cgroup files via monkeypatched `Path` module attributes, plus
the psutil/cgroup min() combination), `TestHostMemoryReserve` (4: spawn
blocked at `acquire()`, prewarm skip with DEBUG log, reserve does NOT
block an existing session or consuming a spare), `TestPressureEviction`
(2: spares evicted/sessions untouched, no eviction above reserve), and
`TestMemoryTelemetry` (4: `memory_summary()` shape, aggregate INFO log
only when pressured, `_record_restart()`'s WARNING naming the memory
cause after 3 genuine hard-breach deaths). One fixture-usage bug caught
and fixed: `_top_up_prewarmed()` no-ops silently before `self._started`
is set — the reserve-skip test needed `pool._started = True` set directly
(bypassing the full `_ensure_started()` background-task machinery) to
reach the code path under test.

`test_integration.py`: added `test_e2e_memory_restart_preserves_envelope_contract`
to `TestE2E` — the memory-cause counterpart to TASK-2781's
`test_e2e_runaway_loop_keeps_namespace`, asserting the G5
`{status, result, error}` envelope shape is exactly preserved (AC9) and
the session transparently gets a restarted worker on the next call.

**Regression check**: ran `test_memory_guardrails.py` + `test_pool.py` +
`test_integration.py` together twice — 48/48 passed both times (no
flakiness). `ruff check` and `black --target-version py312` clean on all
3 touched files.

**Deviations from spec**: none.

# TASK-2775: Implement ProcessObserver sampling and verdicts

**Feature**: FEAT-521 - REPL Worker Idle/Busy Detection & Memory Guardrails
**Spec**: `sdd/specs/repl-worker-idle-detection-memory-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2774
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 introduces the host-side observation primitive that converts cheap process samples into booting, settled, computing, stalled, or unavailable verdicts and enforces RSS thresholds.

## Scope

- Create `observer.py` with the exact `ProcessObserver` API from spec §2.
- Sample CPU seconds, RSS, status, thread count, and Linux `/proc/<pid>/wchan` at `observer_poll_ms` into a bounded ring.
- Implement busy/idle marks, CPU-window progress, verdict derivation, last sample, and one-line descriptions.
- Implement soft-limit state with 90% re-arm hysteresis and a one-shot awaited hard-breach callback.
- Move `/proc` parsing from `handle.probe_process_state()` into a reusable observer helper; keep the existing wrapper behavior for compatibility.
- Ensure `run()` never leaks process-observation exceptions.

**NOT in scope**: starting the observer from `WorkerHandle`, signals, result suffixes, pool reserve checks, or tests owned by TASK-2780.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repl_worker/observer.py` | CREATE | Process sampling, ring, verdicts, RSS checks |
| `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py` | MODIFY | Leave `probe_process_state()` as a compatibility wrapper only |
| `packages/ai-parrot/src/parrot/tools/repl_worker/__init__.py` | MODIFY | Export `ProcessObserver` |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import psutil  # declared in packages/ai-parrot/pyproject.toml; spec verifies >=5.9
from parrot.tools.repl_worker.protocol import MemoryVerdict, ProcessSample, Verdict, WorkerConfig
```

### Existing Signatures to Use

```python
# handle.py:59-102
def probe_process_state(pid: int | None) -> str: ...

# spec §2, created by TASK-2774
class ProcessSample(BaseModel): ...
class MemoryVerdict(BaseModel): ...
Verdict = Literal["booting", "settled", "computing", "stalled", "unavailable"]
```

### Does NOT Exist

- ~~`parrot.tools.repl_worker.observer`~~ and ~~`ProcessObserver`~~ do not exist yet.
- ~~Any `psutil` usage under `repl_worker/`~~ does not exist yet.
- ~~Heartbeat frames~~ do not exist and must not be added.

## Implementation Notes

- `run()` is an owned async background loop; catch `NoSuchProcess`, `AccessDenied`, platform errors, and unexpected sampling errors without failing requests.
- Observation is host-side only; never write to the control pipe.
- Hard-limit callback execution must be idempotent even if multiple samples exceed the limit.
- Preserve `probe_process_state(None/non-Linux) == ""`.

## Acceptance Criteria

- [ ] The public API exactly matches spec §2 New Public Interfaces.
- [ ] Synthetic flat/rising CPU sequences yield settled/computing/stalled correctly.
- [ ] Soft pressure clears below 90% and can trigger a later episode.
- [ ] Hard callback is awaited once and records measured RSS/limit.
- [ ] Sampling failures produce `unavailable` or end quietly; `run()` never raises outward.
- [ ] Existing bootstrap probe callers remain compatible.

## Test Specification

TASK-2780 covers verdict transitions, exception containment, hysteresis, and hard callback invocation with fake sample streams.

## Agent Instructions

Confirm TASK-2774 is completed. Re-read `handle.py:59-102` before moving parsing and preserve its return string contract.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-03
**Notes**: Created `observer.py` with the exact `ProcessObserver` public API
from spec §2, plus reusable `/proc` parsing helpers (`read_proc_status`,
`read_proc_wchan`, `read_proc_cpu_seconds`) used both by the sampler and by
`handle.probe_process_state()`, which is now a thin compatibility wrapper
(exact same signature/return-value contract; all 6 pre-existing
`test_bootstrap_diagnostics.py` tests pass unmodified). Verdict derivation
uses a trailing `stall_window_ms` CPU-progress check gated by an explicit
`_busy_since` timestamp (set on the idle→busy `mark_busy()` transition) so
"stalled" requires the *current* busy period — not the ring's overall
historical span — to have lasted the full window; caught and fixed this via
manual synthetic-sample testing before committing. Soft-limit hysteresis
(90% re-arm) and the one-shot, run()-terminating hard-breach callback were
verified manually (real self-process sampling + synthetic ring
manipulation), including the "unavailable" paths (nonexistent pid,
simulated non-POSIX `os.name`) and never-raises behavior. The `"booting"`
verdict is derived from whether `mark_busy()`/`mark_idle()` has ever been
called (documented in the class docstring) since `ProcessObserver` has no
visibility into the `ReadyResponse` handshake by design (observation is
host-side/pipe-independent) — TASK-2777 wires the handle to call
`mark_idle()` once readiness resolves. Removed the now-unused `pathlib.Path`
import from `handle.py` (flagged by `ruff`) as a direct consequence of
relocating the parsing logic. `ruff check` and `black --target-version
py312` clean on all three touched files. Also fixed two pre-existing,
unrelated environment issues blocking any test run in this worktree (not
task-scoped changes — no tracked files touched): reinstalled a corrupted
`aiohttp-cors` install in the shared venv, and copied the gitignored,
pre-built Cython `.so` extensions from the main checkout into this worktree
(the `.pyx` sources are byte-identical; these are build artifacts, never
part of the task's file list).

**Deviations from spec**: none

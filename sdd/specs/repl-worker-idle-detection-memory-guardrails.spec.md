---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: REPL Worker Idle/Busy Detection & Memory Guardrails (`repl-worker-idle-detection-memory-guardrails`)

**Feature ID**: FEAT-521
**Date**: 2026-09-03
**Author**: Jesus Lara (jesuslarag@gmail.com) + Claude
**Status**: draft
**Target version**: next minor (ships with the next release from `dev`)
**Related**: `sdd/specs/sandbox-hardening.spec.md` (FEAT-380), `sdd/specs/bug-workerpool-repl.spec.md` (FEAT-500), `docs/repl-worker-sandbox.md`
**Inspiration**: [posit-dev/mcp-repl](https://github.com/posit-dev/mcp-repl) — "the server knows precisely when the interpreter is idle and has settled"; "on Unix, a memory guardrail kills the worker if it exceeds threshold"; interrupt keeps the session, reset escalates from a graceful window to forceful termination.

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

The FEAT-380 worker model gives `PythonREPLTool` exactly two signals about
a worker: **a reply frame arrived** or **the deadline expired**. Between
those two, the host is blind. Two concrete failure classes follow:

1. **Busy is indistinguishable from hung.** A legitimately long `merge`/
   `groupby` and a worker stuck on a kernel wait channel look identical
   until `deadline_ms` (60 s) fires — and then both get the same treatment:
   SIGKILL plus a namespace-loss error, so the LLM must rebuild every
   variable. This week's production incident (2026-09-03, `flex_dashboard`,
   `python_repl_pandas`) had the same shape at bootstrap: 30 s of silence,
   `stderr tail: <empty>`, and no way to say *where* the worker was. The
   post-FEAT-500 diagnostics pass added a one-shot `/proc` probe at the
   moment of the kill; nothing observes the worker *while* it runs.
2. **Memory is bounded by the wrong metric, and only in the child.**
   `RLIMIT_AS` (12 GiB, virtual address space, calibrated at 2× the observed
   peak) is the only memory guardrail. It says nothing about resident
   memory: a cross join that inflates RSS to 10 GiB stays under the VA
   limit while it drives the host into swap, and Linux's OOM killer then
   picks by badness — frequently the *server*, not the worker. When the
   worker does die, the cause is inferred from stderr substrings
   (`_MEMORY_MARKERS`), a heuristic that reports `"crash"` whenever the
   kernel killed the process silently. There is no soft warning the LLM
   could act on ("free what you no longer need") before the hard stop.

Both gaps have the same root: the host has no continuous, cheap
**observation** of the worker process. mcp-repl's two ideas — *know when
the interpreter is settled* and *a memory guardrail that kills at a
threshold* — map onto this model as a host-side process observer.

### Goals

- **G1 — Observe, continuously.** Every live `WorkerHandle` samples its
  child (CPU time, RSS, state/wchan, thread count) on a fixed interval from
  the host, from spawn until kill, with negligible overhead (< 0.1 ms per
  sample via `psutil`).
- **G2 — Busy vs hung is a first-class verdict.** From the samples the
  host derives `settled` (no in-flight request and flat CPU), `computing`
  (in-flight request and CPU advancing) and `stalled` (in-flight request,
  CPU flat for `stall_window_ms`). Every timeout, bootstrap failure and
  namespace-loss error names the verdict and the last sample.
- **G3 — Interrupt before kill.** On `deadline_ms` the host first sends
  SIGINT (the worker converts it into a bounded `interrupted` result and
  keeps its namespace), waits `interrupt_grace_ms`, and only then SIGKILLs.
  A namespace is lost only when the snippet cannot be interrupted.
- **G4 — Memory guardrails on the metric that matters.** Soft and hard
  RSS limits per worker, enforced by the host observer: soft → a one-line
  hint appended to the next result and a WARNING log; hard → deterministic
  kill with cause `"memory"` (no stderr heuristics), reported with the
  measured RSS.
- **G5 — Protect the host, not just the worker.** The pool refuses to
  spawn or prewarm when host available memory is below a reserve, evicts
  idle spares first under pressure, and logs aggregate worker RSS.
- **G6 — Same contract, richer messages.** `{status, result, error}` shapes,
  `NamespaceLossError` causes (`timeout|memory|crash`) and the `deadline_ms`
  guarantee (the caller is always answered by `deadline_ms +
  interrupt_grace_ms + grace`) are preserved; no caller has to branch.

### Non-Goals (explicitly out of scope)

- Embedding the interpreter in the host (mcp-repl's model). The
  spawn-only child process and the length-prefixed control pipe stay.
- Unsolicited worker→host frames on the control pipe (a "heartbeat"
  frame). The pipe is strictly request/response ordered (spec §7 of
  FEAT-500, "drain before write"); observation is host-side only so no
  protocol reordering is possible. A separate status pipe is deferred.
- Extending or elasticising `deadline_ms` based on the busy verdict. The
  deadline stays hard; the verdict changes *what is reported* and whether
  SIGINT is attempted first, not *when*.
- Memory or idle guardrails for `execution_mode="inprocess"`
  (`InProcessHandle`). That hatch runs on the host thread; nothing can be
  killed or measured per snippet. Documented as a limitation.
- Windows: the observer degrades to "unavailable" (no `/proc`, SIGINT
  semantics differ); rlimits were already POSIX-only (FEAT-380 AC16).
- Replacing `RLIMIT_AS`. It stays as the last-resort child-side backstop.

---

## 2. Architectural Design

### Overview

A new host-side component, **`ProcessObserver`** (`repl_worker/observer.py`),
is owned by each `WorkerHandle` and started in `start()` right after the
stdio drain task. It runs an `asyncio` loop that every
`observer_poll_ms` (default 500) reads one `ProcessSample` from
`psutil.Process(pid)` — `cpu_times().user+system`, `memory_info().rss`,
`status()`, `num_threads()` — plus `/proc/<pid>/wchan` on Linux (reusing
`probe_process_state`'s parsing), and keeps a bounded ring of samples.

From the ring and the handle's own "in-flight request" flag (set/cleared
around `_roundtrip()` in `_send()`), the observer exposes a **verdict**:

| Verdict | Condition |
|---|---|
| `booting` | no `ReadyResponse` yet |
| `settled` | no in-flight request, CPU delta over the window ≈ 0 |
| `computing` | in-flight request and CPU advanced within `stall_window_ms` |
| `stalled` | in-flight request and CPU flat for ≥ `stall_window_ms` |
| `unavailable` | non-POSIX host or `psutil` failed (never raises) |

**Deadline becomes two-stage (G3).** `WorkerHandle.execute()` keeps its
`wait_for(..., deadline_ms + grace)`; on expiry it now calls
`interrupt()` — `Popen.send_signal(SIGINT)` — and waits
`interrupt_grace_ms` (default 2000) for the reply frame. The worker's
service loop converts the resulting `KeyboardInterrupt` into
`ExecResult(status="error", error="interrupted: exceeded deadline_ms=…;
namespace preserved (partial side effects possible)")`. If that reply
arrives, the namespace survives and no loss error is produced. If it does
not (native code that never returns to the interpreter), SIGKILL follows
as today and the loss error says `timeout (worker was computing: cpu
58.1 s, rss 1.9 GiB)` or `timeout (worker was stalled: state=S
wchan=pipe_read, cpu flat for 42 s)`.

**Memory guardrails (G4/G5).** The observer compares each sample's RSS
with `memory_soft_limit_bytes` / `memory_hard_limit_bytes`:

- Soft breach: the handle records `memory_pressure = (rss, limit)`; the
  next `execute()` result (string or dict `result`) gets a trailing line
  `[REPL memory] RSS 4.3 GiB exceeds the 4.0 GiB soft limit — delete
  DataFrames you no longer need (del name) before continuing.` and the
  pool logs a WARNING once per worker (re-armed when RSS drops below 90 %
  of the soft limit).
- Hard breach: the observer calls `_kill_process()` with a recorded
  verdict `("memory", rss)`. Any in-flight `_send()` observes EOF and
  `execute()`'s existing `_classify_death()` path now consults the
  observer's recorded verdict **before** the stderr heuristic, so the loss
  error is `memory: RSS 8.4 GiB exceeded memory_hard_limit_bytes=8.0 GiB`.
  An idle worker over the hard limit is killed too (a leaked namespace is
  still host memory); the next `acquire()` restarts it as a crash restart
  and `_record_restart()` carries the memory cause.

Pool level: `_top_up_prewarmed()` and the spawn branch of `acquire()`
check `psutil.virtual_memory().available >= host_memory_reserve_bytes`
(default 2 GiB). Below it, prewarm is skipped (DEBUG log) and `acquire()`
raises `WorkerPoolExhaustedError` with a memory-pressure message instead
of spawning. `_maintenance_loop()` additionally kills prewarmed spares
under pressure (spares first, sessions never) and logs the aggregate RSS
of all live workers at INFO every sweep when any soft limit is breached.

**Bootstrap uses the same observer (G2).** `_await_ready()` no longer
takes a one-shot probe at the kill; it reads the observer's ring, so the
`WorkerBootstrapError` says `booting, cpu advanced 0.4 s in 30 s (starved)`
versus `booting, cpu flat since 2.1 s, state=S wchan=futex_wait_queue
(stalled)`. An optional `bootstrap_stall_ms` (default 0 = disabled) fails
the bootstrap early when the verdict has been `stalled` that long.

### Component Diagram

```
 HOST                                                        WORKER (child)
 ┌───────────────────────────────────────────────┐          ┌──────────────────────────┐
 │ WorkerHandle                                  │          │ worker.serve()           │
 │  start() ─┬─ _drain_stdio()  (exists)         │          │  read_frame → dispatch   │
 │           └─ ProcessObserver.run()  ── psutil ─┼─ /proc ─►│  exec() on main thread   │
 │                 │  ring[ProcessSample]         │          │                          │
 │                 │  verdict(): booting/settled/ │  SIGINT  │  KeyboardInterrupt →     │
 │                 │            computing/stalled│ ───────► │  ExecResult(interrupted) │
 │                 │  soft/hard RSS checks        │  SIGKILL │                          │
 │                 └─ on hard: _kill_process()    │ ───────► │  (dies)                  │
 │  execute(): deadline → interrupt() → grace → kill         │                          │
 │  _classify_death(): observer verdict first, stderr second │                          │
 └───────────────────────────────────────────────┘          └──────────────────────────┘
        ▲ verdicts, rss, cpu
 ┌──────┴────────────────────────────────────────┐
 │ WorkerPool                                    │
 │  acquire()/_top_up_prewarmed(): host reserve  │── psutil.virtual_memory()
 │  _maintenance_loop(): evict spares on pressure│
 └───────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `WorkerHandle` (`repl_worker/handle.py`) | extends | owns a `ProcessObserver`; two-stage deadline in `execute()`; `interrupt()`; in-flight flag around `_roundtrip()`; `_classify_death()` consults the observer; `_await_ready()` reports from the ring; result suffix on soft breach |
| `WorkerConfig` (`repl_worker/protocol.py`) | extends | new tunables (see Data Models); all defaulted, all validated |
| `worker.serve()` / `WorkerNamespace.exec()` (`repl_worker/worker.py`) | extends | `KeyboardInterrupt` → `ExecResult` with `status="error"`; SIGINT arriving while idle in `read_frame` is swallowed and logged |
| `WorkerPool` (`repl_worker/pool.py`) | extends | host reserve check on spawn/prewarm; pressure eviction of spares in `_maintenance_loop()`; aggregate RSS log; `_record_restart()` cause |
| `probe_process_state()` (`repl_worker/handle.py:59`) | reuses | parsing of `/proc/<pid>/status|wchan|stat` moves into `observer.py`; the function stays as a thin wrapper for compatibility |
| `PythonREPLTool._execute()` (`tools/pythonrepl.py`) | unchanged | contract preserved; the soft-limit hint arrives inside the string/`result` it already passes through |
| `InProcessHandle` (`repl_worker/inprocess.py`) | documents | exposes `verdict() == "unavailable"` so callers can branch uniformly; no observer |
| `docs/repl-worker-sandbox.md` | documents | new §2 rows (interrupt, memory), §3 fields, a "Reading a timeout" subsection |
| `scripts/sdd/calibrate_rlimit_as.py` | extends | also records peak RSS so `memory_*_limit_bytes` defaults are calibrated by the same procedure |

### Data Models

```python
# repl_worker/protocol.py — additions to WorkerConfig (all optional, defaulted)
class WorkerConfig(BaseModel):
    ...  # existing fields unchanged
    # Observation
    observer_poll_ms: int = Field(default=500, gt=0)
    stall_window_ms: int = Field(default=5_000, gt=0)          # CPU flat this long while busy → "stalled"
    bootstrap_stall_ms: int = Field(default=0, ge=0)           # 0 = never fail bootstrap early on "stalled"
    # Interrupt-before-kill
    interrupt_before_kill: bool = True
    interrupt_grace_ms: int = Field(default=2_000, gt=0)
    # Memory guardrails (0 = disabled). Defaults are provisional — see §8 Q1.
    memory_soft_limit_bytes: int = Field(default=4 * 1024**3, ge=0)
    memory_hard_limit_bytes: int = Field(default=8 * 1024**3, ge=0)
    host_memory_reserve_bytes: int = Field(default=2 * 1024**3, ge=0)
    # validator: hard >= soft when both > 0; hard <= rlimit_as_bytes


# repl_worker/observer.py — new
class ProcessSample(BaseModel):
    t: float                  # time.monotonic()
    cpu_s: float              # user + system seconds
    rss: int                  # bytes
    state: str                # psutil status ("running", "sleeping", "stopped", ...)
    wchan: str = ""           # Linux only
    threads: int = 0

Verdict = Literal["booting", "settled", "computing", "stalled", "unavailable"]

class MemoryVerdict(BaseModel):     # recorded by the observer on a hard breach
    cause: Literal["memory"] = "memory"
    rss: int
    limit: int
```

`ExecResult` gains no field: an interrupted run is
`ExecResult(status="error", result=<msg>, error=<msg>)`, the shape the
host already forwards. `NamespaceLossError.cause` keeps its three literals.

### New Public Interfaces

```python
# repl_worker/observer.py
class ProcessObserver:
    def __init__(self, pid: int, config: WorkerConfig, *, on_hard_breach: Callable[[MemoryVerdict], Awaitable[None]]): ...
    async def run(self) -> None:                   # background task; never raises; exits on process death
    def mark_busy(self) -> None: ...               # called by WorkerHandle._send() around _roundtrip()
    def mark_idle(self) -> None: ...
    def verdict(self) -> Verdict: ...
    def last(self) -> ProcessSample | None: ...
    def cpu_progress(self, window_s: float) -> float: ...   # CPU seconds advanced in the window
    @property
    def memory_pressure(self) -> tuple[int, int] | None: ...   # (rss, soft_limit) while over the soft limit
    @property
    def memory_verdict(self) -> MemoryVerdict | None: ...
    def describe(self) -> str: ...                 # one-line, used in every error message

# repl_worker/handle.py
class WorkerHandle:
    observer: ProcessObserver | None               # None until start(); "unavailable" verdict off-POSIX
    async def interrupt(self) -> bool: ...         # SIGINT; True if a reply frame arrived within interrupt_grace_ms

# repl_worker/pool.py
class WorkerPool:
    def memory_summary(self) -> dict[str, int]: ...   # {"workers": n, "rss_total": bytes, "host_available": bytes}
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

### Module 1: Config + sample models
- **Path**: `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py`
- **Responsibility**: the new `WorkerConfig` fields with validators
  (`hard >= soft`, `hard <= rlimit_as_bytes`, `interrupt_grace_ms <
  deadline_ms`), `ProcessSample`, `MemoryVerdict`, `Verdict`. No wire
  format change (these never cross the pipe).
- **Depends on**: nothing.

### Module 2: `ProcessObserver`
- **Path**: `packages/ai-parrot/src/parrot/tools/repl_worker/observer.py` (new)
- **Responsibility**: the sampling loop (psutil + `/proc` wchan), the ring
  buffer, verdict derivation, soft/hard RSS checks with re-arm hysteresis,
  `describe()`. Moves the parsing out of `probe_process_state()` and leaves
  that function as a wrapper. Must never raise out of `run()`; a
  `psutil.NoSuchProcess` ends the loop quietly.
- **Depends on**: Module 1.

### Module 3: Worker — interruptible exec
- **Path**: `packages/ai-parrot/src/parrot/tools/repl_worker/worker.py`
- **Responsibility**: catch `KeyboardInterrupt` in `WorkerNamespace.exec()`
  and return the bounded `ExecResult`; make `serve()` survive a SIGINT
  delivered while blocked in `read_frame()` (log and continue) or while
  writing a frame (finish the write); leave `PR_SET_PDEATHSIG` and rlimits
  untouched.
- **Depends on**: nothing (protocol shape unchanged).

### Module 4: Handle — observer wiring, two-stage deadline, verdict-first death classification
- **Path**: `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py`
- **Responsibility**: start/stop the observer with the process; busy/idle
  marks around `_roundtrip()`; `interrupt()`; `execute()` deadline →
  interrupt → grace → kill; `_classify_death()` consults
  `observer.memory_verdict` first; `_build_loss_error()` detail includes
  `observer.describe()`; `_await_ready()` reads the ring and honours
  `bootstrap_stall_ms`; soft-limit suffix on results; `kill()` tears the
  observer down.
- **Depends on**: Modules 1, 2, 3.

### Module 5: Pool — host memory reserve and pressure eviction
- **Path**: `packages/ai-parrot/src/parrot/tools/repl_worker/pool.py`
- **Responsibility**: reserve check in `_top_up_prewarmed()` and
  `acquire()`; spare eviction under pressure in `_maintenance_loop()`;
  `memory_summary()`; aggregate RSS INFO log; `_record_restart()` names a
  memory cause.
- **Depends on**: Modules 1, 2, 4.

### Module 6: Tests
- **Path**: `packages/ai-parrot/tests/repl_worker/test_observer.py`,
  `test_interrupt.py`, `test_memory_guardrails.py`, additions to
  `test_handle.py` / `test_pool.py`
- **Responsibility**: see §4. Real subprocesses for interrupt/memory
  behaviour; fake sample streams for verdict derivation.
- **Depends on**: Modules 1–5.

### Module 7: Docs + calibration
- **Path**: `docs/repl-worker-sandbox.md`, `scripts/sdd/calibrate_rlimit_as.py`,
  `artifacts/logs/feat-521-memory-calibration.md`
- **Responsibility**: document verdicts, the two-stage deadline, the memory
  fields and their calibration; extend the calibration script to record
  peak RSS alongside VmPeak and re-derive the soft/hard defaults (§8 Q1).
- **Depends on**: Modules 1–5.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_config_validators` | 1 | `hard < soft`, `hard > rlimit_as_bytes`, `interrupt_grace_ms >= deadline_ms` all raise `ValidationError`; `0` disables a limit |
| `test_verdict_settled_vs_computing` | 2 | fed synthetic samples: flat CPU + idle → `settled`; rising CPU + busy → `computing` |
| `test_verdict_stalled_after_window` | 2 | busy + flat CPU for `stall_window_ms` → `stalled`; CPU tick resets it |
| `test_observer_never_raises` | 2 | `psutil.NoSuchProcess` / `AccessDenied` end the loop quietly; verdict `unavailable` on a fake non-POSIX platform |
| `test_soft_limit_hysteresis` | 2 | pressure set at ≥ soft, cleared below 90 % of soft, WARNING logged once per episode |
| `test_hard_limit_invokes_callback` | 2 | `on_hard_breach` awaited once with the measured RSS, loop stops |
| `test_worker_interrupt_returns_bounded_result` | 3 | SIGINT to a real worker mid-`while True: pass` → `ExecResult(status="error")` mentioning `interrupted`, worker alive, `list_ns` still answers |
| `test_worker_sigint_while_idle_is_harmless` | 3 | SIGINT to an idle worker → next `ping` still `pong` |
| `test_execute_deadline_interrupts_first` | 4 | `deadline_ms=500`: a Python loop is interrupted, no loss error, namespace intact (`x` from before still readable) |
| `test_execute_falls_back_to_sigkill` | 4 | a snippet holding the GIL in native code (e.g. `time.sleep` inside a C call that ignores SIGINT is not reliable — use `signal.pthread_sigmask` to block SIGINT in the worker for the test) → loss error with `timeout`, verdict text present |
| `test_loss_error_names_verdict` | 4 | the `timeout` loss error contains `computing`/`stalled` and the last sample |
| `test_bootstrap_error_reports_cpu_progress` | 4 | silent child (`sleep`) → `WorkerBootstrapError` contains `booting` and `cpu` figures; `bootstrap_stall_ms=1000` fails early |
| `test_memory_hard_kill_is_deterministic` | 4 | `memory_hard_limit_bytes=256 MiB`: allocating 512 MiB → loss error cause `memory` with measured RSS, no dependence on stderr |
| `test_memory_soft_hint_in_result` | 4 | over soft limit → next result ends with the `[REPL memory]` line; below → no suffix |
| `test_acquire_respects_host_reserve` | 5 | `host_memory_reserve_bytes` above `psutil.virtual_memory().available` (monkeypatched) → `WorkerPoolExhaustedError` names memory pressure, no spawn |
| `test_prewarm_skipped_under_pressure` | 5 | same condition → `_top_up_prewarmed()` returns without spawning, DEBUG log |
| `test_pressure_evicts_spares_not_sessions` | 5 | sweep under pressure kills prewarmed spares only |
| `test_inprocess_verdict_unavailable` | 4 | `InProcessHandle.verdict() == "unavailable"`; config memory fields ignored with a DEBUG log |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_long_groupby_completes_under_observation` | a 3 s pandas groupby with `deadline_ms=10_000` completes; observer reported `computing` during the run; overhead of observation < 2 % wall-clock vs observer disabled |
| `test_e2e_runaway_loop_keeps_namespace` | `deadline_ms=1000`, `while True: pass` → interrupted result, then `print(df.shape)` on a previously injected DataFrame still works |
| `test_e2e_memory_bomb_kills_worker_not_host` | `memory_hard_limit_bytes=512 MiB`, a snippet growing a list of arrays → cause `memory`, host process RSS unaffected beyond 100 MiB, pool restarts the session on the next call |

### Test Data / Fixtures
```python
@pytest.fixture
def tight_config():
    return WorkerConfig(deadline_ms=1_000, interrupt_grace_ms=500, observer_poll_ms=100,
                        stall_window_ms=500, memory_soft_limit_bytes=0, memory_hard_limit_bytes=0)

@pytest.fixture
def synthetic_samples():
    """Build ProcessSample sequences (flat / rising CPU, rising RSS) for observer unit tests."""

# Reuse: tests/repl_worker/test_bootstrap_diagnostics.py::_await_ready_against_silent_child
# (drives _await_ready against a `sleep` child) and the `report_dir` fixture pattern in
# tests/repl_worker/test_inprocess.py (monkeypatches parrot.tools.abstract.STATIC_DIR — the
# output_dir guard otherwise rejects tmp_path, which is why 49 pre-existing tests fail at HEAD).
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC1 — Every live worker is sampled every `observer_poll_ms`; a disabled/unavailable observer never blocks or fails a request (verdict `unavailable`).
- [ ] AC2 — Observation overhead is < 2 % wall-clock on the `test_e2e_long_groupby_completes_under_observation` benchmark and < 0.1 ms per sample (measured, recorded in `artifacts/logs/`).
- [ ] AC3 — A pure-Python runaway snippet at `deadline_ms` returns an `interrupted` error **without** a namespace-loss error; previously bound variables remain readable.
- [ ] AC4 — A snippet that ignores SIGINT is SIGKILLed no later than `deadline_ms + interrupt_grace_ms + 250 ms` (the existing grace) and the loss error names the verdict and last sample.
- [ ] AC5 — `WorkerBootstrapError` always carries the bootstrap verdict and CPU progress; with `bootstrap_stall_ms > 0` a stalled bootstrap fails early.
- [ ] AC6 — Crossing `memory_hard_limit_bytes` kills the worker within one poll interval and yields cause `memory` with the measured RSS, independent of stderr content.
- [ ] AC7 — Crossing `memory_soft_limit_bytes` appends exactly one hint line to the next result and logs one WARNING per episode (hysteresis at 90 %).
- [ ] AC8 — With host available memory below `host_memory_reserve_bytes`, the pool spawns nothing (prewarm skipped, `acquire()` raises with a memory-pressure message) and evicts spares before sessions.
- [ ] AC9 — `{status, result, error}` shapes and `NamespaceLossError.cause` literals are unchanged; `tests/repl_worker/test_integration.py` contract tests pass unmodified (once the pre-existing `output_dir` guard failure is fixed — see §7 risks).
- [ ] AC10 — `execution_mode="inprocess"` is unaffected; its handle reports `unavailable`.
- [ ] AC11 — Windows/non-POSIX: observer unavailable, interrupt disabled, everything else works; documented in `docs/repl-worker-sandbox.md` §5.
- [ ] AC12 — Defaults for `memory_soft_limit_bytes` / `memory_hard_limit_bytes` are backed by a calibration run recorded in `artifacts/logs/` (§8 Q1 resolved).
- [ ] AC13 — `pytest packages/ai-parrot/tests/repl_worker -v` passes for every new test; `ruff` and `black --target-version py312` clean on touched files.
- [ ] AC14 — `docs/repl-worker-sandbox.md` documents verdicts, the two-stage deadline and the memory fields.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> All paths below are under `packages/ai-parrot/src/parrot/tools/repl_worker/`
> unless stated otherwise. Line numbers verified on `dev` at commit `6036f275e` (2026-09-03).

### Verified Imports
```python
from parrot.tools.repl_worker import WorkerHandle, WorkerPool, WorkerBootstrapError, NamespaceTimeoutError, InProcessHandle  # __init__.py:14-16
from parrot.tools.repl_worker.protocol import WorkerConfig, ExecRequest, ExecResult, PingRequest, PongResponse, NamespaceLossError, read_frame, write_frame  # protocol.py
from parrot.tools.repl_worker.handle import probe_process_state, _MEMORY_MARKERS, _DEADLINE_GRACE_MS  # handle.py:59, :141, :135
from parrot.tools.repl_worker.worker import serve, main, apply_rlimits, set_parent_death_signal, WorkerNamespace, _stage  # worker.py:273, :330, :108, :81, :144, :60
import psutil  # declared: packages/ai-parrot/pyproject.toml:62 ("psutil>=5.9"); installed 6.0.0
```

### Existing Class Signatures
```python
# protocol.py
class WorkerConfig(BaseModel):                                   # line 365
    rlimit_as_bytes: int = 12 * 1024**3                          # 388
    rlimit_cpu_seconds: int = 300                                # 389
    rlimit_nofile: int = 256                                     # 390
    deadline_ms: int = 60_000                                    # 391
    max_workers: int = 0                                         # 392
    idle_ttl_seconds: int = 1800                                 # 393
    prewarm_pool_size: int = 2                                   # 394
    bootstrap_timeout_ms: int = Field(default=30_000, gt=0)      # 400
    namespace_timeout_ms: int = Field(default=30_000, gt=0)      # 401
class ExecRequest(BaseModel): op="exec"; code: str; debug: bool = False; deadline_ms: int   # 205-211
class ExecResult(BaseModel): output: str|None; status: str|None; result: Any; error: str|None; new_vars: list[str]  # 277-285
class NamespaceLossError(BaseModel): cause: Literal["timeout","memory","crash"]; lost_variables: list[str]; message: str  # 352-363
class ReadyResponse(BaseModel): op="ready"; pid: int; bootstrap_ms: int   # 329-349
def read_frame(stream: BinaryIO) -> BaseModel                    # 469 (blocking; raises EOFError/ValueError)
def write_frame(stream: BinaryIO, message: BaseModel) -> None    # 452

# handle.py
def probe_process_state(pid: int | None) -> str                  # 59  (one-shot /proc snapshot; Linux only)
_DEADLINE_GRACE_MS = 250                                         # 135
_MEMORY_MARKERS = ("MemoryError", "Cannot allocate memory", "bad_alloc", "failed to map segment", "Killed", "OOM")  # 141
class WorkerHandle:                                              # 151
    def __init__(self, config=None, output_dir=None, repl_kwargs=None, executor=None)   # 154
    _proc: subprocess.Popen | None; _executor; _stdio_executor (2 threads); _lifecycle_executor (2 threads)  # 187-247
    _stderr_tail: list[str]; _stdout_tail: list[str]; known_vars: list[str]   # 254-263
    _ready: asyncio.Future | None; _ready_task; _pending_reply    # 266-271
    @property is_alive -> bool                                   # 272
    async def start(self) -> None                                # 276  (Popen with pass_fds, stdout/stderr PIPE; starts _drain_stdio and _await_ready)
    async def _await_ready(self) -> None                         # 329  (bootstrap_timeout_ms; starvation detection via threading.Event; calls probe_process_state before kill)
    def _fail_ready(self, message: str) -> None                  # 409
    async def wait_ready(self, timeout_s=None) -> ReadyResponse  # 433
    async def _drain_stdio(self) -> None                         # 463  (two readline pumps; fills the tails)
    def _roundtrip(self, request) -> Any                         # 499  (write_frame + read_frame, blocking, runs on _executor)
    async def _send(self, request, timeout_s: float, *, lethal: bool = False) -> Any   # 504  (under self._lock; awaits wait_ready; drains pending reply; parks reply on non-lethal timeout)
    async def _drain_pending_reply(self, timeout_s) -> None      # 580
    async def _kill_process(self) -> None                        # 617  (SIGKILL on _lifecycle_executor, under _kill_lock)
    def death_summary(self) -> tuple[int | None, str]            # 645
    async def _classify_death(self) -> str                       # 661  (kills if alive; "memory" if stderr matches _MEMORY_MARKERS else "crash")
    def _build_loss_error(self, cause: str, detail: str) -> dict  # 691
    async def execute(self, code: str, debug: bool = False) -> str | dict   # 714  (lethal _send with deadline_ms + grace; TimeoutError → loss "timeout")
    async def inject_dataframe(self, name, df) -> None           # 758
    async def get_var / set_var / list_vars / snapshot / reset   # 809-833
    async def ping(self, timeout_s: float = 10.0) -> bool        # 835
    async def kill(self) -> None                                 # 855  (kills, cancels ready/stdio tasks, closes pipes, shuts executors)

# worker.py
def _stage(message: str) -> None                                 # 60  (unbuffered stderr stage marker)
def set_parent_death_signal() -> None                            # 81  (PR_SET_PDEATHSIG=SIGKILL, Linux)
def apply_rlimits(config: WorkerConfig) -> None                  # 108
class WorkerNamespace:                                           # 144
    def exec(self, request: ExecRequest) -> ExecResult           # 182  (calls self._tool._execute_code(code, debug=..., enforce_security=True); classifies via _is_error_output)
def _dispatch(namespace, message) -> Any                         # 228
def serve(config, in_stream, out_stream, output_dir=None, repl_kwargs=None, started_at=None) -> None   # 273  (writes ReadyResponse first; loop: read_frame → _dispatch → write_frame; catches Exception only)
def main(argv=None) -> None                                      # 330

# pool.py
_CEILING_CAP = 16; _RESTART_WINDOW_S = 60.0; _RESTART_LOOP_THRESHOLD = 3; _CEILING_FLOOR = 4   # 44-52
class WorkerPoolExhaustedError(RuntimeError)                     # 55
class WorkerPool:                                                # 63
    def __init__(self, config=None, output_dir=None, repl_kwargs=None, executor=None)   # 66
    _sessions: dict[str, WorkerHandle]; _last_active: dict[str, float]; _prewarmed: list[WorkerHandle]; _restarts   # 84-120
    async def _spawn_handle(self) -> WorkerHandle                # 190
    async def _top_up_prewarmed(self) -> None                    # 197  (single-flight; awaits wait_ready outside _lock)
    async def _maintenance_loop(self) -> None                    # 286  (interval = min(5, max(1, idle_ttl/10)); calls _evict_idle)
    async def _evict_idle(self) -> None                          # 296
    def _record_restart(self, session_id, dead: WorkerHandle) -> None   # 315
    async def acquire(self, session_id: str) -> WorkerHandle     # 367
    async def release(self, session_id: str) -> None             # 432
    async def shutdown(self) -> None                             # 442

# inprocess.py (added 2026-09-03, commit 6036f275e)
class InProcessHandle: execute/get_var/set_var/inject_dataframe/list_vars/snapshot/reset/ping/kill; is_alive; is_ready; known_vars; _inflight   # whole file

# tools/pythonrepl.py
class PythonREPLTool:
    def __init__(..., executor_max_workers: int = 4, worker_config=None, execution_mode: Optional[str] = None, **kwargs)   # ~line 213
    _repl_executor: ThreadPoolExecutor; _worker_config; _worker_pool; _session_id; _execution_mode; _inprocess_handle
    async def _execute(self, code, debug=False, **kwargs) -> Any   # host gate → _worker_session() → handle.execute()
    def _is_error_output(self, output) -> bool                    # ~line 782 (pre-6036f275e numbering; re-grep)
```

### Existing Test Helpers (reuse, do not duplicate)
- `tests/repl_worker/test_bootstrap_diagnostics.py::_await_ready_against_silent_child(executor, budget_ms)` — drives `_await_ready` against a `sleep` child with a real pipe.
- `tests/repl_worker/test_inprocess.py::report_dir` fixture — monkeypatches `parrot.tools.abstract.STATIC_DIR` so `report_dir=tmp_path` passes the output_dir guard.
- `tests/repl_worker/test_integration.py::tool` fixture and `_shutdown()` helper.

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ProcessObserver.run()` | `WorkerHandle.start()` | `loop.create_task(...)` next to `_stdio_task` | `handle.py:276-327` |
| `observer.mark_busy()/mark_idle()` | `WorkerHandle._send()` | around `run_in_executor(self._executor, self._roundtrip, request)` | `handle.py:504-578` |
| `WorkerHandle.interrupt()` | `Popen.send_signal(signal.SIGINT)` on `_lifecycle_executor` | same pattern as `_kill_process()` | `handle.py:617-643` |
| `observer.memory_verdict` | `WorkerHandle._classify_death()` | checked before `_MEMORY_MARKERS` | `handle.py:661-689` |
| `observer.describe()` | `WorkerHandle._build_loss_error()` / `_await_ready()` | appended to `detail` / `cause` | `handle.py:691-712`, `:329-407` |
| `KeyboardInterrupt` handling | `WorkerNamespace.exec()` / `serve()` | new `except KeyboardInterrupt` branches | `worker.py:182-200`, `:273-328` |
| host reserve check | `WorkerPool.acquire()` spawn branch and `_top_up_prewarmed()` | `psutil.virtual_memory().available` | `pool.py:367-430`, `:197-284` |
| spare eviction | `WorkerPool._maintenance_loop()` | new `_evict_under_pressure()` after `_evict_idle()` | `pool.py:286-294` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.tools.repl_worker.observer`~~ / ~~`ProcessObserver`~~ / ~~`ProcessSample`~~ / ~~`MemoryVerdict`~~ — new in this spec.
- ~~`WorkerHandle.interrupt()`~~, ~~`WorkerHandle.observer`~~, ~~`WorkerHandle._in_flight`~~ — do not exist yet.
- ~~`WorkerConfig.memory_soft_limit_bytes`~~ and every other field listed under Data Models — do not exist yet.
- ~~`WorkerPool.memory_summary()`~~, ~~`WorkerPool._evict_under_pressure()`~~ — do not exist.
- ~~any `signal` handling in `worker.py`~~ — only `PR_SET_PDEATHSIG` via `prctl`; there is no `signal.signal(...)` registration and `serve()` catches `Exception` only (a `KeyboardInterrupt` today kills the worker).
- ~~a heartbeat/progress frame on the control pipe~~ — the protocol has no unsolicited frames; `PingRequest` exists (`protocol.py:266`) but nothing in the pool calls `ping()` periodically.
- ~~`psutil` usage anywhere under `repl_worker/`~~ — the package is a declared dependency but unused there; `probe_process_state()` reads `/proc` by hand.
- ~~`RLIMIT_RSS` enforcement~~ — Linux does not enforce it; only `RLIMIT_AS/CPU/NOFILE/CORE` are set (`worker.py:131-135`).
- ~~`ExecResult.status == "interrupted"`~~ — keep `"error"`; the word appears in the message only.
- ~~`parrot/tools/repl_worker/` on the repo root~~ — the source root is `packages/ai-parrot/src/parrot/`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Background tasks on the handle follow `_drain_stdio()` exactly: created in
  `start()`, cancelled and awaited in `kill()`, never raise.
- Process signals go through `_lifecycle_executor`, never `_executor`
  (FEAT-500 code review: the kill path must never queue behind blocked
  pipe reads).
- Every error message names the pid, the budget, the verdict and the last
  sample — the FEAT-500 rule "no blank errors" (G3) extended.
- Pydantic for every new structure; `self.logger`/module `logger`, never
  `print`; async-first; Google docstrings + type hints.
- Keep `_execute_code` untouched (FEAT-380: "es el corazón y no se reescribe").

### Known Risks / Gotchas
- **SIGINT reaches native code late or never.** pandas/numpy kernels do not
  check for pending signals; `KeyboardInterrupt` is raised only when
  control returns to the interpreter. Hence `interrupt_grace_ms` and the
  unconditional SIGKILL fallback (AC4). Partial side effects in the
  namespace after an interrupt are possible and are stated in the message.
- **SIGINT while idle.** Racing an interrupt against a reply that just
  landed can deliver SIGINT to a worker blocked in `read_frame()`; the
  service loop must catch `KeyboardInterrupt` there and continue, and the
  host must only send SIGINT while `observer.verdict()` is busy.
- **RSS vs shared memory.** Arrow/shm-injected DataFrames
  (`transport.py`) are shared pages; `memory_info().rss` counts them once
  per process. Use `rss` (not `uss`) for speed; document that a 1 GiB shm
  DataFrame counts in both host and worker figures.
- **Poll cadence vs a fast allocation.** A snippet can allocate gigabytes
  between two 500 ms samples; the hard limit is a guardrail, not a fence.
  `RLIMIT_AS` remains the child-side fence.
- **Host reserve on containers.** `psutil.virtual_memory().available`
  reflects the host, not a cgroup limit; read
  `/sys/fs/cgroup/memory.max` when present (v2) and take the minimum.
  Deferred to §8 Q3 if not trivial.
- **Pre-existing test breakage.** At HEAD, 49 tests + 6 errors in
  `tests/repl_worker` fail because `report_dir=tmp_path` is rejected by
  `AbstractTool`'s output_dir guard (also inside the worker child, which
  then dies during bootstrap). Fix or fixture-patch that first (see the
  `report_dir` fixture) or AC9/AC13 cannot be evaluated.
- **Concurrent sessions share this checkout and venv.** Another session
  downgraded `navigator-api` mid-day on 2026-09-03; re-verify imports
  before attributing failures to this feature.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `psutil` | `>=5.9` (already declared, 6.0.0 installed) | cheap cross-platform CPU/RSS/status sampling and host available memory |

---

## Worktree Strategy

- **Isolation unit**: per-spec — one worktree
  `.claude/worktrees/feat-521-repl-worker-idle-detection-memory-guardrails`
  branched from `origin/dev`.
- **Sequencing**: Modules 1 → 2 → 3 → 4 → 5 → 6 → 7. Modules 2 and 3 are
  independent of each other and may be parallelised by two agents once
  Module 1 lands; Module 4 needs both. Module 5 needs 4. Tests and docs
  follow.
- **Cross-feature dependencies**: none pending. Must merge after
  `6036f275e` (already on `dev`), which this spec's contract is verified
  against.

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [ ] Q1 — Default `memory_soft_limit_bytes` / `memory_hard_limit_bytes`.
  Proposed 4 GiB / 8 GiB (hard = 2/3 of `rlimit_as_bytes`); the FEAT-380
  calibration measured a 5.5 GB *VmPeak* for a bootstrap + 500 MB DataFrame
  + merge/groupby + plot session, so RSS was lower but unmeasured. Resolve
  by extending `scripts/sdd/calibrate_rlimit_as.py` (Module 7) and reading
  peak RSS before shipping. — *Owner: Jesus Lara*
- [ ] Q2 — Should an **idle** worker over the hard limit be killed
  immediately (proposed: yes, it is host memory either way) or only at the
  next `acquire()`? Killing idle workers means the LLM learns about the
  loss one call later, via the crash-restart path. — *Owner: Jesus Lara*
- [ ] Q3 — Container awareness for the host reserve: read cgroup v2
  `memory.max`/`memory.current` in addition to `psutil.virtual_memory()`?
  Proposed: yes if under ~30 lines, else defer to a follow-up. — *Owner: implementer*
- [ ] Q4 — `interrupt_before_kill` default `True`? It changes the observable
  outcome of a deadline breach (namespace kept instead of lost) for every
  existing caller. Proposed: `True`, since keeping the namespace is
  strictly more useful and the error is still bounded. — *Owner: Jesus Lara*
- [ ] Q5 — Should the soft-limit hint go to the LLM (result suffix, as
  proposed) or only to logs? The suffix is the only channel the model
  reads. — *Owner: Jesus Lara*
- [x] Q6 — Heartbeat frames on the control pipe? — *Resolved in this
  spec*: no; observation is host-side only (Non-Goals) to keep the
  request/response ordering guarantee from FEAT-500.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-03 | Jesus Lara + Claude | Initial draft from the 2026-09-03 worker-bootstrap incident and mcp-repl's idle/memory ideas |

# TASK-3169: Subprocess worker pool (tiers 1-2) — `services/sandbox/pool.py`

**Feature**: FEAT-459 — Form Builder: Sandboxed Custom Code on Lifecycle Events
**Spec**: `sdd/specs/formbuilder-custom-code.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3161, TASK-3168
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9, resolving OQ-6. `SubprocessWorkerPool` implements the
existing `SandboxProvider` ABC (`parrot.eval.sandbox.base:166`) with warm
`asyncio.subprocess` workers — no network namespace, wall/CPU/memory
budgets, recycling, health checks, a bounded acquire queue, and a cold-
start path. Today only `NoopSandboxProvider` exists as a concrete
`SandboxProvider` (`base.py:259`) — **this is the first real pooling
implementation** in the codebase (spec §6 "Does NOT Exist").

All ten pool-sizing knobs (spec §7 table) must be configurable with the
documented defaults — this is OQ-6's resolution.

---

## Scope

- Implement `SubprocessWorkerPool(SandboxProvider)` in
  `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/pool.py`:
  `acquire()`/`release()` per the `SandboxProvider` ABC contract, backed by
  a bounded pool of warm `asyncio.subprocess` workers.
- Implement recycling (`recycle_after_invocations`,
  `recycle_after_seconds`), a periodic `health_check()` sweep, a bounded
  acquire queue (`acquire_queue_timeout_ms`, `max_queue_depth`), and a
  cold-start path (`cold_start_timeout_ms`) for when the pool is empty.
- All ten knobs from spec §7's Pool sizing defaults table are constructor
  parameters with the documented default values.
- Write `packages/parrot-formdesigner/tests/unit/test_subprocess_pool.py`.

**NOT in scope**: what actually runs inside the worker subprocess (the
Python entrypoint script that reads a `SandboxContext` frame, executes
`bundle.python_source`, and writes back a `SandboxOutcome` frame) — the
spec's module breakdown does not name a separate task for the worker's
own entrypoint script; if no other task in this feature covers it, note
the gap explicitly in the Completion Note rather than silently
implementing it here beyond a minimal placeholder the tests can target.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/pool.py` | CREATE | `SubprocessWorkerPool` |
| `packages/parrot-formdesigner/tests/unit/test_subprocess_pool.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.eval.sandbox.base import SandboxSpec, ExecResult, Sandbox, SandboxProvider
# Equivalently — verified: packages/ai-parrot/src/parrot/eval/sandbox/__init__.py:10, __all__:20
from parrot.eval.sandbox import SandboxSpec, ExecResult, Sandbox, SandboxProvider, NoopSandbox, NoopSandboxProvider
from parrot_formdesigner.services.sandbox.protocol import encode_frame, decode_frame  # TASK-3168
from parrot_formdesigner.core.snippets import SandboxContext, SandboxOutcome  # TASK-3161
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/eval/sandbox/base.py
class SandboxSpec(BaseModel):                                # line 42
    kind: Literal["docker", "in_memory_state", "mock_api", "noop"] = "noop"
    image: str | None = None
    setup: list[str] = Field(default_factory=list)
    seed_state: dict[str, Any] | None = None
    git_truncate_after: str | None = None

class ExecResult(BaseModel):                                  # line 60
    exit_code: int
    stdout: str = ""
    stderr: str = ""

class Sandbox(ABC):                                           # line 79
    async def __aenter__(self) -> "Sandbox": ...              # line 95
    async def __aexit__(self, *exc: Any) -> None: ...         # line 104
    async def reset(self, seed_state: dict[str, Any] | None) -> None: ...  # line 113
    async def health_check(self) -> bool: ...                 # line 122
    async def snapshot(self) -> dict[str, Any]: ...           # line 131
    async def exec(self, cmd: list[str]) -> ExecResult: ...   # line 139

class SandboxProvider(ABC):                                   # line 166
    async def acquire(self, spec: SandboxSpec) -> Sandbox: ...   # line 174
    async def release(self, sandbox: Sandbox) -> None: ...        # line 186

class NoopSandbox(Sandbox): ...                               # line 209 — reference impl to read before writing this task
class NoopSandboxProvider(SandboxProvider): ...                # line 259 — reference impl to read before writing this task
```

### Pool sizing defaults (resolved OQ-6, spec §7 — verbatim)
| Knob | Default | Rationale |
|---|---|---|
| `tier12_pool_size` | 4 workers per process | Covers typical concurrent submits without holding much RSS |
| `recycle_after_invocations` | 500 | Bounds any slow state leak in a long-lived worker |
| `recycle_after_seconds` | 3600 | Backstop for low-traffic workers that never hit the invocation count |
| `acquire_queue_timeout_ms` | 2000 | Bounded wait, then `on_failure` policy. Never unbounded |
| `max_queue_depth` | 32 | Beyond this, fail fast rather than accumulate latency |
| `health_check_interval_s` | 30 | Detects poisoned workers between requests |
| `cold_start_timeout_ms` | 5000 | A pool miss must not hang a submit indefinitely |

(`tier34_pool_size`, default `timeout_ms`, default `max_memory_mb` belong
to TASK-3170/TASK-3161 respectively, not this task.)

### Does NOT Exist
- ~~Any real pooling `SandboxProvider` implementation~~ — only
  `NoopSandboxProvider` exists (`base.py:259`), which is NOT a pool (it
  presumably no-ops `acquire`/`release`) — read it for the ABC contract
  shape, not for pooling logic to copy, since there is none to copy.
- ~~A worker subprocess entrypoint script~~ — does not exist; out of
  scope for this task per the Scope section above (flag the gap).
- ~~`services/sandbox/pool.py`~~ — created by this task.

---

## Implementation Notes

### Key Constraints
- **Never an unbounded wait.** `acquire()` must respect
  `acquire_queue_timeout_ms` — beyond it, raise (a pool-exhaustion
  exception the caller, TASK-3172's `TierRouter`, treats as a failure
  subject to `on_failure` policy). This is spec's single most repeated
  operational requirement (§5 Operational ACs, §7 risk table).
- Recycling triggers on EITHER `recycle_after_invocations` OR
  `recycle_after_seconds`, whichever comes first, per worker instance.
- `health_check()` failures replace the worker (retry the request at most
  once, per spec §7 risk table row) — do not retry indefinitely.
- `asyncio.subprocess.Process` with `network="none"`-equivalent isolation:
  actual OS-level network namespace restriction is an ops/deployment
  concern (e.g. running the subprocess under a restricted user/cgroup) —
  this task's Python code should still be structured so a future
  isolation mechanism slots in (e.g. a `_spawn_args()` hook), but do not
  invent a fake sandboxing claim in code comments; be explicit that the
  actual kernel-level network denial is outside pure-Python subprocess
  capabilities and is an infra concern for tiers 1-2 (§2 confirms tiers
  1-2 need no container runtime — that is a statement about NOT requiring
  gVisor, not a claim that this Python code alone enforces network
  isolation).

### References in Codebase
- `parrot/eval/sandbox/base.py:79-136` (`Sandbox` ABC), `:166-207`
  (`SandboxProvider` ABC), `:209-` (`NoopSandbox`), `:259-`
  (`NoopSandboxProvider`) — read the whole file before implementing.

---

## Implementation Blueprint

### Steps (in order)
1. Define `_PooledWorker` (internal bookkeeping: process handle,
   invocation count, spawn time, health status).
2. Implement `_spawn_worker()` and `_recycle_if_needed()`.
3. Implement `acquire()` with the bounded-queue + cold-start-timeout logic.
4. Implement `release()` and the periodic health-check sweep task.
5. Write and run tests, prioritizing the four pool-behavior tests named in
   spec §4 (`test_pool_recycles_after_n`, `test_pool_kills_on_timeout`,
   `test_pool_bounded_queue_times_out`, `test_pool_replaces_unhealthy_worker`).

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/pool.py` (CREATE)
```python
"""Warm asyncio.subprocess worker pool for tiers 1-2 (FEAT-459 / M9).

Implements parrot.eval.sandbox.base.SandboxProvider — the ONLY real
pooling implementation in the codebase; NoopSandboxProvider (base.py:259)
is a no-op reference, not pooling logic to extend. All sizing knobs are
configurable with defaults from spec §7 (OQ-6).

NOTE on network isolation: this module's job is process lifecycle and
scheduling, not kernel-level sandboxing. "no network namespace" for tiers
1-2 (spec §2) is an infra/deployment property (e.g. a restricted
execution user, seccomp profile, or cgroup) layered UNDER this pool, not
something asyncio.subprocess enforces by itself. Tiers 3-4's actual kernel
isolation is gVisor (TASK-3170) — this pool is deliberately the
CHEAPER, un-containerised path for the two tiers that need no such
isolation.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from parrot.eval.sandbox.base import Sandbox, SandboxProvider, SandboxSpec

logger = logging.getLogger(__name__)


class PoolExhaustedError(Exception):
    """Raised by acquire() when no worker becomes available within the queue timeout."""


class ColdStartTimeoutError(Exception):
    """Raised when spawning a fresh worker exceeds cold_start_timeout_ms."""


@dataclass
class _PooledWorker:
    process: asyncio.subprocess.Process
    spawned_at: float = field(default_factory=time.monotonic)
    invocation_count: int = 0
    healthy: bool = True


class _SubprocessSandbox(Sandbox):
    """Sandbox ABC wrapper around one _PooledWorker (FILL IN body per method)."""

    def __init__(self, worker: _PooledWorker, pool: "SubprocessWorkerPool") -> None:
        self._worker = worker
        self._pool = pool

    async def __aenter__(self) -> "Sandbox":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._pool.release(self)

    async def reset(self, seed_state: dict | None) -> None:
        # FILL IN: tiers 1-2 workers are stateless per invocation (the
        #   whole point of a SandboxContext/SandboxOutcome round trip per
        #   call) — likely a no-op; confirm against SandboxProvider's
        #   contract docstring in base.py before leaving it empty.
        pass

    async def health_check(self) -> bool:
        # FILL IN: verify self._worker.process is still alive
        #   (process.returncode is None) and optionally exchange a
        #   lightweight ping frame — bounded by
        #   test_pool_replaces_unhealthy_worker.
        raise NotImplementedError

    async def snapshot(self) -> dict:
        return {}  # tiers 1-2 have no persistent state to snapshot

    async def exec(self, cmd: list[str]) -> "ExecResult":
        # FILL IN: this ABC method is for the eval-harness use case
        #   (running shell commands inside a sandbox); the forms use case
        #   instead sends a SandboxContext frame and reads a
        #   SandboxOutcome frame via TASK-3168's encode_frame/decode_frame
        #   over self._worker.process.stdin/stdout. Add a
        #   forms-specific `run_snippet(ctx: SandboxContext) ->
        #   SandboxOutcome` method alongside this ABC-required `exec()`
        #   rather than overloading `exec()`'s cmd-list shape for it.
        raise NotImplementedError


class SubprocessWorkerPool(SandboxProvider):
    """Warm-pooled asyncio.subprocess workers for CapabilityTier PURE/HELPERS."""

    def __init__(
        self,
        *,
        tier12_pool_size: int = 4,
        recycle_after_invocations: int = 500,
        recycle_after_seconds: int = 3600,
        acquire_queue_timeout_ms: int = 2000,
        max_queue_depth: int = 32,
        health_check_interval_s: int = 30,
        cold_start_timeout_ms: int = 5000,
    ) -> None:
        """All defaults per spec §7 OQ-6 pool sizing table.

        Args:
            tier12_pool_size: Warm workers held per process. Under
                gunicorn -w N the REAL total is N * this value — size
                against that, not this number alone (spec §7 note).
            recycle_after_invocations: Retire a worker after this many
                completed invocations.
            recycle_after_seconds: Retire a worker after this much wall
                time regardless of invocation count.
            acquire_queue_timeout_ms: Maximum time acquire() waits for a
                worker before raising PoolExhaustedError. NEVER unbounded.
            max_queue_depth: Beyond this many queued acquire() callers,
                fail fast instead of growing the queue.
            health_check_interval_s: Interval for the background health
                sweep that detects poisoned idle workers.
            cold_start_timeout_ms: Maximum time to spawn a fresh worker
                when the pool is empty and under `tier12_pool_size`.
        """
        self._tier12_pool_size = tier12_pool_size
        self._recycle_after_invocations = recycle_after_invocations
        self._recycle_after_seconds = recycle_after_seconds
        self._acquire_queue_timeout_ms = acquire_queue_timeout_ms
        self._max_queue_depth = max_queue_depth
        self._health_check_interval_s = health_check_interval_s
        self._cold_start_timeout_ms = cold_start_timeout_ms
        self._idle: asyncio.Queue[_PooledWorker] = asyncio.Queue(maxsize=tier12_pool_size)
        self._waiters = 0
        self._live_count = 0
        self.logger = logger

    async def _spawn_worker(self) -> _PooledWorker:
        """Start one fresh worker subprocess, bounded by cold_start_timeout_ms.

        Raises:
            ColdStartTimeoutError: spawn exceeded cold_start_timeout_ms.
        """
        # FILL IN: asyncio.create_subprocess_exec(...) for the (currently
        #   unspecified — see Scope's noted gap) worker entrypoint script,
        #   wrapped in asyncio.wait_for(..., timeout=self._cold_start_timeout_ms / 1000)
        #   catching asyncio.TimeoutError and re-raising ColdStartTimeoutError.
        raise NotImplementedError

    def _needs_recycle(self, worker: _PooledWorker) -> bool:
        age_s = time.monotonic() - worker.spawned_at
        return (
            worker.invocation_count >= self._recycle_after_invocations
            or age_s >= self._recycle_after_seconds
        )

    async def acquire(self, spec: SandboxSpec) -> Sandbox:
        """Acquire a healthy worker, spawning fresh if the pool has room.

        Raises:
            PoolExhaustedError: no worker became available within
                acquire_queue_timeout_ms, AND max_queue_depth callers are
                already waiting.
        """
        if self._waiters >= self._max_queue_depth:
            raise PoolExhaustedError(
                f"acquire queue depth ({self._waiters}) already at max_queue_depth="
                f"{self._max_queue_depth}"
            )
        self._waiters += 1
        try:
            # FILL IN: try self._idle.get_nowait() first (fast path); on
            #   Empty, either spawn fresh (if self._live_count <
            #   self._tier12_pool_size) via _spawn_worker(), or
            #   asyncio.wait_for(self._idle.get(), timeout=
            #   self._acquire_queue_timeout_ms / 1000) — catch
            #   asyncio.TimeoutError and re-raise PoolExhaustedError.
            #   Recycle (discard + spawn replacement) any worker that
            #   _needs_recycle() returns True for, BEFORE handing it out.
            raise NotImplementedError
        finally:
            self._waiters -= 1

    async def release(self, sandbox: Sandbox) -> None:
        """Return a worker to the idle queue, or recycle/discard it first."""
        # FILL IN: extract the _PooledWorker from `sandbox`
        #   (isinstance-check _SubprocessSandbox), increment
        #   invocation_count, and either self._idle.put_nowait(worker) or
        #   discard+respawn if _needs_recycle(worker) is now True.
        raise NotImplementedError
```
**Why this shape**: `_SubprocessSandbox.exec()` deliberately raises
`NotImplementedError` with a FILL IN note rather than being silently
adapted to the forms use case — the `Sandbox` ABC's `exec(cmd: list[str])`
is shaped for the eval harness's shell-command use case, and overloading
its meaning for "run this snippet" would violate "follow the
`SandboxProvider` acquire/release contract exactly so the pools remain
drop-in for the eval harness" (spec §7 Patterns to Follow) — a
`run_snippet()` method alongside it is the correct fix, left as a FILL IN
because its exact call shape depends on how TASK-3172's `TierRouter` ends
up invoking pools, which is written after this task.

### `packages/parrot-formdesigner/tests/unit/test_subprocess_pool.py` (CREATE)
```python
"""Unit tests for SubprocessWorkerPool — FEAT-459 / TASK-3169."""

from __future__ import annotations

import pytest

from parrot_formdesigner.services.sandbox.pool import (
    ColdStartTimeoutError,
    PoolExhaustedError,
    SubprocessWorkerPool,
)


async def test_pool_recycles_after_n() -> None:
    # FILL IN: pool = SubprocessWorkerPool(tier12_pool_size=1,
    #   recycle_after_invocations=2); acquire+release the same slot 3
    #   times; assert the worker object identity changes after the 2nd
    #   release (retired and replaced) — bounded by _needs_recycle().
    pass


async def test_pool_kills_on_timeout() -> None:
    # FILL IN: exercise a wall-clock budget kill path — this likely lives
    #   in the (currently FILL IN) run_snippet()/exec() method rather
    #   than acquire()/release(); coordinate with whichever task/PR
    #   completes that method, since this test cannot be finished until
    #   that shape is decided.
    pass


async def test_pool_bounded_queue_times_out() -> None:
    pool = SubprocessWorkerPool(
        tier12_pool_size=0, acquire_queue_timeout_ms=50, max_queue_depth=32
    )
    with pytest.raises((PoolExhaustedError, ColdStartTimeoutError)):
        await pool.acquire(spec=None)  # type: ignore[arg-type]


async def test_pool_replaces_unhealthy_worker() -> None:
    # FILL IN: acquire a worker, force health_check() to return False
    #   (monkeypatch the _SubprocessSandbox instance), release it, assert
    #   the NEXT acquire() gets a freshly spawned worker, not the
    #   unhealthy one.
    pass


def test_pool_defaults_match_spec() -> None:
    """OQ-6: every knob ships the documented default (spec §7 table)."""
    pool = SubprocessWorkerPool()
    assert pool._tier12_pool_size == 4
    assert pool._recycle_after_invocations == 500
    assert pool._recycle_after_seconds == 3600
    assert pool._acquire_queue_timeout_ms == 2000
    assert pool._max_queue_depth == 32
    assert pool._health_check_interval_s == 30
    assert pool._cold_start_timeout_ms == 5000
```
**Why**: `test_pool_defaults_match_spec` is complete and is arguably the
single most important test in this file — it is the literal, mechanical
check that OQ-6's resolution ("every knob configurable, documented
default") actually shipped. The remaining four are stubbed because they
depend on `_spawn_worker`/`acquire`/`release`/`run_snippet` FILL INs that
this task's blueprint deliberately leaves to the implementer (spawning a
real subprocess in a unit test needs either a trivial test-only
entrypoint script or a mocked `asyncio.create_subprocess_exec` — pick
one and document the choice in the Completion Note).

### FILL IN checklist
- [ ] `_SubprocessSandbox.reset/health_check/exec` — bodies per the inline notes
- [ ] `_SubprocessSandbox` — add a `run_snippet(ctx: SandboxContext) -> SandboxOutcome` method using TASK-3168's frame protocol
- [ ] `SubprocessWorkerPool._spawn_worker` — actual subprocess creation + cold-start timeout
- [ ] `SubprocessWorkerPool.acquire` — fast-path/spawn/bounded-wait logic
- [ ] `SubprocessWorkerPool.release` — return-to-pool / recycle logic
- [ ] A worker entrypoint script this pool spawns (flagged gap — see Scope)
- [ ] 4 of 5 stubbed tests, gated on the above

---

## Acceptance Criteria

- [ ] All ten OQ-6 knobs are constructor parameters with the exact documented defaults (`test_pool_defaults_match_spec`)
- [ ] `acquire()` never blocks longer than `acquire_queue_timeout_ms` before raising `PoolExhaustedError`
- [ ] A worker is retired after `recycle_after_invocations` completed calls, whichever of that or `recycle_after_seconds` comes first
- [ ] An unhealthy worker (failed `health_check()`) is destroyed and replaced, not reused
- [ ] `acquire()` on an empty, at-capacity pool raises `PoolExhaustedError` rather than hanging indefinitely
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_subprocess_pool.py -v`
- [ ] `ruff check` and `mypy` clean on `services/sandbox/pool.py`

---

## Test Specification

See the blueprint's test file above — 5 test functions, 4 stubbed (1 complete).

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 9, §7 Pool sizing defaults table, §7 risk table rows for pool exhaustion/unhealthy workers)
2. **Check dependencies** — TASK-3161 and TASK-3168 must be `done`
3. **Verify the Codebase Contract** — read `parrot/eval/sandbox/base.py` in full; confirm `SandboxProvider`'s abstract method signatures are unchanged
4. **Update status** in `sdd/tasks/index/formbuilder-custom-code.json` → `"in-progress"`
5. **Implement** from the blueprint; complete every `# FILL IN:`; explicitly flag the missing worker-entrypoint-script task in your Completion Note if no other task covers it
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3169-subprocess-worker-pool.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any

# TASK-3434: Bounded lifecycle-managed CpuExecutor

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3418
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 7** (executor half) and §2 *Execution boundaries*. The new
cycle is async-first, but OpenCV proposals, local OCR and PNG/JPEG encoding are
CPU-bound: run on the event loop they would stall every other request of the
aiohttp/gunicorn worker. The user decision (brainstorm, "CPU work") is a
**bounded, lifecycle-managed process executor**; threads are reserved for
blocking file I/O only.

`CpuExecutor` is that seam: one instance per pipeline run, created lazily,
bounded per gunicorn worker (`cpu_workers`, default 2), closed in `finally` by
the run orchestration (a later task). It lives in the `perception` package
created by TASK-3418 — that package directory is the only thing this task needs
from its dependency.

---

## Scope

- Implement `CpuExecutor` with the spec-skeleton surface:
  `__init__(max_workers=2)`, `async run(fn, *args)`, `async aclose()`.
- Lazy `ProcessPoolExecutor` creation on first `run`; bounded in-flight
  submissions; cancellation-safe awaiting; idempotent `aclose`; `RuntimeError`
  when used after close; `async with` support.
- Offline tests (no OpenCV needed).

**NOT in scope**: deciding *what* runs in the pool (perception/OCR tasks do
that); wiring into `PlanogramCompliance.run()`; any thread pool helper
(`asyncio.to_thread` is used directly by callers); editing
`perception/__init__.py` (single owner — import this module by full path).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/executor.py` | CREATE | `CpuExecutor` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_cpu_executor.py` | CREATE | Offline unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references. **DO NOT** invent imports, attributes or methods not listed here.

### Verified Imports
```python
import asyncio
import functools
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any, Callable, Optional, TypeVar
```
Standard library only (Python 3.12.3 in the shared `.venv`; default start method
on this platform is `fork`, verified 2026-09-18).

### Existing Signatures to Use
```python
# Created by TASK-3418 (dependency): the package directory
#   packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/__init__.py
# exists and re-exports only that task's names. This task adds a sibling module and
# imports NOTHING from the package.

# Standard library contracts relied on:
#   loop.run_in_executor(executor, fn, *args) -> asyncio.Future      (args only — no kwargs)
#   ProcessPoolExecutor(max_workers: int, mp_context=...)            .shutdown(wait: bool, *, cancel_futures: bool)
#   multiprocessing.get_context("spawn")
# pytest: `asyncio_mode = auto`  (verified: pytest.ini:3) — async tests need no decorator.
```

### Does NOT Exist
- ~~any process-pool helper in `parrot_pipelines`~~ — none; this is the first.
- ~~`AbstractPipeline.executor` / a pool on the pipeline~~ — not today; wiring belongs to the run-orchestration task.
- ~~kwargs support in `run_in_executor`~~ — positional args only; callers needing kwargs pass a module-level wrapper (do **not** accept lambdas: they are not picklable).
- ~~a way to kill a task already running in a worker~~ — `concurrent.futures` cannot; cancellation only stops waiting and drops queued work.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/executor.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_cpu_executor.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- **Start method `spawn`**, via `multiprocessing.get_context("spawn")` — because
  the host is a gunicorn/aiohttp worker with a running event loop and threads;
  `fork`-ing such a process can deadlock on inherited locks. Cost: slower worker
  start-up, paid once per executor (hence *lazy* creation and one executor per run).
- **Bounded**: never more than `max_workers` processes, and never more than
  `max_workers` submissions in flight — guard `run` with an
  `asyncio.Semaphore(max_workers)` so the pool's internal queue cannot grow
  without limit. Create the semaphore lazily inside `run` (it binds to the
  running loop).
- **Cancellation-safe**: if the awaiting coroutine is cancelled, `CancelledError`
  propagates, the semaphore slot is released (`async with`), and the executor
  remains usable. No background `asyncio.Task` is created by `run`.
- `aclose()` is idempotent and non-blocking:
  `shutdown(wait=False, cancel_futures=True)`; after it, `run` raises
  `RuntimeError("CpuExecutor is closed")`.
- A `BrokenProcessPool` (worker died) is logged and re-raised after discarding
  the pool, so the next `run` builds a fresh one.
- `max_workers < 1` ⇒ `ValueError` at construction.
- `fn` must be module-level and picklable; do not try to validate that up front —
  the pickling error from the pool is the message.
- Logging via `logging.getLogger(__name__)`; no `print`. Google-style docstrings, full type hints.
- Inside a worktree: `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.
  Test helper functions are **module-level in the test file** so `spawn` workers
  can import them (pytest's prepend import mode puts the test folder on
  `sys.path`, and `spawn` forwards `sys.path` to its children).

### References in Codebase
- none — new infrastructure; follow the constraints above.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write the block nearly verbatim, then
> complete every `# FILL IN:`. Never change a signature, class name, or path fixed here.

### Steps (in order)
1. Write `executor.py` from the block — *why*: the public surface is fixed by the
   spec skeleton and consumed by the run-orchestration task.
2. Write the tests with **module-level** helper functions — *why*: `spawn`
   workers import helpers by module name; nested functions fail to pickle.
3. Run the tests with the `PYTHONPATH` prefix; `ruff check` the module.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/executor.py` (CREATE)
```python
"""Bounded, lifecycle-managed process executor for CPU-bound perception work (FEAT-574)."""
from __future__ import annotations

import asyncio
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any, Callable, Optional, TypeVar

T = TypeVar("T")

_START_METHOD = "spawn"  # never fork a process that runs an event loop and threads


class CpuExecutor:
    """Lazily created, bounded ProcessPoolExecutor; one per PlanogramCompliance run.

    Usage::

        async with CpuExecutor(max_workers=2) as cpu:
            shapes = await cpu.run(propose_shapes, image, profiles)
    """

    def __init__(self, max_workers: int = 2) -> None:
        """Store limits only; no process is started here.

        Args:
            max_workers: Upper bound of worker processes AND of in-flight submissions.

        Raises:
            ValueError: ``max_workers`` < 1.
        """
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        self.max_workers = max_workers
        self.logger = logging.getLogger(__name__)
        self._pool: Optional[ProcessPoolExecutor] = None
        self._slots: Optional[asyncio.Semaphore] = None
        self._closed = False

    def _ensure_pool(self) -> ProcessPoolExecutor:
        """Create the pool on first use (spawn context)."""
        if self._pool is None:
            self.logger.debug("starting process pool: %d workers (%s)", self.max_workers, _START_METHOD)
            self._pool = ProcessPoolExecutor(
                max_workers=self.max_workers, mp_context=multiprocessing.get_context(_START_METHOD)
            )
        return self._pool

    async def run(self, fn: Callable[..., T], *args: Any) -> T:
        """Run ``fn(*args)`` in a worker process and await its result.

        ``fn`` must be module-level and picklable. Cancellation-safe: cancelling the awaiting
        coroutine releases its slot and leaves the executor usable.

        Raises:
            RuntimeError: The executor was closed.
            BrokenProcessPool: A worker died; the pool is discarded and rebuilt on the next call.
        """
        if self._closed:
            raise RuntimeError("CpuExecutor is closed")
        # FILL IN: lazily create self._slots = asyncio.Semaphore(self.max_workers); inside
        #          `async with self._slots:` await loop.run_in_executor(self._ensure_pool(), fn, *args);
        #          on BrokenProcessPool: log, shutdown(wait=False, cancel_futures=True), self._pool = None,
        #          re-raise — bounded by: no asyncio.create_task, no swallowing of CancelledError.
        raise NotImplementedError

    async def aclose(self) -> None:
        """Release the pool. Idempotent, non-blocking; queued work is cancelled."""
        # FILL IN: set self._closed; if a pool exists: shutdown(wait=False, cancel_futures=True); self._pool = None
        raise NotImplementedError

    async def __aenter__(self) -> "CpuExecutor":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()
```
**Why this shape**: class name, `__init__`, `run` and `aclose` signatures are the
spec skeleton verbatim; `__aenter__/__aexit__` are additive sugar for the
`finally`-style lifecycle the spec requires. The semaphore — not just
`max_workers` — is what makes it *bounded*: `ProcessPoolExecutor` alone accepts
unlimited queued submissions. `spawn` is a deliberate safety choice for a
forked-server host; keep it a module constant so the public signature stays fixed.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_cpu_executor.py` (CREATE)
Write the **Test Specification** scaffold to this path and complete the bodies.

### FILL IN checklist
- [ ] `executor.py::CpuExecutor.run` — semaphore, `run_in_executor`, `BrokenProcessPool` handling
- [ ] `executor.py::CpuExecutor.aclose` — idempotent non-blocking shutdown
- [ ] `test_cpu_executor.py` — every body

---

## Acceptance Criteria

- [ ] AC-1: `await CpuExecutor().run(math.sqrt, 16.0) == 4.0`; no process exists before the first `run` (`_pool is None` after construction).
- [ ] AC-2: with `max_workers=2`, six concurrent `run` calls of a 0.3 s sleeper return ≤ 2 distinct worker PIDs and take ≥ 0.85 s wall-clock (3 waves).
- [ ] AC-3: cancelling a task awaiting `run` raises `CancelledError` in it, leaves no extra pending `asyncio` task, and a following `run` on the same executor still works.
- [ ] AC-4: `aclose()` twice is fine; `run` after `aclose()` raises `RuntimeError`; `async with` closes on exit and on exception.
- [ ] AC-5: an exception raised by `fn` in the worker propagates to the awaiting caller with its type.
- [ ] AC-6: `CpuExecutor(max_workers=0)` raises `ValueError`.
- [ ] AC-7: a worker that dies (`os._exit(1)`) surfaces `BrokenProcessPool`, and the next `run` succeeds on a rebuilt pool.
- [ ] No linting errors: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/executor.py`
- [ ] All tests pass (see Validation Commands).

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_cpu_executor.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_cpu_executor.py
"""Offline tests for CpuExecutor. Helpers are MODULE-LEVEL so spawn workers can import them."""
import asyncio
import math
import os
import time

import pytest
from concurrent.futures.process import BrokenProcessPool

from parrot_pipelines.planogram.perception.executor import CpuExecutor


def _sleep_and_pid(seconds: float) -> int:
    time.sleep(seconds)
    return os.getpid()


def _boom(message: str) -> None:
    raise KeyError(message)


def _die() -> None:
    os._exit(1)


async def test_lazy_pool_and_basic_result():                       # AC-1
    cpu = CpuExecutor()
    assert cpu._pool is None
    try:
        assert await cpu.run(math.sqrt, 16.0) == 4.0
    finally:
        await cpu.aclose()


async def test_cpu_executor_bounded_and_cancellable():             # AC-2 + AC-3 (spec §4 name)
    ...


async def test_close_is_idempotent_and_blocks_further_use():       # AC-4
    ...


async def test_async_context_manager_closes_on_error():            # AC-4
    ...


async def test_worker_exception_propagates():                      # AC-5
    async with CpuExecutor(max_workers=1) as cpu:
        with pytest.raises(KeyError):
            await cpu.run(_boom, "x")


def test_rejects_non_positive_workers():                           # AC-6
    with pytest.raises(ValueError):
        CpuExecutor(max_workers=0)


async def test_broken_pool_is_rebuilt():                           # AC-7
    ...
```

---

## Agent Instructions

1. **Read the spec** (§2 *Execution boundaries*, §3 Module 7 skeleton, §7 "Process pools under gunicorn")
2. **Check dependencies** — TASK-3418 merged (the `perception` package directory exists)
3. **Verify the Codebase Contract** — confirm the package directory exists; nothing else to verify
4. **Implement** from the blueprint; complete every `# FILL IN:`; never change a fixed signature
5. **Verify** all acceptance criteria (AC-2 is timing-based: assert lower bounds only)
6. **Commit code only** — never touch `sdd/`, never edit `perception/__init__.py`
7. **Fill in the Completion Note** in your final report

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD

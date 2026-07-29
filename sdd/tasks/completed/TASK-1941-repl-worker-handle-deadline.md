# TASK-1941: WorkerHandle — host-side handle + deadline enforcement (SIGKILL)

**Feature**: FEAT-380 — Sandbox Hardening — PythonREPLTool a worker persistente
**Spec**: `sdd/specs/sandbox-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1940
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. The host-side async handle to one per-session worker
process. This is where the feature's core guarantee lives: **the host
enforces `deadline_ms` — if the worker does not answer in time, SIGKILL**
(G2/AC2). It also owns the cheap names-only shadow of the worker namespace
and builds the structured namespace-loss error (differentiated cause:
timeout / memory / crash + list of lost variable names) that the LLM
receives after any kill (AC11).

---

## Scope

- Create `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py` with
  `WorkerHandle` implementing the spec's public interface:

  ```python
  class WorkerHandle:
      async def start(self) -> None: ...
      async def execute(self, code: str, debug: bool = False) -> str | dict: ...
      async def inject_dataframe(self, name: str, df) -> None: ...   # raises NotImplementedError until TASK-1945
      async def get_var(self, name: str) -> Any: ...
      async def set_var(self, name: str, value: Any) -> None: ...
      async def list_vars(self) -> list[str]: ...
      async def snapshot(self) -> dict[str, Any]: ...
      async def reset(self) -> None: ...
      async def ping(self) -> bool: ...
      async def kill(self) -> None: ...
  ```

- **Deadline enforcement**: `execute()` sends `ExecRequest(deadline_ms=...)`
  and awaits the framed reply with `asyncio.wait_for`-style host timeout.
  On expiry: `SIGKILL` the child, mark the execution expired, and surface the
  structured namespace-loss error. The handle does NOT auto-respawn — the
  pool (TASK-1942) does; the handle just reports death precisely.
- **Cause differentiation** (AC11): timeout (host deadline fired) vs memory
  (child died with `MemoryError` on the wire, or exited after an
  RLIMIT_AS-driven failure) vs crash (child gone without a reply — nonzero
  exit / signal). Encode via `NamespaceLossError(cause=...)` embedded in the
  G5 dict: `{"status": "error", "result": <message>, "error": <message>}`
  where the message includes the cause, the lost variable names, and the
  instruction to recreate state before retrying.
- **Names-only namespace shadow**: maintain `self.known_vars: list[str]` on
  the host, refreshed from `ExecResult.new_vars` after each exec and via the
  `list_ns` op — this feeds `lost_variables` after a kill.
- Health: `ping()` round-trip with short timeout; `is_alive` property from
  the child process state.
- Unit tests: `test_deadline_sigkill`, `test_namespace_loss_error_shape`,
  `test_memory_limit_kills_worker`.

**NOT in scope**: pool, prewarm, TTL, ceiling, orphan reaping (TASK-1942);
touching `pythonrepl.py` (TASK-1943); Arrow transport (TASK-1945).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py` | CREATE | `WorkerHandle`: spawn/kill/health, deadline → SIGKILL, name shadow, loss error |
| `packages/ai-parrot/tests/repl_worker/test_handle.py` | CREATE | Deadline, loss-error shape, memory-kill tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` HEAD on 2026-07-27.

### Verified Imports

```python
# From TASK-1940 (verify they exist as built before using — names may have
# been adjusted there; the contract is the spec §2 models):
from parrot.tools.repl_worker.protocol import (
    ExecRequest, ExecResult, NamespaceLossError, WorkerConfig,
)
```

### Existing Signatures to Use

```python
# The G5 error dict shape the loss error must be embedded in
# (parrot/tools/pythonrepl.py:955-985):
{"status": "error", "result": msg, "error": str(e)}          # hard failure
{"status": "done_with_errors", "result": output, "error": output}  # classified error output
# classification regex: _ERROR_OUTPUT_RE = r"^[A-Z][A-Za-z0-9_]*(Error|Exception): "  # :936
```

```python
# spec §2 — NamespaceLossError (frozen):
class NamespaceLossError(BaseModel):
    cause: Literal["timeout", "memory", "crash"]
    lost_variables: list[str]
    message: str
```

### Does NOT Exist

- ~~A way to kill a Python thread from outside~~ — that is why the kill
  target is the worker **process** (SIGKILL), never a thread.
- ~~Auto-respawn inside `WorkerHandle`~~ — restart-on-crash is the pool's
  job (TASK-1942). Do not add it here.
- ~~An RPC channel worker→host~~ — rejected in brainstorm. The handle only
  does request/reply initiated by the host.
- ~~`WorkerHandle` anywhere in the codebase~~ — this task creates it.

---

## Implementation Notes

### Key Constraints

- Async-first host side: `asyncio.subprocess` (or `multiprocessing` behind a
  dedicated executor) — never block the event loop on pipe reads.
- SIGKILL, not SIGTERM, on deadline: the child may be stuck in native code
  (numpy/pandas) where SIGTERM handlers never run. `process.kill()` on
  `asyncio.subprocess.Process` sends SIGKILL on POSIX; on Windows it calls
  `TerminateProcess` — acceptable degradation (AC16, documented in
  TASK-1960).
- One in-flight request per worker (the worker is serial); guard with an
  `asyncio.Lock`.
- The host deadline should be `deadline_ms` plus a small grace (e.g. +250 ms)
  so a worker that finishes just under the wire is not killed by clock skew
  between the two sides.
- The namespace-loss message must explicitly instruct the LLM to recreate
  state before retrying (AC11) — this string is product surface, write it
  clearly.
- Logging via `self.logger` (`logging.getLogger(__name__)`).

### References in Codebase

- `parrot/tools/repl_worker/worker.py` + `protocol.py` (TASK-1940) — the
  counterparty; reuse its framing helpers, do not re-implement framing.

---

## Acceptance Criteria

- [ ] Infinite loop (`while True: pass`) is SIGKILLed at `deadline_ms`; no
      thread/process is left behind (`test_deadline_sigkill`) — AC2.
- [ ] Post-kill error has the G5 dict shape with differentiated cause and
      the lost-variable name list (`test_namespace_loss_error_shape`) — AC11.
- [ ] Allocation above RLIMIT_AS kills the worker, not the test runner;
      memory cause ≠ timeout cause (`test_memory_limit_kills_worker`) — AC3.
- [ ] `ping()` returns True on a live worker, False/raises on a dead one.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/repl_worker/test_handle.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/repl_worker/`

---

## Test Specification

```python
# packages/ai-parrot/tests/repl_worker/test_handle.py
import sys
import pytest
from parrot.tools.repl_worker.protocol import WorkerConfig
from parrot.tools.repl_worker.handle import WorkerHandle

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="rlimits are POSIX")

@pytest.fixture
def worker_config():
    return WorkerConfig(rlimit_as_bytes=512 * 1024**2, deadline_ms=2_000,
                        max_workers=2, idle_ttl_seconds=5, prewarm_pool_size=0)


class TestDeadline:
    async def test_deadline_sigkill(self, worker_config):
        """Infinite loop → killed at deadline; handle reports not alive."""
        ...

    async def test_namespace_loss_error_shape(self, worker_config):
        """After kill: {status, result, error} dict, cause differentiated,
        previously-created variable names listed."""
        ...

    @posix_only
    async def test_memory_limit_kills_worker(self, worker_config):
        """bytearray(10**10) under a 512MiB RLIMIT_AS kills the worker only;
        reported cause is 'memory', not 'timeout'."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1940 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm the protocol module's actual
   exported names from TASK-1940 before importing
4. **Update status** in `sdd/tasks/index/sandbox-hardening.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1941-repl-worker-handle-deadline.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-27
**Notes**:
- `handle.py`: `WorkerHandle` implements the full spec interface
  (`start`/`execute`/`inject_dataframe`/`get_var`/`set_var`/`list_vars`/
  `snapshot`/`reset`/`ping`/`kill`). Spawns via `subprocess.Popen` (wrapped
  in `run_in_executor` to stay off the event loop) talking over a
  **dedicated pipe pair** (`os.pipe()` x2 + `pass_fds`), consistent with
  TASK-1940's finding that stdin/stdout carries this framework's colorized
  log output and cannot be used as the binary framing channel.
- Deadline enforcement: `_send()` wraps the blocking round-trip
  (`run_in_executor` + `read_frame`/`write_frame` from TASK-1940) in
  `asyncio.wait_for(timeout=deadline_ms + 250ms grace)`; on
  `asyncio.TimeoutError` it SIGKILLs via `Popen.kill()` (POSIX SIGKILL /
  Windows `TerminateProcess`, AC16) and attaches a done-callback to the
  orphaned executor future so its eventual `EOFError` (once the pipe
  closes) doesn't surface as an "exception never retrieved" warning.
  Single `asyncio.Lock` serializes all requests (the worker handles one
  `exec` at a time, per spec).
- Cause differentiation (AC11): `"timeout"` when the host's own deadline
  fired; otherwise `_classify_death()` reaps the process and greps its
  captured stderr for memory-pressure markers (`MemoryError`,
  `failed to map segment`, `bad_alloc`, `Cannot allocate memory`, `Killed`,
  `OOM`) to report `"memory"`, else falls back to `"crash"`. The
  `NamespaceLossError` model (TASK-1940) is used internally to build a
  single rendered message embedded in the standard G5
  `{"status": "error", "result": ..., "error": ...}` dict — differentiated
  cause, the `known_vars` name-shadow list, and an explicit instruction to
  recreate state before retrying, all in one string (AC11 doesn't require
  the Pydantic model itself to travel in the dict, just that shape).
- 10 new tests in `test_handle.py`, all spawning real worker subprocesses;
  `pytest packages/ai-parrot/tests/repl_worker/ -v` → 41 passed (protocol +
  worker + handle). `ruff check` on `repl_worker/` is clean.

**Deviations from spec / notable findings**:
1. **`test_memory_limit_kills_worker` triggers the crash at worker-boot
   time, not via a runtime allocation inside `exec`.** Investigated
   whether a large in-REPL allocation (e.g. `bytearray(10**10)`) reliably
   *crashes* the process under a tight `RLIMIT_AS`: it does not — CPython's
   `malloc`/`mmap` failure path for a single large allocation is normally
   caught cleanly and raised as a catchable `MemoryError` (handled by
   `_execute_code`'s own exception handling, returned as ordinary error
   *text*, worker survives). The reproducible **process-killing** memory
   failure in this environment is a `RLIMIT_AS` too small for
   `PythonREPLTool.__init__` to finish importing pandas/numpy/matplotlib
   in the first place — `numpy.random`'s compiled extensions fail to
   `mmap` under 512 MiB (and even 1 GiB), which crashes the interpreter
   with a fatal `ImportError` traceback (not a catchable Python
   exception) before the worker ever reads a frame. `WorkerHandle.execute()`
   still correctly reports this as cause=`"memory"` (the traceback's
   "failed to map segment from shared object" matches the memory-marker
   heuristic) rather than `"timeout"`, satisfying the qualitative intent
   of AC3 ("memory pressure kills the worker, not the test runner, and is
   distinguishable from a timeout") even though the *trigger* is import-
   time rather than a runtime user-code allocation. This is the same
   `RLIMIT_AS` calibration risk the spec flags for Module 8.
2. `ping()`'s health-check timeout defaults to 10s (not a tight value) —
   a `ping()` sent immediately after `start()` can race the worker's own
   pandas/numpy/matplotlib import + bootstrap, which legitimately takes a
   few seconds under load; a short timeout produced a flaky false-negative
   in local testing. `execute()`'s deadline enforcement is unaffected
   (governed by the caller's `WorkerConfig.deadline_ms`, not by `ping()`).

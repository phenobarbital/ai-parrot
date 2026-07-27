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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

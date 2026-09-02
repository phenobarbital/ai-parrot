# TASK-2759: WorkerHandle — readiness future, lethal flag, pending-reply drain, messaged errors

**Feature**: FEAT-500 — REPL Worker Readiness Handshake & Non-Lethal Namespace Timeouts
**Spec**: `sdd/specs/bug-workerpool-repl.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2757, TASK-2758
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 — the core of the fix. `WorkerHandle` currently (a)
returns from `start()` right after `Popen` with no readiness notion, (b)
uses hard-coded `5.0`/`10.0`/`30.0` s budgets for every non-exec request,
and (c) SIGKILLs the worker on *any* timeout and re-raises a bare
`TimeoutError` whose `str()` is `''` (`handle.py:240-263, 405-429`). This
task makes the handle read the worker's `ReadyResponse` (TASK-2758) before
any request, applies the U2 policy (only `execute()` kills), and
guarantees every failure carries a message.

---

## Scope

- **Exceptions** (module level in `handle.py`):
  `class WorkerBootstrapError(RuntimeError)` and
  `class NamespaceTimeoutError(TimeoutError)`; export both from
  `repl_worker/__init__.py` (`__all__`).
- **Readiness**: in `start()`, after the pipes are opened and the drain
  task is created, create `self._ready_task = loop.create_task(self._await_ready())`
  and `self._ready: asyncio.Future[ReadyResponse]`. `_await_ready()` reads
  ONE frame via `loop.run_in_executor(self._executor, read_frame, self._from_worker)`
  under `asyncio.wait_for(..., self._config.bootstrap_timeout_ms / 1000)`.
  On a `ReadyResponse` → set the future's result, log
  `"WorkerHandle: worker pid=%s ready in %d ms"`. On timeout, `EOFError`,
  `OSError`, `ValueError`, or a first frame that is not `ReadyResponse` →
  `await self._kill_process()` and set the future's exception to
  `WorkerBootstrapError(f"REPL worker pid={pid} did not become ready within {budget_ms} ms ({cause}); stderr tail: {tail}")`
  using the last ≤5 lines of `self._stderr_tail`.
- `async def wait_ready(self, timeout_s: float | None = None) -> ReadyResponse`
  (awaits the future; re-raises `WorkerBootstrapError`) and
  `@property is_ready -> bool`.
- **`_send(self, request, timeout_s, *, lethal: bool = False)`** under
  `self._lock`: (1) `await self.wait_ready()`; (2) if `self._pending_reply`
  is not `None`, `await asyncio.wait_for(self._pending_reply, timeout_s)`,
  then clear it and discard the result — on timeout raise
  `NamespaceTimeoutError` (pending kept, still non-lethal); (3) existing
  alive check + round-trip; (4) on `asyncio.TimeoutError`: `lethal=True` →
  kill + re-raise (today's behaviour); `lethal=False` → park the future in
  `self._pending_reply`, attach the exception-retrieving done-callback
  (as :262 does today), and raise
  `NamespaceTimeoutError(f"repl_worker[pid={pid}]: {op!r} request did not answer within {timeout_s:.1f}s; the worker is still alive and the late reply will be drained on the next call")`.
- **`execute()`**: pass `lethal=True`; add `WorkerBootstrapError` to the
  `except (EOFError, OSError, ValueError)` tuple so it becomes the G5 loss
  dict with `cause="crash"` and `detail=str(exc)`.
- **Budgets**: `get_var`, `set_var`, `list_vars`, `snapshot`, `reset`,
  `inject_dataframe` use `self._config.namespace_timeout_ms / 1000` and
  `lethal=False`. `ping(timeout_s=10.0)` keeps its argument, `lethal=False`,
  and returns `False` (not raise) on any failure as today.
- **`kill()`**: cancel `_ready_task` (suppress `CancelledError`), cancel
  and drop `_pending_reply`, then the existing teardown.
- Unit tests in `tests/repl_worker/test_handle.py` (see Test Specification).

**NOT in scope**: pool changes (TASK-2760), `pythonrepl.py`/`pythonpandas.py`/`clients/base.py` (TASK-2761), integration regression (TASK-2762).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py` | MODIFY | readiness, lethal flag, drain, exceptions, budgets |
| `packages/ai-parrot/src/parrot/tools/repl_worker/__init__.py` | MODIFY | export `NamespaceTimeoutError`, `WorkerBootstrapError` |
| `packages/ai-parrot/tests/repl_worker/test_handle.py` | MODIFY | readiness / non-lethal / lethal tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# handle.py:19-51 (current imports) — asyncio, concurrent.futures, contextlib, json, logging, os, subprocess, sys, typing
from .protocol import (ExecRequest, ExecResult, GetVarRequest, InjectDfRequest, ListNsRequest, ListNsResponse,
    NamespaceLossError, PingRequest, PongResponse, ResetRequest, SetVarRequest, SnapshotRequest, SnapshotResponse,
    ValueResponse, WorkerConfig, decode_value, encode_value, read_frame, write_frame)   # handle.py:31-51
from .protocol import ReadyResponse        # add — created by TASK-2757
# tests: from parrot.tools.repl_worker import WorkerHandle, WorkerConfig  (repl_worker/__init__.py:14-16)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/repl_worker/handle.py
_DEADLINE_GRACE_MS = 250                                               # :58
class WorkerHandle:                                                    # :74
    def __init__(self, config=None, output_dir=None, repl_kwargs=None, executor=None)   # :77-147
        self._config: WorkerConfig; self._proc: Optional[subprocess.Popen] = None       # :107-110
        self._to_worker / self._from_worker: Optional[BinaryIO] = None                  # :111-112
        self._lock = asyncio.Lock()                                                     # :113
        self._executor: concurrent.futures.Executor (shared or self-owned, 4 threads)   # :114-117
        self._stdio_executor = ThreadPoolExecutor(max_workers=2)                        # :136-138
        self._stdio_task: Optional[asyncio.Task] = None; self._stderr_tail: list[str] = []; self.known_vars: list[str] = []   # :139-147
    @property def is_alive(self) -> bool                               # :149-152
    async def start(self) -> None                                      # :154-197  Popen at :181; fdopen :185-186; log :187; drain task :197
    def _roundtrip(self, request) -> Any                               # :235-238  write_frame(self._to_worker, request); return read_frame(self._from_worker)
    async def _send(self, request, timeout_s: float) -> Any            # :240-263
        # :249 async with self._lock; :250-251 EOFError("worker process is not running") if not alive
        # :252 future = loop.run_in_executor(self._executor, self._roundtrip, request)
        # :254 await asyncio.wait_for(future, timeout=timeout_s); :255-263 on TimeoutError: await self._kill_process(); future.add_done_callback(...); raise
    async def _kill_process(self) -> None                              # :265-281  idempotent; only touches executor when something is alive
    async def _classify_death(self) -> str                             # :283-311
    def _build_loss_error(self, cause: str, detail: str) -> dict       # :313-334
    async def execute(self, code, debug=False) -> str | dict           # :336-362  :348 deadline_s; :351 _send(request, deadline_s); :352-356 except mapping
    async def inject_dataframe(self, name, df) -> None                 # :364-403  :396 await self._send(request, timeout_s=30.0)
    async def get_var(self, name) -> Any                               # :405-408  _send(GetVarRequest(name=name), 5.0)
    async def set_var(self, name, value) -> None                       # :410-413  _send(SetVarRequest(...), 5.0)
    async def list_vars(self) -> list[str]                             # :415-419  _send(ListNsRequest(), 5.0)
    async def snapshot(self) -> dict                                   # :421-424  _send(SnapshotRequest(), 10.0)
    async def reset(self) -> None                                      # :426-429  _send(ResetRequest(), 30.0)
    async def ping(self, timeout_s: float = 10.0) -> bool              # :431-449
    async def kill(self) -> None                                       # :451-486  does NOT take self._lock (documented at :454-466); cancels _stdio_task :469-473; closes streams :474-481; shuts executors :482-486

# packages/ai-parrot/tests/repl_worker/test_handle.py
fixture real_worker_config  -> WorkerConfig(deadline_ms=5_000, max_workers=2, idle_ttl_seconds=5, prewarm_pool_size=0)   # :20-23
fixture fast_deadline_config -> WorkerConfig(deadline_ms=1_500, ...)                                                      # :26-29
class TestDeadline :51 · class TestPing :104 · class TestNamespaceAPI :120  (test_get_set_var_round_trip :135, test_list_vars_and_snapshot :146)
```

### Does NOT Exist
- ~~`WorkerHandle.wait_ready` / `is_ready` / `_ready` / `_ready_task` / `_pending_reply` / `_await_ready`~~ — you create them.
- ~~`_send(..., lethal=...)`~~ — today `_send` has no keyword; every timeout is lethal.
- ~~`NamespaceTimeoutError` / `WorkerBootstrapError`~~ — you create them (here, not in `protocol.py`).
- ~~request/response sequence ids in frames~~ — the pipe is strictly ordered; the drain step is what keeps it aligned. Do not add ids.
- ~~`WorkerHandle.ping()` callers~~ — none exist anywhere in `src/` (grep verified); keep its signature.
- ~~`concurrent.futures.TimeoutError` distinct from `asyncio.TimeoutError`~~ — on Python ≥3.11 (project floor) `asyncio.TimeoutError is TimeoutError`; catch `asyncio.TimeoutError` as the code does today.

---

## Implementation Notes

### Pattern to Follow
```python
# handle.py:252-263 (today) — keep this shape, branch on `lethal`
future = loop.run_in_executor(self._executor, self._roundtrip, request)
try:
    return await asyncio.wait_for(future, timeout=timeout_s)
except asyncio.TimeoutError:
    if lethal:
        await self._kill_process()
        future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
        raise
    self._pending_reply = future
    future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
    raise NamespaceTimeoutError(...)   # message per Scope
```

### Key Constraints
- `_await_ready` and `_roundtrip` both read `self._from_worker` on `self._executor`; they must never overlap. Readiness completes (or fails) before `_send` reads — guaranteed by `await self.wait_ready()` inside `_send` under `self._lock`.
- `kill()` deliberately does NOT take `self._lock` (`handle.py:454-466`) — keep that. Cancelling `_ready_task` while its executor read is blocked is fine: the process kill closes the pipe and the read returns EOF.
- `asyncio.wait_for` on a `run_in_executor` future does not stop the thread — that is why the parked future must be drained, not abandoned.
- A `wait_ready()` failure must be awaitable by multiple callers (pool + first `_send`): use a Future set once, never re-created.
- Do not lower the default budgets: `bootstrap_timeout_ms` 30 000 / `namespace_timeout_ms` 30 000 (spec §7 risks).
- Every raised exception must have a non-empty `str()`.

### References in Codebase
- `handle.py:240-263` — `_send` (modify)
- `handle.py:336-362` — `execute` (lethal caller)
- `handle.py:451-486` — `kill`
- `test_handle.py:51-160` — existing deadline/ping/namespace tests to keep green

---

## Acceptance Criteria

- [ ] `wait_ready()` after `start()` returns a `ReadyResponse`; `is_ready` becomes `True`
- [ ] With `bootstrap_timeout_ms=500` and a worker whose `setup_code` sleeps 3 s: `wait_ready()` raises `WorkerBootstrapError` whose message contains the pid and `500`; `is_alive` is `False` afterwards
- [ ] With a 3 s-sleeping `setup_code` and default budgets: `set_var()` called immediately after `start()` succeeds (no timeout, no kill)
- [ ] Non-lethal timeout: `NamespaceTimeoutError` with non-empty message, `is_alive` stays `True`, the next namespace call succeeds (parked reply drained)
- [ ] `execute()` deadline still kills and returns the G5 dict (`TestDeadline` unchanged in outcome)
- [ ] `execute()` on a handle whose bootstrap failed returns `{status: "error", ...}` mentioning the bootstrap error — never raises
- [ ] No literal `5.0` / `30.0` request budget remains in `handle.py` (`10.0` only as `ping`'s default arg)
- [ ] `pytest packages/ai-parrot/tests/repl_worker/test_handle.py -v` passes; `ruff check` clean; `from parrot.tools.repl_worker import NamespaceTimeoutError, WorkerBootstrapError` works
- [ ] Spec AC1 (handle half), AC2, AC3, AC4, AC6, AC12 (handle half)

---

## Test Specification

```python
# packages/ai-parrot/tests/repl_worker/test_handle.py (additions)
import asyncio, time, pytest
from parrot.tools.repl_worker import WorkerHandle, WorkerConfig, NamespaceTimeoutError, WorkerBootstrapError
from parrot.tools.repl_worker.protocol import ReadyResponse

SLOW = {"setup_code": "import time\ntime.sleep(3)"}   # delays the worker's own bootstrap; no prod hook

class TestReadiness:
    async def test_wait_ready_success(self, real_worker_config, tmp_path):
        h = WorkerHandle(real_worker_config, output_dir=str(tmp_path))
        await h.start()
        try:
            ready = await h.wait_ready()
            assert isinstance(ready, ReadyResponse) and h.is_ready
        finally:
            await h.kill()

    async def test_bootstrap_timeout_kills_and_reports(self, tmp_path):
        cfg = WorkerConfig(deadline_ms=5_000, max_workers=2, idle_ttl_seconds=5, prewarm_pool_size=0, bootstrap_timeout_ms=500)
        h = WorkerHandle(cfg, output_dir=str(tmp_path), repl_kwargs=SLOW)
        await h.start()
        try:
            with pytest.raises(WorkerBootstrapError, match="500"):
                await h.wait_ready()
            assert h.is_alive is False
        finally:
            await h.kill()

    async def test_send_waits_for_ready(self, real_worker_config, tmp_path):
        h = WorkerHandle(real_worker_config, output_dir=str(tmp_path), repl_kwargs=SLOW)
        await h.start()
        try:
            await h.set_var("x", 1)          # must NOT time out at 5 s
            assert await h.get_var("x") == 1
        finally:
            await h.kill()

class TestNonLethalTimeouts:
    async def test_namespace_timeout_is_non_lethal(self, tmp_path, monkeypatch):
        cfg = WorkerConfig(deadline_ms=5_000, max_workers=2, idle_ttl_seconds=5, prewarm_pool_size=0, namespace_timeout_ms=200)
        h = WorkerHandle(cfg, output_dir=str(tmp_path))
        await h.start(); await h.wait_ready()
        real = h._roundtrip
        def slow(request):
            time.sleep(1.0)
            return real(request)
        monkeypatch.setattr(h, "_roundtrip", slow)
        try:
            with pytest.raises(NamespaceTimeoutError) as ei:
                await h.list_vars()
            assert str(ei.value)
            assert h.is_alive
            monkeypatch.setattr(h, "_roundtrip", real)
            await asyncio.sleep(1.2)                     # let the parked reply land
            assert isinstance(await h.list_vars(), list) # drained, then answered
        finally:
            await h.kill()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2 Overview, §3 Module 3, §7 risks)
2. **Check dependencies** — TASK-2757 and TASK-2758 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-read `handle.py` before editing; line numbers may have shifted
4. **Update status** in `sdd/tasks/index/bug-workerpool-repl.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met (run the whole `tests/repl_worker/` directory, not only `test_handle.py`)
7. **Move this file** to `sdd/tasks/completed/TASK-2759-handle-readiness-and-nonlethal-timeouts.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

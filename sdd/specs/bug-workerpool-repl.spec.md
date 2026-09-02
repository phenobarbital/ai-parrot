---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: REPL Worker Readiness Handshake & Non-Lethal Namespace Timeouts (`bug-workerpool-repl`)

**Feature ID**: FEAT-500
**Date**: 2026-09-02
**Author**: Jesus Lara (jlara@trocglobal.com) + Claude
**Status**: approved
**Target version**: next minor (ships with the next release from `dev` — U1)
**Proposal**: `sdd/proposals/bug-workerpool-repl.proposal.md` (research id FEAT-518 → audit trail at `sdd/state/FEAT-518/`)

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Agents using `python_repl_pandas` (`PythonPandasTool`, the `PandasAgent`
tool) become **permanently unusable** on a loaded host: every call fails
after exactly 5 s with a blank error (`Error executing Python code: `,
`ValueError('')`), and the pool logs `worker is dead, restarting` on a 5 s
grid forever (proposal §0, reproduced in F016).

Root cause (proposal §3, confidence high, reproduced on `dev`):

1. `WorkerHandle.start()` returns right after `Popen` and
   `WorkerPool._top_up_prewarmed()` logs `prewarmed worker ready` in the
   same millisecond — **no readiness handshake exists**. The child still
   has to import the whole `parrot` framework plus pandas and run the
   REPL bootstrap (≈2.4 s idle, 12–14 s under 3× CPU oversubscription;
   ~80 % of the import is `parrot` framework init, not pandas — F015/F018).
2. `PythonPandasTool._get_worker_handle()` seeds `df_locals` into every
   freshly bound worker **before** the caller's request, using
   `WorkerHandle.set_var()` — which has a **hard-coded 5.0 s timeout**
   (`handle.py:412`, same for `get_var`/`list_vars`).
3. `WorkerHandle._send()` **SIGKILLs the worker on any timeout** and
   re-raises a bare `TimeoutError` whose `str()` is `''`.
4. `WorkerPool.acquire()` then binds the *oldest* spare — spawned one
   failure-cycle (5 s) earlier and equally cold — so the next call kills
   it too. While bootstrap > 5 s, **no worker ever reaches
   `repl_worker: ready`**: a self-sustaining death spiral.

The bug is latent since 2026-07-28 (TASK-1941/1942/1944) and identical on
`main`; nothing on these paths changed in the two weeks before the
incident (F012/F013).

### Goals

- **G1 — Readiness is explicit.** A worker is only considered *ready*
  after it has finished bootstrapping and said so; no request is ever
  written to a worker that has not signalled readiness, and a spare is
  only counted as *prewarmed* once ready.
- **G2 — Only the `execute()` deadline kills** (U2, resolved). Timeouts on
  every other request type (`get_var`, `set_var`, `list_vars`,
  `snapshot`, `reset`, `inject_dataframe`, `ping`) are **non-lethal**: the
  caller gets a *messaged* error, the worker stays alive and the session
  namespace is preserved.
- **G3 — No blank errors.** Every failure surfaced by the worker layer
  carries a human-readable message all the way to the LLM
  (`ToolResult.error`, `ValueError(...)` in the client).
- **G4 — Timeouts are configurable** via `WorkerConfig` (bootstrap budget
  and non-exec request budget), with defaults that hold on a loaded host.
- **G5 — Restart loops are visible.** A session that keeps restarting its
  worker is logged as such (count + cause) instead of silently burning
  spares.
- **G6 — The spiral is a regression test.** Proposal Probe B (F016) becomes
  a deterministic test: a worker whose bootstrap is slower than the old 5 s
  budget must still serve seeding + execute successfully.
- **G7 — Bootstrap cost is measured, not guessed** (U3, partially
  resolved). The local `-X importtime` profile is recorded and a host-side
  probe procedure is documented for U3b.

### Non-Goals (explicitly out of scope)

- **Trimming the worker's import surface** (making
  `parrot.tools.repl_worker.worker` avoid the `parrot.tools` /
  `parrot.plugins` → `navconfig` / vault / documentdb / `navigator` auth
  import chain — F018). It is the right follow-up once U3b is measured on
  the host, but it touches package `__init__` layering across
  `parrot.tools`, `parrot.security` and `parrot.conf` and deserves its own
  spec. This spec only *measures* it (Module 7).
- Changing the one-worker-per-tool-instance session model, the prewarm
  pool size semantics, or the Arrow/shm DataFrame transport.
- A hotfix on `main` (rejected in U1 — feature flow on `dev`).
- Reordering `PythonPandasTool` seeding so DataFrames go first "to buy
  time" — that would only hide the race behind hash order (F009/F016 C6).
- Windows-specific work beyond keeping the existing `Popen.kill()`
  degradation documented.

---

## 2. Architectural Design

### Overview

Two protocol-level changes and one policy change, all inside
`parrot/tools/repl_worker/`, plus small legibility fixes at the tool and
client layers:

1. **Ready frame (G1).** The worker writes one `ReadyResponse` frame
   (`op="ready"`, with its pid and measured bootstrap milliseconds) on the
   control pipe *after* `WorkerNamespace` is constructed and *before*
   entering the service loop. Host-side, `WorkerHandle.start()` still
   returns right after spawning, but it arms an internal readiness future:
   a background read of that first frame bounded by
   `WorkerConfig.bootstrap_timeout_ms`. `WorkerHandle._send()` awaits
   readiness before writing anything, so **every** caller — namespace API,
   seeding, execute — gets readiness for free, and `WorkerPool` awaits
   `wait_ready()` before it appends a spare to `_prewarmed` (and before it
   logs `prewarmed worker ready`). A worker that never sends `ready`
   within the bootstrap budget is killed and surfaces a
   `WorkerBootstrapError` naming the pid, the budget and the stderr tail.
2. **Lethal vs. non-lethal timeouts (G2/G4).** `_send()` gains a `lethal`
   flag. Only `execute()` passes `lethal=True` (deadline_ms + grace, SIGKILL
   + G5 loss dict, unchanged). Every other request uses
   `WorkerConfig.namespace_timeout_ms` (default 30 000) and, on timeout,
   raises `NamespaceTimeoutError` (subclass of `TimeoutError`, **with a
   message**) while leaving the process alive. Because the pipe is a strict
   request/response channel, the still-pending reply is retained as
   `_pending_reply` and drained by the next `_send()` before it writes —
   so a late reply can never be mis-attributed to a later request.
3. **Legibility (G3/G5).** `PythonREPLTool._execute()` never emits an
   empty `error`; `PythonPandasTool` logs (debug) the exceptions it
   swallows around `list_vars`/`get_var`; `AbstractClient` never raises
   `ValueError('')`; `WorkerPool` counts per-session restarts and warns on
   a restart loop.

Bootstrap timeout is the one deliberate exception to "only execute
kills": a worker that cannot even boot within `bootstrap_timeout_ms` is
not a live worker — it is killed and reported (see §8 Q1, default agreed
here, revisit if the user objects).

### Component Diagram

```
PythonPandasTool._execute()
   │  list_vars() ── seeding set_var()/inject_dataframe() ── execute()
   ▼
PythonREPLTool._worker_session() ──► WorkerPool.acquire(session_id)
                                          │  spares: only READY handles
                                          │  fresh spawn: returned immediately
                                          ▼
                                    WorkerHandle
                                      start()  ── Popen ── arm _ready future
                                      _await_ready() ◄──── first frame == ReadyResponse
                                      _send(req, timeout, lethal)
                                         ├─ await wait_ready()            (bootstrap_timeout_ms; kill on expiry → WorkerBootstrapError)
                                         ├─ drain _pending_reply if any
                                         ├─ write_frame / read_frame (executor)
                                         ├─ lethal=True  (execute only) → timeout ⇒ SIGKILL + G5 loss dict
                                         └─ lethal=False (everything else) → timeout ⇒ NamespaceTimeoutError, worker alive, reply parked
                                          ▲
                        control pipe      │
                                          ▼
                              worker.py serve()
                                 WorkerNamespace(...)   ← parrot + pandas import + REPL bootstrap
                                 write_frame(ReadyResponse(pid, bootstrap_ms))   ← NEW
                                 loop: read_frame → _dispatch → write_frame
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.tools.repl_worker.protocol` | extends | new `ReadyResponse`, two new `WorkerConfig` fields, `_MESSAGE_TYPES["ready"]` |
| `parrot.tools.repl_worker.worker.serve()` | modifies | writes the ready frame before the loop; measures bootstrap ms |
| `parrot.tools.repl_worker.handle.WorkerHandle` | modifies | readiness future + `wait_ready()`, `_send(lethal=...)`, pending-reply drain, new exceptions |
| `parrot.tools.repl_worker.pool.WorkerPool` | modifies | awaits readiness before appending spares; restart-loop counter + warning |
| `parrot.tools.repl_worker.__init__` | extends | exports `ReadyResponse`, `NamespaceTimeoutError`, `WorkerBootstrapError` |
| `parrot.tools.pythonrepl.PythonREPLTool` | modifies | non-empty `error` on the `_execute` exception path |
| `parrot.tools.pythonpandas.PythonPandasTool` | modifies | debug-log swallowed namespace failures; seeding failures carry the variable name |
| `parrot.clients.base.AbstractClient` | modifies (1 line) | `raise ValueError(result.error or <fallback text>)` |
| `docs/repl-worker-sandbox.md` | updates | failure-mode table, `WorkerConfig` table, readiness section, bootstrap-profile procedure |
| `packages/ai-parrot/tests/repl_worker/` | extends | new tests per §4 |

### Data Models

```python
# parrot/tools/repl_worker/protocol.py  (additions)
class ReadyResponse(BaseModel):
    """First frame a worker writes, after WorkerNamespace is built (FEAT-500)."""
    op: Literal["ready"] = "ready"
    pid: int
    bootstrap_ms: int   # monotonic ms from worker main() entry to ready

class WorkerConfig(BaseModel):
    ...existing fields unchanged...
    bootstrap_timeout_ms: int = 30_000   # host waits this long for ReadyResponse; expiry kills (Q1)
    namespace_timeout_ms: int = 30_000   # budget for every NON-exec request; expiry is non-lethal (U2)
```

### New Public Interfaces

```python
# parrot/tools/repl_worker/handle.py  (additions / changed signatures)
class WorkerBootstrapError(RuntimeError):
    """Worker did not send ReadyResponse within bootstrap_timeout_ms (it was killed)."""

class NamespaceTimeoutError(TimeoutError):
    """A non-exec request timed out; the worker is still alive. Always carries a message."""

class WorkerHandle:
    @property
    def is_ready(self) -> bool: ...
    async def wait_ready(self, timeout_s: float | None = None) -> ReadyResponse: ...
    async def _send(self, request: Any, timeout_s: float, *, lethal: bool = False) -> Any: ...
    # execute(): unchanged signature, now the ONLY caller passing lethal=True
    # get_var/set_var/list_vars/snapshot/reset/inject_dataframe/ping: timeout comes from
    #   self._config.namespace_timeout_ms (ping keeps its explicit arg), lethal=False

# parrot/tools/repl_worker/pool.py
class WorkerPool:
    def restart_count(self, session_id: str) -> int: ...   # observability only
```

---

## 3. Module Breakdown

> Modules map 1:1 to task artifacts. Order is the dependency order.

### Module 1: Protocol — ready frame + config fields
- **Path**: `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py`, `packages/ai-parrot/src/parrot/tools/repl_worker/__init__.py`
- **Responsibility**: add `ReadyResponse` (registered in `_MESSAGE_TYPES` under `"ready"`), add `WorkerConfig.bootstrap_timeout_ms` and `WorkerConfig.namespace_timeout_ms` (validated `> 0`), export the new model and the two new exception classes (defined in Module 3) from the package `__init__`. Round-trip test for the new frame.
- **Depends on**: —

### Module 2: Worker — emit the ready frame
- **Path**: `packages/ai-parrot/src/parrot/tools/repl_worker/worker.py`
- **Responsibility**: `main()` records `time.monotonic()` on entry and passes it to `serve()`; `serve()` writes `ReadyResponse(pid=os.getpid(), bootstrap_ms=...)` to `out_stream` immediately after `WorkerNamespace(...)` is constructed and before the `while True` loop. The existing `repl_worker: ready` log line stays (now logging `bootstrap_ms`). If `WorkerNamespace` construction raises, the worker must still exit non-zero (current behaviour) — the host's bootstrap timeout / EOF path handles it.
- **Depends on**: Module 1

### Module 3: Handle — readiness future, lethal flag, pending-reply drain, exceptions
- **Path**: `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py`
- **Responsibility**:
  - `start()`: after spawning and opening the pipes, create `self._ready_task = loop.create_task(self._await_ready())`, which reads exactly one frame via `run_in_executor(self._executor, read_frame, self._from_worker)` under `asyncio.wait_for(..., bootstrap_timeout_ms/1000)`. Success → store the `ReadyResponse`, resolve readiness, `logger.debug("... ready in %d ms")`. Timeout or `EOFError`/`OSError`/`ValueError` (including a non-`ReadyResponse` first frame) → `await self._kill_process()`, resolve readiness with `WorkerBootstrapError` whose message names pid, the budget, the observed cause and the last stderr lines from `_stderr_tail`.
  - `wait_ready()`: awaits the readiness future (re-raises `WorkerBootstrapError`); `is_ready` property.
  - `_send(request, timeout_s, *, lethal=False)`: under `self._lock`: (a) `await self.wait_ready()`; (b) if `self._pending_reply` is set, `await asyncio.wait_for(pending, timeout_s)` and discard its result (a timeout here raises `NamespaceTimeoutError` again, still non-lethal, pending kept); (c) round-trip as today; (d) on `asyncio.TimeoutError`: if `lethal` → kill + re-raise (unchanged); else → park the future in `self._pending_reply`, add the done-callback that retrieves its exception, and `raise NamespaceTimeoutError(f"repl_worker[pid={pid}]: {request.op!r} did not answer within {timeout_s:.1f}s; worker is still alive, reply will be drained on the next call")`.
  - `execute()`: pass `lethal=True`; unchanged G5 mapping. Add `WorkerBootstrapError` to the `except` tuple that builds the loss dict (cause `"crash"`, detail = the error message) so a failed *fresh* spawn on the execute path still returns the G5 dict rather than raising.
  - `get_var/set_var/list_vars/snapshot/reset/inject_dataframe`: use `self._config.namespace_timeout_ms / 1000` (remove the literal `5.0`/`10.0`/`30.0`); `ping(timeout_s=10.0)` keeps its explicit argument, non-lethal.
  - `kill()`: also cancel `_ready_task` and cancel/discard `_pending_reply`.
- **Depends on**: Module 1, Module 2

### Module 4: Pool — readiness-gated spares + restart-loop visibility
- **Path**: `packages/ai-parrot/src/parrot/tools/repl_worker/pool.py`
- **Responsibility**:
  - `_top_up_prewarmed()`: after `_spawn_handle()`, `await handle.wait_ready()` **outside** `self._lock`; on `WorkerBootstrapError` log with `logger.exception` and return (mirrors the existing spawn-failure branch). Only then append + log `prewarmed worker ready (pid=%s, bootstrap_ms=%d, pool size=%d)`.
  - `acquire()`: unchanged binding logic (spares are ready by construction; a fresh spawn is returned immediately — its first `_send()` awaits readiness). Maintain `self._restarts: dict[str, list[float]]` (monotonic timestamps); on the `worker is dead, restarting` branch append `now`, prune entries older than 60 s, and if `len >= 3` log `logger.warning("WorkerPool: session %r restarted %d times in the last 60s — possible restart loop (last cause: %s)")` where the cause comes from the dead handle (exit code / `_stderr_tail` last line). Expose `restart_count(session_id)`.
  - `shutdown()`: unchanged; add cancellation of in-flight `_ready_task`s through `handle.kill()` (Module 3 already does it).
- **Depends on**: Module 3

### Module 5: Tool & client legibility
- **Path**: `packages/ai-parrot/src/parrot/tools/pythonrepl.py`, `packages/ai-parrot/src/parrot/tools/pythonpandas.py`, `packages/ai-parrot/src/parrot/clients/base.py`
- **Responsibility**:
  - `PythonREPLTool._execute()` exception path: `detail = str(e) or type(e).__name__`; `result = f"ToolError: {type(e).__name__}: {detail}"`; `error = detail`. Never an empty `error`.
  - `PythonPandasTool._get_worker_handle()`: wrap each seeding call so a `NamespaceTimeoutError`/`WorkerBootstrapError` is re-raised with the variable name (`f"seeding {name!r} into the REPL worker failed: {exc}"`); keep the identity-based reseed logic.
  - `PythonPandasTool._execute()`: the two `except Exception: pass`-style blocks around `list_vars()`/`get_var()` log at `debug` with the exception text.
  - `AbstractClient` (`clients/base.py:1500`): `raise ValueError(result.error or f"Tool {tool_name} returned status=error without a message")`.
- **Depends on**: Module 3

### Module 6: Regression & behaviour tests
- **Path**: `packages/ai-parrot/tests/repl_worker/test_protocol.py`, `test_worker.py`, `test_handle.py`, `test_pool.py`, `test_integration.py`, `test_e2e.py`
- **Responsibility**: implement §4. The cold-start reproduction uses `PythonREPLTool(setup_code=...)` / `PythonPandasTool(setup_code=...)` with a setup snippet that sleeps (e.g. `import time; time.sleep(8)`) — `setup_code` is mirrored into the worker via `repl_kwargs` and executed during the worker's own `PythonREPLTool.__init__` → `_bootstrap()` with `enforce_security=False` (`pythonrepl.py:440`), so bootstrap is delayed deterministically **without any test hook in production code**. Namespace non-lethal timeout is tested with a monkeypatched `WorkerHandle._roundtrip` that sleeps past a tiny `namespace_timeout_ms` before answering.
- **Depends on**: Modules 1–5

### Module 7: Docs + bootstrap profile (U3b procedure)
- **Path**: `docs/repl-worker-sandbox.md`, `artifacts/logs/feat-500-bootstrap-profile.md`
- **Responsibility**: document the ready handshake, the two new `WorkerConfig` fields, the lethal/non-lethal table, the restart-loop warning, and a "measuring bootstrap on your host" procedure (`python -X importtime -c "from parrot.tools.pythonrepl import PythonREPLTool"` + grep of `spawned worker pid=` → `repl_worker: ready` in the drain logs). Record the local F018 profile (1.41 s total; `parrot.tools` init 0.90 s of which `parrot.plugins`→`navconfig.logging` 0.58 s; `parrot.security.redaction`→vault→documentdb 0.28 s; `parrot.tools.abstract`→events/conf→`navigator` auth 0.25 s; pandas 0.22 s) as the baseline the follow-up import-trim spec will start from.
- **Depends on**: Modules 1–5 (for accuracy)

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_ready_response_roundtrip` | 1 | `ReadyResponse` survives `write_frame`/`read_frame` (parametrize into the existing `test_protocol_roundtrip`) |
| `test_worker_config_new_fields_defaults_and_validation` | 1 | defaults 30 000 / 30 000; `<= 0` rejected |
| `test_worker_first_frame_is_ready` | 2 | `SpawnedWorker` (existing helper in `test_worker.py`): the first `read_frame` yields `ReadyResponse` with `pid == proc.pid` and `bootstrap_ms > 0` |
| `test_handle_wait_ready_success` | 3 | after `start()`, `wait_ready()` returns a `ReadyResponse`; `is_ready` flips to `True` |
| `test_handle_bootstrap_timeout_kills_and_reports` | 3 | `bootstrap_timeout_ms=500` + `setup_code` sleeping 3 s → `wait_ready()` raises `WorkerBootstrapError` (message contains pid and budget), `is_alive` is `False` |
| `test_handle_send_waits_for_ready` | 3 | `setup_code` sleeping 3 s, `namespace_timeout_ms=30_000`: `set_var` right after `start()` succeeds (no timeout, no kill) |
| `test_namespace_timeout_is_non_lethal` | 3 | monkeypatch `_roundtrip` to sleep > `namespace_timeout_ms` (e.g. 200 ms budget, 1 s sleep): `list_vars()` raises `NamespaceTimeoutError` with a non-empty message; `is_alive` stays `True`; a subsequent `list_vars()` (real `_roundtrip` restored) succeeds after the parked reply is drained |
| `test_execute_deadline_is_still_lethal` | 3 | existing `TestDeadline` behaviour preserved: infinite loop → G5 loss dict with `cause="timeout"`, worker dead |
| `test_fresh_spawn_bootstrap_failure_returns_loss_dict` | 3 | `execute()` on a handle whose bootstrap fails returns `{status:"error", ...}` mentioning the bootstrap error, never raises |
| `test_pool_spare_not_ready_until_ready_frame` | 4 | `prewarm_pool_size=1` + slow `setup_code`: `_prewarmed` stays empty until the ready frame; the log line `prewarmed worker ready` is emitted only afterwards (caplog) |
| `test_pool_restart_loop_warning` | 4 | kill the session worker externally three times within 60 s → `restart_count == 3` and one `possible restart loop` warning in caplog |
| `test_execute_error_dict_never_blank` | 5 | force `_worker_session` to raise `TimeoutError()` → returned dict has `error == "TimeoutError"` (non-empty) |
| `test_client_value_error_never_blank` | 5 | `ToolResult(status="error", error="")` → `ValueError` message is the fallback text |

### Integration Tests
| Test | Description |
|---|---|
| `test_cold_worker_seeding_survives_slow_bootstrap` (**the Probe B regression**) | `PythonPandasTool(dataframes=None, setup_code="import time; time.sleep(8)")`, `df_locals["n_rows"]=3`, default config: three consecutive `_execute("print(n_rows)")` calls all succeed; caplog contains **zero** `worker is dead, restarting` lines and exactly one `spawned worker pid=` for the session |
| `test_pandas_seeding_order_independent` | same as above but with a real DataFrame *and* scalars registered; success must not depend on `set` iteration order (run with `PYTHONHASHSEED` varied via subprocess, or assert seeding never times out by timing) |
| `test_e2e_runaway_loop_recovery` (existing) | keeps passing; its `deadline_ms=4_000` no longer has to cover bootstrap (readiness is separate) — update its docstring |
| `test_namespace_api_after_soft_timeout_keeps_state` | set `x=1` via execute, force one non-lethal `list_vars` timeout, then `get_var("x") == 1` — namespace preserved |

### Test Data / Fixtures
```python
# tests/repl_worker — extend the existing fixtures (test_handle.py:20-29, test_pool.py:21-25)
@pytest.fixture
def slow_bootstrap_kwargs():
    """Delay the worker's own bootstrap deterministically (no prod hook needed)."""
    return {"setup_code": "import time\ntime.sleep(8)"}

@pytest.fixture
def tight_bootstrap_config():
    return WorkerConfig(deadline_ms=5_000, max_workers=2, idle_ttl_seconds=5,
                        prewarm_pool_size=0, bootstrap_timeout_ms=500)

@pytest.fixture
def tight_namespace_config():
    return WorkerConfig(deadline_ms=5_000, max_workers=2, idle_ttl_seconds=5,
                        prewarm_pool_size=0, namespace_timeout_ms=200)
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **AC1 (G1)** — `WorkerHandle` never writes a request frame before it has read the worker's `ReadyResponse`; `WorkerPool._prewarmed` only ever contains ready handles, and `prewarmed worker ready` is logged only after the ready frame.
- [ ] **AC2 (G1)** — A worker that does not send `ReadyResponse` within `bootstrap_timeout_ms` is killed and every waiter receives `WorkerBootstrapError` with pid, budget and stderr tail in the message; on the `execute()` path this becomes the G5 `{status:"error"}` dict.
- [ ] **AC3 (G2, U2)** — A timeout on `get_var`/`set_var`/`list_vars`/`snapshot`/`reset`/`inject_dataframe`/`ping` raises `NamespaceTimeoutError` (non-empty message), leaves the process alive (`is_alive` true) and preserves the namespace; the parked reply is drained before the next request is written.
- [ ] **AC4 (G2)** — `execute()` exceeding `deadline_ms + 250 ms` still SIGKILLs and returns the G5 loss dict with `cause="timeout"` and `lost_variables` (existing `TestDeadline` and `test_e2e_runaway_loop_recovery` pass unchanged in outcome).
- [ ] **AC5 (G3)** — No code path in `handle.py`, `pythonrepl.py`, `pythonpandas.py` or `clients/base.py` can surface an empty error string: `ToolResult.error` and the client `ValueError` are non-empty for every worker failure.
- [ ] **AC6 (G4)** — `WorkerConfig.bootstrap_timeout_ms` and `WorkerConfig.namespace_timeout_ms` exist (defaults 30 000, `> 0` validated), are honoured by the handle, and the literals `5.0`, `10.0` (except `ping`'s default arg) and `30.0` no longer appear as request budgets in `handle.py`.
- [ ] **AC7 (G6)** — The Probe B regression (`test_cold_worker_seeding_survives_slow_bootstrap`) passes: with an 8 s bootstrap, three consecutive `PythonPandasTool._execute` calls succeed with zero `worker is dead, restarting` log lines.
- [ ] **AC8 (G5)** — Three session restarts within 60 s produce one `possible restart loop` warning naming the session and the last death cause; `WorkerPool.restart_count()` reports it.
- [ ] **AC9** — `pytest packages/ai-parrot/tests/repl_worker/ -v` and `pytest packages/ai-parrot/tests/test_pythonrepl_executor.py -v` pass; `ruff check` clean on changed files.
- [ ] **AC10 (G7, U3b)** — `docs/repl-worker-sandbox.md` documents the handshake, the new fields, the lethal/non-lethal table and the host-side bootstrap measurement procedure; `artifacts/logs/feat-500-bootstrap-profile.md` records the F018 baseline.
- [ ] **AC11** — No breaking change to the public namespace API signatures (`get_var/set_var/list_vars/snapshot/inject_dataframe/reset/ping`) or to the `{status, result, error}` contract of `_execute()`.
- [ ] **AC12** — `WorkerHandle.kill()` / `WorkerPool.shutdown()` leave no live worker, no pending `_ready_task` and no parked `_pending_reply` future behind (existing orphan-reaping tests pass).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against `dev` at `2df051300` (2026-09-02). Line numbers are for that revision.

### Verified Imports
```python
from parrot.tools.repl_worker import WorkerPool, WorkerPoolExhaustedError, WorkerHandle, WorkerConfig  # repl_worker/__init__.py:14-16, __all__ :40-65
from parrot.tools.repl_worker.protocol import (                                 # protocol.py
    ExecRequest, ExecResult, GetVarRequest, InjectDfRequest, ListNsRequest, ListNsResponse,
    NamespaceLossError, OkResponse, PingRequest, PongResponse, ResetRequest, SetVarRequest,
    SnapshotRequest, SnapshotResponse, ValueResponse, WorkerConfig, decode_value, encode_value,
    read_frame, write_frame,
)                                                                                # handle.py:31-51 imports exactly this set
from parrot.tools.repl_worker.handle import WorkerHandle                         # pool.py:38
from parrot.tools.pythonrepl import PythonREPLTool                               # worker.py:146 (local import, after rlimits)
from parrot.tools.pythonpandas import PythonPandasTool                           # bots/data.py:26
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py
_LENGTH_STRUCT = struct.Struct(">I")                                   # :32
class PingRequest(BaseModel):  op: Literal["ping"] = "ping"           # :250-253
class PongResponse(BaseModel): op: Literal["pong"] = "pong"           # :300-303
class ErrorResponse(BaseModel): op: Literal["error"] = "error"; message: str   # :306-309
class NamespaceLossError(BaseModel):                                   # :313-323
    cause: Literal["timeout", "memory", "crash"]; lost_variables: list[str]; message: str
class WorkerConfig(BaseModel):                                         # :326-341
    rlimit_as_bytes: int = 12 * 1024**3; rlimit_cpu_seconds: int = 300; rlimit_nofile: int = 256
    deadline_ms: int = 60_000; max_workers: int = 0; idle_ttl_seconds: int = 1800; prewarm_pool_size: int = 2
_MESSAGE_TYPES: dict[str, type[BaseModel]] = {"exec": ..., "ping": PingRequest, ..., "pong": PongResponse, "error": ErrorResponse}  # :346-362
def _read_exact(stream, n) -> bytes   # :365-387  raises EOFError("repl_worker protocol: stream closed[ mid-frame]")
def write_frame(stream, message) -> None   # :391-405  4-byte BE length + JSON
def read_frame(stream) -> BaseModel        # :408-429  ValueError on unknown op

# packages/ai-parrot/src/parrot/tools/repl_worker/handle.py
_DEADLINE_GRACE_MS = 250                                               # :58
_MEMORY_MARKERS = (...)                                                # :64-71
class WorkerHandle:                                                    # :74
    def __init__(self, config=None, output_dir=None, repl_kwargs=None, executor=None)   # :77-147
        self._proc: Optional[subprocess.Popen]; self._to_worker/_from_worker: Optional[BinaryIO]
        self._lock = asyncio.Lock()                                    # :113
        self._executor (shared or self-owned ThreadPoolExecutor(4))     # :114-117
        self._stdio_executor = ThreadPoolExecutor(2)                   # :136-138
        self._stdio_task: Optional[asyncio.Task]; self._stderr_tail: list[str]; self.known_vars: list[str]   # :139-147
    @property is_alive(self) -> bool                                   # :149-152  (proc.poll() is None)
    async def start(self) -> None                                      # :154-197  Popen(argv, pass_fds), fdopen pipes, logs :187, creates _drain_stdio task
    async def _drain_stdio(self) -> None                               # :199-233
    def _roundtrip(self, request) -> Any                               # :235-238  write_frame + read_frame (blocking)
    async def _send(self, request, timeout_s: float) -> Any            # :240-263  lock; EOFError if not alive; wait_for; on timeout kill + raise
    async def _kill_process(self) -> None                              # :265-281
    async def _classify_death(self) -> str                             # :283-311  "memory" | "crash"
    def _build_loss_error(self, cause, detail) -> dict                 # :313-334
    async def execute(self, code, debug=False) -> str | dict           # :336-362  deadline = (deadline_ms+250)/1000
    async def inject_dataframe(self, name, df) -> None                 # :364-403  _send(..., timeout_s=30.0) at :396
    async def get_var(self, name) -> Any                               # :405-408  _send(GetVarRequest, 5.0)
    async def set_var(self, name, value) -> None                       # :410-413  _send(SetVarRequest, 5.0)
    async def list_vars(self) -> list[str]                             # :415-419  _send(ListNsRequest, 5.0)
    async def snapshot(self) -> dict                                   # :421-424  _send(SnapshotRequest, 10.0)
    async def reset(self) -> None                                      # :426-429  _send(ResetRequest, 30.0)
    async def ping(self, timeout_s: float = 10.0) -> bool              # :431-449  UNUSED anywhere (F014)
    async def kill(self) -> None                                       # :451-486

# packages/ai-parrot/src/parrot/tools/repl_worker/pool.py
class WorkerPoolExhaustedError(RuntimeError)                           # :50
class WorkerPool:                                                      # :58
    def __init__(self, config=None, output_dir=None, repl_kwargs=None, executor=None)   # :61-110
        self._sessions: dict[str, WorkerHandle]; self._last_active: dict[str, float]; self._prewarmed: list[WorkerHandle]   # :93-95
        self._lock, self._topup_lock: asyncio.Lock; self._background_tasks: set[asyncio.Task]; self._started: bool   # :97-110
    async def _ensure_started(self) -> None                            # :119-131
    def _track_background(self, coro) -> asyncio.Task                  # :133-138
    async def _spawn_handle(self) -> WorkerHandle                       # :140-145  WorkerHandle(...); await handle.start()
    async def _top_up_prewarmed(self) -> None                          # :147-187  logs "prewarmed worker ready (pool size=%d)" at :187
    async def _maintenance_loop / _evict_idle                          # :189-212
    async def acquire(self, session_id: str) -> WorkerHandle           # :214-276  "worker is dead, restarting" :241; pop(0) :264; "bound to a prewarmed worker" :265; fresh spawn :267-268
    async def release(self, session_id: str) -> None                   # :278-286
    async def shutdown(self) -> None                                   # :288-326

# packages/ai-parrot/src/parrot/tools/repl_worker/worker.py
def set_parent_death_signal() -> None                                  # :58-82
def apply_rlimits(config: WorkerConfig) -> None                        # :85-118
class WorkerNamespace:                                                 # :121
    def __init__(self, output_dir=None, sanitize_input_enabled=True, repl_kwargs=None)   # :138-157  imports PythonREPLTool, builds it
def _dispatch(namespace, message) -> Any                               # :205-247
def serve(config, in_stream, out_stream, output_dir=None, repl_kwargs=None) -> None   # :250-287  logs "repl_worker: ready" :275 then loop
def main(argv=None) -> None                                            # :290-337  argv: config-json, read_fd, write_fd, [output_dir], [repl_kwargs-json]

# packages/ai-parrot/src/parrot/tools/pythonrepl.py
class PythonREPLTool(AbstractTool):
    _bootstrapped = False                                              # :97 (class var; per-process → per-worker)
    def __init__(..., setup_code: Optional[str] = None, ..., executor_max_workers: int = 4, worker_config=None, **kwargs)   # :180-193
        self.setup_code                                                # :236
        self._repl_executor = ThreadPoolExecutor(max_workers=executor_max_workers)   # :245-248
        self._session_id = f"pythonrepl-{uuid4().hex}"; self._worker_config; self._worker_pool = None; self._pending_worker_reset = False   # :262-265
        self._worker_repl_kwargs = {"setup_code": self.setup_code}     # :266-268
    def _bootstrap(self) -> None                                       # :433-446  _execute_code(self.setup_code, enforce_security=False)
    async def _acquire_worker_pool(self)                               # :837-869  WorkerPool(config=self._worker_config, ..., executor=self._repl_executor)
    async def _get_worker_handle(self)                                 # :871-892
    _worker_session (asynccontextmanager)                              # :894-918
    async def _execute(self, code, debug=False, **kwargs) -> Any       # :920-977  :945 info log; :959-962 except → {"status":"error","result":f"ToolError: {type}: {e}","error":str(e)}
    async def get_var/set_var/list_vars/snapshot/inject_dataframe      # :979-1019
    def reset_environment(self) -> None                                # :1048-1078  sets _pending_worker_reset = True

# packages/ai-parrot/src/parrot/tools/pythonpandas.py
class PythonPandasTool(PythonREPLTool):                                # :25
    name = "python_repl_pandas"                                        # :40
    async def _get_worker_handle(self)                                 # :137-181  identity-based reseed; inject_dataframe for DataFrames, set_var otherwise (:176-180)
    def reset_environment(self) -> None                                # :183-193
    def _process_dataframes(...)                                       # :505-522  df_locals[name|alias] + *_row_count/_col_count/_shape/_columns
    async def _execute(self, code, debug=False, **kwargs) -> Any       # :910-1010  list_vars() :940 (try/except), super()._execute :944, audit list_vars/get_var :983/:993

# packages/ai-parrot/src/parrot/clients/base.py
#   AbstractClient tool wrapper: `if result.status == "error": raise ValueError(result.error)`   # :1499-1500; logs "Error executing tool" :1504

# packages/ai-parrot/src/parrot/tools/abstract.py
#   AbstractTool.execute(): dict with status+result → ToolResult(**raw_result)   # :1014-1028
```

### Existing Test Helpers (reuse, do not duplicate)
```python
# tests/repl_worker/test_worker.py
class SpawnedWorker            # :81   real subprocess + dedicated pipes; read/write via read_frame/write_frame
def _spawn_worker(config, output_dir) -> SpawnedWorker   # :129
# tests/repl_worker/test_handle.py fixtures: real_worker_config :20-23, fast_deadline_config :26-29, tiny_as_config :32-49; classes TestDeadline :51, TestPing :104, TestNamespaceAPI :120
# tests/repl_worker/test_pool.py fixture worker_config :21-25 (prewarm_pool_size=0); TestWorkerPool :28 (prewarm case at :84)
# tests/repl_worker/test_integration.py: _shutdown(tool) :26, fixture tool :32, TestE2E.test_e2e_runaway_loop_recovery :137-165
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ReadyResponse` | `_MESSAGE_TYPES` / `read_frame` dispatch | new `"ready"` key | `protocol.py:346-362, 425-428` |
| `serve()` ready frame | `write_frame(out_stream, ...)` before loop | function call | `worker.py:274-276` |
| `WorkerHandle._await_ready` | `read_frame(self._from_worker)` in `self._executor` | `loop.run_in_executor` | `handle.py:181-186, 252` |
| `WorkerHandle._send(lethal=...)` | `execute()` only lethal caller | keyword arg | `handle.py:351` |
| `WorkerPool._top_up_prewarmed` | `handle.wait_ready()` before `self._prewarmed.append` | await outside `_lock` | `pool.py:166-187` |
| `WorkerPool.acquire` restart counter | the `worker is dead, restarting` branch | list of monotonic timestamps | `pool.py:237-243` |
| `PythonPandasTool._get_worker_handle` | `handle.inject_dataframe` / `handle.set_var` | unchanged calls, wrapped errors | `pythonpandas.py:176-180` |
| `PythonREPLTool._execute` | error dict | non-empty `error` | `pythonrepl.py:959-962` |
| `AbstractClient` | `ValueError(result.error or ...)` | fallback text | `clients/base.py:1500` |

### Does NOT Exist (Anti-Hallucination)
- ~~`ReadyResponse` / `ReadyRequest`~~ — no ready/handshake frame of any kind exists in `protocol.py` (Module 1 creates `ReadyResponse` only; there is no request side).
- ~~`WorkerHandle.wait_ready()` / `is_ready` / `_ready_task` / `_pending_reply`~~ — to be created in Module 3.
- ~~`WorkerConfig.bootstrap_timeout_ms` / `namespace_timeout_ms`~~ — to be created in Module 1. There is no timeout-related field in `WorkerConfig` besides `deadline_ms`.
- ~~`NamespaceTimeoutError` / `WorkerBootstrapError`~~ — to be created in Module 3; today `_send` raises the bare `asyncio.TimeoutError` (== builtin `TimeoutError` on 3.11+, `str()` is `''`).
- ~~`WorkerPool.restart_count()` / `_restarts`~~ — to be created in Module 4.
- ~~`WorkerHandle.ping()` callers~~ — none exist (F014); do not assume the pool pings.
- ~~`tests/repl_worker/conftest.py`~~ — there is no conftest in that directory; fixtures live in each test module.
- ~~an in-process `exec()` fallback in `PythonREPLTool._execute`~~ — removed by FEAT-380 (G8/AC8); do not reintroduce one "while the worker boots".
- ~~`asyncio.wait_for` / `asyncio.timeout` wrappers around tool execution in `tools/abstract.py` or `tools/manager.py`~~ — none (F007); the 5 s cadence comes only from `handle.py`.
- ~~`WorkerConfig.preexec_fn`~~ — rlimits are applied worker-side in `worker.main()` (`apply_rlimits`), not via `Popen(preexec_fn=...)` (the docs table wording at `docs/repl-worker-sandbox.md:126` is stale; fix it in Module 7).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Readiness is a handle concern, not a pool concern.** Put the future in `WorkerHandle` so standalone `WorkerHandle` users and the pool share one implementation; the pool only *awaits* it.
- **Never touch the pipe from two threads.** `_await_ready` must complete (or fail) before `_send` issues its first `_roundtrip`; both run on `self._executor` and are serialised by `self._lock` + the readiness future. Keep the existing "kill without taking `_lock`" rule in `kill()` (`handle.py:451-467`).
- **Drain before write.** After a non-lethal timeout the pipe holds an unread reply; the next `_send` must await `_pending_reply` (bounded) *before* `write_frame`, otherwise responses shift by one. Add a protocol test that proves the shift cannot happen.
- **Keep the G5 dict contract** (`handle.py:313-334`, `docs/repl-worker-sandbox.md §2`) for `execute()`; new failure kinds on the execute path are folded into it, never raised.
- **Async-first, logger not print**, Google-style docstrings, Pydantic for `ReadyResponse` and config fields (project rules).
- **Tests spawn real workers** (existing convention in `tests/repl_worker/`): use `setup_code` to shape bootstrap timing; use monkeypatching only for the non-lethal-timeout unit test.
- Reuse `SpawnedWorker` (`test_worker.py:81`) for the "first frame is ready" test rather than building a new harness.

### Known Risks / Gotchas
- **Late replies after a soft timeout.** If the parked reply is never drained (e.g. the caller gives up and the handle is reused), the next request would read the stale frame. Mitigation: unconditional drain in `_send` + `kill()` cancels `_pending_reply`; test `test_namespace_timeout_is_non_lethal` covers the drain.
- **Bootstrap budget vs. deadline.** `test_e2e_runaway_loop_recovery` currently relies on `deadline_ms` also covering bootstrap; after this change the first `execute()` waits for readiness *outside* the deadline budget. Update the docstring, keep the assertions.
- **Prewarm contention.** Readiness makes spares honest but does not make them faster: three workers booting concurrently per tool instance was measured at 12–14 s under load (F016). Do not lower `bootstrap_timeout_ms` below 30 s by default; document the knob.
- **`_bootstrapped` is a class variable** (`pythonrepl.py:97`) — fine per worker process, but the slow `setup_code` used by tests also runs in the *host* `PythonREPLTool.__init__` (`_bootstrap` at :433-446). Test wall-time budgets must account for it, or construct the host tool with `setup_code` that sleeps only when `os.getpid()` differs from a recorded host pid (simplest: sleep unconditionally and accept ~8 s per test; mark `@pytest.mark.slow` if the suite has such a marker).
- **`ping()` semantics.** Keep `ping()` non-lethal and readiness-aware; it is now a real health check the pool *may* use later, but AC1 is satisfied by the ready frame alone.
- **Windows.** `Popen.kill()` mapping is unchanged; the ready frame is plain pipe I/O and works there too (no `prctl`).
- **Other namespace callers** (`bots/data.py` `get_var`/`snapshot`, `bots/agent.py:251` `snapshot`, `tools/agent.py:424-430` `set_var`) now see `NamespaceTimeoutError` instead of a blank `TimeoutError`; they already catch broad exceptions (F008) — verify no caller special-cases `asyncio.TimeoutError` by identity (grep in Module 5).
- **Concurrent SDD sessions on this repo**: another session is actively committing on `dev` (FEAT-499); use a worktree for implementation and push early (see CLAUDE.md worktree policy).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | No new dependencies (stdlib `asyncio`, `subprocess`, `struct`, `time`; existing `pydantic`) |

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — all modules edit the same three files (`protocol.py`, `handle.py`, `pool.py`) and the tests build on each other; run tasks **sequentially** in one worktree.
- **Parallelizable**: Module 7 (docs + profile) can be written in parallel once Modules 1–4 are merged in the worktree, but it is small enough that sequential is fine.
- **Cross-feature dependencies**: none. The follow-up "trim the worker import surface" spec (Non-Goal here) should depend on this one.
- Create from `dev` after task decomposition:
  ```bash
  git worktree add -b feat-500-bug-workerpool-repl .claude/worktrees/feat-500-bug-workerpool-repl origin/dev
  ```

---

## 8. Open Questions

> Carried forward from `sdd/proposals/bug-workerpool-repl.proposal.md` §5 (U1–U3 resolved by the user on 2026-09-02).

- [x] **U1 — Hotfix on `main` or feature on `dev`?** — *Resolved in proposal*: "currently the issue is on dev (also in main), add in dev to be later launched in a new release" → `type: feature`, `base_branch: dev` (frontmatter, §1 Non-Goals).
- [x] **U2 — Should a namespace-API timeout on an alive worker stay lethal?** — *Resolved in proposal*: "execute deadline kill" → only `execute()` kills; every other request is non-lethal (`_send(lethal=False)`, §2 Overview, AC3/AC4).
- [x] **U3 — What dominates bootstrap?** — *Resolved (partially) in proposal*: "maybe a research is required, I don't know the answer" → local profile F018: ~80 % `parrot` framework init, ~16 % pandas; recorded in Module 7 as the baseline; trimming is a follow-up spec (§1 Non-Goals).
- [ ] **U3b — Measure spawn→ready and `-X importtime` on the affected host** — *Owner: Jesus Lara* (needs host access). Not blocking: Module 7 documents the procedure; the numbers feed the follow-up import-trim spec. *Blocks*: nothing in this spec.
- [ ] **Q1 — Bootstrap timeout stays lethal?** — *Owner: Jesus Lara*. This spec kills a worker that never sends `ready` within `bootstrap_timeout_ms` (it is not a live worker). If you want strictly "only execute kills", the alternative is to keep waiting and let the caller's own budget fail softly — decide before Module 3; default here is *kill*.
- [ ] **Q2 — Default for `namespace_timeout_ms`** — *Owner: implementer*. 30 000 chosen to cover large `get_var`/`snapshot` pickles on a loaded host; can be tuned during Module 6 from measured test timings. Not blocking.
- [ ] **Q3 — Should `WorkerPool.acquire()` prefer the *readiest* spare or keep FIFO?** — *Owner: implementer*. With readiness-gated spares FIFO is already safe; deferred (non-blocking).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-02 | Jesus Lara + Claude | Initial draft from proposal FEAT-518 (research) — feature id FEAT-500 reserved via ledger |

# PythonREPLTool Sandbox: Worker-Process Execution Model

**Feature**: FEAT-380 — Sandbox Hardening
**Applies to**: `PythonREPLTool` (`parrot.tools.pythonrepl`) and
`PythonPandasTool` (`parrot.tools.pythonpandas`)
**Status**: current as of this feature's merge (TASK-1939–1946)

`PythonREPLTool` no longer runs LLM-generated code in the host server
process. Each tool **instance** owns a persistent, per-instance worker
**process** — spawned, resource-limited, and torn down on timeout/crash —
that holds the REPL namespace and actually calls `exec()`/`eval()`. This
document describes that execution model, its failure modes, every deployment
knob, the namespace API that replaced direct `.locals`/`.globals` access,
and — **read this if you deploy on Windows** — the degraded guarantees
there.

> **What this is not.** The worker is a resource-bounding sandbox, not an
> adversarial security boundary. It shares the kernel, network, and
> filesystem with the host process. It buys bounded resource consumption and
> blast-radius reduction (a runaway loop or a memory bomb kills the worker,
> never the server) — it does **not** buy containment against a
> deliberately malicious actor. Full container isolation (one container per
> session) is a documented future evolution, not implemented here.

---

## 1. Execution model

```
   HOST (server process)                       WORKER (one per PythonREPLTool instance)
  ┌───────────────────────────┐               ┌──────────────────────────────┐
  │ PythonREPLTool._execute()  │               │ preexec: setrlimit(          │
  │  1. sanitize_input()       │               │   AS, CPU, NOFILE, CORE=0)   │
  │  2. host gate (allowlist   │   dedicated   │                              │
  │     + AST denylist) ───────┼──── pipe ────►│  gate re-validated (defence  │
  │     — cheap reject, no     │  (never       │  in depth) before exec()     │
  │     round-trip if denied   │  stdin/stdout)│  ns = worker's own locals    │
  │  3. WorkerPool.acquire()   │               │    _execute_code() — moved   │
  │     → WorkerHandle         │◄──────────────┤    verbatim, unmodified      │
  │  4. handle.execute(code)   │   deadline_ms │  save_current_plot() writes  │
  │     enforces deadline_ms   │   → SIGKILL   │    to the shared output dir  │
  │     on the host side       │   on timeout  │                              │
  └───────────────────────────┘               └──────────────────────────────┘
          shared output directory (plots, reports) — visible to both sides
```

- **Host gate first.** `PythonREPLTool._execute()` runs the same allowlist +
  AST-denylist gate it always has, *before* the worker is ever contacted —
  denied code never starts a worker (cheap, no round-trip).
- **Worker re-validates.** The worker independently re-runs the same gate
  before calling `exec()` — defence in depth in case a future caller
  reaches the worker without going through the host gate.
- **`_execute_code()` moved, not rewritten.** The method that actually runs
  `exec()`/`eval()` is unchanged; it now runs inside a `PythonREPLTool`
  instance that lives in the worker process instead of the host.
- **One worker per tool instance.** There is no broader "session" concept
  in `PythonREPLTool` — the tool instance itself is the isolation unit
  (matching its pre-existing per-instance `.locals`, never shared across
  instances). Lazy start: the worker is spawned on the first `_execute()`
  (or namespace-API) call, never in `__init__`.
- **Spawn only, never fork.** Connection pools and the parent's
  threads do not tolerate `fork()`.
- **No automatic in-process fallback.** If the worker cannot start,
  `_execute()` returns an explicit error (see §2) — the tool never silently
  downgrades. The only way to run in-process is the explicit, logged
  `execution_mode="inprocess"` escape hatch (see §3b), chosen at
  construction time.

### Readiness handshake (FEAT-500)

A freshly spawned worker is **not** usable yet: it still has to import the
`parrot` framework plus pandas and run the REPL bootstrap (~2.4 s on an idle
host, 12–14 s under heavy CPU contention — see
[`artifacts/logs/feat-500-bootstrap-profile.md`](../artifacts/logs/feat-500-bootstrap-profile.md)).
So readiness is explicit:

1. The worker writes exactly one `ReadyResponse` frame — its pid plus the
   measured `bootstrap_ms` — as the **first** frame on the control pipe, after
   its namespace is fully constructed and before it reads any request. It also
   logs `repl_worker: ready in <N> ms (...), entering service loop`.
2. Host-side, `WorkerHandle.start()` still returns as soon as the process is
   spawned, but it arms an internal readiness future: a background read of
   that first frame, bounded by `WorkerConfig.bootstrap_timeout_ms`.
3. **`WorkerHandle._send()` awaits readiness before writing anything**, so
   every caller — namespace API, `PythonPandasTool`'s DataFrame seeding,
   `execute()` — gets it for free. No request frame can reach a
   still-bootstrapping worker.
4. `WorkerPool` awaits `handle.wait_ready()` before appending a spare to its
   prewarmed list, so **"prewarmed" means ready**, not merely spawned. The
   `WorkerPool: prewarmed worker ready (pid=..., bootstrap_ms=..., pool
   size=...)` line is emitted only after the frame arrives.

`await handle.wait_ready()` and `handle.is_ready` are available to
integrators; awaiting readiness explicitly is optional (any request does it
implicitly).

Before FEAT-500 there was no handshake: the pool counted a still-booting
worker as a ready spare, and the first namespace request into it timed out at
a hard-coded 5 s and killed it — a self-sustaining restart loop on any host
where bootstrap exceeded 5 s.

### The one exception: `execute_sync()`

`PythonREPLTool.execute_sync()` is a **separate, pre-existing synchronous
escape hatch** that still calls `_execute_code()` **in-process**, unchanged.
It predates this feature and was deliberately left alone — hardening it
(routing it through the worker too) is future work. Anything calling
`execute_sync()` gets none of this document's guarantees (no rlimits, no
deadline, no isolation from the host process).

---

## 2. Failure modes

Every failure surfaces through the same return contract `_execute()` has
always had:

- **Success** → a plain `str`.
- **Error** → `{"status": "error" | "done_with_errors", "result": <text>, "error": <text>}`.

| Cause | What happens | `status` | `result`/`error` text |
|---|---|---|---|
| Code denied by the host or worker gate | Rejected before/without running | `done_with_errors` | The `SecurityError:`/`BlockedOperationError:` message (unchanged from before this feature) |
| Runaway loop / hang | Host's `deadline_ms` timer fires → `SIGKILL` (POSIX) / `TerminateProcess` (Windows) | `error` | `REPL worker terminated (timeout: ...)` — see below |
| Allocation over `rlimit_as_bytes` | Worker dies (often at import time under a very tight limit; see the calibration note in §3) | `error` | `REPL worker terminated (memory: ...)` |
| Worker crash (segfault, OOM-killed, etc.) | Detected the next time the host tries to talk to it | `error` | `REPL worker terminated (crash: ...)` |
| Concurrency ceiling reached | `WorkerPool.acquire()` raises immediately — no queueing | `error` (wraps `WorkerPoolExhaustedError`) | States the current ceiling and suggests raising `WorkerConfig.max_workers` |
| Worker idle past `idle_ttl_seconds` | Killed and unmapped by the pool's background sweep; next use spawns fresh | *(not an error — the session's next call just gets a fresh, empty namespace)* | — |
| **Bootstrap timeout** (FEAT-500) | `bootstrap_timeout_ms` expired without a `ReadyResponse` → the worker is killed (it never became a live worker) and every waiter gets a `WorkerBootstrapError` | `error` on the `execute()` path (folded into the usual namespace-loss dict); a raised `WorkerBootstrapError` on the namespace API | `REPL worker pid=<pid> did not become ready within <N> ms (<cause>); stderr tail: <...>` |
| **Namespace-API timeout** (FEAT-500) | `namespace_timeout_ms` expired on a non-`exec` request → **`NamespaceTimeoutError`, worker left ALIVE**, namespace preserved; the late reply is parked and drained before the next request | *(raises on the namespace API — no dict)* | `repl_worker[pid=<pid>]: '<op>' request did not answer within <N>s; the worker is still alive and the late reply will be drained on the next call` |
| **Undrained straggler on the `execute()` path** (FEAT-500) | A reply parked by an earlier non-lethal timeout had still not arrived when `execute()`'s drain step ran. The worker is **alive** and its namespace is **intact**, so this is deliberately *not* reported as a namespace loss | `error` | `repl_worker[pid=<pid>]: a reply from a previously timed-out request has still not arrived after <N>s; the worker is still alive and the reply stays queued for the next call` — note the absence of the "ALL variables were lost" wording, which would be false here |

Every request is preceded by a **drain step**: if an earlier non-lethal
timeout left a reply in flight, the next request waits for that straggler
(bounded by its own budget) before writing, so a late reply can never be
handed to the wrong caller. `execute()` performs this drain too — which is
why it has its own row above — but its drain expiring never kills the worker.

### Which timeouts kill the worker?

Only two, by design (FEAT-500 G2): a worker is expensive to replace and its
namespace is the session's state, so losing them must be deliberate.

| Budget | Applies to | On expiry |
|---|---|---|
| `deadline_ms` (+250 ms grace) | `execute()` — running LLM code | **Lethal.** `SIGKILL` + namespace-loss dict (`cause="timeout"`). |
| `bootstrap_timeout_ms` | waiting for the worker's first `ReadyResponse` | **Lethal.** A process that cannot boot is not a live worker; killed + `WorkerBootstrapError`. |
| `namespace_timeout_ms` | `get_var`, `set_var`, `list_vars`, `snapshot`, `reset`, `inject_dataframe` | **Non-lethal.** `NamespaceTimeoutError`; process and namespace survive. |
| `ping(timeout_s=...)` | health check only | **Non-lethal.** Returns `False`. |

### Namespace-loss error shape

The three worker-death causes (timeout / memory / crash) all produce the
**same structured shape**, with the cause differentiated in the text:

```json
{
  "status": "error",
  "result": "REPL worker terminated (timeout: execution exceeded deadline_ms=60000). ALL variables in this session were lost: x, y, df. You must recreate any state you need before retrying.",
  "error": "REPL worker terminated (timeout: execution exceeded deadline_ms=60000). ALL variables in this session were lost: x, y, df. You must recreate any state you need before retrying."
}
```

The message always includes: the differentiated **cause**
(`timeout`/`memory`/`crash`), the **list of variable names** that existed
right before the kill (a cheap, names-only shadow the host maintains from
each successful call's new-variable list — never the values), and an
explicit instruction that the LLM must **recreate state before retrying**.
The session itself is still usable afterward — the next call transparently
gets a fresh worker.

---

## 3. Deployment configuration (`WorkerConfig`)

```python
from parrot.tools.repl_worker.protocol import WorkerConfig
```

| Field | Default | Meaning |
|---|---|---|
| `rlimit_as_bytes` | **12 GiB** (`12 * 1024**3`) | Virtual address space ceiling (`RLIMIT_AS`) applied to the worker. Applied by the worker itself in `worker.main()` (via `apply_rlimits()`) before any heavy import runs — **not** via `Popen(preexec_fn=...)`. **Empirically calibrated** — see [`artifacts/logs/feat-380-rlimit-as-calibration.md`](../artifacts/logs/feat-380-rlimit-as-calibration.md) for the measurements (peak observed VmPeak 5522.8 MB across a real bootstrap+500MB-load+merge+plot session, ×2 margin — predates FEAT-423's reduction of the REPL bootstrap import surface; actual footprint is now smaller, so this default is conservative). Re-run `scripts/sdd/calibrate_rlimit_as.py` after a pandas/numpy/pyarrow version bump (or to tighten this default post-FEAT-423). |
| `rlimit_cpu_seconds` | `300` | `RLIMIT_CPU` — a safety net if the host's own `SIGKILL`-on-timeout somehow failed to fire. |
| `rlimit_nofile` | `256` | `RLIMIT_NOFILE` — bounds file descriptors. |
| `deadline_ms` | `60_000` | Host-enforced wall-clock deadline per `exec` call. On expiry: `SIGKILL` + namespace-loss error (see §2). |
| `max_workers` | `0` (→ `max(4, cpu_count())`, capped at 16) | Concurrency ceiling across the pool. Reaching it makes `acquire()` raise immediately — no queueing. |
| `idle_ttl_seconds` | `1800` (30 min) | A session's worker idle past this is killed and unmapped by the pool's background sweep. |
| `prewarm_pool_size` | `2` | Idle, pre-booted spare workers (pandas/numpy already imported — the bootstrap import surface shrank as of FEAT-423) kept ready so a session's first call doesn't pay the 1–3s import cost. Since FEAT-500 a spare is only added to this pool **after** it signals readiness. |
| `bootstrap_timeout_ms` | `30_000` | **FEAT-500.** How long the host waits for a freshly spawned worker's `ReadyResponse`. Expiry is **lethal** (see §2). Do not lower this casually: bootstrap was measured at 12–14 s under 3× CPU oversubscription, and workers boot concurrently (1 session + `prewarm_pool_size` spares). Validated `> 0`. |
| `namespace_timeout_ms` | `30_000` | **FEAT-500.** Budget for every **non-`exec`** request (`get_var`/`set_var`/`list_vars`/`snapshot`/`reset`/`inject_dataframe`). Expiry is **non-lethal**: `NamespaceTimeoutError`, worker and namespace intact. Replaces the old hard-coded 5 s/10 s/30 s literals. Validated `> 0`. |

`RLIMIT_CORE = 0` is hardcoded, non-configurable — a core dump with live
DataFrames in memory is a data-exfiltration vector, not a tuning knob.

**Tuning notes:**

- `rlimit_as_bytes` bounds *virtual* address space, not resident memory
  (Linux doesn't enforce `RLIMIT_RSS` at all — this is why the spec uses
  `RLIMIT_AS`). Setting it too low doesn't just reject huge allocations — it
  can crash the worker **during its own bootstrap** (numpy/pandas import),
  before any user code runs at all. Don't set it below the calibrated
  default without re-running the calibration script against your own
  pandas/numpy versions.
- `max_workers` bounds concurrent sessions, but each worker independently
  reserves up to `rlimit_as_bytes` of virtual address space — plan
  `max_workers × rlimit_as_bytes` for worst-case aggregate exposure on
  memory-constrained hosts, not just the per-worker number.
- `prewarm_pool_size` workers count against `max_workers` too (the pool
  caps `sessions + prewarmed spares` together).

## 3b. Execution modes — the `inprocess` escape hatch

`PythonREPLTool` (and therefore `PythonPandasTool`, `PandasAgent`, and every
agent that builds one internally) has two execution modes, fixed at
construction time:

| Mode | Where generated code runs | Sandbox | Selected by |
|---|---|---|---|
| `worker` (**default**) | a persistent child process (`WorkerHandle`/`WorkerPool`, everything in this document) | rlimits, SIGKILL on `deadline_ms`, crash isolation, namespace-loss reporting | default |
| `inprocess` | inside the host process, on the tool's own `locals`/`globals`, on its dedicated `_repl_executor` thread — the pre-FEAT-380 behaviour | **none** of the above; the allowlist + AST denylist gate still applies | `PythonREPLTool(execution_mode="inprocess")` or `PYTHON_REPL_EXECUTION_MODE=inprocess` in the environment |

Resolution order: explicit constructor argument → `PYTHON_REPL_EXECUTION_MODE`
(read through navconfig, case-insensitive) → `worker`. Any other value raises
`ValueError` at construction. Selecting `inprocess` logs a **WARNING** naming
the tool, every time an instance is built.

```bash
# Deployment-wide kill switch — no agent code changes needed
export PYTHON_REPL_EXECUTION_MODE=inprocess
```

```python
# Per instance
tool = PythonREPLTool(execution_mode="inprocess")
```

What `inprocess` keeps, so callers do not have to branch: the
`{status, result, error}` return contract, the namespace API
(`get_var`/`set_var`/`list_vars`/`snapshot`/`inject_dataframe`),
`PythonPandasTool`'s DataFrame seeding and audit preview, and session
clones (each clone builds its own `InProcessHandle` over its own copied
namespace). `WorkerPool` is never instantiated in this mode.

What it gives up: a snippet that exceeds `deadline_ms` still returns the
bounded error to the caller, but the thread keeps running until the snippet
finishes (nothing can SIGKILL it) — the error text says so, and the
namespace is *not* reported as lost because nothing died; the handle stays
busy until that thread finishes, so a follow-up call gets a "still running"
error instead of mutating the namespace concurrently. A hard crash in
generated code (segfault, `os._exit`) takes the host down. And because
`_execute_code` captures output with `redirect_stdout` (process-global),
anything else the host prints to stdout during a snippet can leak into that
snippet's result — the pre-FEAT-380 behaviour, accepted as a documented
limitation of the hatch.

Intended use: a temporary, deployment-level escape hatch while the worker
path is being battle-tested on a given host, or hosts where spawning a
child interpreter is impossible. It is implemented as
`parrot.tools.repl_worker.inprocess.InProcessHandle`, a `WorkerHandle`
look-alike, so removing the hatch later is a one-branch change in
`PythonREPLTool._get_worker_handle()`.

### Instantiating a tool with a custom config

```python
from parrot.tools.pythonrepl import PythonREPLTool
from parrot.tools.repl_worker.protocol import WorkerConfig

tool = PythonREPLTool(
    worker_config=WorkerConfig(deadline_ms=15_000, max_workers=8),
)
```

---

## 4. Namespace API (for integrators)

`tool.locals` / `tool.globals` are **no longer the source of truth** for
what the REPL namespace actually contains — the namespace lives in the
worker process. The host instance's `.locals`/`.globals` dicts still exist
and stay populated (for backward compatibility with any code not yet
ported), but they are a **stale, construction-time snapshot** — never
updated by code the worker actually executes. Reading them to discover
what a session computed will not see anything the LLM created.

Use the async namespace API instead:

```python
value = await tool.get_var("my_dataframe")
await tool.set_var("previous_result", some_value)
names = await tool.list_vars()
snapshot = await tool.snapshot()   # full, JSON-safe(ish) dump of the namespace
```

Any of these calls can raise **`NamespaceTimeoutError`** (FEAT-500) if the
worker does not answer within `WorkerConfig.namespace_timeout_ms`:

```python
from parrot.tools.repl_worker import NamespaceTimeoutError, WorkerBootstrapError

try:
    value = await tool.get_var("my_dataframe")
except NamespaceTimeoutError as exc:
    # The worker is STILL ALIVE and its namespace is intact — retrying is
    # legitimate. `exc` always carries a readable message naming the pid,
    # the operation and the budget.
    logger.warning("namespace read timed out: %s", exc)
```

It subclasses `TimeoutError`, so existing `except TimeoutError` handlers keep
working — but unlike the bare `asyncio.TimeoutError` this used to raise, its
`str()` is never empty. It is **non-lethal**: the process keeps running, the
namespace is preserved, and the straggling reply is drained before the next
request is written. `WorkerBootstrapError` (also always messaged) is raised
instead if the worker never finished booting at all.

There is **no synchronous variant** and **no compatibility dict-proxy** —
that was explicitly rejected (round-trip-per-key semantics and "looks live
but isn't" behavior would break silently and worse than an honest
`AttributeError`). Every call site that needs the namespace must be, or
become, `async`.

### DataFrames specifically

`await tool.inject_dataframe(name, df)` pushes a `pandas.DataFrame` into the
worker via Arrow IPC over shared memory (falling back to pickle, with a
logged warning, only for dtypes Arrow can't represent) — cheaper than
`set_var()` for DataFrame-sized payloads, which always pickles. This is
what `PythonPandasTool`'s own DataFrame seeding uses internally, and what
`ToolManager.share_dataframe()`/`auto_push_to_pandas` deliver through
transparently.

### Snapshot semantics changed for `WorkingMemoryToolkit` wiring

`BasicAgent` auto-wires REPL/pandas tool namespaces into any registered
`WorkingMemoryToolkit` from `configure()` (its async setup hook — this
wiring needs to `await tool.snapshot()`, so it moved out of `__init__`,
which can't await). The wired dict is a **snapshot frozen at wiring time**,
not a live reference: DataFrames the agent loads *after* `configure()` runs
are not automatically visible through that registry entry. This is a
deliberate, spec-decided behavior change — a live cross-process reference
was never possible to begin with once the namespace moved into a separate
process.

---

## 4b. Restart-loop warning (FEAT-500)

A session whose worker keeps dying used to burn one replacement every few
seconds in complete silence. The pool now counts restarts per session in a
60-second sliding window and, from the third one, logs:

```
WorkerPool: session 'pythonrepl-<uuid>' restarted 3 times in the last 60s —
possible restart loop (last worker exit code=-9, stderr tail='...')
```

The per-session count is also readable programmatically:

```python
pool.restart_count(session_id)          # restarts in the last 60 s; observability only
exit_code, stderr_tail = handle.death_summary()   # what the warning reports
```

Nothing branches on this value — it exists so the *cause* is visible. When you
see it, check, in order:

1. **Bootstrap time on this host** — see the procedure below. If
   spawn→ready approaches `bootstrap_timeout_ms`, spares are being killed for
   failing to boot; raise the budget or reduce `prewarm_pool_size` (fewer
   workers booting concurrently).
2. **Host load** — bootstrap is CPU/IO bound, and 12–14 s under 3× CPU
   oversubscription is measured, not hypothetical.
3. **The reported exit code and stderr tail** — `-9` means the host killed it
   (deadline or bootstrap timeout); a traceback in the tail means the worker
   died on its own (e.g. an import failure, or `RLIMIT_AS` too tight for
   pandas/numpy to `mmap` their extensions).
4. **The code being run** — a genuine runaway loop hitting `deadline_ms` on
   every call is a *correct* restart loop; the warning is then telling you the
   LLM keeps submitting non-terminating code.

### A related warning: an undersized shared executor

```
WorkerPool: the shared executor has 4 thread(s) but this pool can hold up to 6
live worker(s) (max_workers=4 + prewarm_pool_size=2), each of which can occupy
one thread for an entire blocking pipe read. ...
```

Each live worker can hold one thread of the shared executor for a whole
blocking pipe read — a request round-trip, or its readiness read while it
bootstraps. When there are fewer threads than possible live workers, requests
queue behind one another and the pool looks "slow" for reasons that have
nothing to do with the workers. Raise `PythonREPLTool(executor_max_workers=…)`
or lower `prewarm_pool_size`. The warning is advisory — nothing is clamped.

**Process teardown is deliberately immune to this.** `WorkerHandle` kills
workers on its own small, always-self-owned executor, never the shared one:
dispatching the SIGKILL to the same pool whose threads are parked on blocking
reads would mean the `deadline_ms` kill could never obtain a thread, while
freeing a thread required that kill to run — a deadlock in which the deadline
guarantee silently stops working. Keep that split if you refactor this class.

## 4c. Measuring worker bootstrap on your host (U3b)

Two independent measurements. The recorded baseline for both lives in
[`artifacts/logs/feat-500-bootstrap-profile.md`](../artifacts/logs/feat-500-bootstrap-profile.md).

**Import cost** — what the worker pays before it can serve anything:

```bash
python -X importtime -c "from parrot.tools.pythonrepl import PythonREPLTool" 2> importtime.log
sort -t'|' -k2 -n importtime.log | tail -25
```

On the reference dev box this totals **1.41 s**, of which only ~0.22 s is
pandas — ≈80 % is `parrot` framework init (navconfig/vault/documentdb/events/
navigator auth) that the REPL child never uses. Trimming that surface is
deliberately **out of scope** for FEAT-500 and tracked as a follow-up spec.

**Real spawn→ready** — from a running server's logs, for one session:

```bash
grep -E "spawned worker pid=|repl_worker: ready|prewarmed worker ready|worker is dead|possible restart loop" server.log
```

A healthy cold start looks like this (one spawn, one ready, no restarts):

```
WorkerHandle: spawned worker pid=81228
repl_worker: ready in 2412 ms (max_workers config=0), entering service loop
WorkerPool: prewarmed worker ready (pid=81228, bootstrap_ms=2412, pool size=1)
```

`bootstrap_ms` is measured by the worker itself (monotonic, from `main()`
entry to readiness) and reported in the `ReadyResponse` frame, so it is the
number to compare against `bootstrap_timeout_ms` — no host-side clock
arithmetic needed. The `WorkerHandle: spawned worker pid=` and
`prewarmed worker ready` lines are at **DEBUG** level.

---

## 5. ⚠️ Windows degradation (read this before deploying on Windows)

**On Windows, the worker gets none of the resource-limit guarantees this
document otherwise describes.**

| Guarantee | POSIX (Linux/macOS) | Windows |
|---|---|---|
| Separate process | ✅ | ✅ |
| Hard timeout enforcement | ✅ (`SIGKILL`) | ✅ (`TerminateProcess`, via `subprocess.Popen.kill()`) |
| Memory ceiling (`RLIMIT_AS`) | ✅ | ❌ **not enforced at all** |
| CPU ceiling (`RLIMIT_CPU`) | ✅ | ❌ **not enforced at all** |
| File-descriptor ceiling (`RLIMIT_NOFILE`) | ✅ | ❌ **not enforced at all** |
| No core dumps (`RLIMIT_CORE=0`) | ✅ | N/A (no Windows core-dump equivalent applied) |

`resource.setrlimit()` is POSIX-only. On import failure, the worker logs a
visible `logger.warning` ("rlimits are POSIX-only... running WITHOUT
memory/CPU/fd limits") and continues **without any memory or CPU bound** —
a runaway allocation or infinite loop on Windows is only stopped by the
host's `deadline_ms` timeout (which still works, since `Popen.kill()` maps
to `TerminateProcess` regardless of platform) or by Windows itself running
out of memory.

**Do not deploy `PythonREPLTool` on Windows for untrusted/LLM-generated
code without understanding this gap.** Windows Job Objects (which *can*
enforce memory/CPU/process-count limits, similar in spirit to POSIX
rlimits) are the natural next step and are tracked as future work — not
implemented in this feature.

---

## 6. History

- **Module 1 (palliative, landed first, independently)**: replaced the
  shared default `ThreadPoolExecutor` (`loop.run_in_executor(None, ...)`)
  with a dedicated, bounded one (`executor_max_workers`, default 4) — so a
  runaway loop, even before the rest of this feature existed, could only
  exhaust `PythonREPLTool`'s own thread pool, never the framework's shared
  one. That attribute (`tool._repl_executor`) still exists but is no
  longer on the code-execution path — the worker process replaced it as of
  Module 5.
- **Modules 2–9**: the worker protocol, `WorkerHandle`/`WorkerPool`
  lifecycle, `PythonREPLTool` integration, the namespace-API port, Arrow
  DataFrame transport, and the `RLIMIT_AS` calibration this document
  reflects.
- **FEAT-500 — readiness handshake & non-lethal namespace timeouts**: added
  the `ReadyResponse` frame plus `WorkerHandle.wait_ready()`/`is_ready`, so a
  worker is only used (and only counted as a prewarmed spare) once it has
  finished bootstrapping; made every non-`exec` timeout **non-lethal**
  (`NamespaceTimeoutError`, configurable via `namespace_timeout_ms`, replacing
  hard-coded 5 s/10 s/30 s budgets that SIGKILLed the worker); added
  `bootstrap_timeout_ms` and `WorkerBootstrapError`; guaranteed every worker
  failure carries a readable message (no more `ValueError('')` reaching the
  LLM); and made restart loops visible (`possible restart loop` warning +
  `WorkerPool.restart_count()`). Fixes a cold-start death spiral in which a
  host slower than the old 5 s budget could never produce a usable worker.
  See `sdd/specs/bug-workerpool-repl.spec.md`.
- **Post-FEAT-500 — `inprocess` escape hatch + bootstrap diagnostics**:
  added `execution_mode` / `PYTHON_REPL_EXECUTION_MODE` (§3b,
  `InProcessHandle`) as an explicit, logged way to run the pre-worker
  in-process path while the worker pool is battle-tested; enriched
  `WorkerBootstrapError` with the child's `/proc` state, a thread-starvation
  cause, the stdout tail, and worker-side stage markers on stderr (§6
  "Reading a `WorkerBootstrapError`").

### Reading a `WorkerBootstrapError`

Since the diagnostics pass that followed FEAT-500, the message a worker that
never sent its ready frame produces carries three extra facts:

```
REPL worker pid=31958 did not become ready within 30000 ms
  (no ready frame within the bootstrap budget;
   process: state=S (sleeping) threads=13 vmpeak=1234567 kB wchan=pipe_read cpu=1.20s);
  stderr tail: repl_worker[pid=31958] rlimits applied (...) | repl_worker[pid=31958] building namespace (...)
```

- **`cause`** distinguishes a stuck child (`no ready frame within the
  bootstrap budget`) from **thread starvation on the host** (`the readiness
  read never got an executor thread — all N thread(s) ... were busy`): in
  the second case the worker may be perfectly healthy and the fix is
  `executor_max_workers` / `prewarm_pool_size`, not the worker.
- **`process:`** is a `/proc/<pid>` snapshot taken *before* the kill
  (Linux only): `state=T` means stopped (SIGSTOP/SIGTTOU/debugger),
  `state=S` + `wchan` names what it sleeps on, `state=R` with a tiny `cpu=`
  means it never got scheduled, a huge `vmpeak` means it is thrashing
  against `rlimit_as_bytes`.
- **`stderr tail`** now always contains the worker's own stage markers
  (`interpreter up` → `rlimits applied` → `building namespace` →
  `namespace built ... sending ready frame`), written unbuffered to stderr
  before any logging is configured, so the last line is the last stage the
  child reached. `<empty>` now means the interpreter never executed the
  first line of `worker.main()` at all.

## See also

- `sdd/specs/sandbox-hardening.spec.md` — the full feature spec (design
  rationale, brainstorm decisions, acceptance criteria).
- [`docs/executors/docker-executor.md`](executors/docker-executor.md) — a
  **different, complementary** isolation layer: routes an entire tool
  call (`_execute()`) to a remote Docker/K8s runtime via the
  `parrot.tools.executors` framework. That mechanism relocates *where*
  `_execute()` runs; this document describes what `PythonREPLTool` itself
  does *within* that call. The two can be combined.
- [`artifacts/logs/feat-500-bootstrap-profile.md`](../artifacts/logs/feat-500-bootstrap-profile.md) —
  the worker bootstrap profile (import breakdown + spawn→ready timings) and
  the procedure for measuring both on your own host.
- [`artifacts/logs/feat-380-rlimit-as-calibration.md`](../artifacts/logs/feat-380-rlimit-as-calibration.md) —
  the `RLIMIT_AS` calibration evidence referenced in §3.

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
- **No in-process fallback.** If the worker cannot start, `_execute()`
  returns an explicit error (see §2) — the in-process `exec()` path is
  structurally unreachable from the async execution entrypoint.

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
| `rlimit_as_bytes` | **12 GiB** (`12 * 1024**3`) | Virtual address space ceiling (`RLIMIT_AS`) applied to the worker via `preexec_fn`. **Empirically calibrated** — see [`artifacts/logs/feat-380-rlimit-as-calibration.md`](../artifacts/logs/feat-380-rlimit-as-calibration.md) for the measurements (peak observed VmPeak 5522.8 MB across a real bootstrap+500MB-load+merge+plot session, ×2 margin — predates FEAT-423's reduction of the REPL bootstrap import surface; actual footprint is now smaller, so this default is conservative). Re-run `scripts/sdd/calibrate_rlimit_as.py` after a pandas/numpy/pyarrow version bump (or to tighten this default post-FEAT-423). |
| `rlimit_cpu_seconds` | `300` | `RLIMIT_CPU` — a safety net if the host's own `SIGKILL`-on-timeout somehow failed to fire. |
| `rlimit_nofile` | `256` | `RLIMIT_NOFILE` — bounds file descriptors. |
| `deadline_ms` | `60_000` | Host-enforced wall-clock deadline per `exec` call. On expiry: `SIGKILL` + namespace-loss error (see §2). |
| `max_workers` | `0` (→ `max(4, cpu_count())`, capped at 16) | Concurrency ceiling across the pool. Reaching it makes `acquire()` raise immediately — no queueing. |
| `idle_ttl_seconds` | `1800` (30 min) | A session's worker idle past this is killed and unmapped by the pool's background sweep. |
| `prewarm_pool_size` | `2` | Idle, pre-booted spare workers (pandas/numpy already imported — the bootstrap import surface shrank as of FEAT-423) kept ready so a session's first call doesn't pay the 1–3s import cost. |

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

## See also

- `sdd/specs/sandbox-hardening.spec.md` — the full feature spec (design
  rationale, brainstorm decisions, acceptance criteria).
- [`docs/executors/docker-executor.md`](executors/docker-executor.md) — a
  **different, complementary** isolation layer: routes an entire tool
  call (`_execute()`) to a remote Docker/K8s runtime via the
  `parrot.tools.executors` framework. That mechanism relocates *where*
  `_execute()` runs; this document describes what `PythonREPLTool` itself
  does *within* that call. The two can be combined.
- [`artifacts/logs/feat-380-rlimit-as-calibration.md`](../artifacts/logs/feat-380-rlimit-as-calibration.md) —
  the `RLIMIT_AS` calibration evidence referenced in §3.

---
id: F016
query_id: Q015
type: read
intent: Probe — reproduce the exact log signature with PythonPandasTool under CPU load
executed_at: 2026-09-02T13:43:00+02:00
duration_ms: 40000
parent_id: F009
depth: 1
---

# F016 — Reproduced: the report's exact log signature, on `dev`, with 36 busy-loop processes on 12 cores

## Summary

Two probes (`scratchpad/repro_load.py`, `scratchpad/repro_spiral.py`), each spawning `3 × cpu_count` CPU hogs first.

**Probe A** (`PythonPandasTool(dataframes={"sales": df})`): `df_locals` = 10 names (2 DataFrames + 8 scalars). Worker took **12.5 s** to reach `ready` (spawn 13:43:10.597 → ready 13:43:23.157). Call 0 nevertheless **succeeded in 12.69 s** — the set-iteration happened to seed a DataFrame first (`inject_dataframe`, 30 s budget), so the worker had time to boot. Demonstrates the hash-order dependency of F009.

**Probe B** (`PythonPandasTool(dataframes=None)` + one scalar `df_locals["n_rows"]=3` → seeded via `set_var`): output matches the report line-for-line:
`Executing Python code` (945) → `worker is dead, restarting` (241) → `bound to a prewarmed worker` (265) → spawn → `prewarmed worker ready` (187) → **5.09 s later** `Error executing Python code: ` (960, blank) → `worker is dead, restarting` again → returned `{'status': 'error', 'result': 'ToolError: TimeoutError: ', 'error': ''}`. Call 0 total 14.17 s; the spiral only ended because the third spare finished booting (14 s after spawn) before being consumed. Calls 1-2 then took 0.00 s. On a host that stays loaded (or has slower bootstrap) the spiral never ends, matching the report.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/pythonpandas.py`
  lines: 169-181
  symbol: `PythonPandasTool._get_worker_handle` (seeding; the `set_var` that timed out)
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py`
  lines: 412
  symbol: `WorkerHandle.set_var` (5.0 s)
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/pool.py`
  lines: 241, 265, 187
  excerpt: |
    [INFO]    13:44:01,406 python_repl_pandas.Tool(pythonrepl.py:945) :: Executing Python code: print(n_rows)...
    [WARNING] 13:44:01,407 parrot.tools.repl_worker.pool(pool.py:241) :: WorkerPool: session '...' worker is dead, restarting
    [DEBUG]   13:44:01,407 parrot.tools.repl_worker.pool(pool.py:265) :: WorkerPool: session '...' bound to a prewarmed worker
    [DEBUG]   13:44:01,410 parrot.tools.repl_worker.handle(handle.py:187) :: WorkerHandle: spawned worker pid=87572
    [DEBUG]   13:44:01,410 parrot.tools.repl_worker.pool(pool.py:187) :: WorkerPool: prewarmed worker ready (pool size=2)
    [ERROR]   13:44:06,495 python_repl_pandas.Tool(pythonrepl.py:960) :: Error executing Python code: 
    [WARNING] 13:44:06,496 parrot.tools.repl_worker.pool(pool.py:241) :: WorkerPool: session '...' worker is dead, restarting
    CALL 0 (14.17s): {'status': 'error', 'result': 'ToolError: TimeoutError: ', 'error': ''}

## Notes

Probe scripts live in the session scratchpad (not committed); the spec should turn Probe B into a deterministic regression test (e.g. a worker entrypoint with an injected bootstrap delay, or a fake handle whose first reply is delayed > 5 s).

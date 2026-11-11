---
kind: brief
slug: repl-executor-default-size
key: repl-executor-default-size
base_branch: dev
source:
  type: text
  ref: "PandasAgent startup warning: WorkerPool shared executor undersized"
  url: null
jira_issue_key: null
ledger_issue: null
created: "2026-11-11"
---

# Brief: Size PythonREPLTool's executor to the WorkerPool capacity by default

## Problem
Every default `PandasAgent` logs at first worker use:

```
[WARNING] parrot.tools.repl_worker.pool(pool.py:193) :: WorkerPool: the shared executor has 4 thread(s)
but this pool can hold up to 14 live worker(s) (max_workers=12 + prewarm_pool_size=2), ... Requests will
queue once 4 worker(s) are busy — consider PythonREPLTool(executor_max_workers=14) or a smaller prewarm_pool_size.
```

The warning is accurate: with the defaults, at most 4 worker round-trips run concurrently and the
rest queue behind thread starvation. `PandasAgent` gives the caller no way to change it.

## Root cause
Two independent defaults disagree. `PythonREPLTool.__init__` hard-codes
`executor_max_workers: int = 4` (`packages/ai-parrot/src/parrot/tools/pythonrepl.py:222`) and builds
`ThreadPoolExecutor(max_workers=executor_max_workers)` (`pythonrepl.py:286-287`). That executor is handed to
the `WorkerPool` (`pythonrepl.py:902-913`), whose live-worker capacity is
`_effective_ceiling(config) + prewarm_pool_size` (`packages/ai-parrot/src/parrot/tools/repl_worker/pool.py:190`),
where the ceiling auto-resolves to `min(max(4, os.cpu_count()), 16)` when `WorkerConfig.max_workers == 0`
(`pool.py:208-212`). On any host with >4 CPUs (or with prewarm > 0) the default executor is undersized,
and `_warn_if_executor_undersized()` (`pool.py:168-205`) fires. `PandasAgent` constructs the tool at
`packages/ai-parrot/src/parrot/bots/data.py:621` without `executor_max_workers`.

## Research findings
- `worker_config` is already known in `__init__` (`self._worker_config = worker_config`, `pythonrepl.py:304`),
  so the needed size can be computed before the executor is created.
- `PythonPandasTool` session clones reuse the source's `_repl_executor` (`pythonpandas.py:275`) but get their own
  `WorkerPool`; out of scope here (each pool's per-pool check still holds).
- Existing test `packages/ai-parrot/tests/test_pythonrepl_executor.py:49-56` asserts the default bound is 4 and
  that an explicit value overrides it — the first must be updated.
- `inprocess` mode also uses `_repl_executor` (`pythonrepl.py:992`); a larger default is harmless there.
- No open ledger issues on the touched files.

## Assumptions
- `executor_max_workers` becomes `Optional[int] = None`; `None` = auto-size to
  `WorkerPool._effective_ceiling(cfg) + cfg.prewarm_pool_size` with `cfg = worker_config or WorkerConfig()`.
  An explicit int keeps today's behaviour exactly (including the advisory warning when undersized).
- `PandasAgent.__init__` gains `python_repl_executor_max_workers: Optional[int] = None`, forwarded to
  `PythonPandasTool` alongside `python_repl_execution_mode`.
- Reuse the existing `_effective_ceiling` static method rather than duplicating the formula.

## Fix plan
- HOTFIX-repl-executor-default-size-1: auto-size the default executor in `PythonREPLTool`, expose the knob on
  `PandasAgent`, update/add tests.

## Validation commands
- `pytest packages/ai-parrot/tests/test_pythonrepl_executor.py -q`

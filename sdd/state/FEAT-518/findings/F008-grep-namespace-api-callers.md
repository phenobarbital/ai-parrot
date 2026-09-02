---
id: F008
query_id: Q009
type: grep
intent: Which tool is python_repl_pandas and who calls the namespace API around an execution
executed_at: 2026-09-02T13:38:30+02:00
duration_ms: 700
parent_id: null
depth: 0
---

# F008 — `python_repl_pandas` is `PythonPandasTool`; it calls the 5 s namespace API before AND after every execution

## Summary

`python_repl_pandas` is the `name` of `PythonPandasTool(PythonREPLTool)` in `tools/pythonpandas.py` (25, 40), instantiated by `PandasAgent` in `bots/data.py:577`. Namespace-API callers on the tool call path: `pythonpandas.py:178/180` (worker seeding via `inject_dataframe`/`set_var`), `:940` (`list_vars` before execute), `:983/:993` (`list_vars`/`get_var` after execute). Other callers exist outside the tool (`bots/data.py` 1724/2210/2501/2613/2677 `get_var`/`snapshot`; `bots/agent.py:251` `snapshot`; `tools/agent.py:424/430` `set_var`) — all share the same 5 s/10 s timeouts and the same kill-on-timeout semantics.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/pythonpandas.py`
  lines: 25-40
  symbol: `PythonPandasTool`
  excerpt: |
    class PythonPandasTool(PythonREPLTool):
        ...
        name = "python_repl_pandas"
- path: `packages/ai-parrot/src/parrot/bots/data.py`
  lines: 577-584
  symbol: `PandasAgent` tool construction
  excerpt: |
    pandas_tool = PythonPandasTool(dataframes=None, generate_guide=True, include_summary_stats=False, include_sample_data=False, sample_rows=2, report_dir=report_dir)
- path: `packages/ai-parrot/src/parrot/tools/pythonpandas.py`
  lines: 178-180
  symbol: `PythonPandasTool._get_worker_handle` (seeding)
- path: `packages/ai-parrot/src/parrot/tools/pythonpandas.py`
  lines: 940, 983, 993
  symbol: `PythonPandasTool._execute` (pre/post namespace calls)
- path: `packages/ai-parrot/src/parrot/bots/data.py`
  lines: 1724, 2210, 2501, 2613, 2677
  symbol: `PandasAgent` `get_var` / `snapshot` callers
- path: `packages/ai-parrot/src/parrot/bots/agent.py`
  lines: 251
  symbol: working-memory `tool.snapshot()` wiring
- path: `packages/ai-parrot/src/parrot/tools/agent.py`
  lines: 424-430
  symbol: `python_repl.set_var(...)` callers

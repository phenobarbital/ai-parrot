---
id: F006
query_id: Q006
type: read
intent: PythonREPLTool._execute and worker acquisition (log sites pythonrepl.py:945/960)
executed_at: 2026-09-02T13:38:00+02:00
duration_ms: 700
parent_id: null
depth: 0
---

# F006 — pythonrepl.py: any exception escaping the worker session becomes an error dict whose `error` is `str(e)`

## Summary

`_execute()` (920-977) logs `Executing Python code` at **945** and, on any `Exception`, logs `Error executing Python code: {e}` at **960** and returns `{"status": "error", "result": f"ToolError: {type(e).__name__}: {e}", "error": str(e)}` — line numbers match the report exactly. The worker is reached through `_worker_session()` (894-918) → `_get_worker_handle()` (871-892) → `pool.acquire(self._session_id)`; the pool is created lazily (837-869) with the tool's own 4-thread `_repl_executor` (245-248). `_get_worker_handle` is `async` and overridable (PythonPandasTool overrides it, F009); anything it raises lands in the 959 handler. `WorkerConfig` is whatever the constructor got (`worker_config=None` → defaults, 191/263).

## Citations

- path: `packages/ai-parrot/src/parrot/tools/pythonrepl.py`
  lines: 944-962
  symbol: `PythonREPLTool._execute`
  excerpt: |
    self.logger.info(f"Executing Python code: {code[:100]}...")          # :945
    ...
    async with self._worker_session() as handle:
        output = await handle.execute(query, debug=debug)
    except Exception as e:
        self.logger.error(f"Error executing Python code: {e}")          # :960
        msg = f"ToolError: {type(e).__name__}: {str(e)}"
        return {"status": "error", "result": msg, "error": str(e)}
- path: `packages/ai-parrot/src/parrot/tools/pythonrepl.py`
  lines: 871-892
  symbol: `PythonREPLTool._get_worker_handle`
  excerpt: |
    pool = await self._acquire_worker_pool()
    ...
    return await pool.acquire(self._session_id)
- path: `packages/ai-parrot/src/parrot/tools/pythonrepl.py`
  lines: 894-918
  symbol: `PythonREPLTool._worker_session`
- path: `packages/ai-parrot/src/parrot/tools/pythonrepl.py`
  lines: 853-868
  symbol: `PythonREPLTool._acquire_worker_pool`
  excerpt: |
    self._worker_pool = WorkerPool(config=self._worker_config, output_dir=..., repl_kwargs=..., executor=self._repl_executor)
- path: `packages/ai-parrot/src/parrot/tools/pythonrepl.py`
  lines: 245-248
  symbol: `PythonREPLTool._repl_executor`
  excerpt: |
    self._repl_executor = ThreadPoolExecutor(max_workers=executor_max_workers, thread_name_prefix="python-repl")
- path: `packages/ai-parrot/src/parrot/tools/pythonrepl.py`
  lines: 979-1019
  symbol: `PythonREPLTool.get_var` / `set_var` / `list_vars` / `snapshot` / `inject_dataframe`

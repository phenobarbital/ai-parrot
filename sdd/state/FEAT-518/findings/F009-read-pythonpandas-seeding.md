---
id: F009
query_id: Q010
type: read
intent: PythonPandasTool worker seeding (_get_worker_handle) and metadata scalars
executed_at: 2026-09-02T13:39:00+02:00
duration_ms: 800
parent_id: F008
depth: 1
---

# F009 — Every fresh worker is seeded with `set_var` (5 s) scalars before the caller's request is even sent

## Summary

`PythonPandasTool._get_worker_handle()` (137-181) wraps the base acquisition and, whenever the pool hands back a **different `WorkerHandle` object** (crash restart, TTL eviction, deadline kill — the docstring names them), clears `_seeded_df_names` and re-pushes every `df_locals` entry: DataFrames via `inject_dataframe` (30 s timeout, F004) and everything else via `set_var` (**5.0 s**). `_process_dataframes` (505-522) puts **four scalar metadata entries per DataFrame name and per alias** (`*_row_count`, `*_col_count`, `*_shape`, `*_columns`) into `df_locals`, so a single registered dataset yields 8 `set_var` calls. Iteration is over a `set` (`new_names = set(self.df_locals) - self._seeded_df_names`), so **which call hits the cold worker first is hash-order dependent** — a DataFrame first gives the worker 30 s to boot, a scalar first gives it 5 s.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/pythonpandas.py`
  lines: 137-181
  symbol: `PythonPandasTool._get_worker_handle`
  excerpt: |
    handle = await super()._get_worker_handle()
    if id(handle) != self._seeded_worker_handle_id:
        self._seeded_df_names = set()
        self._seeded_worker_handle_id = id(handle)
    new_names = set(self.df_locals) - self._seeded_df_names
    if new_names:
        for name in new_names:
            value = self.df_locals[name]
            if isinstance(value, pd.DataFrame):
                await handle.inject_dataframe(name, value)
            else:
                await handle.set_var(name, value)
- path: `packages/ai-parrot/src/parrot/tools/pythonpandas.py`
  lines: 505-522
  symbol: `PythonPandasTool._process_dataframes`
  excerpt: |
    self.df_locals[df_name] = df
    self.df_locals[df_alias] = df
    for key in [df_name, df_alias]:
        self.df_locals[f"{key}_row_count"] = len(df)
        self.df_locals[f"{key}_col_count"] = len(df.columns)
        self.df_locals[f"{key}_shape"] = df.shape
        self.df_locals[f"{key}_columns"] = df.columns.tolist()
- path: `packages/ai-parrot/src/parrot/tools/pythonpandas.py`
  lines: 183-192
  symbol: `PythonPandasTool.reset_environment`

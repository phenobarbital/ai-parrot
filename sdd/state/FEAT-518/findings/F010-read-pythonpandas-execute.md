---
id: F010
query_id: Q010
type: read
intent: PythonPandasTool._execute override — pre/post namespace calls and their error handling
executed_at: 2026-09-02T13:39:10+02:00
duration_ms: 600
parent_id: F008
depth: 1
---

# F010 — `_execute` swallows namespace-API failures, but each swallowed timeout has already killed the worker

## Summary

`PythonPandasTool._execute()` (910-1010): (1) `pre_keys = set(await self.list_vars())` inside `try/except Exception: pre_keys = set()` (939-942) — a 5 s timeout here is silently ignored, **but `_send` has already SIGKILLed the worker** (F004); (2) `super()._execute()` (944) then acquires again → pool sees a dead worker → binds the next spare → seeding (F009) → 5 s → `TimeoutError` → 960 log + error dict; (3) the audit block (981-995) calls `list_vars`/`get_var` again in try/except → another acquire, another dead spare, another 5 s. Three 5 s waits per tool call, each killing a worker — matching the report's 5 s grid (`10.205 → 15.208 → 20.213 → 25.217`).

## Citations

- path: `packages/ai-parrot/src/parrot/tools/pythonpandas.py`
  lines: 939-944
  symbol: `PythonPandasTool._execute` (pre-exec)
  excerpt: |
    try:
        pre_keys = set(await self.list_vars())
    except Exception:
        pre_keys = set()
    result = await super()._execute(code, debug=debug, **kwargs)
- path: `packages/ai-parrot/src/parrot/tools/pythonpandas.py`
  lines: 981-995
  symbol: `PythonPandasTool._execute` (audit / DataFrame preview)
  excerpt: |
    try:
        current_keys = set(await self.list_vars())
    except Exception:
        current_keys = set()
    new_keys = current_keys - pre_keys
    for key in new_keys:
        ...
        try:
            val = await self.get_var(key)
        except Exception:
            continue

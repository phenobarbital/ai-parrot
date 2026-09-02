---
id: F007
query_id: Q008
type: grep
intent: Where the empty ValueError comes from (manager.py:1864, base.py:1504)
executed_at: 2026-09-02T13:38:20+02:00
duration_ms: 600
parent_id: null
depth: 0
---

# F007 — The empty `ValueError` is `raise ValueError(result.error)` with `result.error == ""`

## Summary

Three hits for "Error executing tool". `AbstractClient` (clients/base.py 1495-1506) calls `tool_manager.execute_tool`, and if the `ToolResult.status == "error"` it does `raise ValueError(result.error)` — when `error` is the empty string (F006 with a `TimeoutError`, whose `str()` is `''`, F017) the result is `ValueError('')`, i.e. exactly `Raw Result Type: <class 'ValueError'>` with blank text. `ToolManager.execute_tool` (tools/manager.py 1862-1864) only logs and re-raises. `AbstractTool.execute` (tools/abstract.py 1014-1028) builds the `ToolResult` from the `{status, result, error}` dict verbatim — no timeout wrapper exists on this path (grep for `wait_for|asyncio.timeout` in abstract.py/manager.py: 0 hits).

## Citations

- path: `packages/ai-parrot/src/parrot/clients/base.py`
  lines: 1495-1506
  symbol: `AbstractClient` tool execution wrapper
  excerpt: |
    result = await self.tool_manager.execute_tool(tool_name, merged, permission_context=perm_ctx)
    if isinstance(result, ToolResult):
        if result.status == "error":
            raise ValueError(result.error)
    ...
    except Exception as e:
        self.logger.error(f"Error executing tool {tool_name}: {e}")   # :1504
- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 1862-1864
  symbol: `ToolManager.execute_tool`
  excerpt: |
    except Exception as e:
        self.logger.error("Error executing tool %s: %s", tool_name, e)
        raise
- path: `packages/ai-parrot/src/parrot/tools/abstract.py`
  lines: 1014-1028
  symbol: `AbstractTool.execute` (ToolResult normalisation)
  excerpt: |
    elif isinstance(raw_result, dict) and "status" in raw_result and "result" in raw_result:
        tool_result = ToolResult(**raw_result)
- path: `packages/ai-parrot/src/parrot/clients/google/client.py`
  lines: 1959-1961
  symbol: Google client tool-result loop
  excerpt: |
    elif isinstance(result, Exception):
        tc.error = str(result)
        self.logger.error(f"Tool {tc.name} failed: {result}")

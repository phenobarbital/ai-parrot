---
id: F005
query_id: Q005
type: read
intent: Understand ToolManager.execute_tool dispatch path for delegate proposals
executed_at: 2026-09-21T22:09:00Z
depth: 0
parent_id: null
---

# F005 — ToolManager.execute_tool dispatch

## Summary

`ToolManager.execute_tool(tool_name, parameters, permission_context, return_tool_result)` at manager.py:L1609-1668 is the public entry point for tool dispatch. It wraps `_execute_tool_impl` with an optional FEAT-538 invocation observer. The delegate's accepted proposals would dispatch through this same method, preserving permission checks, guardrails, result hooks, and observation. The `return_tool_result=True` opt-in (FEAT-536) returns a complete `ToolResult` rather than just the result value.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 1609-1668
  symbol: `ToolManager.execute_tool`
  excerpt: |
    async def execute_tool(
        self, tool_name: str, parameters: Dict[str, Any],
        permission_context: Optional["PermissionContext"] = None,
        *, return_tool_result: bool = False,
    ) -> Any:
        observer = self._invocation_observer
        if observer is None:
            return await self._execute_tool_impl(
                tool_name, parameters, permission_context,
                return_tool_result=return_tool_result)

## Notes

The delegate's dispatch path mirrors PlanToolNode's: validate the proposal against `args_schema`, then call `ToolManager.execute_tool()`. The observer integration means delegate dispatches automatically participate in task-memory correlation (FEAT-538) if enabled.

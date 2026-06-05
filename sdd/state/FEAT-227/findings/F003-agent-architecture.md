---
id: F003
query_id: Q003
type: read
intent: Understand Agent/Bot architecture and toolkit integration patterns
executed_at: 2026-06-05T00:00:00Z
duration_ms: 2000
parent_id: null
depth: 0
---

# F003 — Agent/Bot architecture and toolkit patterns

## Summary

AI-Parrot agents inherit from BasicAgent → Chatbot → BaseBot → AbstractBot. Agents
define tools via `agent_tools()` override, returning a list of AbstractTool instances.
AbstractToolkit auto-discovers public async methods as tools via reflection. Tools are
registered in a ToolManager which handles schema adaptation per provider. Agents are
registered with `@register_agent(name=...)`. The tool invocation loop is ReAct-style
with up to 10 rounds of tool calls.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/agent.py`
  lines: 37-264
  symbol: `BasicAgent(Chatbot)`
  excerpt: |
    class BasicAgent(Chatbot):
        def agent_tools(self) -> List[AbstractTool]:
            """Override to return agent-specific tools"""
        def _get_default_tools(self):
            # Adds PythonREPLTool, ToJsonTool by default

- path: `packages/ai-parrot/src/parrot/tools/toolkit.py`
  lines: 191-544
  symbol: `AbstractToolkit`
  excerpt: |
    class AbstractToolkit:
        def get_tools(self) -> List[AbstractTool]:  # auto-discovers async methods
        def _pre_execute(self, tool_name, **kwargs):  # lifecycle hook
        def _post_execute(self, tool_name, result, **kwargs):  # lifecycle hook

- path: `packages/ai-parrot/src/parrot/tools/abstract.py`
  lines: 46-78
  symbol: `ToolResult`
  excerpt: |
    class ToolResult:
        success: bool, status: str, result: Any, error: Optional[str],
        metadata: Dict, files: Optional[list], images: Optional[list]

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  symbol: `@register_agent`
  excerpt: |
    @register_agent(name="hr_agent", at_startup=True)
    class HRAgent(Agent): ...

## Notes

- `as_tool()` method on agents enables agent composition (agent-as-tool)
- MCP server integration is built-in (add_mcp_server, add_local_mcp_server)
- Tool lifecycle events: BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent
- ToolResult supports `images` field — directly useful for returning screenshots

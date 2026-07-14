---
type: Wiki Entity
title: ToolManager
id: class:parrot.tools.manager.ToolManager
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Unified tool manager for handling tools across AbstractBot and AbstractClient.
relates_to:
- concept: class:parrot.tools.mcp_mixin.MCPToolManagerMixin
  rel: extends
---

# ToolManager

Defined in [`parrot.tools.manager`](../summaries/mod:parrot.tools.manager.md).

```python
class ToolManager(MCPToolManagerMixin)
```

Unified tool manager for handling tools across AbstractBot and AbstractClient.

Capabilities:
- Local tool registration and execution
- MCP server management (via MCPToolManagerMixin)
- Tool schema generation for LLM providers

## Methods

- `def resolver(self) -> Optional['AbstractPermissionResolver']` — Get the current permission resolver.
- `def set_resolver(self, resolver: 'AbstractPermissionResolver') -> None` — Set or swap the permission resolver at runtime.
- `def broker(self) -> Optional[Any]` — Return the credential broker, or None if none is configured.
- `def set_broker(self, broker: Any) -> None` — Set the credential broker that gates credentialed tool calls.
- `def set_grant_guard(self, guard: 'GrantGuard') -> None` — Set the grant guard for tool-level bounded approval windows.
- `def grant_guard(self) -> Optional[GrantGuard]` — Return the current grant guard, or None if not configured.
- `def set_confirmation_guard(self, guard: 'ConfirmationGuard') -> None` — Set the confirmation guard for per-call HITL tool-call review.
- `def confirmation_guard(self) -> Optional['ConfirmationGuard']` — Return the current confirmation guard, or None if not configured.
- `def search_tools(self, query: str, limit: int=15) -> str` — Search for tools by name or description.
- `def default_tools(self, tools: list=None) -> List[AbstractTool]`
- `def tools(self) -> List[AbstractTool]` — Get list of registered tool instances.
- `def sync(self, other_manager: 'ToolManager') -> None` — Sync tools from another ToolManager instance.
- `def add_tool(self, tool: Union[ToolDefinition, AbstractTool], name: Optional[str]=None) -> None` — Add a tool to the manager.
- `def register_tool(self, tool: Union[dict, ToolDefinition, AbstractTool]=None, name: str=None, description: str=None, input_schema: Dict[str, Any]=None, function: Callable=None) -> None` — Register a tool in the unified format.
- `def register(self, tool: Union[dict, ToolDefinition, AbstractTool]=None, name: str=None, description: str=None, input_schema: Dict[str, Any]=None, function: Callable=None, capability_registry=None) -> None` — Alias for register_tool with optional CapabilityRegistry auto-registration.
- `def register_tools(self, tools: List[Union[ToolDefinition, AbstractTool]]) -> None` — Register multiple tools from list or dictionary.
- `def load_tool(self, tool_name: str, **kwargs) -> bool` — Load a tool by name.
- `def register_toolkit(self, toolkit: Union[str, 'AbstractToolkit', type], **kwargs) -> List[AbstractTool]` — Register all tools from a toolkit.
- `def get_tool_schemas(self, provider_format: ToolFormat=ToolFormat.GENERIC) -> List[Dict[str, Any]]` — Get tool schemas formatted for specific LLM provider.
- `def get_tool(self, tool_name: str) -> Optional[Any]` — Get tool instance by name.
- `def list_categories(self) -> List[str]` — List available tool categories.
- `def get_tools_by_category(self, category: str) -> List[str]` — Get tools by category.
- `def list_tools(self) -> List[str]` — Get list of registered tool names.
- `def get_tools(self) -> Dict[str, Any]` — Get all registered tools.
- `def get_all_tools(self) -> List[Union[ToolDefinition, AbstractTool]]` — Get all registered tool instances.
- `def all_tools(self) -> Generator[Any, Any, Any]` — Get all registered tools with their schemas as a generator.
- `def unregister_tool(self, tool_name: str) -> bool` — Unregister a tool by name.
- `def clear_tools(self) -> None` — Clear all registered tools.
- `def remove_tool(self, tool_name: str) -> None` — Remove a tool by name.
- `def build_tools_description(self, format_style: str='compact', include_parameters: bool=True, include_examples: bool=False, max_tools: Optional[int]=None) -> str` — Build formatted tool descriptions for system prompts.
- `def get_tools_summary(self) -> Dict[str, Any]` — Get a summary of all registered tools.
- `async def execute_tool(self, tool_name: str, parameters: Dict[str, Any], permission_context: Optional['PermissionContext']=None) -> Any` — Execute a registered tool function.
- `async def register_a2a_agent(self, url: str) -> RegisteredAgent` — Register an A2A agent by its URL.
- `def get_a2a_agents(self) -> List[RegisteredAgent]` — Get all registered A2A agents.
- `def get_by_skill(self, skill: str) -> List[RegisteredAgent]` — Get agents that have a specific skill (by ID or name substring).
- `def get_by_tag(self, tag: str) -> List[RegisteredAgent]` — Get agents that have a specific tag.
- `def search_a2a_agents(self, query: str) -> List[RegisteredAgent]` — Search agents by name, description, tags, or skills.
- `def list_a2a_agents(self) -> List[str]` — List names of registered A2A agents.
- `async def execute_tool_call(self, content_block: Dict[str, Any]) -> Dict[str, Any]` — Execute a single tool call and return the result.
- `def tool_count(self) -> int` — Get the number of registered tools.
- `def clone(self, *, include_search_tool: bool=False) -> 'ToolManager'` — Return a new ``ToolManager`` sharing this manager's tool registrations.
- `def share_dataframe(self, name: str, df: 'pd.DataFrame', meta: Dict[str, Any]=None) -> str` — Store df in shared context and push into python_pandas if present.
- `def get_shared_dataframe(self, name: str) -> 'pd.DataFrame'`
- `def list_shared_dataframes(self) -> List[str]`
- `def clear_shared(self) -> None`
- `def add_result_hook(self, fn: Callable[[str, Any, Dict[str, Any]], None]) -> None` — Register a function(tool_name, result, metadata) -> None run after each tool.

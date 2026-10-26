---
id: F003
query_id: [Q022, Q039, Q032, Q049]
type: read
intent: "ToolManager registration / removal API (verify no category mount/unmount) and how tool schemas are compiled per provider."
executed_at: 2026-10-25T22:43:31Z
duration_ms: 0
parent_id: null
depth: 0
lane_origin: FC-004-toolmanager-registration-schemas
---

# F003 — ToolManager: flat register/unregister by name, categories are a dict index, no mount/unmount lifecycle; one ToolSchemaAdapter already emits per-provider schemas

## Summary

`ToolManager(MCPToolManagerMixin)` (core `parrot/tools/manager.py`, 3038 lines) registers tools with `register_tool(tool, name, description, input_schema, function)`, `register_tools`, `register_toolkit(toolkit, **kwargs)`, and removes with `unregister_tool(name) -> bool` / `remove_tool(name)` / `clear_tools()`. Categories exist only as `self._categories: dict[str, list[str]]` read by `list_categories()` / `get_tools_by_category()` — there is no "mount/unmount a category" operation and no lazy definition loading; `search_tools(query, limit)` / `rank_tools` do lexical search over registered tools. Provider tool specs come from `get_tool_schemas(provider_format: ToolFormat)` through `ToolSchemaAdapter.clean_schema_for_provider` with `ToolFormat {OPENAI, ANTHROPIC, GOOGLE, GROQ, VERTEX, GENERIC, BEDROCK}` (S3 feasibility: the per-provider compile step already exists). Execution goes through `execute_tool(tool_name, parameters, permission_context, return_tool_result)` → `_execute_tool_impl`, with pluggable `resolver`, `execution_policy`, `broker`, `grant_guard`, `confirmation_guard`, `invocation_observer`, output guards (`_apply_output_guards`) and result hooks. ToolManager also owns A2A remote registration: `register_a2a_agent(url) -> RegisteredAgent` fetches the agent card over HTTP and stores it in `self._registered_agents`; `share_dataframe`/`get_shared_dataframe` share pandas frames between tools. Prompt-cache hints are a client-level hook `AbstractClient._apply_cache_hints(payload, segments, trace_context)` (Anthropic `cache_control`, Google `CachedContent`, OpenAI automatic) — S4 lands there.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 75-85
  symbol: `ToolFormat`
  excerpt: |
    class ToolFormat(Enum):
        OPENAI = "openai"
        ANTHROPIC = "anthropic"
        GOOGLE = "google"
        GROQ = "groq"
        VERTEX = "vertex"
        GENERIC = "generic"
        BEDROCK = "bedrock"
- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 87-93
  symbol: `ToolSchemaAdapter.clean_schema_for_provider`
- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 289
  symbol: `ToolManager`
  excerpt: |
    class ToolManager(MCPToolManagerMixin):
- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 853-860
  symbol: `ToolManager.register_tool`
  excerpt: |
    def register_tool(self, tool: Union[dict, ToolDefinition, AbstractTool] = None, name: str = None,
                      description: str = None, input_schema: Dict[str, Any] = None, function: Callable = None) -> None:
- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 1190
  symbol: `ToolManager.register_toolkit`
- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 1313
  symbol: `ToolManager.get_tool_schemas`
  excerpt: |
    def get_tool_schemas(self, provider_format: ToolFormat = ToolFormat.GENERIC) -> List[Dict[str, Any]]:
- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 1404-1410
  symbol: `ToolManager.list_categories`, `get_tools_by_category`
  excerpt: |
    def list_categories(self) -> List[str]:
        return list(self._categories.keys())
    def get_tools_by_category(self, category: str) -> List[str]:
        return self._categories.get(category, [])
- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 1434-1458
  symbol: `ToolManager.unregister_tool`, `clear_tools`, `remove_tool`
  excerpt: |
    def unregister_tool(self, tool_name: str) -> bool:
        if tool_name in self._tools:
            del self._tools[tool_name]
            return True
- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 723-794
  symbol: `ToolManager.rank_tools`, `search_tools`
- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 1787-1800
  symbol: `ToolManager.execute_tool`
  excerpt: |
    async def execute_tool(self, tool_name: str, parameters: Dict[str, Any],
                           permission_context: Optional["PermissionContext"] = None, *,
                           return_tool_result: bool = False) -> Any:
- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 435-583
  symbol: `set_resolver`, `set_execution_policy`, `set_broker`, `set_grant_guard`, `set_confirmation_guard`
- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 2302-2338
  symbol: `ToolManager.register_a2a_agent`
  excerpt: |
    async def register_a2a_agent(self, url: str) -> RegisteredAgent:
        agent_url = f"{url}/.well-known/agent.json"
        card = AgentCard.from_dict(data)
        agent = RegisteredAgent(url=url, card=card)
        self._registered_agents[card.name] = agent
- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 18
  symbol: import `RegisteredAgent`
  excerpt: |
    from ..a2a.models import RegisteredAgent, AgentCard
- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 2429
  symbol: `ToolManager._apply_output_guards`
- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 2895-2937
  symbol: `ToolManager.share_dataframe`, `get_shared_dataframe`, `list_shared_dataframes`
- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 2952
  symbol: `ToolManager.cleanup_toolkits`
- path: `packages/ai-parrot/src/parrot/tools/abstract.py`
  lines: 703-711
  symbol: `AbstractTool.get_tool_schema`
  excerpt: |
    def get_tool_schema(self) -> Dict[str, Any]:
        return self.get_schema()
- path: `packages/ai-parrot/src/parrot/clients/base.py`
  lines: 565-590
  symbol: `AbstractClient._apply_cache_hints`
  excerpt: |
    def _apply_cache_hints(self, payload, segments, trace_context=None):
        """Translate CacheableSegments to provider-native cache hints.
        - AnthropicClient — cache_control blocks.
        - OpenAIClient — automatic (pass-through).
        - GoogleGenAIClient — CachedContent.
- path: `packages/ai-parrot/src/parrot/tools/decorators.py`
  lines: 39
  symbol: `tool_schema`

## Notes

`MCPToolManagerMixin` (`parrot/tools/mcp_mixin.py:31`) is what gives ToolManager its MCP-server attach methods — the natural seam for a "RemoteToolkit attach" too. Category-level mount/unmount (D8) is NEW; the `_categories` index and `search_tools` are reusable building blocks.

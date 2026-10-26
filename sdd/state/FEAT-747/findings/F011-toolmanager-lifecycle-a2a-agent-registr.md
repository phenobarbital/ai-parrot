---
id: F011
query_id: Q037
type: read
intent: "Read ToolManager: registration/removal lifecycle, per-session identity, execute path (where catalog.mount and the gating would hook)."
executed_at: 2026-10-25T23:08:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: FC-014
---

# F011 — ToolManager lifecycle, A2A agent registry and skill search

## Summary

`ToolManager(MCPToolManagerMixin)` (3038 lines) owns local tools (`add_tool`/`register_tool`/`register_tools`/`register_toolkit`, `unregister_tool`/`remove_tool`/`clear_tools`), schema generation (`get_tool_schemas`), execution (`execute_tool` 1787, `execute_tool_call` 2403) with pluggable `resolver`, `execution_policy`, `grant_guard`, `confirmation_guard`, `invocation_observer`, `result_hook`s, and `clone()` for per-session copies. It ALSO is where remote A2A agents live: `register_a2a_agent(url)` fetches `/.well-known/agent.json`, stores a `RegisteredAgent(url, card)` in `_registered_agents`, and `get_by_skill` / `get_by_tag` / `search_a2a_agents` do substring matching over card skills/tags — the only existing capability-ish search, and it is per-ToolManager, remote-only, string-matching. `_shared['dataframes']` is the intra-agent dataframe hand-off.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 289-330
  symbol: `ToolManager.__init__`
  excerpt: |
    def __init__(self, logger=None, debug=False, include_search_tool=False,
                 resolver: Optional["AbstractPermissionResolver"] = None, execution_policy: Optional[Any] = None):
        self._shared: Dict[str, Any] = {"dataframes": {}}  # name -> (df, meta)
        self._invocation_observer: Optional[Any] = None

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 827-853
  symbol: `ToolManager.add_tool / register_tool`
  excerpt: |
    def add_tool(self, tool: Union[ToolDefinition, AbstractTool], name: Optional[str] = None

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 1190
  symbol: `ToolManager.register_toolkit`
  excerpt: |
    def register_toolkit(self, toolkit: Union[str, "AbstractToolkit", type], **kwargs)

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 1434-1458
  symbol: `ToolManager.unregister_tool / clear_tools / remove_tool`
  excerpt: |
    def unregister_tool(self, tool_name: str) -> bool:
    def remove_tool(self, tool_name: str) -> None:

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 1787
  symbol: `ToolManager.execute_tool`
  excerpt: |
    async def execute_tool(

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 2302-2336
  symbol: `ToolManager.register_a2a_agent`
  excerpt: |
    agent_url = f"{url}/.well-known/agent.json"
    card = AgentCard.from_dict(data)
    agent = RegisteredAgent(url=url, card=card)
    self._registered_agents[card.name] = agent

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 2342-2398
  symbol: `ToolManager.get_by_skill / get_by_tag / search_a2a_agents`
  excerpt: |
    def get_by_skill(self, skill: str) -> List[RegisteredAgent]:
        for s in agent.card.skills:
            if skill_lower in s.id.lower() or skill_lower in s.name.lower():

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 2403
  symbol: `ToolManager.execute_tool_call`
  excerpt: |
    async def execute_tool_call(

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 2824
  symbol: `ToolManager.clone`
  excerpt: |
    def clone(self, *, include_search_tool: bool = False) -> "ToolManager":

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 2934-2952
  symbol: `ToolManager.list_shared_dataframes / add_result_hook / cleanup_toolkits`
  excerpt: |
    def add_result_hook(self, fn: Callable[[str, Any, Dict[str, Any]], None])

## Notes

Per-session caller identity is not a ToolManager attribute per se; it arrives as `PermissionContext` in guardrail extras (FC-013) and via `set_resolver`. `identity|session_id|user_id|principal|policy|pbac|guardrail` matches 86 lines in manager.py — the execute path threads them. Dynamic register/unregister exists, so a `catalog.mount` could add a tool at runtime with no new lifecycle machinery.

[citation-check: stale] packages/ai-parrot/src/parrot/tools/manager.py:289-330 — `class ToolManager(MCPToolManagerMixin)` at l.289, its `__init__` at l.299 (the file's other `__init__` at l.284 belongs to a different class); add_tool 827, register_tool 853, unregister_tool 1434, clear_tools 1441, remove_tool 1447, execute_tool 1787, register_a2a_agent 2302, get_by_skill 2342, search_a2a_agents 2371, execute_tool_call 2403, clone 2824 verified

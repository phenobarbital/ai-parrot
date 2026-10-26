---
id: F020
query_id: Q009
type: wiki_page
intent: "Orient: ToolManager — tool registration/removal lifecycle and per-session identity (needed for catalog.mount and caller identity)."
executed_at: 2026-10-25T23:08:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: FW-010
---

# F020 — ToolManager has add/register/unregister/remove and category listing but no mount/unmount-by-category lifecycle; guard chain (resolver, execution_policy, broker, grant/confirmation guards) is the hook point; a CapabilityRegistry parameter exists

## Summary

`tools/manager.py::ToolManager` API: `add_tool`, `register_tool(tool, name, description, input_schema, function)`, `register(..., capability_registry)` ('Alias for register_tool with optional CapabilityRegistry auto-registration'), `register_tools`, `register_toolkit`, `load_tool` (from discovered `TOOL_REGISTRY`), `get_tool`, `list_tools`, `get_tools`, `unregister_tool`, `remove_tool`, `clear_tools`, `list_categories`, `get_tools_by_category(category)`, `search_tools/rank_tools` (lexical), `get_tool_schemas(provider_format)` via `ToolSchemaAdapter` (google/groq/openai/bedrock). Policy/identity hooks: `set_resolver` (permission resolver), `set_execution_policy` + `_apply_execution_policy(tool)`, `set_broker` (credential broker), `set_grant_guard`, `set_confirmation_guard`, `set_toolkit_param_hook(hook, subject)`, `set_server_param_source`, `build_toolkit`. `_log_enforcement(tool_name, tool_kind, layer, decision, permission_context, reason)` emits a uniform structured enforcement record. Per-session ToolManagers exist (TASK-3662 'AgentTalk._apply_user_toolkit_overrides on the session ToolManager'; ledger 294a7574640e). No `mount/unmount` category lifecycle (confirms parent VERIFY), but `list_categories/get_tools_by_category/unregister_tool` are the primitives it would compose from. The `capability_registry` argument to `register()` means a `CapabilityRegistry` type exists somewhere — not resolved in this lane.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: n/a (API outline)
  symbol: `ToolManager`
  wiki_page_id: file:packages/ai-parrot/src/parrot/tools/manager.py
  excerpt: |
    class ToolManager: __init__(self, logger, debug, include_search_tool, resolver, execution_policy)
      set_resolver / set_execution_policy / set_broker / set_grant_guard / set_confirmation_guard
      register(self, tool, name, description, input_schema, function, capability_registry): Alias for register_tool with optional CapabilityRegistry auto-registration.
      list_categories(); get_tools_by_category(category); unregister_tool(tool_name); remove_tool(tool_name)
      _log_enforcement(self, tool_name, tool_kind, layer, decision, permission_context, reason)

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: n/a (API outline)
  symbol: `ToolSchemaAdapter / ToolDefinition / ToolNameCollisionError`

- path: `sdd/tasks/completed/TASK-3662-agenttalk-session-overrides.md`
  lines: n/a
  symbol: `session ToolManager overrides`
  wiki_page_id: file:sdd/tasks/completed/TASK-3662-agenttalk-session-overrides.md (score=0.28)

## Notes

`[cross-lane: type=grep, intent=class CapabilityRegistry — where it lives and what it indexes (may already be the capability catalog the brainstorm wants)]`. `[cross-lane: type=grep, intent=def execute_tool in manager.py — guard chain and PermissionContext construction line range]`.

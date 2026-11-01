---
id: F019
query_id: Q039
type: grep
intent: "Existing per-agent tool allow/deny mechanism (tools_deny equivalent)."
executed_at: 2026-10-30T16:44:46Z
duration_ms: 700
parent_id: null
depth: 0
merged_from: [FC-020-tool-allowlist-mechanisms]
---

# F019 — Tool gating today is allowlist-shaped (`allowed_tools` on Agent/MCP/execution_plan/host_hooks) plus PBAC policy denial in ToolManager; no `tools_deny` blocklist field exists

## Summary

~120 matches; clusters: `tools/execution_plan/{toolkit,catalog,repair}.py`, `tools/host_hooks.py` (14), `tools/spawn.py`, `tools/mcp_mixin.py`, `bots/flows/authoring/catalog.py`, `mcp/integration.py`, `tools/manager.py` (policy "denied" paths), `bots/agent.py` (`allowed_tools` whitelist when registering MCP tools). No identifier named tools_deny/denied_tools/disallowed_tools/tool_blocklist/exclude_tools exists → a deny list is a new field, or the expert manifest expresses it as an allowlist.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/agent.py`
  lines: 1090-1142
  symbol: `Agent (MCP registration allowed_tools)`
  excerpt: |
    allowed_tools: Optional[List[str]] = None,
        allowed_tools: Whitelist of tool names to register
    if allowed_tools: config.allowed_tools = allowed_tools

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 1945-2029
  symbol: `ToolManager (policy denial)`
  excerpt: |
    error_message = tool_call_outcome.reason or "Policy denied"
    error=f"Permission denied: '{tool.name}' requires {required}",

- path: `packages/ai-parrot/src/parrot/tools/host_hooks.py`
  lines: 1-200
  symbol: `host hooks allowed_tools`
  excerpt: |
    (14 allowed_tools mentions — host-level tool allowlist hook)

- path: `packages/ai-parrot/src/parrot/tools/mcp_mixin.py`
  lines: 1-200
  symbol: `MCP allowed_tools`
  excerpt: |
    (11 allowed_tools mentions)

## Notes

PBAC (`BotConfig.policies`, FC-006) is the existing deny mechanism with audit; a per-expert "never spawn" rule could be a policy rule rather than a new field.

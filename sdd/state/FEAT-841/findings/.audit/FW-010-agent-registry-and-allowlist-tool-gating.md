---
id: FW-010
query_id: Q006
type: wiki_query
intent: "Orient: AgentRegistry registration and per-session ToolManager with a restricted tool manifest."
executed_at: 2026-11-07T01:23:54Z
duration_ms: 900
parent_id: null
depth: 1
---

# FW-010 — AgentRegistry registers local bot classes via @register_agent(name, priority) or YAML; tool restriction is allowlist-shaped (allowed_tools on Agent/MCP/execution_plan/host_hooks) plus PBAC denial inside ToolManager — no deny-list field exists

## Summary

`parrot/registry/registry.py:AgentRegistry` (L302-1710): "register(): programmatic registration · register_agent decorator: declarative registration on class definition · YAML `agents:` config"; `await agent_registry.get_instance("MyAgent")`. Prior research findings (FEAT-746 F004, FEAT-747 F001/FW-001): it registers LOCAL bots only, no remote-agent kind, no capability index. FEAT-778 F019: tool gating is allowlist-shaped — `Agent` MCP registration takes `allowed_tools: Optional[List[str]]` (`bots/agent.py:1090-1142`), `ToolManager` enforces PBAC policy denial (`tools/manager.py:1945-2029`, "Policy denied" / "Permission denied: '<tool>' requires <perm>"), `tools/host_hooks.py` and `tools/execution_plan/*` carry allowlists; no `tools_deny` identifier exists. A read-only verdict agent therefore declares its manifest as an allowlist (git read, file read, test-output read) — matching the brainstorm's "closed read-only manifest".

## Citations

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 302-1710
  symbol: `AgentRegistry`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry
  score: 0.11
  excerpt: |
    class AgentRegistry:
        - register(): programmatic registration
        - register_agent decorator: declarative registration on class definition
        @register_agent(name="MySpecialAgent", priority=10)
        class MyAgent(AbstractBot): pass
        agent = await agent_registry.get_instance("MyAgent")
- path: `packages/ai-parrot/src/parrot/registry/__init__.py`
  lines: 1-1
  symbol: `register_agent`
  wiki_page_id: file:packages/ai-parrot/src/parrot/registry/__init__.py
  score: 0.62
- path: `packages/ai-parrot/src/parrot/bots/agent.py`
  lines: 1090-1142
  symbol: `Agent (MCP registration allowed_tools)`
  wiki_page_id: file:sdd/state/FEAT-778/findings/F019-tool-allowlist-mechanisms.md
  excerpt: |
    allowed_tools: Optional[List[str]] = None,   # Whitelist of tool names to register
- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 1945-2029
  symbol: `ToolManager (policy denial)`
  excerpt: |
    error_message = tool_call_outcome.reason or "Policy denied"
    error=f"Permission denied: '{tool.name}' requires {required}",
- path: `packages/ai-parrot/src/parrot/tools/host_hooks.py`
  lines: 1-1
  symbol: `host_hooks allowlist`
- path: `sdd/state/FEAT-746/findings/F004-agent-registry-remote-agents.md`
  lines: 1-1
  symbol: `F004 AgentRegistry registers LOCAL bots only`
  wiki_page_id: file:sdd/state/FEAT-746/findings/F004-agent-registry-remote-agents.md
  score: 1.00

## Notes

Line numbers for agent.py/manager.py are carried from FEAT-778's F019 (2026-10-30) — re-verify. [cross-lane: type=grep, intent=codebase lane Q031/Q032 should confirm the `register_agent` decorator signature and the current `allowed_tools` lines.] An escrow verdict agent run as a Claude Code subagent (like `sdd-secondopinion`, read-only `Read/Grep/Glob/Bash`) is an alternative to an AgentRegistry bot and needs no ToolManager at all.

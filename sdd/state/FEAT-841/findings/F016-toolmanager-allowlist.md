---
id: F016
query_id: Q032
type: grep
intent: "ToolManager constructor and how a restricted/allowlisted tool set is passed (read-only manifest for verdict agents)."
executed_at: 2026-11-07T01:24:35Z
duration_ms: 1000
parent_id: null
depth: 0
merged_from: [FC-016]
---

# F016 — ToolManager has no allowlist argument; allowlists live in SpawnSubAgentTool.allowed_tools, MCP mixin allowed_tools and tooling_policy

## Summary

`ToolManager` (`packages/ai-parrot/src/parrot/tools/manager.py:292`) is constructed with `(logger, debug, include_search_tool, resolver: AbstractPermissionResolver, execution_policy)` (302-308) — restriction is by what you `register_tool`/`register_tools`/`register_toolkit` (856/1072/1193) plus a permission `resolver` and `execution_policy`, not by an allowlist parameter. Allowlist semantics exist elsewhere: `tools/spawn.py` `SpawnSubAgentTool(allowed_tools=[...])` intersects a child's requested tools with the parent allowlist (127-192); `tools/mcp_mixin.py` honours `allowed_tools`/`blocked_tools` (66-84, 334); `tools/tooling_policy.py` declares `allowed_tools`/`blocked_tools` as tenant-overridable fields (44, 81). A read-only manifest for an in-process expert agent is therefore "register only read-only tools + a resolver", while for a Claude Code markdown agent it is the `tools:` frontmatter list (as `sdd-secondopinion` uses Read/Grep/Glob/Bash only).

## Citations

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 292-308
  symbol: `ToolManager.__init__`
  excerpt: |
    class ToolManager(MCPToolManagerMixin):
        def __init__(
            self,
            logger: Optional[logging.Logger] = None,
            debug: bool = False,
            include_search_tool: bool = False,
            resolver: Optional["AbstractPermissionResolver"] = None,
            execution_policy: Optional[Any] = None,
        ):

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 856-856
  symbol: `ToolManager.register_tool`
  excerpt: |
        def register_tool(

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 1193-1193
  symbol: `ToolManager.register_toolkit`
  excerpt: |
        def register_toolkit(self, toolkit: Union[str, "AbstractToolkit", type], **kwargs) -> List[AbstractTool]:

- path: `packages/ai-parrot/src/parrot/tools/spawn.py`
  lines: 127-138
  symbol: `SpawnSubAgentTool`
  excerpt: |
            allowed_tools: Optional[List[str]] = None,
                allowed_tools: Parent-defined allowlist of tool names.  Sub-agents

- path: `packages/ai-parrot/src/parrot/tools/spawn.py`
  lines: 165-169
  symbol: null
  excerpt: |
        """Compute the intersection of *requested* tools with the parent allowlist.
        If ``allowed_tools`` is empty (no allowlist configured), the
        If ``allowed_tools`` is non-empty, only tools present in it are allowed.

- path: `packages/ai-parrot/src/parrot/tools/mcp_mixin.py`
  lines: 334-334
  symbol: null
  excerpt: |
            # Check allowed_tools whitelist

- path: `packages/ai-parrot/src/parrot/tools/tooling_policy.py`
  lines: 81-81
  symbol: null
  excerpt: |
        tenant_fields: frozenset[str] = frozenset({"allowed_tools", "blocked_tools", "description"})

## Notes

- The brainstorm's "mirrors the python_repl allowlist-first gate" was not verified (no grep for python_repl within budget).

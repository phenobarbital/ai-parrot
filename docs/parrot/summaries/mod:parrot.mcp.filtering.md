---
type: Wiki Summary
title: parrot.mcp.filtering
id: mod:parrot.mcp.filtering
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tool filtering module for dynamic, context-aware MCP tool filtering.
relates_to:
- concept: class:parrot.mcp.filtering.ToolPredicate
  rel: defines
- concept: func:parrot.mcp.filtering.allow_all_tools
  rel: defines
- concept: func:parrot.mcp.filtering.by_organization
  rel: defines
- concept: func:parrot.mcp.filtering.by_permission
  rel: defines
- concept: func:parrot.mcp.filtering.by_role
  rel: defines
- concept: func:parrot.mcp.filtering.by_scope
  rel: defines
- concept: func:parrot.mcp.filtering.by_server
  rel: defines
- concept: func:parrot.mcp.filtering.by_tool_name
  rel: defines
- concept: func:parrot.mcp.filtering.by_tool_pattern
  rel: defines
- concept: func:parrot.mcp.filtering.by_user
  rel: defines
- concept: func:parrot.mcp.filtering.combine_and
  rel: defines
- concept: func:parrot.mcp.filtering.combine_or
  rel: defines
- concept: func:parrot.mcp.filtering.deny_all_tools
  rel: defines
- concept: func:parrot.mcp.filtering.exclude_by_tool_name
  rel: defines
- concept: func:parrot.mcp.filtering.filter_tools
  rel: defines
- concept: func:parrot.mcp.filtering.negate
  rel: defines
- concept: mod:parrot.mcp.context
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.mcp.filtering`

Tool filtering module for dynamic, context-aware MCP tool filtering.

This module provides:
- ToolPredicate protocol for custom filtering logic
- Built-in predicates (by_name, by_permission, by_role, by_organization)
- Predicate combinators (combine_and, combine_or)

Example:
    >>> # Simple allowlist
    >>> predicate = by_tool_name(['read_file', 'write_file'])
    >>>
    >>> # Permission-based
    >>> predicate = by_permission('use_mcp_tools')
    >>>
    >>> # Combined predicates
    >>> predicate = combine_and(
    ...     by_organization(['acme-corp']),
    ...     by_permission('admin'),
    ...     lambda tool, ctx: 'delete' not in tool.name  # Custom logic
    ... )

## Classes

- **`ToolPredicate(Protocol)`** — Protocol for tool filtering logic.

## Functions

- `def allow_all_tools(tool: AbstractTool, context: Optional['ReadonlyContext']=None) -> bool` — Allow all tools regardless of context.
- `def deny_all_tools(tool: AbstractTool, context: Optional['ReadonlyContext']=None) -> bool` — Deny all tools regardless of context.
- `def by_tool_name(allowed_names: List[str]) -> ToolPredicate` — Create predicate that filters by tool name (simple allowlist).
- `def exclude_by_tool_name(blocked_names: List[str]) -> ToolPredicate` — Create predicate that blocks specific tool names (blocklist).
- `def by_permission(required_permission: str) -> ToolPredicate` — Create predicate that requires specific permission.
- `def by_role(required_role: str) -> ToolPredicate` — Create predicate that requires specific role.
- `def by_scope(required_scope: str) -> ToolPredicate` — Create predicate that requires OAuth scope.
- `def by_organization(allowed_org_ids: List[str]) -> ToolPredicate` — Create predicate that restricts to specific organizations (multi-tenancy).
- `def by_user(allowed_user_ids: List[str]) -> ToolPredicate` — Create predicate that restricts to specific users.
- `def by_tool_pattern(pattern: str) -> ToolPredicate` — Create predicate that filters tools by name pattern.
- `def by_server(server_name: str) -> ToolPredicate` — Create predicate that filters by MCP server name.
- `def combine_and(*predicates: ToolPredicate) -> ToolPredicate` — Combine multiple predicates with AND logic (all must pass).
- `def combine_or(*predicates: ToolPredicate) -> ToolPredicate` — Combine multiple predicates with OR logic (any can pass).
- `def negate(predicate: ToolPredicate) -> ToolPredicate` — Negate a predicate (invert boolean result).
- `def filter_tools(tools: List[AbstractTool], predicate: Optional[Union[ToolPredicate, List[str]]], context: Optional['ReadonlyContext']=None) -> List[AbstractTool]` — Filter tools using a predicate or allowlist.

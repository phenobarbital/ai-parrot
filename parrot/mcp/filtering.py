"""
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
"""
from __future__ import annotations
from typing import Protocol, Optional, List, Union
# Use TYPE_CHECKING to avoid circular imports
from typing import TYPE_CHECKING
from ..tools.abstract import AbstractTool
if TYPE_CHECKING:
    from .context import ReadonlyContext


class ToolPredicate(Protocol):
    """Protocol for tool filtering logic.

    A ToolPredicate is a callable that determines if a tool should be
    available in a given context. It receives:
    - tool: The AbstractTool to evaluate
    - context: Optional ReadonlyContext with user/org information

    Returns True if tool should be available, False otherwise.

    Example:
        >>> def my_predicate(tool: AbstractTool, context: Optional[ReadonlyContext]) -> bool:
        ...     if not context:
        ...         return False
        ...     return context.has_permission('admin')
        >>>
        >>> # Use with MCPClient
        >>> client = MCPClient(config, tool_filter=my_predicate)
    """

    def __call__(
        self,
        tool: AbstractTool,
        context: Optional['ReadonlyContext'] = None
    ) -> bool:
        """Determine if tool should be available."""
        ...


# Built-in predicates
def allow_all_tools(
    tool: AbstractTool,
    context: Optional['ReadonlyContext'] = None
) -> bool:
    """Allow all tools regardless of context."""
    return True


def deny_all_tools(
    tool: AbstractTool,
    context: Optional['ReadonlyContext'] = None
) -> bool:
    """Deny all tools regardless of context."""
    return False


def by_tool_name(allowed_names: List[str]) -> ToolPredicate:
    """Create predicate that filters by tool name (simple allowlist).

    Args:
        allowed_names: List of tool names to allow

    Returns:
        ToolPredicate that checks if tool name is in allowed list

    Example:
        >>> predicate = by_tool_name(['read_file', 'list_dir', 'write_file'])
        >>> filter_tools(tools, predicate)
    """
    def predicate(tool: AbstractTool, context: Optional['ReadonlyContext'] = None) -> bool:
        return tool.name in allowed_names
    return predicate


def exclude_by_tool_name(blocked_names: List[str]) -> ToolPredicate:
    """Create predicate that blocks specific tool names (blocklist).

    Args:
        blocked_names: List of tool names to block

    Returns:
        ToolPredicate that denies tools in blocked list

    Example:
        >>> predicate = exclude_by_tool_name(['delete_file', 'format_drive'])
        >>> filter_tools(tools, predicate)
    """
    def predicate(tool: AbstractTool, context: Optional['ReadonlyContext'] = None) -> bool:
        return tool.name not in blocked_names
    return predicate


def by_permission(required_permission: str) -> ToolPredicate:
    """Create predicate that requires specific permission.

    Args:
        required_permission: Permission string (e.g., 'use_mcp_tools', 'admin')

    Returns:
        ToolPredicate that checks user permission via context

    Example:
        >>> predicate = by_permission('use_external_tools')
        >>> # Only tools with users having 'use_external_tools' permission
    """
    def predicate(tool: AbstractTool, context: Optional['ReadonlyContext'] = None) -> bool:
        return context.has_permission(required_permission) if context else False
    return predicate


def by_role(required_role: str) -> ToolPredicate:
    """Create predicate that requires specific role.

    Args:
        required_role: Role name (e.g., 'admin', 'hr', 'finance')

    Returns:
        ToolPredicate that checks user role via context

    Example:
        >>> predicate = by_role('admin')
        >>> # Only admins can use these tools
    """
    def predicate(tool: AbstractTool, context: Optional['ReadonlyContext'] = None) -> bool:
        return context.has_role(required_role) if context else False
    return predicate


def by_scope(required_scope: str) -> ToolPredicate:
    """Create predicate that requires OAuth scope.

    Args:
        required_scope: OAuth scope (e.g., 'read:calendar', 'write:email')

    Returns:
        ToolPredicate that checks OAuth scopes via context

    Example:
        >>> predicate = by_scope('write:email')
        >>> # Only users with email write scope
    """
    def predicate(tool: AbstractTool, context: Optional['ReadonlyContext'] = None) -> bool:
        return context.has_scope(required_scope) if context else False
    return predicate


def by_organization(allowed_org_ids: List[str]) -> ToolPredicate:
    """Create predicate that restricts to specific organizations (multi-tenancy).

    Args:
        allowed_org_ids: List of organization IDs that can access tools

    Returns:
        ToolPredicate that checks organization via context

    Example:
        >>> predicate = by_organization(['acme-corp', 'widgets-inc'])
        >>> # Only these organizations can use the tools
    """
    def predicate(tool: AbstractTool, context: Optional['ReadonlyContext'] = None) -> bool:
        return context.organization_id in allowed_org_ids if context else False
    return predicate


def by_user(allowed_user_ids: List[str]) -> ToolPredicate:
    """Create predicate that restricts to specific users.

    Args:
        allowed_user_ids: List of user IDs that can access tools

    Returns:
        ToolPredicate that checks user via context

    Example:
        >>> predicate = by_user(['admin@example.com', 'superuser@example.com'])
        >>> # Only these users can use the tools
    """
    def predicate(tool: AbstractTool, context: Optional['ReadonlyContext'] = None) -> bool:
        return context.user_id in allowed_user_ids if context else False
    return predicate


def by_tool_pattern(pattern: str) -> ToolPredicate:
    """Create predicate that filters tools by name pattern.

    Args:
        pattern: Glob-style pattern (e.g., 'mcp_*_read_*', 'chrome_*')

    Returns:
        ToolPredicate that matches tool names against pattern

    Example:
        >>> predicate = by_tool_pattern('mcp_admin_*')
        >>> # Only admin tools from MCP servers
    """
    import fnmatch  # pylint: disable=import-outside-toplevel

    def predicate(tool: AbstractTool, context: Optional['ReadonlyContext'] = None) -> bool:
        return fnmatch.fnmatch(tool.name, pattern)
    return predicate


def by_server(server_name: str) -> ToolPredicate:
    """Create predicate that filters by MCP server name.

    Args:
        server_name: Server name (e.g., 'chrome-devtools', 'fireflies')

    Returns:
        ToolPredicate that checks if tool belongs to server

    Example:
        >>> predicate = by_server('chrome-devtools')
        >>> # Only tools from Chrome DevTools server
    """
    def predicate(tool: AbstractTool, context: Optional['ReadonlyContext'] = None) -> bool:
        # Tool names are typically formatted as "mcp_{server}_{tool}"
        return f"mcp_{server_name}_" in tool.name
    return predicate


def combine_and(*predicates: ToolPredicate) -> ToolPredicate:
    """Combine multiple predicates with AND logic (all must pass).

    Args:
        *predicates: Variable number of ToolPredicate functions

    Returns:
        ToolPredicate that passes only if all predicates pass

    Example:
        >>> predicate = combine_and(
        ...     by_role('admin'),
        ...     by_organization(['acme-corp']),
        ...     by_permission('use_external_tools')
        ... )
        >>> # Tool available only if user is admin AND in org AND has permission
    """
    def combined(tool: AbstractTool, context: Optional['ReadonlyContext'] = None) -> bool:
        return all(p(tool, context) for p in predicates)
    return combined


def combine_or(*predicates: ToolPredicate) -> ToolPredicate:
    """Combine multiple predicates with OR logic (any can pass).

    Args:
        *predicates: Variable number of ToolPredicate functions

    Returns:
        ToolPredicate that passes if any predicate passes

    Example:
        >>> predicate = combine_or(
        ...     by_role('admin'),
        ...     by_role('super-admin'),
        ...     by_user(['special-user@example.com'])
        ... )
        >>> # Tool available for admins, super-admins, or special user
    """
    def combined(tool: AbstractTool, context: Optional['ReadonlyContext'] = None) -> bool:
        return any(p(tool, context) for p in predicates)
    return combined


def negate(predicate: ToolPredicate) -> ToolPredicate:
    """Negate a predicate (invert boolean result).

    Args:
        predicate: ToolPredicate to negate

    Returns:
        ToolPredicate that returns the opposite of input predicate

    Example:
        >>> # Allow all except delete operations
        >>> predicate = negate(by_tool_pattern('*_delete_*'))
    """
    def negated(tool: AbstractTool, context: Optional['ReadonlyContext'] = None) -> bool:
        return not predicate(tool, context)
    return negated


# Utility function for filtering tools
def filter_tools(
    tools: List[AbstractTool],
    predicate: Optional[Union[ToolPredicate, List[str]]],
    context: Optional['ReadonlyContext'] = None
) -> List[AbstractTool]:
    """Filter tools using a predicate or allowlist.

    Args:
        tools: List of tools to filter
        predicate: ToolPredicate, list of tool names, or None
        context: Optional ReadonlyContext for context-aware filtering

    Returns:
        Filtered list of tools

    Example:
        >>> tools = await client.get_available_tools()
        >>>
        >>> # Filter by allowlist
        >>> filtered = filter_tools(tools, ['read_file', 'list_dir'])
        >>>
        >>> # Filter by predicate
        >>> filtered = filter_tools(
        ...     tools,
        ...     by_permission('admin'),
        ...     context=user_context
        ... )
    """
    if predicate is None:
        return tools

    if isinstance(predicate, list):
        # Simple allowlist
        return [t for t in tools if t.name in predicate]

    if callable(predicate):
        # ToolPredicate
        return [t for t in tools if predicate(t, context)]

    return tools

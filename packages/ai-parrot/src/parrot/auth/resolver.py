"""Permission resolvers for granular tool/toolkit access control.

This module provides the resolver abstraction and default implementations:
- AbstractPermissionResolver: Pluggable ABC for permission checks
- DefaultPermissionResolver: RBAC implementation with hierarchy and LRU cache
- AllowAllResolver: Development/testing resolver (allows everything)
- DenyAllResolver: Lockdown resolver (denies restricted tools)
- PBACPermissionResolver: PBAC-backed Layer 2 safety net via PolicyEvaluator

The resolver is the single point of truth for "can this user execute this tool?"
It supports both Layer 1 (filtering) and Layer 2 (enforcement) permission checks.
"""

import logging
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Any, Optional, TYPE_CHECKING

from .permission import PermissionContext, to_eval_context

if TYPE_CHECKING:
    from navigator_auth.abac.policies.evaluator import PolicyEvaluator


class AbstractPermissionResolver(ABC):
    """Pluggable resolver for tool permission checks.

    This ABC defines the interface for permission resolution. Implementations
    can use different backends (in-memory, Redis, database) and different
    permission models (RBAC, ABAC, custom).

    The two main methods serve different enforcement layers:
    - can_execute(): Layer 2 reactive enforcement per tool call
    - filter_tools(): Layer 1 preventive filtering at agent startup

    Example:
        >>> class CustomResolver(AbstractPermissionResolver):
        ...     async def can_execute(self, context, tool_name, required_permissions):
        ...         # Custom logic here
        ...         return True
    """

    @abstractmethod
    def can_execute(
        self,
        context: PermissionContext,
        tool_name: str,
        required_permissions: set[str],
    ) -> bool:
        """Check if user in context may execute the tool.

        This is the Layer 2 reactive check called before each tool execution.

        Args:
            context: The permission context with user session and metadata.
            tool_name: Name of the tool being executed.
            required_permissions: Set of permissions required by the tool.
                If empty, the tool is unrestricted.

        Returns:
            True if the user is allowed to execute the tool, False otherwise.
        """
        ...

    def filter_tools(
        self,
        context: PermissionContext,
        tools: list[Any],
    ) -> list[Any]:
        """Return subset of tools the user is allowed to execute.

        This is the Layer 1 preventive filter called when building the tool
        list for the LLM context. Unauthorized tools are removed before the
        LLM sees them.

        Default implementation iterates tools and calls can_execute() for each.
        Subclasses may override for bulk optimization.

        Args:
            context: The permission context with user session and metadata.
            tools: List of tool objects (must have .name attribute and
                optional ._required_permissions attribute).

        Returns:
            Filtered list containing only tools the user can execute.
        """
        allowed = []
        for tool in tools:
            perms = getattr(tool, "_required_permissions", set())
            if self.can_execute(context, tool.name, perms):
                allowed.append(tool)
        return allowed


class DefaultPermissionResolver(AbstractPermissionResolver):
    """Reference RBAC implementation with LRU-cached role expansion.

    This resolver implements role-based access control with hierarchical
    role expansion. Roles can imply other roles (e.g., 'admin' implies
    'write' which implies 'read').

    The expansion is cached using LRU cache for performance. Cache is
    per-resolver-instance; role hierarchy changes require a new resolver.

    Attributes:
        _hierarchy: Dict mapping roles to their implied permissions/roles.
        _expand_cached: LRU-cached role expansion function.

    Example:
        >>> hierarchy = {
        ...     'admin': {'manage', 'write', 'read'},
        ...     'manage': {'write', 'read'},
        ...     'write': {'read'},
        ...     'read': set(),
        ... }
        >>> resolver = DefaultPermissionResolver(role_hierarchy=hierarchy)
        >>> session = UserSession(user_id="u1", tenant_id="t1", roles=frozenset({'admin'}))
        >>> ctx = PermissionContext(session=session)
        >>> resolver.can_execute(ctx, "create_issue", {'write'})
        True  # admin has write through hierarchy
    """

    def __init__(
        self,
        role_hierarchy: Optional[dict[str, set[str]]] = None,
        cache_size: int = 256,
    ) -> None:
        """Initialize the resolver with role hierarchy.

        Args:
            role_hierarchy: Dict mapping roles to their implied permissions.
                Keys are role names, values are sets of implied roles/permissions.
                If None, no hierarchy is used (direct matching only).
            cache_size: Maximum number of role expansions to cache.
                Default 256 should be sufficient for most deployments.
        """
        self._hierarchy: dict[str, set[str]] = role_hierarchy or {}
        self._cache_size = cache_size
        # Create cached version of expand_roles
        self._expand_cached = lru_cache(maxsize=cache_size)(self._expand_roles)

    def _expand_roles(self, roles: frozenset[str]) -> frozenset[str]:
        """Expand roles to all implicitly granted permissions.

        Uses BFS traversal to follow the role hierarchy graph and collect
        all transitively implied permissions.

        Args:
            roles: Initial set of user roles.

        Returns:
            Expanded set including all implied permissions.
        """
        expanded: set[str] = set(roles)
        queue: list[str] = list(roles)

        while queue:
            role = queue.pop(0)  # BFS: pop from front
            implied = self._hierarchy.get(role, set())
            new_roles = implied - expanded
            expanded |= new_roles
            queue.extend(new_roles)

        return frozenset(expanded)

    def can_execute(
        self,
        context: PermissionContext,
        tool_name: str,
        required_permissions: set[str],
    ) -> bool:
        """Check if user has any of the required permissions.

        Unrestricted tools (empty required_permissions) are always allowed.
        Otherwise, uses OR logic: any matching permission grants access.

        Args:
            context: The permission context with user session.
            tool_name: Name of the tool (for logging/audit, not used in check).
            required_permissions: Set of permissions, any of which grants access.

        Returns:
            True if tool is unrestricted or user has any required permission.
        """
        # Unrestricted tools are always allowed
        if not required_permissions:
            return True

        # Expand user's roles through hierarchy
        expanded = self._expand_cached(context.roles)

        # OR logic: any matching permission grants access
        return bool(required_permissions & expanded)

    def clear_cache(self) -> None:
        """Clear the role expansion cache.

        Call this if the role hierarchy has been modified and you want
        to invalidate cached expansions without creating a new resolver.
        """
        self._expand_cached.cache_clear()

    @property
    def cache_info(self) -> Any:
        """Return cache statistics for monitoring.

        Returns:
            Named tuple with hits, misses, maxsize, currsize.
        """
        return self._expand_cached.cache_info()


class AllowAllResolver(AbstractPermissionResolver):
    """Resolver that allows all tool executions.

    Use this for development/testing or when permission checks are
    handled elsewhere (e.g., at the API gateway level).
    """

    def can_execute(
        self,
        context: PermissionContext,
        tool_name: str,
        required_permissions: set[str],
    ) -> bool:
        """Always returns True."""
        return True


class DenyAllResolver(AbstractPermissionResolver):
    """Resolver that denies all tool executions.

    Use this for lockdown scenarios or as a fail-safe default.
    """

    def can_execute(
        self,
        context: PermissionContext,
        tool_name: str,
        required_permissions: set[str],
    ) -> bool:
        """Always returns False for restricted tools, True for unrestricted."""
        # Unrestricted tools are still allowed
        return not required_permissions


class PBACPermissionResolver(AbstractPermissionResolver):
    """PBAC-backed permission resolver — Layer 2 safety net.

    Wraps navigator-auth's ``PolicyEvaluator`` and implements the
    ``AbstractPermissionResolver`` interface so that tool executions are
    checked against YAML-defined PBAC policies.

    **Role in the architecture**:
    Primary enforcement (Layer 1) happens at the handler level via
    ``Guardian.filter_resources()``.  This resolver provides defense-in-depth
    by re-checking policies inside ``AbstractTool.execute()`` (Layer 2).
    A denial at this layer indicates that a tool slipped through the handler
    filter — it is logged as a warning for audit purposes.

    Both this resolver and the handler-level Guardian MUST share the same
    ``PolicyEvaluator`` instance (wired by ``setup_pbac()``) to guarantee
    consistent decisions.

    Attributes:
        _evaluator: Shared ``PolicyEvaluator`` instance.
        logger: Standard Python logger for denial audit events.

    Example::

        resolver = PBACPermissionResolver(evaluator=evaluator)
        tool_manager.set_resolver(resolver)
    """

    def __init__(
        self,
        evaluator: "PolicyEvaluator",
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """Initialize the resolver with a shared PolicyEvaluator.

        Args:
            evaluator: A ``PolicyEvaluator`` instance (shared with Guardian).
            logger: Optional logger; defaults to ``logging.getLogger(__name__)``.
        """
        self._evaluator = evaluator
        self.logger = logger or logging.getLogger(__name__)

    async def can_execute(
        self,
        context: PermissionContext,
        tool_name: str,
        required_permissions: set[str],
    ) -> bool:
        """Layer 2 PBAC check — evaluate tool execution permission.

        Bridges ``PermissionContext`` to ``EvalContext`` and delegates to
        ``PolicyEvaluator.check_access()``.  Logs a warning on denial to
        provide an audit trail for tools that bypassed the handler filter.

        Args:
            context: The permission context carrying user session and metadata.
            tool_name: Name of the tool being executed.
            required_permissions: Set of required permissions declared on the
                tool.  For PBAC, policies supersede these declarations; this
                parameter is not used in the PBAC evaluation but is part of
                the interface contract.

        Returns:
            ``True`` if the PBAC policy allows execution, ``False`` otherwise.
        """
        try:
            from navigator_auth.abac.policies.resources import ResourceType
            from navigator_auth.abac.policies.environment import Environment
        except ImportError:
            # navigator-auth not installed — fail open to preserve backward compat
            return True

        eval_ctx = to_eval_context(context)
        env = Environment()

        result = self._evaluator.check_access(
            ctx=eval_ctx,
            resource_type=ResourceType.TOOL,
            resource_name=tool_name,
            action="tool:execute",
            env=env,
        )

        if not result.allowed:
            self.logger.warning(
                "PBAC Layer 2 DENY: tool=%s user=%s policy=%s reason=%s",
                tool_name,
                context.user_id,
                result.matched_policy,
                result.reason,
            )

        return result.allowed

    async def filter_tools(
        self,
        context: PermissionContext,
        tools: list[Any],
    ) -> list[Any]:
        """Layer 1 PBAC filter — batch filter tools by policy.

        Collects tool names, delegates to ``PolicyEvaluator.filter_resources()``
        for efficient batch evaluation, and returns only the allowed subset.

        Args:
            context: The permission context carrying user session and metadata.
            tools: List of tool objects that each have a ``.name`` attribute.

        Returns:
            Filtered list containing only tools the user is permitted to execute.
        """
        try:
            from navigator_auth.abac.policies.resources import ResourceType
            from navigator_auth.abac.policies.environment import Environment
        except ImportError:
            return list(tools)

        if not tools:
            return []

        eval_ctx = to_eval_context(context)
        env = Environment()
        tool_names = [t.name for t in tools]

        filtered = self._evaluator.filter_resources(
            ctx=eval_ctx,
            resource_type=ResourceType.TOOL,
            resource_names=tool_names,
            action="tool:execute",
            env=env,
        )

        allowed_set = set(filtered.allowed)
        return [t for t in tools if t.name in allowed_set]

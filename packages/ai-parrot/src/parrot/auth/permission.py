"""Permission data models for granular tool/toolkit access control.

This module provides foundational data structures for the permission system:
- UserSession: Immutable session carrying user identity and role claims
- PermissionContext: Request-scoped wrapper with session and metadata
- to_eval_context: Bridge function from PermissionContext to EvalContext

These are lightweight structures that flow through the execution chain,
enabling Layer 1 (filtering) and Layer 2 (enforcement) permission checks.
"""

from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from navigator_auth.abac.context import EvalContext


@dataclass(frozen=True)
class UserSession:
    """Minimal session carrying identity and role claims.

    Immutable and hashable — safe for use as cache keys in permission resolvers.

    Attributes:
        user_id: Unique identifier for the user.
        tenant_id: Tenant/organization identifier for multi-tenant deployments.
        roles: Set of role claims (e.g., frozenset({'jira.manage', 'github.read'})).
            Uses frozenset for immutability and hashability.
        metadata: Optional additional session metadata (e.g., auth provider info).
            Note: metadata dict contents should be immutable for cache safety.

    Example:
        >>> session = UserSession(
        ...     user_id="user-123",
        ...     tenant_id="acme-corp",
        ...     roles=frozenset({'jira.write', 'github.read'})
        ... )
        >>> 'jira.write' in session.roles
        True
        >>> hash(session)  # Hashable for cache keys
        -1234567890
    """

    user_id: str
    tenant_id: str
    roles: frozenset[str]
    metadata: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)

    def __post_init__(self) -> None:
        """Validate that roles is a frozenset."""
        if not isinstance(self.roles, frozenset):
            # Convert to frozenset if necessary (for convenience)
            object.__setattr__(self, 'roles', frozenset(self.roles))

    def has_role(self, role: str) -> bool:
        """Check if session has a specific role.

        Args:
            role: Role name to check.

        Returns:
            True if the role is present in the session's roles.
        """
        return role in self.roles

    def has_any_role(self, roles: set[str] | frozenset[str]) -> bool:
        """Check if session has any of the specified roles.

        Args:
            roles: Set of role names to check.

        Returns:
            True if at least one role is present.
        """
        return bool(self.roles & roles)


@dataclass
class PermissionContext:
    """Request-scoped wrapper grouping session with extra context.

    This is the primary object passed through the permission checking pipeline.
    It wraps an immutable UserSession with mutable request-specific metadata.

    Attributes:
        session: The underlying UserSession with identity and roles.
        request_id: Optional request/correlation ID for tracing.
        extra: Additional request-scoped metadata (e.g., source IP, API version).

    Example:
        >>> session = UserSession(
        ...     user_id="user-123",
        ...     tenant_id="acme-corp",
        ...     roles=frozenset({'admin'})
        ... )
        >>> ctx = PermissionContext(
        ...     session=session,
        ...     request_id="req-456",
        ...     extra={"source": "api", "version": "v2"}
        ... )
        >>> ctx.user_id
        'user-123'
        >>> ctx.roles
        frozenset({'admin'})
    """

    session: UserSession
    request_id: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def user_id(self) -> str:
        """Get the user ID from the underlying session."""
        return self.session.user_id

    @property
    def tenant_id(self) -> str:
        """Get the tenant ID from the underlying session."""
        return self.session.tenant_id

    @property
    def roles(self) -> frozenset[str]:
        """Get the roles from the underlying session."""
        return self.session.roles

    def has_role(self, role: str) -> bool:
        """Check if session has a specific role.

        Args:
            role: Role name to check.

        Returns:
            True if the role is present.
        """
        return self.session.has_role(role)

    def has_any_role(self, roles: set[str] | frozenset[str]) -> bool:
        """Check if session has any of the specified roles.

        Args:
            roles: Set of role names to check.

        Returns:
            True if at least one role is present.
        """
        return self.session.has_any_role(roles)


def to_eval_context(context: "PermissionContext") -> "EvalContext":
    """Bridge a PermissionContext to a navigator-auth EvalContext.

    Creates a minimal ``EvalContext`` that the ``PolicyEvaluator`` can use
    to evaluate PBAC policies.  Extracts ``username``, ``groups``, ``roles``,
    and ``programs`` from the ``UserSession.metadata`` where available.

    Args:
        context: The AI-Parrot permission context carrying user session data.

    Returns:
        An ``EvalContext`` instance populated with the session's userinfo.

    Raises:
        ImportError: If navigator-auth is not installed.
    """
    from navigator_auth.abac.context import EvalContext as _EvalContext

    session = context.session
    metadata = session.metadata or {}

    userinfo: dict[str, Any] = {
        "username": session.user_id,
        "user_id": session.user_id,
        "tenant_id": session.tenant_id,
        "groups": list(metadata.get("groups", [])),
        "roles": list(session.roles),
        "programs": list(metadata.get("programs", [])),
    }

    # Build EvalContext without a real request (Layer 2 context has no request)
    ctx = _EvalContext.__new__(_EvalContext)
    ctx.store = {}
    ctx.store["request"] = None
    ctx.store["user"] = session.user_id
    ctx.store["userinfo"] = userinfo
    ctx.store["session"] = None
    ctx._columns = list(ctx.store.keys())
    return ctx
